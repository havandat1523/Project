import os
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QGridLayout, 
                             QMessageBox, QFrame, QTextEdit, QComboBox)
from PyQt5.QtCore import pyqtSlot, Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap, QFont
from config import config
from services.logger import get_logger

from apps.camera.camera_service import FaceVectorWorker

logger = get_logger("UI")

class BusMonitoringApp(QMainWindow):
    # Signals for thread-safe UI updates from MQTT callbacks
    driver_login_ack_signal = pyqtSignal(dict)
    driver_logout_ack_signal = pyqtSignal(dict)
    attendant_login_ack_signal = pyqtSignal(dict)
    attendant_logout_ack_signal = pyqtSignal(dict)
    server_command_signal = pyqtSignal(dict)

    def __init__(self, uart_thread, mqtt_client, camera_service, auth_service, session_manager, boarding_logic, seat_debouncer):
        super().__init__()
        self.uart = uart_thread
        self.mqtt = mqtt_client
        self.camera = camera_service
        self.auth = auth_service
        self.session = session_manager
        self.boarding = boarding_logic
        self.debouncer = seat_debouncer
        
        self.setWindowTitle(f"SchoolBus Gateway - {config.VEHICLE_ID}")
        self.resize(1024, 768)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #12121e;
            }
            QWidget {
                color: #e2e2ec;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QFrame {
                background-color: #1a1a2e;
                border-radius: 12px;
                border: 1px solid #2e2e4f;
            }
            QLabel {
                font-size: 14px;
            }
            QPushButton {
                background-color: #3b3b5c;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background-color: #4c4c78;
            }
            QPushButton:pressed {
                background-color: #2c2c45;
            }
            QPushButton#sosBtn {
                background-color: #c0392b;
            }
            QPushButton#sosBtn:hover {
                background-color: #e74c3c;
            }
            QPushButton#loginBtn {
                background-color: #27ae60;
            }
            QPushButton#loginBtn:hover {
                background-color: #2ecc71;
            }
            QTextEdit {
                background-color: #0c0c16;
                border: 1px solid #2e2e4f;
                border-radius: 8px;
                color: #00ff66;
                font-family: 'Consolas', monospace;
                font-size: 12px;
            }
        """)

        # Main Widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        
        # State tracking UI elements
        self.seat_labels = {}
        self.latest_seats_state = {str(i): 0 for i in range(1, 17)}
        self.latest_temp = 0.0
        self.latest_humid = 0.0
        
        # Build panels
        self.init_ui()
        
        # Connect background signals
        self.connect_signals()
        
        # UI Refresh timer (every 1 second)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status_labels)
        self.timer.start(1000)

    def init_ui(self):
        # Create left video panel
        self.left_panel = QFrame()
        self.left_layout = QVBoxLayout(self.left_panel)
        
        self.video_label = QLabel("Camera Stream Loading...")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setFixedSize(640, 480)
        self.video_label.setStyleSheet("background-color: black; border-radius: 8px; border: 2px solid #2e2e4f;")
        self.left_layout.addWidget(self.video_label)
        
        # Logging field
        self.log_field = QTextEdit()
        self.log_field.setReadOnly(True)
        self.left_layout.addWidget(self.log_field)
        self.log("SchoolBus Gateway running.")
        
        # Create right dashboard panel
        self.right_panel = QFrame()
        self.right_layout = QVBoxLayout(self.right_panel)
        
        # Dashboard header
        self.header_label = QLabel(f"XE: {config.VEHICLE_ID}")
        self.header_label.setFont(QFont("Arial", 18, QFont.Bold))
        self.header_label.setStyleSheet("color: #00bcd4;")
        self.right_layout.addWidget(self.header_label)
        
        # Status Card info
        self.status_frame = QFrame()
        self.status_layout = QVBoxLayout(self.status_frame)
        self.driver_label = QLabel("Tài xế: Chưa đăng nhập")
        self.attendant_label = QLabel("Phụ xe: Chưa đăng nhập")
        self.passenger_label = QLabel("Học sinh trên xe: 0")
        self.gps_label = QLabel("Tọa độ: Đang định vị...")
        self.dht_label = QLabel("Nhiệt độ: -- C | Độ ẩm: -- %")
        
        self.status_layout.addWidget(self.driver_label)
        self.status_layout.addWidget(self.attendant_label)
        self.status_layout.addWidget(self.passenger_label)
        self.status_layout.addWidget(self.gps_label)
        self.status_layout.addWidget(self.dht_label)
        self.right_layout.addWidget(self.status_frame)
        
        # Seat grid panel
        self.seats_frame = QFrame()
        self.seats_layout = QGridLayout(self.seats_frame)
        self.seats_layout.setSpacing(6)
        
        # Generate 16 seat indicators
        for i in range(1, 17):
            lbl = QLabel(f"G{i}")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(50, 45)
            # Seat styles: 1,2 are staff (driver/attendant), 3-16 are students
            lbl.setStyleSheet("background-color: #2c3e50; border-radius: 6px; font-weight: bold; font-size: 14px;")
            self.seat_labels[str(i)] = lbl
            
            # 4x4 Grid layout
            row = (i - 1) // 4
            col = (i - 1) % 4
            self.seats_layout.addWidget(lbl, row, col)
            
        self.right_layout.addWidget(self.seats_frame)
        
        # Actions Layout
        self.actions_layout = QHBoxLayout()
        
        self.login_btn = QPushButton("TÀI XẾ ĐĂNG NHẬP")
        self.login_btn.setObjectName("loginBtn")
        self.login_btn.clicked.connect(self.driver_login_click)
        self.actions_layout.addWidget(self.login_btn)
        
        self.logout_btn = QPushButton("ĐĂNG XUẤT")
        self.logout_btn.setEnabled(False)
        self.logout_btn.clicked.connect(self.driver_logout_click)
        self.actions_layout.addWidget(self.logout_btn)
        
        self.right_layout.addLayout(self.actions_layout)
        
        # Config combo & SOS Button
        self.bottom_layout = QHBoxLayout()
        
        self.phase_box = QComboBox()
        self.phase_box.addItems(["Morning Pickup (PICKUP)", "Arrive School", "Depart School", "Afternoon Dropoff (DROPOFF)"])
        self.phase_box.currentIndexChanged.connect(self.trip_phase_changed)
        self.phase_box.setStyleSheet("background-color: #3b3b5c; padding: 8px; border-radius: 6px; font-weight: bold;")
        self.bottom_layout.addWidget(self.phase_box)
        
        self.sos_btn = QPushButton("SOS KHẨN CẤP")
        self.sos_btn.setObjectName("sosBtn")
        self.sos_btn.clicked.connect(self.sos_click)
        self.bottom_layout.addWidget(self.sos_btn)
        
        self.right_layout.addLayout(self.bottom_layout)
        
        # Assemble main splits
        self.main_layout.addWidget(self.left_panel, 2)
        self.main_layout.addWidget(self.right_panel, 1)

    def log(self, text):
        self.log_field.append(text)
        logger.info(text)

    def connect_signals(self):
        # Connect Camera frame callback
        self.camera.frame_received.connect(self.update_video_frame)
        
        # Connect Serial input callbacks
        self.uart.gps_received.connect(self.on_gps_received)
        self.uart.seats_received.connect(self.on_seats_received)
        self.uart.rfid_received.connect(self.on_rfid_received)
        self.uart.sos_received.connect(self.on_sos_received)
        self.uart.dht11_received.connect(self.on_dht11_received)

        # Connect MQTT response signals to main thread handlers
        self.driver_login_ack_signal.connect(self._handle_driver_login_ack)
        self.driver_logout_ack_signal.connect(self._handle_driver_logout_ack)
        self.attendant_login_ack_signal.connect(self._handle_attendant_login_ack)
        self.attendant_logout_ack_signal.connect(self._handle_attendant_logout_ack)
        self.server_command_signal.connect(self._handle_server_command)

    @pyqtSlot(QImage)
    def update_video_frame(self, image):
        pixmap = QPixmap.fromImage(image)
        target_w = max(self.video_label.width(), 320)
        target_h = max(self.video_label.height(), 240)
        self.video_label.setPixmap(pixmap.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @pyqtSlot(float, float, float)
    def on_gps_received(self, lat, lon, speed):
        self.gps_label.setText(f"Tọa độ: {lat:.6f}, {lon:.6f} | Vận tốc: {speed:.1f} km/h")
        self.boarding.update_gps(lat, lon, speed)
        # Periodic publish of telemetry
        self.mqtt.publish_message(14, {
            "lat": lat,
            "lon": lon,
            "speed_kmh": speed,
            "students_onboard": len(self.boarding.students_onboard),
            "temperature": self.latest_temp,
            "humidity": self.latest_humid
        }, priority=0)

    @pyqtSlot(dict)
    def on_seats_received(self, raw_seats):
        # Pass raw seats to double debounce filter on Pi
        changed, debounced_seats = self.debouncer.update_raw_seats(raw_seats)
        self.latest_seats_state = debounced_seats
        
        # Synchronize indicators
        for seat_num, occupied in debounced_seats.items():
            lbl = self.seat_labels.get(seat_num)
            if lbl:
                if occupied == 1:
                    # Highlight seat: orange for students, purple for staff
                    color = "#9b59b6" if seat_num in ("1", "2") else "#e67e22"
                    lbl.setStyleSheet(f"background-color: {color}; border-radius: 6px; font-weight: bold; font-size: 14px; color: white;")
                else:
                    lbl.setStyleSheet("background-color: #2c3e50; border-radius: 6px; font-weight: bold; font-size: 14px; color: #a0a0a0;")
                    
        # Update seat pointer inside presence monitor
        # Set students onboard counts
        student_seats = sum(1 for i in range(3, 17) if debounced_seats.get(str(i), 0) == 1)
        self.session.set_student_count(student_seats)
        self.passenger_label.setText(f"Học sinh trên xe: {student_seats}")
        
        # Forward updates to boarding logic (child alone logic, bulk unloading)
        self.boarding.update_seats(debounced_seats)
        
        # If seat status changed, publish updates
        if changed:
            self.log("Seat configuration change detected.")
            # Convert dictionary keys to int for MQTT payload
            formatted_seats = {int(k): v for k, v in debounced_seats.items()}
            self.mqtt.publish_message(13, {"seats": formatted_seats}, priority=1)

    @pyqtSlot(str)
    def on_rfid_received(self, rfid_uid):
        self.log(f"Thẻ RFID quẹt trên xe: {rfid_uid}")
        
        # Check if attendant login
        if self.auth.active_driver and not self.auth.active_attendant:
            # Attendant logins (sends type 6 request to server)
            self.log("Sending Attendant check-in request...")
            self.mqtt.publish_message(6, {"rfid_code": rfid_uid}, priority=1)
        elif self.auth.active_attendant and rfid_uid == self.auth.active_attendant.get("rfid_code"):
            # Attendant logouts (sends type 8 request to server)
            self.log("Sending Attendant check-out request...")
            self.mqtt.publish_message(8, {"rfid_code": rfid_uid}, priority=1)
        else:
            # Student check-in / check-out
            self.boarding.handle_rfid_scan(rfid_uid)

    @pyqtSlot()
    def on_sos_received(self):
        self.log("!!! CẢNH BÁO SOS NHẬN TỪ SLAVE !!!")
        self.trigger_sos_broadcast()

    @pyqtSlot(float, float)
    def on_dht11_received(self, temp, humid):
        self.latest_temp = temp
        self.latest_humid = humid
        self.dht_label.setText(f"Nhiệt độ: {temp:.1f} °C | Độ ẩm: {humid:.1f} %")

    def trip_phase_changed(self, idx):
        phases = ["PICKUP", "ARRIVE_SCHOOL", "DEPART_SCHOOL", "DROPOFF"]
        selected_phase = phases[idx]
        self.boarding.set_trip_phase(selected_phase)
        self.log(f"Chuyển giai đoạn tuyến: {selected_phase}")

    def driver_login_click(self):
        self.log("Đang lấy đặc trưng khuôn mặt tài xế (vui lòng nhìn vào camera)...")
        self.login_btn.setEnabled(False)
        self.login_btn.setText("ĐANG QUÉT KHUÔN MẶT...")
        
        self.login_face_worker = FaceVectorWorker(self.camera)
        self.login_face_worker.vector_ready.connect(self.on_login_face_captured)
        self.login_face_worker.start()

    def on_login_face_captured(self, vector):
        self.login_btn.setText("TÀI XẾ ĐĂNG NHẬP")
        self.login_btn.setEnabled(True)
        
        if vector is None:
            QMessageBox.critical(self, "Lỗi đăng nhập", "Không phát hiện khuôn mặt tài xế! Vui lòng căn chỉnh lại khuôn mặt trước camera.")
            return
            
        # Try offline authentication first as fallback
        cached_user = self.auth.match_face_offline(vector, "driver")
        if cached_user and not self.mqtt.is_connected:
            self.log(f"Mất mạng. Xác thực offline thành công: {cached_user['full_name']}")
            self.session.process_driver_login(cached_user["user_id"], cached_user["full_name"])
            self.update_status_labels()
            return
            
        # Send online auth request (type 1)
        if self.mqtt.is_connected:
            self.log("Sending online Driver verification request...")
            self._login_vector = vector
            self.mqtt.publish_message(1, {"face_vector": vector}, priority=1)
        else:
            QMessageBox.critical(self, "Lỗi kết nối", "Không có mạng và tài xế chưa được đồng bộ offline!")

    def driver_logout_click(self):
        can_logout, reason = self.session.can_driver_logout()
        if not can_logout:
            QMessageBox.warning(self, "Không thể đăng xuất", reason)
            return
            
        self.log("Xác thực khuôn mặt trước khi đăng xuất...")
        self.logout_btn.setEnabled(False)
        
        self.logout_face_worker = FaceVectorWorker(self.camera)
        self.logout_face_worker.vector_ready.connect(self.on_logout_face_captured)
        self.logout_face_worker.start()

    def on_logout_face_captured(self, vector):
        self.logout_btn.setEnabled(True)
        if vector is None:
            QMessageBox.critical(self, "Lỗi xác thực", "Không phát hiện khuôn mặt tài xế!")
            return
            
        if self.auth.verify_driver_presence(vector):
            self.mqtt.publish_message(3, {}, priority=1)
            self.session.process_driver_logout()
            self.update_status_labels()
        else:
            self.log("Đăng xuất thất bại: Khuôn mặt không khớp!")
            QMessageBox.critical(self, "Lỗi xác thực", "Khuôn mặt đăng xuất không khớp với tài xế hiện tại!")

    def sos_click(self):
        self.log("!!! NÚT SOS TRÊN XE ĐƯỢC NHẤN !!!")
        self.trigger_sos_broadcast()

    def trigger_sos_broadcast(self):
        # Play local alarm voice code 07/001
        self.uart.send_frame(0x07, 0x01)
        # Send Emergency SOS (type 15) to Server
        self.mqtt.publish_message(15, {
            "lat": self.boarding.school_lat if self.gps_label.text() == "Tọa độ: Đang định vị..." else 21.0021, # fallback
            "lon": 105.8462,
            "triggered_by": 1, # 1 = driver / 2 = student
            "seat_number": 1
        }, priority=2)

    def update_status_labels(self):
        # 1. Driver Label
        if self.auth.active_driver:
            self.driver_label.setText(f"Tài xế: {self.auth.active_driver['full_name']} (Mã: {self.auth.active_driver['driver_id']})")
            self.login_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)
        else:
            self.driver_label.setText("Tài xế: Chưa đăng nhập")
            self.login_btn.setEnabled(True)
            self.logout_btn.setEnabled(False)
            
        # 2. Attendant Label
        if self.auth.active_attendant:
            self.attendant_label.setText(f"Phụ xe: {self.auth.active_attendant['full_name']}")
        else:
            self.attendant_label.setText("Phụ xe: Chưa đăng nhập")

    # Callbacks triggered by MQTT response messages (called from MQTT Background Thread)
    def on_driver_login_ack(self, data):
        self.driver_login_ack_signal.emit(data)

    def on_driver_logout_ack(self, data):
        self.driver_logout_ack_signal.emit(data)

    def on_attendant_login_ack(self, data):
        self.attendant_login_ack_signal.emit(data)

    def on_attendant_logout_ack(self, data):
        self.attendant_logout_ack_signal.emit(data)

    def on_server_command(self, data):
        self.server_command_signal.emit(data)

    # Main GUI Thread handlers for MQTT Signals
    @pyqtSlot(dict)
    def _handle_driver_login_ack(self, data):
        result = data.get("result", 0)
        if result == 1:
            driver_id = data.get("driver_id")
            name = data.get("full_name")
            self.log(f"Xác thực máy chủ thành công: {name} ({driver_id})")
            
            # Cache face vector locally for future offline check
            if hasattr(self, "_login_vector"):
                self.auth.cache_user_vector(driver_id, "driver", name, self._login_vector)
                
            self.session.process_driver_login(driver_id, name)
            self.update_status_labels()
        else:
            self.log("Màn hình đăng nhập: Tài xế bị từ chối từ Server!")
            self.uart.send_frame(0x01, 0x02)
            QMessageBox.critical(self, "Lỗi đăng nhập", "Tài khoản tài xế không hợp lệ hoặc khuôn mặt không khớp!")

    @pyqtSlot(dict)
    def _handle_driver_logout_ack(self, data):
        self.log("Server confirmed Driver check-out.")

    @pyqtSlot(dict)
    def _handle_attendant_login_ack(self, data):
        result = data.get("result", 0)
        if result == 1:
            att_id = data.get("attendant_id")
            name = data.get("full_name")
            rfid = data.get("rfid_code")
            self.log(f"Phụ xe đăng nhập thành công: {name}")
            
            self.session.process_attendant_login(att_id, name)
            self.auth.active_attendant["rfid_code"] = rfid
            self.update_status_labels()
        else:
            self.log("Đăng nhập phụ xe thất bại!")
            self.uart.send_frame(0x03, 0x02)

    @pyqtSlot(dict)
    def _handle_attendant_logout_ack(self, data):
        self.session.process_attendant_logout()
        self.update_status_labels()

    @pyqtSlot(dict)
    def _handle_server_command(self, data):
        cmd = data.get("cmd")
        action = data.get("action")
        
        if cmd == "force_logout":
            self.log("!!! LỆNH ĐĂNG XUẤT CƯỠNG CHẾ TỪ MÁY CHỦ !!!")
            self.session.process_attendant_logout()
            self.session.process_driver_logout()
            self.update_status_labels()
        elif action == "start_stream":
            self.log("!!! NHẬN LỆNH BẬT CAMERA STREAM TỪ SERVER !!!")
            host = data.get("stream_host", "192.168.0.107")
            port = data.get("stream_port", 8554)
            rtsp_url = self.camera.start_streaming(host, port)
            
            if rtsp_url:
                self.log(f"Đang phát luồng video RTSP: {rtsp_url}")
                reply = {
                    "action": "stream_status",
                    "status": "active",
                    "stream_url": rtsp_url,
                    "message": f"Streaming successfully to {host}:{port}"
                }
                self.mqtt.publish_message(20, reply, priority=1)
            else:
                self.log("Lỗi khởi động phát luồng camera!")
                reply = {
                    "action": "stream_status",
                    "status": "error",
                    "stream_url": "",
                    "message": "Failed to launch streaming process"
                }
                self.mqtt.publish_message(20, reply, priority=1)
        elif action == "stop_stream":
            self.log("!!! NHẬN LỆNH TẮT CAMERA STREAM TỪ SERVER !!!")
            self.camera.stop_streaming()
            reply = {
                "action": "stream_status",
                "status": "inactive",
                "stream_url": "",
                "message": "Stream stopped"
            }
            self.mqtt.publish_message(20, reply, priority=1)

    def closeEvent(self, event):
        self.camera.stop()
        self.uart.stop()
        self.mqtt.stop()
        event.accept()
