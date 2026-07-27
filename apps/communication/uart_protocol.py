import serial
import threading
import time
from PyQt5.QtCore import QThread, pyqtSignal
from config import config
from services.logger import get_logger

logger = get_logger("UART")

class UARTThread(QThread):
    # PyQt5 Signals to propagate data to UI & Logic
    gps_received = pyqtSignal(float, float, float)     # lat, lon, speed_kmh
    seats_received = pyqtSignal(dict)                  # {"1": 0/1, ..., "16": 0/1}
    rfid_received = pyqtSignal(str)                    # RFID tag string
    sos_received = pyqtSignal()                        # SOS button press
    dht11_received = pyqtSignal(float, float)          # temperature, humidity
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.ser = None
        self.lock = threading.Lock()
        
        # State machine variables
        self.state = "STX"
        self.rx_main = 0
        self.rx_sub = 0
        self.rx_len = 0
        self.rx_data = bytearray()
        self.rx_chk = 0
        
        self.simulation_mode = False

    def open_port(self):
        try:
            self.ser = serial.Serial(
                port=config.UART_MASTER_PORT,
                baudrate=config.UART_MASTER_BAUDRATE,
                timeout=0.1
            )
            logger.info("Connected to STM32 Master on port %s", config.UART_MASTER_PORT)
            self.simulation_mode = False
        except serial.SerialException as e:
            logger.warning("Could not connect to UART port %s (%s). Will retry continuously. (Use standalone stm32_sim.py tool for simulation).", config.UART_MASTER_PORT, e)
            self.simulation_mode = True

    def send_frame(self, main_evt: int, sub_evt: int, data: bytes = b""):
        """
        Thread-safe wrapper to construct and transmit binary frames down to STM32 Master.
        Format: AA [MAIN] [SUB] [LEN] [DATA] [CHECKSUM] 55
        """
        length = len(data)
        frame = bytearray([0xAA, main_evt, sub_evt, length])
        frame.extend(data)
        
        # XOR Checksum of MAIN, SUB, LEN, and DATA
        chk = main_evt ^ sub_evt ^ length
        for b in data:
            chk ^= b
        frame.append(chk)
        frame.append(0x55)
        
        with self.lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.write(frame)
                    logger.debug("Sent UART frame: %s", frame.hex().upper())
                except serial.SerialException as e:
                    logger.error("Error writing to serial: %s", e)

    def run(self):
        self.running = True
        self.open_port()

        while self.running:
            if not self.ser or not self.ser.is_open:
                time.sleep(2)
                self.open_port()
                continue
                
            try:
                waiting = self.ser.in_waiting
                if waiting > 0:
                    data_bytes = self.ser.read(waiting)
                    for byte in data_bytes:
                        self.parse_byte(byte)
            except Exception as e:
                logger.error("Error reading serial data: %s", e)
                time.sleep(1)
                
            time.sleep(0.01)

    def parse_byte(self, b: int):
        if self.state == "STX":
            if b == 0xAA:
                self.state = "MAIN"
        elif self.state == "MAIN":
            self.rx_main = b
            self.state = "SUB"
        elif self.state == "SUB":
            self.rx_sub = b
            self.state = "LEN"
        elif self.state == "LEN":
            self.rx_len = b
            self.rx_data = bytearray()
            if self.rx_len > 0:
                self.state = "DATA"
            else:
                self.state = "CHECKSUM"
        elif self.state == "DATA":
            self.rx_data.append(b)
            if len(self.rx_data) >= self.rx_len:
                self.state = "CHECKSUM"
        elif self.state == "CHECKSUM":
            self.rx_chk = b
            self.state = "ETX"
        elif self.state == "ETX":
            if b == 0x55:
                # Calculate and verify checksum
                chk = self.rx_main ^ self.rx_sub ^ self.rx_len
                for x in self.rx_data:
                    chk ^= x
                if chk == self.rx_chk:
                    self.process_received_frame(self.rx_main, self.rx_sub, self.rx_data)
                else:
                    logger.warning("Checksum mismatch! Calc: 0x%02X, Recv: 0x%02X", chk, self.rx_chk)
            self.state = "STX"

    def process_received_frame(self, main_evt: int, sub_evt: int, data: bytearray):
        logger.debug("Received UART Frame: Main=0x%02X, Sub=0x%02X, Len=%d, Hex=%s", 
                     main_evt, sub_evt, len(data), data.hex().upper())
                     
        if main_evt == 0xF0:
            # GPS Telemetry: "lat,lon,speed"
            try:
                gps_str = data.decode("ascii")
                lat, lon, speed = map(float, gps_str.split(","))
                self.gps_received.emit(lat, lon, speed)
            except Exception as e:
                logger.error("Failed to parse GPS telemetry: %s", e)
                
        elif main_evt == 0xF1:
            # Seat Status: "s1:0s2:1...s16:0"
            try:
                status_str = data.decode("ascii")
                # Parse s1:0 s2:1 ... s16:0
                # Use split to separate tokens
                # Quick regex replacement or manual parsing
                seats = {}
                tokens = status_str.replace("s", "").split(":")
                # tokens looks like: ['', '1', '02', '13', '04', '05', '06', '07', '08', '09', '010', '011', '012', '013', '014', '015', '016', '0']
                # Better: format is s1:0s2:1s3:0...
                # Let's parse with substrings since formats are regular
                # e.g., finding sX:Y
                import re
                matches = re.findall(r"s(\d+):([01])", status_str)
                for seat_num, occupied in matches:
                    seats[seat_num] = int(occupied)
                
                if len(seats) == 16:
                    self.seats_received.emit(seats)
            except Exception as e:
                logger.error("Failed to parse Seat status: %s (Raw: %s)", e, data)
                
        elif main_evt == 0xF2:
            # RFID Card ID scanned
            try:
                card_str = data.decode("ascii").strip()
                self.rfid_received.emit(card_str)
            except Exception as e:
                logger.error("Failed to decode RFID: %s", e)
                
        elif main_evt == 0xF3:
            # SOS Button Pressed
            self.sos_received.emit()
            
        elif main_evt == 0xF5:
            # DHT11 Temperature/humidity: "temp,humid"
            try:
                dht_str = data.decode("ascii")
                temp, humid = map(float, dht_str.split(","))
                self.dht11_received.emit(temp, humid)
            except Exception as e:
                logger.error("Failed to parse DHT11 telemetry: %s", e)

    def stop(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.wait()
