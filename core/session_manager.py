from services.logger import get_logger

logger = get_logger("SessionManager")

class SessionManager:
    def __init__(self, auth_service, uart_thread, mqtt_client):
        self.auth = auth_service
        self.uart = uart_thread
        self.mqtt = mqtt_client
        self.students_onboard = 0

    def set_student_count(self, count: int):
        self.students_onboard = count

    def can_driver_logout(self) -> tuple:
        """
        Validates if the driver is allowed to logout.
        Returns (bool, reason_string).
        """
        if not self.auth.active_driver:
            return False, "Không có tài xế nào đang đăng nhập."
            
        if self.auth.active_attendant:
            return False, "Phụ xe phải đăng xuất trước khi tài xế đăng xuất."
            
        if self.students_onboard > 0:
            return False, f"Vẫn còn {self.students_onboard} học sinh trên xe!"
            
        return True, ""

    def process_driver_login(self, driver_id: str, full_name: str):
        """
        Saves the logged in driver profile.
        """
        self.auth.active_driver = {
            "driver_id": driver_id,
            "full_name": full_name
        }
        self.auth.mismatch_count = 0
        logger.info("Driver logged in: %s (%s)", full_name, driver_id)
        # Notify Master via UART to play 01/001 (driver login success)
        self.uart.send_frame(0x01, 0x01, driver_id.encode("ascii"))

    def process_driver_logout(self):
        """
        Clears the logged in driver profile.
        """
        if self.auth.active_driver:
            driver_id = self.auth.active_driver["driver_id"]
            self.auth.active_driver = None
            self.auth.mismatch_count = 0
            logger.info("Driver logged out")
            # Play 02/001 (driver logout success)
            self.uart.send_frame(0x02, 0x01)

    def process_attendant_login(self, attendant_id: str, full_name: str):
        """
        Saves the logged in attendant profile.
        """
        self.auth.active_attendant = {
            "attendant_id": attendant_id,
            "full_name": full_name
        }
        self.auth.absence_count = 0
        logger.info("Attendant logged in: %s (%s)", full_name, attendant_id)
        
        # Check if students are already onboard (attendant logging in late is warned by 06/002)
        if self.students_onboard > 0:
            self.uart.send_frame(0x06, 0x02) # Phụ xe check-in sau khi đã có học sinh trên xe
        else:
            self.uart.send_frame(0x03, 0x01) # Phụ xe login thành công

    def process_attendant_logout(self):
        """
        Clears the logged in attendant profile.
        """
        if self.auth.active_attendant:
            self.auth.active_attendant = None
            self.auth.absence_count = 0
            logger.info("Attendant logged out")
            # Play 04/001 (attendant logout success)
            self.uart.send_frame(0x04, 0x01)
