import sys
import os
from PyQt5.QtWidgets import QApplication
from config import config
from services.logger import get_logger
from services.database import init_db
from apps.communication.uart_protocol import UARTThread
from apps.communication.mqtt_client import MQTTClient
from apps.camera.camera_service import CameraService
from apps.authentication.auth_service import AuthService
from apps.presence_monitor.presence_service import PresenceThread
from core.session_manager import SessionManager
from core.boarding_logic import BoardingLogic
from core.seat_state import SeatDebouncer
from apps.ui.app import BusMonitoringApp

logger = get_logger("Main")

def main():
    logger.info("==============================================")
    logger.info("Starting School Bus Gateway Application...")
    logger.info("VEHICLE ID: %s", config.VEHICLE_ID)
    logger.info("==============================================")

    # 1. Initialize SQLite Database
    init_db()

    # 2. Instantiate core services
    auth_service = AuthService()
    seat_debouncer = SeatDebouncer()
    
    # 3. Instantiate thread components
    camera_service = CameraService()
    uart_thread = UARTThread()
    
    # 4. Instantiate MQTT client
    # The callback_handler will be set to the UI application later
    mqtt_client = MQTTClient()

    # 5. Instantiate managers & logic layers
    session_manager = SessionManager(auth_service, uart_thread, mqtt_client)
    boarding_logic = BoardingLogic(uart_thread, mqtt_client)
    
    # 6. Instantiate presence check thread
    presence_thread = PresenceThread(auth_service, camera_service, uart_thread, mqtt_client)

    # 7. Start background threads
    camera_service.start()
    uart_thread.start()
    mqtt_client.start()
    presence_thread.start()

    # 8. Start PyQt5 GUI Application
    app = QApplication(sys.argv)
    
    # Create main UI window
    ui_app = BusMonitoringApp(
        uart_thread=uart_thread,
        mqtt_client=mqtt_client,
        camera_service=camera_service,
        auth_service=auth_service,
        session_manager=session_manager,
        boarding_logic=boarding_logic,
        seat_debouncer=seat_debouncer
    )
    
    # Link MQTT callback receiver to UI
    mqtt_client.callback_handler = ui_app
    
    # Connect seat state updates to the presence monitor thread
    # We update the seats pointer inside presence thread when seats signal fires
    uart_thread.seats_received.connect(presence_thread.set_seats)

    # Show UI window
    ui_app.show()

    # Execute Qt main event loop
    logger.info("UI Window launched. Entering Qt main loop.")
    exit_code = app.exec_()

    # Cleanup threads on exit
    logger.info("Shutting down threads...")
    camera_service.stop()
    uart_thread.stop()
    mqtt_client.stop()
    presence_thread.stop()
    logger.info("Application exited with code %d", exit_code)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
