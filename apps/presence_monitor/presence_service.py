import time
from PyQt5.QtCore import QThread, pyqtSignal
from config import config
from services.logger import get_logger

logger = get_logger("PresenceMonitor")

class PresenceThread(QThread):
    # Signals to update UI state
    driver_mismatch_signal = pyqtSignal(int) # mismatch_count
    attendant_absence_signal = pyqtSignal(int) # absence_count

    def __init__(self, auth_service, camera_service, uart_thread, mqtt_client):
        super().__init__()
        self.auth_service = auth_service
        self.camera_service = camera_service
        self.uart_thread = uart_thread
        self.mqtt_client = mqtt_client
        self.running = False
        
        # Debounced seats dictionary pointer
        self.current_seats = {}
        
        # Checking variables
        self.last_driver_check = time.time()
        self.attendant_empty_since = None
        self.last_attendant_warn_time = 0

    def set_seats(self, seats):
        self.current_seats = seats

    def run(self):
        self.running = True
        logger.info("Presence monitoring thread started.")
        
        # Give initial setup delay
        time.sleep(5)
        self.last_driver_check = time.time()

        while self.running:
            now = time.time()
            
            # --- 1. Driver Presence Check (Face Scan every 3 minutes) ---
            if self.auth_service.active_driver:
                if now - self.last_driver_check >= config.PRESENCE_CHECK_INTERVAL_SEC:
                    self.last_driver_check = now
                    logger.info("Triggering periodic driver presence check...")
                    
                    # Capture face vector
                    vector = self.camera_service.capture_face_vector()
                    is_present = self.auth_service.verify_driver_presence(vector)
                    
                    if is_present:
                        logger.info("Driver presence verified.")
                        self.auth_service.mismatch_count = 0
                        self.driver_mismatch_signal.emit(0)
                    else:
                        self.auth_service.mismatch_count += 1
                        m_count = self.auth_service.mismatch_count
                        logger.warning("Driver mismatch detected (Count: %d/4)", m_count)
                        self.driver_mismatch_signal.emit(m_count)
                        
                        # Play Warning 06/001
                        self.uart_thread.send_frame(0x06, 0x01)
                        
                        if m_count >= 4:
                            logger.error("Driver presence violation! Reporting to server...")
                            driver_id = self.auth_service.active_driver["driver_id"]
                            self.mqtt_client.publish_message(5, {
                                "driver_id": driver_id,
                                "mismatch_count": m_count
                            }, priority=1)
            else:
                self.last_driver_check = now # Reset timer when no driver logged in

            # --- 2. Attendant Presence Check (Seat 2 status) ---
            if self.auth_service.active_attendant:
                # Get seat 2 status (0 = empty, 1 = occupied)
                # Default to 0 if not received yet to be safe
                seat2_occupied = self.current_seats.get("2", 0)
                
                if seat2_occupied == 0:
                    if self.attendant_empty_since is None:
                        self.attendant_empty_since = now
                        logger.info("Attendant left seat 2. Starting timer...")
                    else:
                        elapsed = now - self.attendant_empty_since
                        # Trigger warning and increment counts every 3 minutes (180s)
                        if elapsed >= config.PRESENCE_CHECK_INTERVAL_SEC:
                            # Trigger warning and update
                            self.attendant_empty_since = now # Reset cycle
                            self.auth_service.absence_count += 1
                            a_count = self.auth_service.absence_count
                            logger.warning("Attendant absent from seat 2 (Count: %d/3)", a_count)
                            self.attendant_absence_signal.emit(a_count)
                            
                            # Play Warning 06/003
                            self.uart_thread.send_frame(0x06, 0x03)
                            
                            if a_count >= 3:
                                logger.error("Attendant presence violation! Reporting to server...")
                                attendant_id = self.auth_service.active_attendant["attendant_id"]
                                self.mqtt_client.publish_message(10, {
                                    "attendant_id": attendant_id,
                                    "absence_count": a_count
                                }, priority=1)
                else:
                    if self.attendant_empty_since is not None:
                        logger.info("Attendant returned to seat 2. Resetting timers.")
                        self.attendant_empty_since = None
                        self.auth_service.absence_count = 0
                        self.attendant_absence_signal.emit(0)
            else:
                self.attendant_empty_since = None
                self.auth_service.absence_count = 0

            time.sleep(1)

    def stop(self):
        self.running = False
        self.wait()
