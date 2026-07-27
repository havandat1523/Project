import os
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QGridLayout, 
                             QMessageBox, QFrame, QTextEdit, QComboBox)
from PyQt5.QtCore import pyqtSlot, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap, QFont
from config import config
from services.logger import get_logger

from apps.camera.camera_service import FaceVectorWorker

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    WEB_ENGINE_AVAILABLE = True
except ImportError:
    WEB_ENGINE_AVAILABLE = False

logger = get_logger("UI")

class BusMonitoringApp(QMainWindow):
    # Signals for thread-safe UI updates from MQTT callbacks
    driver_login_ack_signal = pyqtSignal(dict)
    driver_logout_ack_signal = pyqtSignal(dict)
    attendant_login_ack_signal = pyqtSignal(dict)
    attendant_logout_ack_signal = pyqtSignal(dict)
    server_command_signal = pyqtSignal(dict)
    vehicle_status_ack_signal = pyqtSignal(dict)
    student_scan_ack_signal = pyqtSignal(dict)

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
        # Create left video & map panel
        self.left_panel = QFrame()
        self.left_layout = QVBoxLayout(self.left_panel)
        
        # Logo and Title Bar
        self.logo_layout = QHBoxLayout()
        logo_path = os.path.join(config.BASE_DIR, "image", "logo.png")
        if os.path.exists(logo_path):
            self.logo_label = QLabel()
            pix = QPixmap(logo_path).scaledToHeight(45, Qt.SmoothTransformation)
            self.logo_label.setPixmap(pix)
            self.logo_layout.addWidget(self.logo_label)
            
        self.app_title = QLabel("HỆ THỐNG GIÁM SÁT XE ĐƯA ĐÓN HỌC SINH")
        self.app_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.app_title.setStyleSheet("color: #00bcd4;")
        self.logo_layout.addWidget(self.app_title)
        self.logo_layout.addStretch()
        self.left_layout.addLayout(self.logo_layout)

        # 4 System Status Indicator Badges (GNSS, Camera, Wifi, Database)
        self.status_badges_layout = QHBoxLayout()
        
        self.badge_gnss = QLabel("GNSS: OFF")
        self.badge_gnss.setStyleSheet("background-color: #c0392b; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")
        
        self.badge_cam = QLabel("CAM: READY")
        self.badge_cam.setStyleSheet("background-color: #27ae60; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")
        
        self.badge_wifi = QLabel("WIFI: DISCONNECTED")
        self.badge_wifi.setStyleSheet("background-color: #c0392b; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")
        
        self.badge_db = QLabel("DB: DISCONNECTED")
        self.badge_db.setStyleSheet("background-color: #c0392b; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")
        
        self.status_badges_layout.addWidget(self.badge_gnss)
        self.status_badges_layout.addWidget(self.badge_cam)
        self.status_badges_layout.addWidget(self.badge_wifi)
        self.status_badges_layout.addWidget(self.badge_db)
        self.left_layout.addLayout(self.status_badges_layout)

        # Camera preview label
        self.video_label = QLabel("Camera Stream Loading...")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setFixedSize(640, 420)
        self.video_label.setStyleSheet("background-color: black; border-radius: 8px; border: 2px solid #2e2e4f;")
        self.left_layout.addWidget(self.video_label)
        
        # OpenStreetMap Map View Widget (Displayed after Driver Login Success)
        if WEB_ENGINE_AVAILABLE:
            self.map_view = QWebEngineView()
            self.map_view.setFixedSize(640, 420)
            self.map_view.setStyleSheet("border-radius: 8px; border: 2px solid #2e2e4f;")
            map_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8" />
                <style>
                    html, body, #map {{ width: 100%; height: 100%; margin: 0; padding: 0; background: #12121e; }}
                    .leaflet-container {{ background: #1a1a2e; }}
                </style>
                <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
                <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            </head>
            <body>
                <div id="map"></div>
                <script>
                    var map = L.map('map').setView([21.003118, 105.845899], 15);
                    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                        maxZoom: 19,
                        attribution: '© OpenStreetMap'
                    }}).addTo(map);
                    
                    var busIcon = L.icon({{
                        iconUrl: 'https://cdn-icons-png.flaticon.com/512/3448/3448339.png',
                        iconSize: [38, 38],
                        iconAnchor: [19, 19],
                        popupAnchor: [0, -10]
                    }});

                    var marker = L.marker([21.003118, 105.845899], {{icon: busIcon}}).addTo(map);
                    marker.bindPopup("<b>Xe Bus: {config.VEHICLE_ID}</b><br>Đang hoạt động").openPopup();
                    
                    function updateMapLocation(lat, lon, speed) {{
                        if (!lat || !lon) return;
                        var newLatLng = new L.LatLng(lat, lon);
                        marker.setLatLng(newLatLng);
                        map.panTo(newLatLng);
                        marker.setPopupContent("<b>Xe Bus: {config.VEHICLE_ID}</b><br>Vận tốc: " + speed + " km/h");
                    }}
                </script>
            </body>
            </html>
            """
            self.map_view.setHtml(map_html)
            self.left_layout.addWidget(self.map_view)
            self.map_view.hide()
        else:
            self.map_view = QFrame()
            self.map_view.setFixedSize(640, 420)
            self.map_view.setStyleSheet("background-color: #1a1a2e; border-radius: 8px; border: 2px solid #2e2e4f;")
            map_layout = QVBoxLayout(self.map_view)
            
            self.map_title_label = QLabel(f"🗺️ BẢN ĐỒ THEO DÕI HÀNH TRÌNH XE {config.VEHICLE_ID}")
            self.map_title_label.setFont(QFont("Arial", 16, QFont.Bold))
            self.map_title_label.setStyleSheet("color: #00bcd4; margin-top: 20px;")
            self.map_title_label.setAlignment(Qt.AlignCenter)
            
            self.map_status_label = QLabel("OpenStreetMap Live Tracking\n\nTọa độ GPS: 21.003118, 105.845899\nVận tốc: 0.0 km/h\n\nTrạng thái: Đã đăng nhập & Đang theo dõi")
            self.map_status_label.setFont(QFont("Arial", 14))
            self.map_status_label.setStyleSheet("color: #00ff66; line-height: 1.6;")
            self.map_status_label.setAlignment(Qt.AlignCenter)
            
            map_layout.addWidget(self.map_title_label)
            map_layout.addWidget(self.map_status_label)
            self.left_layout.addWidget(self.map_view)
            self.map_view.hide()
        
        # Logging field
        self.log_field = QTextEdit()
        self.log_field.setReadOnly(True)
        self.left_layout.addWidget(self.log_field)
        self.log("SchoolBus Gateway running.")
        
        # Create right dashboard panel
        self.right_panel = QFrame()
        self.right_layout = QVBoxLayout(self.right_panel)
        
        # Header Label with Vehicle Placa Plate (#BUS04)
        self.header_label = QLabel(f"XE ĐƯA ĐÓN HỌC SINH - BIỂN SỐ: {config.VEHICLE_ID}")
        self.header_label.setFont(QFont("Arial", 14, QFont.Bold))
        self.header_label.setStyleSheet("color: #00bcd4; padding-bottom: 4px;")
        self.right_layout.addWidget(self.header_label)

        # Crew Info Panel (Driver & Attendant Cards, Page 8/9)
        self.crew_frame = QFrame()
        self.crew_frame.setStyleSheet("background-color: #1a1a2e; border: 1px solid #2e2e4f; border-radius: 8px; padding: 6px;")
        crew_layout = QHBoxLayout(self.crew_frame)
        
        self.driver_card_label = QLabel("TX: Chưa đăng nhập\nMã: ---")
        self.driver_card_label.setStyleSheet("color: #f39c12; font-weight: bold; font-size: 11px;")
        
        self.attendant_card_label = QLabel("PX: Chưa đăng nhập\nMã: ---")
        self.attendant_card_label.setStyleSheet("color: #9b59b6; font-weight: bold; font-size: 11px;")
        
        crew_layout.addWidget(self.driver_card_label)
        crew_layout.addWidget(self.attendant_card_label)
        self.right_layout.addWidget(self.crew_frame)

        # Destination Card ("ĐIỂM ĐẾN TỚI") Widget (Page 8/9)
        self.dest_card = QFrame()
        self.dest_card.setStyleSheet("background-color: #0f1f38; border: 1px solid #1f3b64; border-radius: 10px; padding: 8px;")
        dest_layout = QVBoxLayout(self.dest_card)
        
        dest_header = QLabel("📍 ĐIỂM ĐẾN KẾ TIẾP")
        dest_header.setFont(QFont("Arial", 12, QFont.Bold))
        dest_header.setStyleSheet("color: #f39c12;")
        
        self.dest_student_label = QLabel("Học sinh: Đang cập nhật...")
        self.dest_student_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.dest_student_label.setStyleSheet("color: #ffffff;")
        
        self.dest_address_label = QLabel("Vận tốc: 0.0 Km/h")
        self.dest_address_label.setStyleSheet("color: #00bcd4; font-size: 11px; font-weight: bold;")
        
        self.dest_stats_label = QLabel("Đang trên xe: 0 / 14 | Còn lại: --")
        self.dest_stats_label.setStyleSheet("color: #2ecc71; font-weight: bold; font-size: 11px;")
        
        dest_layout.addWidget(dest_header)
        dest_layout.addWidget(self.dest_student_label)
        dest_layout.addWidget(self.dest_address_label)
        dest_layout.addWidget(self.dest_stats_label)
        self.right_layout.addWidget(self.dest_card)

        # 3 Bottom Summary Cards (HỌC SINH TRÊN XE, GIAI ĐOẠN CHUYẾN, NHIỆT ĐỘ|ĐỘ ẨM - Page 8/9)
        self.summary_cards_layout = QHBoxLayout()
        
        # Card 1: Học sinh trên xe
        self.card_students = QFrame()
        self.card_students.setStyleSheet("background-color: #16243b; border-radius: 8px; padding: 4px;")
        c1_layout = QVBoxLayout(self.card_students)
        c1_title = QLabel("HỌC SINH TRÊN XE")
        c1_title.setStyleSheet("font-size: 10px; color: #e67e22; font-weight: bold;")
        c1_title.setAlignment(Qt.AlignCenter)
        self.lbl_students_count = QLabel("8 / 14")
        self.lbl_students_count.setStyleSheet("font-size: 13px; color: #2ecc71; font-weight: bold;")
        self.lbl_students_count.setAlignment(Qt.AlignCenter)
        c1_layout.addWidget(c1_title)
        c1_layout.addWidget(self.lbl_students_count)
        
        # Card 2: Giai đoạn chuyến
        self.card_phase = QFrame()
        self.card_phase.setStyleSheet("background-color: #16243b; border-radius: 8px; padding: 4px;")
        c2_layout = QVBoxLayout(self.card_phase)
        c2_title = QLabel("GIAI ĐOẠN CHUYẾN")
        c2_title.setStyleSheet("font-size: 10px; color: #e67e22; font-weight: bold;")
        c2_title.setAlignment(Qt.AlignCenter)
        self.lbl_phase_val = QLabel("PICK UP")
        self.lbl_phase_val.setStyleSheet("font-size: 12px; color: #3498db; font-weight: bold;")
        self.lbl_phase_val.setAlignment(Qt.AlignCenter)
        c2_layout.addWidget(c2_title)
        c2_layout.addWidget(self.lbl_phase_val)
        
        # Card 3: Nhiệt độ | Độ ẩm
        self.card_dht = QFrame()
        self.card_dht.setStyleSheet("background-color: #16243b; border-radius: 8px; padding: 4px;")
        c3_layout = QVBoxLayout(self.card_dht)
        c3_title = QLabel("NHIỆT ĐỘ | ĐỘ ẨM")
        c3_title.setStyleSheet("font-size: 10px; color: #e67e22; font-weight: bold;")
        c3_title.setAlignment(Qt.AlignCenter)
        self.lbl_dht_val = QLabel("21 C | 60%")
        self.lbl_dht_val.setStyleSheet("font-size: 12px; color: #9b59b6; font-weight: bold;")
        self.lbl_dht_val.setAlignment(Qt.AlignCenter)
        c3_layout.addWidget(c3_title)
        c3_layout.addWidget(self.lbl_dht_val)
        
        self.summary_cards_layout.addWidget(self.card_students)
        self.summary_cards_layout.addWidget(self.card_phase)
        self.summary_cards_layout.addWidget(self.card_dht)
        self.right_layout.addLayout(self.summary_cards_layout)
        
        # Seat grid panel & Title (SƠ ĐỒ VỊ TRÍ GHẾ NGỒI - Page 8/9)
        self.seats_header = QLabel("SƠ ĐỒ VỊ TRÍ GHẾ NGỒI")
        self.seats_header.setFont(QFont("Arial", 12, QFont.Bold))
        self.seats_header.setStyleSheet("color: #ffffff; padding-top: 4px;")
        self.right_layout.addWidget(self.seats_header)

        self.seats_frame = QFrame()
        self.seats_layout = QGridLayout(self.seats_frame)
        self.seats_layout.setSpacing(6)
        
        for i in range(1, 17):
            lbl = QLabel(f"G{i}")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(44, 38)
            lbl.setStyleSheet("background-color: #2c3e50; border-radius: 6px; font-weight: bold; font-size: 12px;")
            self.seat_labels[str(i)] = lbl
            
            row = (i - 1) // 4
            col = (i - 1) % 4
            self.seats_layout.addWidget(lbl, row, col)
            
        self.right_layout.addWidget(self.seats_frame)

        # Seat Legend (Page 8/9: Tài xế, Phụ xe, Học sinh, Trống)
        self.legend_layout = QHBoxLayout()
        lg1 = QLabel("● TX")
        lg1.setStyleSheet("color: #e67e22; font-size: 10px; font-weight: bold;")
        lg2 = QLabel("● PX")
        lg2.setStyleSheet("color: #9b59b6; font-size: 10px; font-weight: bold;")
        lg3 = QLabel("● Học sinh")
        lg3.setStyleSheet("color: #2ecc71; font-size: 10px; font-weight: bold;")
        lg4 = QLabel("○ Trống")
        lg4.setStyleSheet("color: #bdc3c7; font-size: 10px; font-weight: bold;")
        self.legend_layout.addWidget(lg1)
        self.legend_layout.addWidget(lg2)
        self.legend_layout.addWidget(lg3)
        self.legend_layout.addWidget(lg4)
        self.right_layout.addLayout(self.legend_layout)
        
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
        self.phase_box.setStyleSheet("background-color: #3b3b5c; padding: 6px; border-radius: 6px; font-weight: bold; font-size: 11px;")
        self.bottom_layout.addWidget(self.phase_box)
        
        self.sos_btn = QPushButton("SOS KHẨN CẤP")
        self.sos_btn.setObjectName("sosBtn")
        self.sos_btn.clicked.connect(self.sos_click)
        self.bottom_layout.addWidget(self.sos_btn)
        
        self.right_layout.addLayout(self.bottom_layout)
        
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
        self.vehicle_status_ack_signal.connect(self._handle_vehicle_status_ack)
        self.student_scan_ack_signal.connect(self._handle_student_scan_ack)

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

        # Update GNSS Badge status
        if speed >= 0:
            self.badge_gnss.setText(f"GNSS: ACTIVE ({speed:.0f} km/h)")
            self.badge_gnss.setStyleSheet("background-color: #27ae60; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")
        else:
            self.badge_gnss.setText("GNSS: DEGRADE")
            self.badge_gnss.setStyleSheet("background-color: #f39c12; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")

        # Update OpenStreetMap position if map view is active
        if hasattr(self, 'map_view') and self.map_view.isVisible():
            if WEB_ENGINE_AVAILABLE:
                self.map_view.page().runJavaScript(f"updateMapLocation({lat}, {lon}, {speed});")
            elif hasattr(self, 'map_status_label'):
                self.map_status_label.setText(f"OpenStreetMap Live Tracking\n\nTọa độ GPS: {lat:.6f}, {lon:.6f}\nVận tốc: {speed:.1f} km/h\n\nTrạng thái: Đã đăng nhập & Đang theo dõi")

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
                    color = "#9b59b6" if seat_num in ("1", "2") else "#e67e22"
                    lbl.setStyleSheet(f"background-color: {color}; border-radius: 6px; font-weight: bold; font-size: 14px; color: white;")
                else:
                    lbl.setStyleSheet("background-color: #2c3e50; border-radius: 6px; font-weight: bold; font-size: 14px; color: #a0a0a0;")
                    
        student_seats = sum(1 for i in range(3, 17) if debounced_seats.get(str(i), 0) == 1)
        self.session.set_student_count(student_seats)
        self.passenger_label.setText(f"Học sinh trên xe: {student_seats}")
        
        self.boarding.update_seats(debounced_seats)
        
        if changed:
            self.log("Seat configuration change detected.")
            formatted_seats = {int(k): v for k, v in debounced_seats.items()}
            self.mqtt.publish_message(13, {"seats": formatted_seats}, priority=1)

    @pyqtSlot(str)
    def on_rfid_received(self, rfid_uid):
        self.log(f"Thẻ RFID quẹt trên xe: {rfid_uid}")
        
        if self.auth.active_driver and not self.auth.active_attendant:
            self.log("Sending Attendant check-in request...")
            self.mqtt.publish_message(6, {"rfid_code": rfid_uid}, priority=1)
        elif self.auth.active_attendant and rfid_uid == self.auth.active_attendant.get("rfid_code"):
            self.log("Sending Attendant check-out request...")
            self.mqtt.publish_message(8, {"rfid_code": rfid_uid}, priority=1)
        else:
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
        
        # Specific login error 1: No driver detected in camera frame
        if vector is None:
            self.log("Lỗi đăng nhập: Không thấy tài xế trong khung hình camera!")
            self.uart.send_frame(0x01, 0x02)
            QMessageBox.critical(self, "Lỗi Đăng Nhập", "Không thấy tài xế!\n\nCamera không phát hiện khuôn mặt tài xế. Vui lòng đứng đúng vị trí trước camera.")
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
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("KHÔNG THỂ ĐĂNG XUẤT")
            msg_box.setText(f"⚠️ KHÔNG THỂ ĐĂNG XUẤT\n\nCảnh báo an toàn (Đặc tả 2.8):\n{reason}")
            msg_box.addButton("ĐÃ HIỂU - KIỂM TRA XE NGAY", QMessageBox.AcceptRole)
            msg_box.exec_()
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
            
            if hasattr(self, 'map_view') and hasattr(self, 'video_label'):
                self.map_view.hide()
                self.video_label.show()
            self.log("Tài xế đã đăng xuất thành công. Chuyển màn hình về Camera Stream.")
        else:
            self.log("Đăng xuất thất bại: Khuôn mặt không khớp!")
            QMessageBox.critical(self, "Lỗi xác thực", "Khuôn mặt đăng xuất không khớp với tài xế hiện tại!")

    def sos_click(self):
        self.log("!!! NÚT SOS TRÊN XE ĐƯỢC NHẤN !!!")
        self.trigger_sos_broadcast()
        
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("CẢNH BÁO SOS")
        msg_box.setText(f"🚨 CẢNH BÁO SOS ĐÃ ĐƯỢC KÍCH HOẠT!\n\nĐã phát còi cảnh báo khẩn cấp trên xe & gửi tọa độ GPS khẩn (Type 15 QoS 2) về Server Quản Trị.\n\n• Biển số xe: {config.VEHICLE_ID} (#BUS04)\n• Trạng thái: Đang phát tín hiệu ưu tiên cao nhất")
        msg_box.addButton("HỦY CẢNH BÁO SOS", QMessageBox.RejectRole)
        msg_box.exec_()

    def trigger_sos_broadcast(self):
        self.uart.send_frame(0x07, 0x01)
        self.mqtt.publish_message(15, {
            "lat": self.boarding.school_lat if self.gps_label.text() == "Tọa độ: Đang định vị..." else 21.0021,
            "lon": 105.8462,
            "triggered_by": 1,
            "seat_number": 1
        }, priority=2)

    def update_status_labels(self):
        # Update Wifi & DB badges
        if self.mqtt.is_connected:
            self.badge_wifi.setText("WIFI: CONNECTED")
            self.badge_wifi.setStyleSheet("background-color: #27ae60; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")
            self.badge_db.setText("DB: CONNECTED")
            self.badge_db.setStyleSheet("background-color: #27ae60; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")
        else:
            self.badge_wifi.setText("WIFI: DISCONNECTED")
            self.badge_wifi.setStyleSheet("background-color: #c0392b; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")
            self.badge_db.setText("DB: DISCONNECTED")
            self.badge_db.setStyleSheet("background-color: #c0392b; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")

        # Update Camera Badge
        if getattr(self.camera, 'is_streaming', False):
            self.badge_cam.setText("CAM: STREAMING")
            self.badge_cam.setStyleSheet("background-color: #2980b9; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")
        elif getattr(self.camera, 'running', False):
            self.badge_cam.setText("CAM: READY")
            self.badge_cam.setStyleSheet("background-color: #27ae60; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")
        else:
            self.badge_cam.setText("CAM: OFF")
            self.badge_cam.setStyleSheet("background-color: #c0392b; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 12px;")

        # 1. Driver Card & State
        if self.auth.active_driver:
            d_name = self.auth.active_driver.get("full_name", "Tài xế")
            d_id = self.auth.active_driver.get("driver_id", "---")
            d_lic = self.auth.active_driver.get("license_class", "B2")
            self.driver_card_label.setText(f"TX: {d_name}\nMã: {d_id} . Bằng: {d_lic}")
            self.login_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)
        else:
            self.driver_card_label.setText("TX: Chưa đăng nhập\nMã: ---")
            self.login_btn.setEnabled(True)
            self.logout_btn.setEnabled(False)
            
        # 2. Attendant Card & State
        if self.auth.active_attendant:
            att_name = self.auth.active_attendant.get("full_name", "Phụ xe")
            att_id = self.auth.active_attendant.get("attendant_id", "---")
            self.attendant_card_label.setText(f"PX: {att_name}\nMã: {att_id}")
        else:
            self.attendant_card_label.setText("PX: Chưa đăng nhập\nMã: ---")

        # 3. Dynamic Summary Cards
        onboard_count = sum(1 for i in range(3, 17) if self.latest_seats_state.get(str(i), 0) == 1)
        self.lbl_students_count.setText(f"{onboard_count} / 14")
        self.lbl_phase_val.setText(getattr(self.boarding, "trip_phase", "PICKUP"))
        self.lbl_dht_val.setText(f"{self.latest_temp:.0f} C | {self.latest_humid:.0f}%")

    # Callbacks triggered by MQTT response messages
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

    def on_vehicle_status_ack(self, data):
        self.vehicle_status_ack_signal.emit(data)

    def on_student_scan_ack(self, data):
        self.student_scan_ack_signal.emit(data)

    # Main GUI Thread handlers for MQTT Signals
    @pyqtSlot(dict)
    def _handle_driver_login_ack(self, data):
        result = data.get("result", 0)
        if result == 1:
            driver_id = data.get("driver_id")
            name = data.get("full_name")
            self.log(f"Xác thực máy chủ thành công: {name} ({driver_id})")
            self.uart.send_frame(0x01, 0x01, driver_id.encode("ascii"))
            self.log("Chuyển màn hình sang Bản đồ theo dõi OpenStreetMap!")
            
            if hasattr(self, 'map_view') and hasattr(self, 'video_label'):
                self.video_label.hide()
                self.map_view.show()

            if hasattr(self, "_login_vector"):
                self.auth.cache_user_vector(driver_id, "driver", name, self._login_vector)
                
            self.session.process_driver_login(driver_id, name)
            self.update_status_labels()
        else:
            # Specific login error 2: Face vector mismatch
            self.log("Màn hình đăng nhập: Tài xế bị từ chối từ Server (Không khớp khuôn mặt)!")
            self.uart.send_frame(0x01, 0x02)
            QMessageBox.critical(self, "Lỗi Đăng Nhập", "Không khớp khuôn mặt!\n\nMẫu khuôn mặt không trùng khớp với dữ liệu tài xế đã đăng ký.")

    @pyqtSlot(dict)
    def _handle_vehicle_status_ack(self, data):
        session_state = data.get("session_state", 0)
        if session_state == 1:
            # PENDING_CONFIRM
            driver_name = data.get("existing_driver_name", "Tài xế cũ")
            self.log(f"Đang chờ xác nhận phiên làm việc cho {driver_name} từ trung tâm...")
            self.login_btn.setEnabled(False)
            self.login_btn.setText("ĐANG CHỜ TRUNG TÂM XÁC NHẬN...")
        elif session_state == 2:
            # RESUMED
            driver_id = data.get("driver_id")
            name = data.get("driver_full_name")
            self.log(f"Khôi phục phiên làm việc từ Server: {name} ({driver_id})")
            self.session.process_driver_login(driver_id, name)
            if hasattr(self, 'map_view') and hasattr(self, 'video_label'):
                self.video_label.hide()
                self.map_view.show()
            self.update_status_labels()
        elif session_state == 3 or session_state == 0:
            # REQUIRE_NEW_LOGIN / NONE
            self.log("Cho phép thực hiện đăng nhập tài xế mới.")
            self.login_btn.setEnabled(True)
            self.login_btn.setText("TÀI XẾ ĐĂNG NHẬP")

    @pyqtSlot(dict)
    def _handle_student_scan_ack(self, data):
        next_id = data.get("next_student_id")
        next_name = data.get("next_student_name", "---")
        next_addr = data.get("next_address", "---")
        onboard = data.get("students_onboard", 0)
        remaining = data.get("students_remaining", 0)
        
        self.dest_student_label.setText(f"Học sinh: {next_name}")
        self.dest_address_label.setText(f"Địa chỉ: {next_addr}")
        self.dest_stats_label.setText(f"Đang trên xe: {onboard} | Còn lại: {remaining}")
        self.log(f"Cập nhật Điểm Đến kế tiếp: {next_name} ({next_addr})")

        # If next_student_id is None (list finished), trigger final audio notification 05/003 or 05/004
        if next_id is None:
            phase = getattr(self.boarding, "trip_phase", "PICKUP")
            if phase == "PICKUP":
                self.log("🔊 Phát thông báo 05/003: Học sinh cuối cùng đã lên xe (Chiều đón)")
                self.uart.send_frame(0x05, 0x03)
                self.mqtt.publish_message(12, {"event_code": 503, "students_onboard": onboard}, priority=1)
            elif phase == "DROPOFF":
                self.log("🔊 Phát thông báo 05/004: Học sinh cuối cùng đã xuống xe (Chiều trả)")
                self.uart.send_frame(0x05, 0x04)
                self.mqtt.publish_message(12, {"event_code": 504, "students_onboard": onboard}, priority=1)

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
