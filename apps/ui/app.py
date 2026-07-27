import os
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QGridLayout, 
                             QMessageBox, QFrame, QTextEdit, QComboBox, QStackedWidget, QDialog)
from PyQt5.QtCore import pyqtSlot, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap, QFont, QPainter, QPen, QColor
from config import config
from services.logger import get_logger

from apps.camera.camera_service import FaceVectorWorker

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    WEB_ENGINE_AVAILABLE = True
except ImportError:
    WEB_ENGINE_AVAILABLE = False

logger = get_logger("UI")

# Custom Dialog Popup for Slide 10: Cannot Logout Warning
class CannotLogoutDialog(QDialog):
    def __init__(self, reason_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KHÔNG THỂ ĐĂNG XUẤT")
        self.setFixedSize(540, 340)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        container = QFrame()
        container.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 3px solid #e74c3c;
                border-radius: 20px;
            }
        """)
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(25, 20, 25, 20)
        
        icon_lbl = QLabel("[ ! ]")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setFont(QFont("Arial", 32, QFont.Bold))
        icon_lbl.setStyleSheet("color: #dc2626; border: none;")
        c_layout.addWidget(icon_lbl)
        
        title_lbl = QLabel("KHÔNG THỂ ĐĂNG XUẤT")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title_lbl.setStyleSheet("color: #111111; border: none; margin-bottom: 5px;")
        c_layout.addWidget(title_lbl)
        
        detail_box = QFrame()
        detail_box.setStyleSheet("background-color: #fdf2f2; border: 1px solid #f8d7da; border-radius: 10px; padding: 10px;")
        d_layout = QVBoxLayout(detail_box)
        
        warn_txt = QLabel(f"<b>Cảnh báo an toàn (Đặc tả 2.8):</b><br>{reason_text}")
        warn_txt.setWordWrap(True)
        warn_txt.setFont(QFont("Segoe UI", 11))
        warn_txt.setStyleSheet("color: #c0392b; border: none;")
        d_layout.addWidget(warn_txt)
        
        c_layout.addWidget(detail_box)
        
        btn = QPushButton("ĐÃ HIỂU - KIỂM TRA XE NGAY")
        btn.setFont(QFont("Segoe UI", 12, QFont.Bold))
        btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #ffffff;
                border: none;
                border-radius: 12px;
                padding: 12px;
                margin-top: 10px;
            }
            QPushButton:hover { background-color: #334155; }
        """)
        btn.clicked.connect(self.accept)
        c_layout.addWidget(btn)
        main_layout.addWidget(container)

# Custom Dialog Popup for Slide 12: SOS Alert Triggered
class SOSAlertDialog(QDialog):
    def __init__(self, lat, lon, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CẢNH BÁO SOS")
        self.setFixedSize(560, 380)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        container = QFrame()
        container.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 3px solid #dc2626;
                border-radius: 20px;
            }
        """)
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(25, 20, 25, 20)
        
        icon_lbl = QLabel("[ SOS ]")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setFont(QFont("Arial", 32, QFont.Bold))
        icon_lbl.setStyleSheet("color: #dc2626; border: none;")
        c_layout.addWidget(icon_lbl)
        
        title_lbl = QLabel("CẢNH BÁO SOS ĐÃ ĐƯỢC KÍCH HOẠT!")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title_lbl.setStyleSheet("color: #dc2626; border: none;")
        c_layout.addWidget(title_lbl)
        
        desc = QLabel("Đã phát loa cảnh báo còi khẩn cấp trên xe & gửi tọa độ GPS khẩn (Type 15 QoS 2) về Server Quản Trị.")
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignCenter)
        desc.setFont(QFont("Segoe UI", 10))
        desc.setStyleSheet("color: #4b5563; border: none; margin-bottom: 5px;")
        c_layout.addWidget(desc)
        
        detail_box = QFrame()
        detail_box.setStyleSheet("background-color: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px;")
        d_layout = QVBoxLayout(detail_box)
        
        txt1 = QLabel(f"• Kinh độ/Vĩ độ: {lat:.6f}° N, {lon:.6f}° E")
        txt2 = QLabel(f"• Biển số xe: {config.VEHICLE_ID} (#BUS04)")
        txt3 = QLabel("• Trạng thái: Đang phát tín hiệu ưu tiên cao nhất")
        
        for t in (txt1, txt2, txt3):
            t.setFont(QFont("Consolas", 10))
            t.setStyleSheet("color: #1f2937; border: none;")
            d_layout.addWidget(t)
            
        c_layout.addWidget(detail_box)
        
        btn = QPushButton("HỦY CẢNH BÁO SOS")
        btn.setFont(QFont("Segoe UI", 12, QFont.Bold))
        btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                border: none;
                border-radius: 12px;
                padding: 12px;
                margin-top: 8px;
            }
            QPushButton:hover { background-color: #ef4444; }
        """)
        btn.clicked.connect(self.accept)
        c_layout.addWidget(btn)
        main_layout.addWidget(container)

# Custom Dialog Popup for Session Verification ("ĐANG KIỂM TRA PHIÊN LÀM VIỆC")
class SessionCheckDialog(QDialog):
    def __init__(self, driver_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ĐANG XÁC NHẬN PHIÊN LÀM VIỆC")
        self.setFixedSize(520, 300)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        container = QFrame()
        container.setStyleSheet("background-color: #ffffff; border: 3px solid #0284c7; border-radius: 20px;")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(25, 20, 25, 20)
        
        icon_lbl = QLabel("[ WAIT ]")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setFont(QFont("Arial", 28, QFont.Bold))
        icon_lbl.setStyleSheet("color: #0284c7; border: none;")
        c_layout.addWidget(icon_lbl)
        
        title_lbl = QLabel("ĐANG KIỂM TRA PHIÊN LÀM VIỆC")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setFont(QFont("Arial", 15, QFont.Bold))
        title_lbl.setStyleSheet("color: #0369a1; border: none; margin-bottom: 5px;")
        c_layout.addWidget(title_lbl)
        
        txt = QLabel(f"Hệ thống đang chờ Trung tâm Quản lý xác nhận phiên làm việc dở dang của tài xế <b>{driver_name}</b>...")
        txt.setWordWrap(True)
        txt.setAlignment(Qt.AlignCenter)
        txt.setFont(QFont("Arial", 11))
        txt.setStyleSheet("color: #4b5563; border: none; margin-bottom: 10px;")
        c_layout.addWidget(txt)
        
        btn = QPushButton("ĐÃ HIỂU - CHỜ TRUNG TÂM XÁC NHẬN")
        btn.setFont(QFont("Arial", 11, QFont.Bold))
        btn.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: #ffffff;
                border: none;
                border-radius: 12px;
                padding: 12px;
            }
            QPushButton:hover { background-color: #0369a1; }
        """)
        btn.clicked.connect(self.accept)
        c_layout.addWidget(btn)
        main_layout.addWidget(container)


class BusMonitoringApp(QMainWindow):
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
        self.resize(1024, 680)
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #eef2f5;
            }
            QWidget {
                color: #1f2937;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QFrame#cardFrame {
                background-color: #ffffff;
                border-radius: 16px;
                border: 1px solid #dcdfe6;
            }
            QLabel {
                font-size: 13px;
            }
            QPushButton#orangeBtn {
                background-color: #e67e22;
                border: none;
                border-radius: 10px;
                padding: 10px 18px;
                font-size: 13px;
                font-weight: bold;
                color: white;
            }
            QPushButton#orangeBtn:hover {
                background-color: #d35400;
            }
            QPushButton#sosTopBtn {
                background-color: #dc2626;
                border: none;
                border-radius: 8px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: bold;
                color: white;
            }
            QPushButton#sosTopBtn:hover {
                background-color: #b91c1c;
            }
            QPushButton#logoutTopBtn {
                background-color: #f3f4f6;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: bold;
                color: #374151;
            }
            QPushButton#logoutTopBtn:hover {
                background-color: #e5e7eb;
            }
        """)

        self.seat_labels = {}
        self.latest_seats_state = {str(i): 0 for i in range(1, 17)}
        self.latest_temp = 21.0
        self.latest_humid = 60.0
        self.current_speed = 0.0

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.root_layout = QVBoxLayout(self.central_widget)
        self.root_layout.setContentsMargins(12, 10, 12, 10)
        self.root_layout.setSpacing(10)
        
        self.build_top_header()
        
        self.stack = QStackedWidget()
        self.root_layout.addWidget(self.stack)
        
        self.login_screen = self.build_login_screen()
        self.stack.addWidget(self.login_screen)
        
        self.operating_screen = self.build_operating_screen()
        self.stack.addWidget(self.operating_screen)
        
        self.stack.setCurrentIndex(0)

        self.connect_signals()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status_labels)
        self.timer.start(1000)

    def build_top_header(self):
        header_frame = QFrame()
        header_frame.setObjectName("cardFrame")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 8, 12, 8)
        
        logo_path = os.path.join(config.BASE_DIR, "image", "logo.png")
        if os.path.exists(logo_path):
            logo_lbl = QLabel()
            pix = QPixmap(logo_path).scaledToHeight(40, Qt.SmoothTransformation)
            logo_lbl.setPixmap(pix)
            header_layout.addWidget(logo_lbl)
            
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        
        t_row = QHBoxLayout()
        h_title = QLabel("HỌC VIỆN KÝ THUẬT MẬT MÃ")
        h_title.setFont(QFont("Arial", 13, QFont.Bold))
        h_title.setStyleSheet("color: #991b1b;")
        
        bus_badge = QLabel("#BUS04")
        bus_badge.setFont(QFont("Arial", 11, QFont.Bold))
        bus_badge.setStyleSheet("background-color: #f59e0b; color: white; padding: 2px 8px; border-radius: 4px;")
        
        t_row.addWidget(h_title)
        t_row.addWidget(bus_badge)
        t_row.addStretch()
        
        h_sub = QLabel(f"XE ĐƯA ĐÓN HỌC SINH – BIỂN SỐ: {config.VEHICLE_ID}")
        h_sub.setFont(QFont("Arial", 9, QFont.Bold))
        h_sub.setStyleSheet("color: #4b5563;")
        
        title_box.addLayout(t_row)
        title_box.addWidget(h_sub)
        header_layout.addLayout(title_box)
        
        header_layout.addStretch()
        
        self.badge_gnss = QLabel("GNSS: OFF")
        self.badge_gnss.setStyleSheet("background-color: #ffffff; color: #dc2626; border: 1px solid #fca5a5; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;")
        
        self.badge_cam = QLabel("CAM: READY")
        self.badge_cam.setStyleSheet("background-color: #ffffff; color: #16a34a; border: 1px solid #93c5fd; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;")
        
        self.badge_wifi = QLabel("WIFI: CONNECTED")
        self.badge_wifi.setStyleSheet("background-color: #ffffff; color: #16a34a; border: 1px solid #93c5fd; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;")
        
        self.badge_db = QLabel("DB: DISCONNECTED")
        self.badge_db.setStyleSheet("background-color: #ffffff; color: #dc2626; border: 1px solid #fca5a5; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;")
        
        self.sos_btn = QPushButton("SOS")
        self.sos_btn.setObjectName("sosTopBtn")
        self.sos_btn.clicked.connect(self.sos_click)
        
        header_layout.addWidget(self.badge_gnss)
        header_layout.addWidget(self.badge_cam)
        header_layout.addWidget(self.badge_wifi)
        header_layout.addWidget(self.badge_db)
        header_layout.addWidget(self.sos_btn)
        
        self.root_layout.addWidget(header_frame)

    def build_login_screen(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        cam_card = QFrame()
        cam_card.setObjectName("cardFrame")
        cam_layout = QVBoxLayout(cam_card)
        cam_layout.setContentsMargins(15, 15, 15, 15)
        
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setFixedSize(620, 480)
        self.video_label.setStyleSheet("background-color: #000000; border-radius: 12px; border: 2px solid #1e293b;")
        
        cam_hint = QLabel("GIỮ THẲNG ĐẦU TRƯỚC CAMERA")
        cam_hint.setAlignment(Qt.AlignCenter)
        cam_hint.setFont(QFont("Arial", 12, QFont.Bold))
        cam_hint.setStyleSheet("color: #1f2937; margin-top: 8px;")
        
        self.login_error_toast = QLabel("LOGIN FAILED - Không khớp khuôn mặt")
        self.login_error_toast.setStyleSheet("background-color: #dc2626; color: white; padding: 8px 16px; border-radius: 8px; font-weight: bold;")
        self.login_error_toast.hide()
        
        cam_layout.addWidget(self.video_label)
        cam_layout.addWidget(self.login_error_toast, alignment=Qt.AlignRight)
        cam_layout.addWidget(cam_hint)
        
        layout.addWidget(cam_card, 2)
        
        right_card = QFrame()
        right_card.setObjectName("cardFrame")
        r_layout = QVBoxLayout(right_card)
        r_layout.setContentsMargins(20, 20, 20, 20)
        
        login_header = QHBoxLayout()
        h_txt = QLabel("ĐĂNG NHẬP")
        h_txt.setFont(QFont("Arial", 16, QFont.Bold))
        h_txt.setStyleSheet("color: #ea580c;")
        login_header.addWidget(h_txt)
        login_header.addStretch()
        r_layout.addLayout(login_header)
        
        bus_box = QFrame()
        bus_box.setStyleSheet("background-color: #fef3c7; border-radius: 16px; padding: 15px;")
        b_layout = QVBoxLayout(bus_box)
        b_layout.setAlignment(Qt.AlignCenter)
        
        bus_img_path = os.path.join(config.BASE_DIR, "image", "school_bus.png")
        if os.path.exists(bus_img_path):
            bus_img_lbl = QLabel()
            pix = QPixmap(bus_img_path).scaledToHeight(180, Qt.SmoothTransformation)
            bus_img_lbl.setPixmap(pix)
            b_layout.addWidget(bus_img_lbl)
        else:
            bus_img_lbl = QLabel("SCHOOL BUS")
            bus_img_lbl.setFont(QFont("Arial", 28, QFont.Bold))
            bus_img_lbl.setStyleSheet("color: #d97706;")
            b_layout.addWidget(bus_img_lbl)
            
        r_layout.addWidget(bus_box)
        
        info_sub = QFrame()
        info_sub.setStyleSheet("background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px;")
        i_layout = QVBoxLayout(info_sub)
        i_layout.setAlignment(Qt.AlignCenter)
        
        lbl1 = QLabel("Xác thực tài xế")
        lbl1.setFont(QFont("Arial", 12, QFont.Bold))
        lbl1.setStyleSheet("color: #1e2937;")
        lbl2 = QLabel("Nhấn nút bên dưới để quét khuôn mặt")
        lbl2.setStyleSheet("color: #64748b; font-size: 11px;")
        
        i_layout.addWidget(lbl1, alignment=Qt.AlignCenter)
        i_layout.addWidget(lbl2, alignment=Qt.AlignCenter)
        r_layout.addWidget(info_sub)
        
        r_layout.addStretch()
        
        self.login_btn = QPushButton("ĐĂNG NHẬP")
        self.login_btn.setObjectName("orangeBtn")
        self.login_btn.setFont(QFont("Arial", 14, QFont.Bold))
        self.login_btn.setMinimumHeight(50)
        self.login_btn.clicked.connect(self.driver_login_click)
        r_layout.addWidget(self.login_btn)
        
        layout.addWidget(right_card, 1)
        return page

    def build_operating_screen(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        left_card = QFrame()
        left_card.setObjectName("cardFrame")
        l_layout = QVBoxLayout(left_card)
        l_layout.setContentsMargins(12, 12, 12, 12)
        l_layout.setSpacing(10)
        
        crew_bar = QHBoxLayout()
        
        self.drv_box = QFrame()
        self.drv_box.setStyleSheet("background-color: #fff7ed; border: 1px solid #ffedd5; border-radius: 10px; padding: 6px 12px;")
        drv_l = QHBoxLayout(self.drv_box)
        tx_badge = QLabel("TX")
        tx_badge.setStyleSheet("background-color: #f97316; color: white; font-weight: bold; border-radius: 4px; padding: 4px 8px;")
        self.tx_info = QLabel("Chưa đăng nhập\nMã: ---")
        self.tx_info.setFont(QFont("Arial", 10, QFont.Bold))
        self.tx_info.setStyleSheet("color: #c2410c;")
        drv_l.addWidget(tx_badge)
        drv_l.addWidget(self.tx_info)
        
        self.px_box = QFrame()
        self.px_box.setStyleSheet("background-color: #f0f9ff; border: 1px solid #e0f2fe; border-radius: 10px; padding: 6px 12px;")
        px_l = QHBoxLayout(self.px_box)
        px_badge = QLabel("PX")
        px_badge.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; border-radius: 4px; padding: 4px 8px;")
        self.px_info = QLabel("Chưa đăng nhập\nMã: ---")
        self.px_info.setFont(QFont("Arial", 10, QFont.Bold))
        self.px_info.setStyleSheet("color: #0369a1;")
        px_l.addWidget(px_badge)
        px_l.addWidget(self.px_info)
        
        self.logout_btn = QPushButton("↳ Đăng xuất")
        self.logout_btn.setObjectName("logoutTopBtn")
        self.logout_btn.clicked.connect(self.driver_logout_click)
        
        crew_bar.addWidget(self.drv_box)
        crew_bar.addWidget(self.px_box)
        crew_bar.addStretch()
        crew_bar.addWidget(self.logout_btn)
        l_layout.addLayout(crew_bar)
        
        self.map_container = QFrame()
        self.map_container.setStyleSheet("background-color: #e2e8f0; border-radius: 14px; border: 1px solid #cbd5e1;")
        map_c_layout = QVBoxLayout(self.map_container)
        map_c_layout.setContentsMargins(8, 8, 8, 8)
        
        dest_overlay = QFrame()
        dest_overlay.setStyleSheet("background-color: #ffffff; border-radius: 10px; border: 1px solid #e2e8f0; padding: 8px 14px;")
        d_o_layout = QHBoxLayout(dest_overlay)
        
        self.dest_title_lbl = QLabel("ĐIỂM ĐẾN: LK6D – NGUYỄN VĂN LỘC")
        self.dest_title_lbl.setFont(QFont("Arial", 12, QFont.Bold))
        self.dest_title_lbl.setStyleSheet("color: #0f172a;")
        
        self.speed_lbl = QLabel("0.0 Km/h")
        self.speed_lbl.setFont(QFont("Arial", 14, QFont.Bold))
        self.speed_lbl.setStyleSheet("color: #0284c7;")
        
        d_o_layout.addWidget(self.dest_title_lbl)
        d_o_layout.addStretch()
        d_o_layout.addWidget(self.speed_lbl)
        map_c_layout.addWidget(dest_overlay)
        
        if WEB_ENGINE_AVAILABLE:
            self.map_view = QWebEngineView()
            self.map_view.setStyleSheet("border-radius: 10px;")
            map_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8" />
                <style>
                    html, body, #map {{ width: 100%; height: 100%; margin: 0; padding: 0; background: #e2e8f0; }}
                </style>
                <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
                <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            </head>
            <body>
                <div id="map"></div>
                <script>
                    var map = L.map('map').setView([21.003118, 105.845899], 15);
                    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                        maxZoom: 19, attribution: '© OpenStreetMap'
                    }}).addTo(map);
                    
                    var busIcon = L.icon({{
                        iconUrl: 'https://cdn-icons-png.flaticon.com/512/3448/3448339.png',
                        iconSize: [40, 40], iconAnchor: [20, 20]
                    }});
                    var marker = L.marker([21.003118, 105.845899], {{icon: busIcon}}).addTo(map);
                    
                    function updateMapLocation(lat, lon, speed) {{
                        if (!lat || !lon) return;
                        var newLatLng = new L.LatLng(lat, lon);
                        marker.setLatLng(newLatLng);
                        map.panTo(newLatLng);
                    }}
                </script>
            </body>
            </html>
            """
            self.map_view.setHtml(map_html)
            map_c_layout.addWidget(self.map_view)
        else:
            self.map_view = QLabel("OpenStreetMap Tracking Active")
            self.map_view.setAlignment(Qt.AlignCenter)
            self.map_view.setFont(QFont("Arial", 14, QFont.Bold))
            self.map_view.setStyleSheet("color: #0284c7;")
            map_c_layout.addWidget(self.map_view)
            
        l_layout.addWidget(self.map_container, 3)
        
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        
        c1 = QFrame()
        c1.setStyleSheet("background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 8px;")
        c1_l = QVBoxLayout(c1)
        c1_l.setAlignment(Qt.AlignCenter)
        t1 = QLabel("HỌC SINH TRÊN XE")
        t1.setFont(QFont("Arial", 11, QFont.Bold))
        t1.setStyleSheet("color: #ea580c;")
        self.val_students = QLabel("0 / 14")
        self.val_students.setFont(QFont("Arial", 18, QFont.Bold))
        self.val_students.setStyleSheet("color: #16a34a;")
        c1_l.addWidget(t1, alignment=Qt.AlignCenter)
        c1_l.addWidget(self.val_students, alignment=Qt.AlignCenter)
        
        c2 = QFrame()
        c2.setStyleSheet("background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 8px;")
        c2_l = QVBoxLayout(c2)
        c2_l.setAlignment(Qt.AlignCenter)
        t2 = QLabel("GIAI ĐOẠN CHUYẾN")
        t2.setFont(QFont("Arial", 11, QFont.Bold))
        t2.setStyleSheet("color: #ea580c;")
        self.val_phase = QLabel("PICK UP")
        self.val_phase.setFont(QFont("Arial", 16, QFont.Bold))
        self.val_phase.setStyleSheet("color: #0284c7;")
        c2_l.addWidget(t2, alignment=Qt.AlignCenter)
        c2_l.addWidget(self.val_phase, alignment=Qt.AlignCenter)
        
        c3 = QFrame()
        c3.setStyleSheet("background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 8px;")
        c3_l = QVBoxLayout(c3)
        c3_l.setAlignment(Qt.AlignCenter)
        t3 = QLabel("NHIỆT ĐỘ | ĐỘ ẨM")
        t3.setFont(QFont("Arial", 11, QFont.Bold))
        t3.setStyleSheet("color: #ea580c;")
        self.val_dht = QLabel("21 C | 60%")
        self.val_dht.setFont(QFont("Arial", 16, QFont.Bold))
        self.val_dht.setStyleSheet("color: #9333ea;")
        c3_l.addWidget(t3, alignment=Qt.AlignCenter)
        c3_l.addWidget(self.val_dht, alignment=Qt.AlignCenter)
        
        cards_row.addWidget(c1)
        cards_row.addWidget(c2)
        cards_row.addWidget(c3)
        l_layout.addLayout(cards_row)
        
        layout.addWidget(left_card, 2)
        
        right_card = QFrame()
        right_card.setObjectName("cardFrame")
        r_layout = QVBoxLayout(right_card)
        r_layout.setContentsMargins(15, 15, 15, 15)
        
        seats_title = QLabel("SƠ ĐỒ VỊ TRÍ GHẾ NGỒI")
        seats_title.setFont(QFont("Arial", 13, QFont.Bold))
        seats_title.setStyleSheet("color: #1e2937; margin-bottom: 5px;")
        r_layout.addWidget(seats_title)
        
        seat_grid_frame = QFrame()
        seat_grid_frame.setStyleSheet("background-color: #f8fafc; border-radius: 12px; border: 1px solid #e2e8f0; padding: 8px;")
        sg_layout = QGridLayout(seat_grid_frame)
        sg_layout.setSpacing(8)
        
        for i in range(1, 17):
            lbl = QLabel(f"G{i}")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(48, 40)
            lbl.setStyleSheet("background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; font-weight: bold; font-size: 12px; color: #475569;")
            self.seat_labels[str(i)] = lbl
            
            row = (i - 1) // 4
            col = (i - 1) % 4
            sg_layout.addWidget(lbl, row, col)
            
        r_layout.addWidget(seat_grid_frame)
        r_layout.addStretch()
        
        legend_frame = QHBoxLayout()
        lg1 = QLabel("● Tài xế")
        lg1.setStyleSheet("color: #f97316; font-size: 11px; font-weight: bold;")
        lg2 = QLabel("● Phụ xe")
        lg2.setStyleSheet("color: #0284c7; font-size: 11px; font-weight: bold;")
        lg3 = QLabel("● Học sinh")
        lg3.setStyleSheet("color: #16a34a; font-size: 11px; font-weight: bold;")
        lg4 = QLabel("○ Trống")
        lg4.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
        
        legend_frame.addWidget(lg1)
        legend_frame.addWidget(lg2)
        legend_frame.addWidget(lg3)
        legend_frame.addWidget(lg4)
        r_layout.addLayout(legend_frame)
        
        layout.addWidget(right_card, 1)
        return page

    def log(self, text):
        logger.info(text)

    def connect_signals(self):
        self.driver_login_ack_signal.connect(self._handle_driver_login_ack)
        self.driver_logout_ack_signal.connect(self._handle_driver_logout_ack)
        self.attendant_login_ack_signal.connect(self._handle_attendant_login_ack)
        self.attendant_logout_ack_signal.connect(self._handle_attendant_logout_ack)
        self.server_command_signal.connect(self._handle_server_command)
        self.vehicle_status_ack_signal.connect(self._handle_vehicle_status_ack)
        self.student_scan_ack_signal.connect(self._handle_student_scan_ack)
        
        self.camera.frame_received.connect(self.update_camera_frame)
        self.uart.seats_received.connect(self.on_seats_received)
        self.uart.rfid_received.connect(self.on_rfid_received)
        self.uart.sos_received.connect(self.on_sos_received)
        self.uart.dht11_received.connect(self.on_dht11_received)
        self.uart.gps_received.connect(self.on_gps_received)

    @pyqtSlot(QImage)
    def update_camera_frame(self, q_img):
        if hasattr(self, "video_label") and self.video_label:
            # Burn dashed green bounding box and top orange label directly into frame
            q_img_draw = q_img.convertToFormat(QImage.Format_ARGB32)
            painter = QPainter(q_img_draw)
            painter.setRenderHint(QPainter.Antialiasing)
            
            w, h = q_img_draw.width(), q_img_draw.height()
            box_w, box_h = int(w * 0.55), int(h * 0.65)
            x = (w - box_w) // 2
            y = (h - box_h) // 2 + 10
            
            # Dashed Green Bounding Box
            pen = QPen(QColor("#16a34a"), 4, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(x, y, box_w, box_h, 8, 8)
            
            # Top Orange Label Box: "CĂN MẶT VÀO KHUNG"
            lbl_w, lbl_h = 200, 32
            lbl_x = (w - lbl_w) // 2
            lbl_y = y - 16
            
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ea580c"))
            painter.drawRoundedRect(lbl_x, lbl_y, lbl_w, lbl_h, 6, 6)
            
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Arial", 11, QFont.Bold))
            painter.drawText(lbl_x, lbl_y, lbl_w, lbl_h, Qt.AlignCenter, "CĂN MẶT VÀO KHUNG")
            painter.end()
            
            pix = QPixmap.fromImage(q_img_draw).scaled(
                self.video_label.width(),
                self.video_label.height(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            self.video_label.setPixmap(pix)

    @pyqtSlot(dict)
    def on_seats_received(self, seats_dict):
        processed = self.debouncer.update(seats_dict)
        if processed:
            self.latest_seats_state = processed
            self.boarding.update_seats(processed)
            self.update_seats_ui(processed)

    def update_seats_ui(self, seats_dict):
        for seat_num, status in seats_dict.items():
            if seat_num in self.seat_labels:
                lbl = self.seat_labels[seat_num]
                if seat_num == "1":
                    lbl.setStyleSheet("background-color: #f97316; color: white; border-radius: 6px; font-weight: bold;")
                elif seat_num == "2":
                    lbl.setStyleSheet("background-color: #0284c7; color: white; border-radius: 6px; font-weight: bold;")
                elif status == 1:
                    lbl.setStyleSheet("background-color: #16a34a; color: white; border-radius: 6px; font-weight: bold;")
                else:
                    lbl.setStyleSheet("background-color: #ffffff; color: #475569; border: 1px solid #cbd5e1; border-radius: 6px; font-weight: bold;")

    @pyqtSlot(str)
    def on_rfid_received(self, rfid_uid):
        self.log(f"RFID quẹt: {rfid_uid}")
        if self.auth.active_driver and not self.auth.active_attendant:
            self.mqtt.publish_message(6, {"rfid_code": rfid_uid}, priority=1)
        elif self.auth.active_attendant and rfid_uid == self.auth.active_attendant.get("rfid_code"):
            self.mqtt.publish_message(8, {"rfid_code": rfid_uid}, priority=1)
        else:
            self.boarding.handle_rfid_scan(rfid_uid)

    @pyqtSlot()
    def on_sos_received(self):
        self.sos_click()

    @pyqtSlot(float, float, float)
    def on_gps_received(self, lat, lon, speed):
        self.current_speed = speed
        self.speed_lbl.setText(f"{speed:.1f} Km/h")
        self.badge_gnss.setText("GNSS: ACTIVE")
        self.badge_gnss.setStyleSheet("background-color: #ffffff; color: #16a34a; border: 1px solid #93c5fd; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;")
        self.boarding.update_gps(lat, lon, speed)
        if hasattr(self, "map_view") and WEB_ENGINE_AVAILABLE:
            self.map_view.page().runJavaScript(f"updateMapLocation({lat:.6f}, {lon:.6f}, {speed:.1f});")

    @pyqtSlot(float, float)
    def on_dht11_received(self, temp, humid):
        self.latest_temp = temp
        self.latest_humid = humid
        self.val_dht.setText(f"{temp:.0f} C | {humid:.0f}%")

    def driver_login_click(self):
        self.login_btn.setEnabled(False)
        self.login_btn.setText("ĐANG QUÉT...")
        self.login_error_toast.hide()
        
        self.login_face_worker = FaceVectorWorker(self.camera)
        self.login_face_worker.vector_ready.connect(self.on_login_face_captured)
        self.login_face_worker.start()

    def on_login_face_captured(self, vector):
        self.login_btn.setText("ĐĂNG NHẬP")
        self.login_btn.setEnabled(True)
        
        if vector is None:
            self.uart.send_frame(0x01, 0x02)
            self.login_error_toast.setText("LOGIN FAILED - Không thấy tài xế")
            self.login_error_toast.show()
            return
            
        cached_user = self.auth.match_face_offline(vector, "driver")
        if cached_user and not self.mqtt.is_connected:
            self.session.process_driver_login(cached_user["user_id"], cached_user["full_name"])
            self.stack.setCurrentIndex(1)
            self.update_status_labels()
            return
            
        if self.mqtt.is_connected:
            self._login_vector = vector
            self.mqtt.publish_message(1, {"face_vector": vector}, priority=1)
        else:
            self.login_error_toast.setText("Không có kết nối mạng!")
            self.login_error_toast.show()

    def driver_logout_click(self):
        can_logout, reason = self.session.can_driver_logout()
        if not can_logout:
            dlg = CannotLogoutDialog(reason, self)
            dlg.exec_()
            return
            
        self.logout_face_worker = FaceVectorWorker(self.camera)
        self.logout_face_worker.vector_ready.connect(self.on_logout_face_captured)
        self.logout_face_worker.start()

    def on_logout_face_captured(self, vector):
        if vector is not None and self.auth.verify_driver_presence(vector):
            self.mqtt.publish_message(3, {}, priority=1)
            self.session.process_driver_logout()
            self.stack.setCurrentIndex(0)
            self.update_status_labels()
        else:
            QMessageBox.critical(self, "Lỗi xác thực", "Khuôn mặt đăng xuất không khớp!")

    def sos_click(self):
        self.uart.send_frame(0x07, 0x01)
        self.mqtt.publish_message(15, {"lat": 21.0021, "lon": 105.8462, "triggered_by": 1, "seat_number": 1}, priority=2)
        dlg = SOSAlertDialog(21.0021, 105.8462, self)
        dlg.exec_()

    def update_status_labels(self):
        if self.mqtt.is_connected:
            self.badge_wifi.setText("WIFI: CONNECTED")
            self.badge_wifi.setStyleSheet("background-color: #ffffff; color: #16a34a; border: 1px solid #93c5fd; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;")
        else:
            self.badge_wifi.setText("WIFI: DISCONNECTED")
            self.badge_wifi.setStyleSheet("background-color: #ffffff; color: #dc2626; border: 1px solid #fca5a5; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;")

        if self.auth.active_driver:
            d_name = self.auth.active_driver.get("full_name", "Tài xế")
            d_id = self.auth.active_driver.get("driver_id", "DR_001")
            d_lic = self.auth.active_driver.get("license_class", "B2")
            self.tx_info.setText(f"{d_name}\nMã: {d_id} . Bằng: {d_lic}")
        else:
            self.tx_info.setText("Chưa đăng nhập\nMã: ---")
            
        if self.auth.active_attendant:
            att_name = self.auth.active_attendant.get("full_name", "Phụ xe")
            att_id = self.auth.active_attendant.get("attendant_id", "PX001")
            self.px_info.setText(f"{att_name}\nMã: {att_id}")
        else:
            self.px_info.setText("Chưa đăng nhập\nMã: ---")

        onboard_count = sum(1 for i in range(3, 17) if self.latest_seats_state.get(str(i), 0) == 1)
        self.val_students.setText(f"{onboard_count} / 14")
        self.val_phase.setText(getattr(self.boarding, "trip_phase", "PICKUP"))

    # MQTT Callbacks
    def _handle_driver_login_ack(self, data):
        res = data.get("result", 0)
        if res == 1:
            name = data.get("full_name", "Tài xế")
            driver_id = data.get("driver_id", "DR_001")
            self.uart.send_frame(0x01, 0x01, driver_id.encode("ascii"))
            self.session.process_driver_login(driver_id, name)
            self.stack.setCurrentIndex(1)
            self.update_status_labels()
        else:
            self.uart.send_frame(0x01, 0x02)
            self.login_error_toast.setText("LOGIN FAILED - Không khớp khuôn mặt")
            self.login_error_toast.show()

    def _handle_vehicle_status_ack(self, data):
        session_state = data.get("session_state", 0)
        self.badge_db.setText("DB: CONNECTED")
        self.badge_db.setStyleSheet("background-color: #ffffff; color: #16a34a; border: 1px solid #93c5fd; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;")
        
        if session_state == 1:
            driver_name = data.get("existing_driver_name", "Tài xế cũ")
            dlg = SessionCheckDialog(driver_name, self)
            dlg.exec_()
        elif session_state == 2:
            driver_id = data.get("driver_id")
            name = data.get("driver_full_name")
            self.session.process_driver_login(driver_id, name)
            self.stack.setCurrentIndex(1)
            self.update_status_labels()

    def _handle_student_scan_ack(self, data):
        next_id = data.get("next_student_id")
        next_name = data.get("next_student_name", "---")
        next_addr = data.get("next_address", "---")
        self.dest_title_lbl.setText(f"ĐIỂM ĐẾN: {next_name} – {next_addr}")
        
        if next_id is None:
            phase = getattr(self.boarding, "trip_phase", "PICKUP")
            if phase == "PICKUP":
                self.uart.send_frame(0x05, 0x03)
            elif phase == "DROPOFF":
                self.uart.send_frame(0x05, 0x04)

    def _handle_driver_logout_ack(self, data): pass
    def _handle_attendant_login_ack(self, data): pass
    def _handle_attendant_logout_ack(self, data): pass
    def _handle_server_command(self, data): pass
