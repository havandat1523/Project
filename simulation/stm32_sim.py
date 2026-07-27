"""
stm32_sim.py
-------------
Công cụ mô phỏng phần cứng STM32 Master độc lập cho Raspberry Pi.
Chạy độc lập bằng lệnh:
    python stm32_sim.py [PORT] [BAUDRATE]

Cung cấp giao diện dòng lệnh interactive CMD> để giả lập:
  - run_system                                    (CHỈ CHẠY ĐƯỢC KHI TÀI XẾ ĐÃ ĐĂNG NHẬP THÀNH CÔNG TRÊN UI)
  - stop_system                                   (Dừng chế độ mô phỏng tự động)
  - rfid <MÃ_THẺ>                                 (VD: rfid ABX12SSDX hoặc rfid 04A3F1B2)
  - seat <SỐ_GHẾ_1_16> <0|1>                      (VD: seat 3 1)
  - gnss <active|degrade|off> [lat] [lon] [speed] (VD: gnss active 21.0021 105.8462 35)
  - sos                                           (Nhấn nút khẩn cấp)
  - dht <nhiệt_độ> <độ_ẩm>                        (VD: dht 29.5 65.0)
  - status                                        (Xem trạng thái mô phỏng & tài xế hiện tại)
  - help / exit
"""

import sys
import os
import json
import time
import threading
import serial

try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# Default Port / Baudrate (configurable via argv or environment)
PORT = sys.argv[1] if len(sys.argv) > 1 else os.getenv("UART_SIM_PORT", "COM2" if os.name == "nt" else "/tmp/ttyVIRTUAL_PI")
BAUDRATE = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

# Current simulation state
seat_states = {i: 0 for i in range(1, 17)}
gnss_state = "active"
current_lat = 21.0021
current_lon = 105.8462
current_speed = 0.0

# Session State tracking (Updated when Pi sends UART frames down to Master)
driver_logged_in = False
active_driver_id = ""

auto_sim_running = False
auto_sim_thread = None

# Base path for Map files
MAP_DIR = r"C:\Users\Admin\OneDrive\Desktop\DO_AN\Map"
if not os.path.exists(MAP_DIR):
    MAP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Map"))

# MySQL Connection config
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "schoolbus",
    "charset": "utf8mb4"
}

def fetch_stops_from_db():
    default_stops = [
        {"file": "0.geojson", "student_name": "Tran Van C", "rfid": "04A3F1B2", "seat": 3, "address": "LK6D, Mo Lao, Ha Dong"},
        {"file": "1.geojson", "student_name": "Nguyen Van D", "rfid": "1A2B3C4D", "seat": 4, "address": "Ecolife Capitol, 58 To Huu"},
        {"file": "2.geojson", "student_name": "Le Thi E", "rfid": "2A2B3C4D", "seat": 5, "address": "Louis City Dai Mo"},
        {"file": "3.geojson", "student_name": "Pham Van F", "rfid": "3A2B3C4D", "seat": 6, "address": "Van Phuc, Ha Dong"},
        {"file": "4.geojson", "student_name": "Hoang Thi G", "rfid": "4A2B3C4D", "seat": 7, "address": "KDT Duong Noi, Ha Noi"},
        {"file": "5.geojson", "student_name": "Vu Van H", "rfid": "5A2B3C4D", "seat": 8, "address": "FLC Star Tower, Le Trong Tan"},
        {"file": "6.geojson", "student_name": "Truong Hoc", "rfid": None, "seat": None, "address": "Truong hoc"}
    ]
    
    if not MYSQL_AVAILABLE:
        return default_stops

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT r.stop_order, r.address, s.student_id, s.rfid_code, s.full_name
            FROM RouteStop r
            LEFT JOIN students s ON r.student_id = s.student_id
            WHERE r.route_id = 1
            ORDER BY r.stop_order ASC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return default_stops

        stops = []
        for i, row in enumerate(rows):
            file_name = f"{i}.geojson"
            rfid = row.get("rfid_code") or f"RFID_{row.get('student_id')}" if row.get("student_id") else None
            seat = i + 2 if row.get("student_id") else None
            stops.append({
                "file": file_name,
                "student_name": row.get("full_name") or "Học sinh",
                "rfid": rfid,
                "seat": seat,
                "address": row.get("address") or "Điểm dừng"
            })
        return stops
    except Exception as e:
        return default_stops

def build_frame(main_evt: int, sub_evt: int, data: bytes = b"") -> bytes:
    length = len(data)
    frame = bytearray([0xAA, main_evt, sub_evt, length])
    frame.extend(data)
    chk = main_evt ^ sub_evt ^ length
    for b in data:
        chk ^= b
    frame.append(chk)
    frame.append(0x55)
    return bytes(frame)

class STM32Simulator:
    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.master_fd = None
        self.running = True

    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
            print(f"[STM32 Sim] Connected to serial port: {self.port} at {self.baudrate} baud.")
            return True
        except Exception as e:
            if os.name != "nt":
                try:
                    import pty
                    master, slave = pty.openpty()
                    slave_name = os.ttyname(slave)
                    if os.path.exists("/tmp/ttyVIRTUAL_PI"):
                        try: os.unlink("/tmp/ttyVIRTUAL_PI")
                        except Exception: pass
                    os.symlink(slave_name, "/tmp/ttyVIRTUAL_PI")
                    self.master_fd = master
                    print(f"[STM32 Sim] Created Linux Virtual PTY: /tmp/ttyVIRTUAL_PI -> {slave_name}")
                    return True
                except Exception as pty_err:
                    print(f"[STM32 Sim] PTY creation error: {pty_err}")
            print(f"[STM32 Sim] Warning: Cannot open serial port {self.port}: {e}")
            print("[STM32 Sim] Running in console-only print mode.")
            return False

    def start_receiver(self):
        t = threading.Thread(target=self._receive_loop, daemon=True)
        t.start()

    def _receive_loop(self):
        state = "STX"
        rx_main = rx_sub = rx_len = 0
        rx_data = bytearray()
        rx_chk = 0

        while self.running:
            try:
                data_bytes = None
                if self.ser and self.ser.is_open:
                    waiting = self.ser.in_waiting
                    if waiting > 0:
                        data_bytes = self.ser.read(waiting)
                elif self.master_fd is not None:
                    import select
                    r, _, _ = select.select([self.master_fd], [], [], 0.1)
                    if r:
                        data_bytes = os.read(self.master_fd, 1024)
                else:
                    time.sleep(0.5)
                    continue

                if data_bytes:
                    for b in data_bytes:
                        if state == "STX":
                            if b == 0xAA: state = "MAIN"
                        elif state == "MAIN":
                            rx_main = b; state = "SUB"
                        elif state == "SUB":
                            rx_sub = b; state = "LEN"
                        elif state == "LEN":
                            rx_len = b; rx_data = bytearray()
                            state = "DATA" if rx_len > 0 else "CHECKSUM"
                        elif state == "DATA":
                            rx_data.append(b)
                            if len(rx_data) >= rx_len: state = "CHECKSUM"
                        elif state == "CHECKSUM":
                            rx_chk = b; state = "ETX"
                        elif state == "ETX":
                            if b == 0x55:
                                chk = rx_main ^ rx_sub ^ rx_len
                                for x in rx_data: chk ^= x
                                if chk == rx_chk:
                                    self._on_frame_received(rx_main, rx_sub, rx_data)
                            state = "STX"
            except Exception as e:
                time.sleep(0.5)

    def _on_frame_received(self, main_evt, sub_evt, data):
        global driver_logged_in, active_driver_id
        data_str = data.decode("utf-8", errors="ignore")
        print(f"\n[ALL LOG] RECV Frame from Pi: Main=0x{main_evt:02X}, Sub=0x{sub_evt:02X}, Data='{data_str}'")
        
        if main_evt == 0x01 and sub_evt == 0x01: # Driver Login Success
            driver_logged_in = True
            active_driver_id = data_str
            print(f"✅ [ALL LOG] Tài xế {active_driver_id} đã ĐĂNG NHẬP THÀNH CÔNG trên Pi UI.")
        elif main_evt == 0x02 and sub_evt == 0x01: # Driver Logout Success
            driver_logged_in = False
            active_driver_id = ""
            print(f"🔒 [ALL LOG] Tài xế đã ĐĂNG XUẤT THÀNH CÔNG trên Pi UI.")

        audio_map = {
            (0x01, 0x01): "🔊 LOA PHÁT: 01/001 - Tài xế login THÀNH CÔNG",
            (0x01, 0x02): "🔊 LOA PHÁT: 01/002 - Tài xế login THẤT BẠI",
            (0x02, 0x01): "🔊 LOA PHÁT: 02/001 - Tài xế logout THÀNH CÔNG",
            (0x03, 0x01): "🔊 LOA PHÁT: 03/001 - Phụ xe login THÀNH CÔNG",
            (0x05, 0x01): "🔊 LOA PHÁT: 05/001 - Học sinh quẹt thẻ THÀNH CÔNG",
            (0x05, 0x03): "🔊 LOA PHÁT: 05/003 - Học sinh cuối cùng đã lên xe (Chiều đón)",
            (0x05, 0x04): "🔊 LOA PHÁT: 05/004 - Học sinh cuối cùng đã xuống xe (Chiều trả)",
            (0x05, 0x06): "🔊 LOA PHÁT: 05/006 - Xuống xe hàng loạt tại trường. Bác tài & phụ xe kiểm tra kỹ xe!",
            (0x07, 0x01): "🚨 LOA PHÁT: 07/001 - CẢNH BÁO SOS KHẨN CẤP",
            (0x08, 0x01): "🚨 LOA PHÁT: 08/001 - CẢNH BÁO: HỌC SINH TRÊN XE KHÔNG CÓ TÀI XẾ/PHỤ XE!",
        }
        key = (main_evt, sub_evt)
        if key in audio_map:
            print(f"[ALL LOG] {audio_map[key]}")
        sys.stdout.write("CMD> ")
        sys.stdout.flush()

    def send_data(self, frame: bytes):
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(frame)
                print(f"[ALL LOG] SENT Frame ({len(frame)} bytes): {frame.hex().upper()}")
            except Exception as e:
                print(f"[ALL LOG] Send error: {e}")
        elif self.master_fd is not None:
            try:
                os.write(self.master_fd, frame)
                print(f"[ALL LOG] SENT Frame via PTY ({len(frame)} bytes): {frame.hex().upper()}")
            except Exception as e:
                print(f"[ALL LOG] Virtual PTY send error: {e}")
        else:
            print(f"[ALL LOG] [Simulated Out] Frame ({len(frame)} bytes): {frame.hex().upper()}")

def send_seats(sim: STM32Simulator):
    seat_str = "".join([f"s{i}:{seat_states[i]}" for i in range(1, 17)])
    frame = build_frame(0xF1, 0x00, seat_str.encode("ascii"))
    sim.send_data(frame)

def send_gnss(sim: STM32Simulator, lat, lon, speed):
    gps_str = f"{lat:.6f},{lon:.6f},{speed:.1f}"
    frame = build_frame(0xF0, 0x00, gps_str.encode("ascii"))
    sim.send_data(frame)

def load_geojson_coordinates(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["geometry"]["coordinates"]
    except Exception as e:
        return []

def run_system_simulation(sim: STM32Simulator):
    global auto_sim_running, current_lat, current_lon, current_speed, driver_logged_in
    auto_sim_running = True
    stops = fetch_stops_from_db()
    
    print("\n[ALL LOG] 🚀 BẮT ĐẦU MÔ PHỎNG TỰ ĐỘNG XE DI CHUYỂN & ĐÓN HỌC SINH")

    seat_states[1] = 1 # Driver
    seat_states[2] = 1 # Attendant
    send_seats(sim)
    time.sleep(1.5)

    for idx, stop in enumerate(stops):
        if not auto_sim_running: break

        geojson_path = os.path.join(MAP_DIR, stop["file"])
        coords = load_geojson_coordinates(geojson_path)
        if not coords: continue

        print(f"\n[ALL LOG] 🚌 [ĐOẠN {idx+1}/{len(stops)}] Xe bắt đầu di chuyển đến: {stop['address']}")

        step = max(1, len(coords) // 25)
        sampled_coords = coords[::step]
        if coords[-1] not in sampled_coords:
            sampled_coords.append(coords[-1])

        speed = 35.0
        for lon, lat in sampled_coords:
            if not auto_sim_running: break
            current_lat = lat; current_lon = lon; current_speed = speed
            send_gnss(sim, lat, lon, speed)
            time.sleep(0.3)

        if not auto_sim_running: break

        current_speed = 0.0
        send_gnss(sim, current_lat, current_lon, 0.0)
        print(f"[ALL LOG] 📍 XE ĐÃ TỚI ĐIỂM DỪNG: {stop['address']}")

        if stop["rfid"] and stop["seat"]:
            print(f"[ALL LOG] 💳 [QUẸT THẺ TỰ ĐỘNG] Học sinh: {stop['student_name']} (Thẻ: {stop['rfid']})")
            rfid_frame = build_frame(0xF2, 0x00, stop["rfid"].encode("ascii"))
            sim.send_data(rfid_frame)
            time.sleep(1.0)

            print(f"[ALL LOG] 🪑 [VÀO GHẾ TỰ ĐỘNG] Học sinh ngồi vào Ghế {stop['seat']}")
            seat_states[stop["seat"]] = 1
            send_seats(sim)
            time.sleep(2.5)
        elif idx == len(stops) - 1:
            print("[ALL LOG] 🏫 Xe đã về đến trường học! Học sinh xuống xe hàng loạt.")
            for s in range(3, 17): seat_states[s] = 0
            send_seats(sim)
            time.sleep(2.0)

    auto_sim_running = False
    print("\n[ALL LOG] ✅ HOÀN THÀNH CHUYẾN ĐI! Xe đã đưa toàn bộ học sinh về trường.")
    sys.stdout.write("CMD> ")
    sys.stdout.flush()

def print_help():
    print("""
================================================================================
                                    ALL LOG
================================================================================
[ALL LOGS DISPLAYED HERE]

--------------------------------------------------------------------------------
CMD>
--------------------------------------------------------------------------------
run_system - TỰ ĐỘNG Mô phỏng xe chạy & đón học sinh (YÊU CẦU ĐÃ LOGIN)
stop_system - Dừng chế độ mô phỏng tự động
rfid <MÃ_THẺ> - Gửi mã thẻ RFID quẹt (VD: rfid ABX12SSDX)
seat <SỐ_GHẾ_1_16> <0|1> - Đặt trạng thái ghế (VD: seat 3 1)
gnss <active|degrade|off> [lat] [lon] [spd] - Đặt trạng thái GNSS (VD: gnss active 21.0021 105.8462 30)
sos - Giả lập nhấn nút SOS khẩn cấp
dht <nhiệt_độ> <độ_ẩm> - Gửi thông số nhiệt độ/độ ẩm (VD: dht 28.5 65.0)
status - Hiển thị trạng thái mô phỏng & tài xế hiện tại
help / exit
================================================================================
""")

def main():
    sim = STM32Simulator(PORT, BAUDRATE)
    sim.connect()
    sim.start_receiver()
    print_help()

    global gnss_state, current_lat, current_lon, current_speed, auto_sim_running, auto_sim_thread, driver_logged_in

    try:
        while True:
            cmd = input("CMD> ").strip()
            if not cmd:
                continue

            parts = cmd.split()
            op = parts[0].lower()

            if op in ("exit", "quit"):
                print("[ALL LOG] Exiting simulator.")
                auto_sim_running = False
                sim.running = False
                break

            elif op == "help":
                print_help()

            elif op == "run_system":
                if not driver_logged_in:
                    print("\n[ALL LOG] ❌ KHÔNG THỂ CHẠY 'run_system': Tài xế CHƯA ĐĂNG NHẬP trên giao diện Pi!")
                elif auto_sim_running:
                    print("[ALL LOG] Mô phỏng tự động đang chạy.")
                else:
                    auto_sim_thread = threading.Thread(target=run_system_simulation, args=(sim,), daemon=True)
                    auto_sim_thread.start()

            elif op == "stop_system":
                if auto_sim_running:
                    print("[ALL LOG] Đang dừng mô phỏng tự động...")
                    auto_sim_running = False

            elif op == "status":
                print(f"[ALL LOG] Tài xế logged in: {driver_logged_in} ({active_driver_id}) | Auto-Sim: {auto_sim_running}")
                print(f"[ALL LOG] GNSS: {gnss_state.upper()} | Lat: {current_lat}, Lon: {current_lon}, Speed: {current_speed} km/h")

            elif op == "rfid":
                if len(parts) >= 2:
                    code = parts[1]
                    frame = build_frame(0xF2, 0x00, code.encode("ascii"))
                    sim.send_data(frame)

            elif op == "seat":
                if len(parts) >= 3:
                    try:
                        s_num = int(parts[1]); val = int(parts[2])
                        if 1 <= s_num <= 16 and val in (0, 1):
                            seat_states[s_num] = val
                            send_seats(sim)
                    except ValueError: pass

            elif op == "gnss":
                if len(parts) >= 2:
                    st = parts[1].lower()
                    if st in ("active", "degrade", "off"):
                        gnss_state = st
                        if len(parts) >= 5:
                            try:
                                current_lat = float(parts[2])
                                current_lon = float(parts[3])
                                current_speed = float(parts[4])
                            except ValueError: pass
                        send_gnss(sim, current_lat, current_lon, current_speed)

            elif op == "sos":
                frame = build_frame(0xF3, 0x01, b"\x01")
                sim.send_data(frame)

            elif op == "dht":
                if len(parts) >= 3:
                    try:
                        temp = float(parts[1]); humid = float(parts[2])
                        dht_str = f"{temp:.1f},{humid:.1f}"
                        frame = build_frame(0xF5, 0x00, dht_str.encode("ascii"))
                        sim.send_data(frame)
                    except ValueError: pass

    except KeyboardInterrupt:
        sim.running = False

if __name__ == "__main__":
    main()
