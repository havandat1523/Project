import math
import time
from config import config
from services.logger import get_logger

logger = get_logger("BoardingLogic")

class BoardingLogic:
    def __init__(self, uart_thread, mqtt_client):
        self.uart = uart_thread
        self.mqtt = mqtt_client
        
        # Geofence parameters
        self.school_lat = config.SCHOOL_GEOFENCE_LAT
        self.school_lon = config.SCHOOL_GEOFENCE_LON
        self.school_radius = config.SCHOOL_GEOFENCE_RADIUS_M
        
        # State
        self.at_school = False
        self.trip_phase = "PICKUP"  # "PICKUP" (morning home route), "ARRIVE_SCHOOL", "DEPART_SCHOOL", "DROPOFF" (afternoon route)
        
        # Tracking student lists
        self.students_onboard = {}  # {rfid: seat_num}
        self.seat_student_map = {}  # {seat_num: rfid}
        
        # Critical alert state
        self.child_alone_active = False
        self.child_alone_start_time = None
        
        # Last known seats
        self.current_seats = {}

    def calculate_distance(self, lat1, lon1, lat2, lon2) -> float:
        """
        Haversine formula to compute distance in meters between two GPS coordinates.
        """
        R = 6371000.0  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        
        a = math.sin(dphi/2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2.0)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def update_gps(self, lat: float, lon: float, speed: float):
        """
        Called when new GPS coordinates are received. Updates school geofence status and trip phase.
        """
        dist = self.calculate_distance(lat, lon, self.school_lat, self.school_lon)
        previously_at_school = self.at_school
        self.at_school = (dist <= self.school_radius)
        
        if self.at_school and not previously_at_school:
            logger.info("Vehicle entered school geofence (Distance: %.1fm)", dist)
            # Automatic transition from PICKUP to ARRIVE_SCHOOL in morning
            if self.trip_phase == "PICKUP":
                self.trip_phase = "ARRIVE_SCHOOL"
                logger.info("Trip phase transitioned to: ARRIVE_SCHOOL")
                
        elif not self.at_school and previously_at_school:
            logger.info("Vehicle left school geofence (Distance: %.1fm)", dist)
            # Automatic transition from DEPART_SCHOOL to DROPOFF in afternoon
            if self.trip_phase == "DEPART_SCHOOL":
                self.trip_phase = "DROPOFF"
                logger.info("Trip phase transitioned to: DROPOFF")

    def update_seats(self, seats: dict):
        """
        Handles seat status updates. Runs safety alarm check and bulk boarding transitions.
        """
        self.current_seats = seats
        self.check_child_alone_safety(seats)
        
        # If we are in ARRIVE_SCHOOL, check for bulk student unloading
        if self.trip_phase == "ARRIVE_SCHOOL":
            self.check_bulk_alight(seats)
            
        # If we are in DEPART_SCHOOL, check for bulk boarding
        elif self.trip_phase == "DEPART_SCHOOL":
            self.check_bulk_board(seats)

    def check_child_alone_safety(self, seats: dict):
        """
        Monitors whether any student is left alone (student seats occupied, driver & attendant absent).
        Triggers alarms if this state exceeds 15 seconds.
        """
        driver_present = seats.get("1", 0) == 1
        attendant_present = seats.get("2", 0) == 1
        
        # Check student seats (3 to 16)
        student_onboard = False
        occupied_student_seats = []
        for i in range(3, 17):
            if seats.get(str(i), 0) == 1:
                student_onboard = True
                occupied_student_seats.append(i)
                
        # Condition: student on board, but both driver and attendant are missing
        if student_onboard and not driver_present and not attendant_present:
            if self.child_alone_start_time is None:
                self.child_alone_start_time = time.time()
                logger.warning("Safety Hazard: Student detected on board but NO driver/attendant present. Starting 15s timer...")
            else:
                elapsed = time.time() - self.child_alone_start_time
                if elapsed >= 15 and not self.child_alone_active:
                    self.child_alone_active = True
                    logger.critical("SAFETY CRITICAL: CHILD LEFT ALONE TRIGGERED! Playing siren & notifying server.")
                    # Trigger repeating siren on Master 08/001
                    self.uart.send_frame(0x08, 0x01)
                    # Notify Server (type=16)
                    self.mqtt.publish_message(16, {
                        "occupied_student_seats": occupied_student_seats,
                        "driver_seat": 0,
                        "attendant_seat": 0,
                        "duration_sec": int(elapsed)
                    }, priority=2)
                elif self.child_alone_active:
                    # Periodically republish alert while active (every 10s)
                    if int(elapsed) % 10 == 0:
                        self.mqtt.publish_message(16, {
                            "occupied_student_seats": occupied_student_seats,
                            "driver_seat": 0,
                            "attendant_seat": 0,
                            "duration_sec": int(elapsed)
                        }, priority=2)
        else:
            # Safe condition
            if self.child_alone_start_time is not None:
                logger.info("Driver or attendant returned (or students left). Silencing safety alarm.")
                self.child_alone_start_time = None
                if self.child_alone_active:
                    self.child_alone_active = False
                    # Stop repeating alarm on Master (0xF4)
                    self.uart.send_frame(0xF4, 0x00)

    def handle_rfid_scan(self, rfid: str):
        """
        Associates scanned RFID card with the seat that was occupied most recently.
        """
        # Find a seat (3-16) that is occupied but has no student mapped to it
        unmapped_seat = None
        for i in range(3, 17):
            seat_num = str(i)
            if self.current_seats.get(seat_num, 0) == 1 and seat_num not in self.seat_student_map:
                unmapped_seat = i
                break
                
        # Fallback to a default if all mapped (e.g. child scanning again or scan before sitting)
        seat_num_val = unmapped_seat if unmapped_seat is not None else 0
        
        phase_map = {"PICKUP": 1, "ARRIVE_SCHOOL": 2, "DEPART_SCHOOL": 3, "DROPOFF": 4}
        phase_num = phase_map.get(self.trip_phase, 1)
        
        # Publish student scan event (type 11)
        # Server verifies if RFID is active and responds
        logger.info("Student RFID scanned: %s on seat %d (Phase: %s)", rfid, seat_num_val, self.trip_phase)
        self.mqtt.publish_message(11, {
            "rfid_code": rfid,
            "seat_number": seat_num_val,
            "trip_phase": phase_num
        }, priority=1)
        
        # Temporarily save mapping locally (will be overridden on Server ack)
        if seat_num_val > 0:
            self.students_onboard[rfid] = seat_num_val
            self.seat_student_map[str(seat_num_val)] = rfid

    def check_bulk_alight(self, seats: dict):
        """
        Buổi sáng: Xe đến trường. Khi tất cả học sinh xuống xe (số học sinh = 0):
        Phát thoại 05/006 nhắc nhở kiểm tra xe.
        """
        student_count = sum(1 for i in range(3, 17) if seats.get(str(i), 0) == 1)
        
        # If vehicle arrived at school and student count drops to 0
        # and we had students recorded on board previously
        if student_count == 0 and len(self.seat_student_map) > 0:
            logger.info("Bulk alight detected at school. All student seats are now empty.")
            
            # Match count
            expected = len(self.seat_student_map)
            # Send student event (type 12, event_code 506 = bulk dropoff)
            self.mqtt.publish_message(12, {
                "event_code": 506,
                "seats_emptied": expected,
                "expected_boarded": expected,
                "match": True
            }, priority=1)
            
            # Send play command 05/006 ("Tất cả học sinh đã xuống xe... bác tài và phụ xe hãy kiểm tra kỹ...")
            self.uart.send_frame(0x05, 0x06)
            
            # Clear local student seat mappings
            self.students_onboard.clear()
            self.seat_student_map.clear()

    def check_bulk_board(self, seats: dict):
        """
        Buổi chiều: Xe đón học sinh tại trường. Học sinh lên hàng loạt không cần quẹt thẻ.
        Chỉ ghi nhận log và gửi lên Server.
        """
        student_count = sum(1 for i in range(3, 17) if seats.get(str(i), 0) == 1)
        if student_count > 0 and len(self.seat_student_map) == 0:
            # Populate local stubs to enable later tracking during DROPOFF
            for i in range(3, 17):
                seat_num = str(i)
                if seats.get(seat_num, 0) == 1:
                    stub_rfid = f"STUB_{i}"
                    self.students_onboard[stub_rfid] = i
                    self.seat_student_map[seat_num] = stub_rfid
                    
            logger.info("Bulk boarding at school detected. Loaded %d student stubs for route tracking.", student_count)
            # Send student event (type 12, event_code 507 = bulk boarding)
            self.mqtt.publish_message(12, {
                "event_code": 507,
                "students_onboard": student_count
            }, priority=1)

    def set_trip_phase(self, phase: str):
        if phase in ("PICKUP", "ARRIVE_SCHOOL", "DEPART_SCHOOL", "DROPOFF"):
            self.trip_phase = phase
            logger.info("Trip phase manually set to: %s", phase)
            if phase == "DEPART_SCHOOL":
                self.students_onboard.clear()
                self.seat_student_map.clear()
