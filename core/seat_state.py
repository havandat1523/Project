import time
from services.logger import get_logger

logger = get_logger("SeatDebouncer")

class SeatDebouncer:
    def __init__(self):
        self.current_states = {str(i): 0 for i in range(1, 17)}
        self.target_states = {str(i): 0 for i in range(1, 17)}
        self.change_timestamps = {str(i): 0.0 for i in range(1, 17)}
        self.debounce_delay = 10.0 # 10 seconds

    def update_raw_seats(self, raw_seats: dict) -> tuple:
        """
        Receives raw seat readings.
        Returns (changed_boolean, debounced_seats_dict).
        """
        now = time.time()
        changed = False
        
        for i in range(1, 17):
            seat_num = str(i)
            raw_val = raw_seats.get(seat_num, 0)
            
            # If the raw value is different from the current target state, reset debounce timer
            if raw_val != self.target_states[seat_num]:
                self.target_states[seat_num] = raw_val
                self.change_timestamps[seat_num] = now
            # If it is stable but different from the debounced state, verify debounce duration
            elif raw_val != self.current_states[seat_num]:
                if now - self.change_timestamps[seat_num] >= self.debounce_delay:
                    self.current_states[seat_num] = raw_val
                    changed = True
                    logger.info("Seat %s state settled to %d", seat_num, raw_val)
                    
        return changed, self.current_states.copy()
