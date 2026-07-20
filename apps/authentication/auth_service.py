import numpy as np
import json
import time
from services.database import get_db_connection
from services.logger import get_logger

logger = get_logger("AuthService")

class AuthService:
    def __init__(self):
        self.active_driver = None     # Holds active driver dict
        self.active_attendant = None  # Holds active attendant dict
        self.mismatch_count = 0
        self.absence_count = 0

    def cache_user_vector(self, user_id: str, user_type: str, full_name: str, face_vector: list):
        """
        Caches a user's face vector in the local SQLite database for offline validation.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        vector_json = json.dumps(face_vector)
        timestamp = int(time.time())
        try:
            cursor.execute(
                """INSERT OR REPLACE INTO face_cache (user_id, user_type, full_name, face_vector_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, user_type, full_name, vector_json, timestamp)
            )
            conn.commit()
            logger.info("Cached %s vector locally: ID=%s, Name=%s", user_type, user_id, full_name)
        except Exception as e:
            logger.error("Failed to cache user vector: %s", e)
        finally:
            conn.close()

    def get_cached_user(self, user_id: str):
        """
        Gets cached user profile and face vector.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM face_cache WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "user_id": row["user_id"],
                    "user_type": row["user_type"],
                    "full_name": row["full_name"],
                    "face_vector": json.loads(row["face_vector_json"])
                }
            return None
        except Exception as e:
            logger.error("Error reading face cache: %s", e)
            return None
        finally:
            conn.close()

    def match_face_offline(self, captured_vector: list, user_type_filter: str = "driver"):
        """
        Matches a captured vector against all cached profiles in the database.
        Returns the best matching user dict if Euclidean distance is < 0.6.
        """
        if captured_vector is None:
            return None
            
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM face_cache WHERE user_type = ?", (user_type_filter,))
            rows = cursor.fetchall()
            
            best_match = None
            min_distance = 999.0
            
            cap_arr = np.array(captured_vector)
            
            for row in rows:
                cached_vec = np.array(json.loads(row["face_vector_json"]))
                # Calculate Euclidean distance
                distance = np.linalg.norm(cap_arr - cached_vec)
                logger.debug("Distance to %s (%s): %.4f", row["full_name"], row["user_id"], distance)
                
                if distance < 0.6 and distance < min_distance:
                    min_distance = distance
                    best_match = {
                        "user_id": row["user_id"],
                        "user_type": row["user_type"],
                        "full_name": row["full_name"],
                        "distance": distance
                    }
                    
            if best_match:
                logger.info("Offline face match found! %s (%s) with distance %.4f", 
                            best_match["full_name"], best_match["user_id"], min_distance)
            else:
                logger.warning("No matching face vector found offline (min distance was %.4f or database empty)", min_distance if rows else 0)
                
            return best_match
        except Exception as e:
            logger.error("Error matching face offline: %s", e)
            return None
        finally:
            conn.close()

    def verify_driver_presence(self, captured_vector: list) -> bool:
        """
        Verifies that the captured vector matches the logged-in active driver.
        Returns True if matched, False otherwise.
        """
        if not self.active_driver:
            logger.warning("Presence verification called but no active driver is logged in")
            return False
            
        if captured_vector is None:
            logger.warning("Verification failed: No face captured")
            return False
            
        # Get cached vector for the active driver
        cached_profile = self.get_cached_user(self.active_driver["driver_id"])
        if not cached_profile:
            logger.error("Logged in driver ID %s not found in cache", self.active_driver["driver_id"])
            return False
            
        cap_arr = np.array(captured_vector)
        cached_arr = np.array(cached_profile["face_vector"])
        
        distance = np.linalg.norm(cap_arr - cached_arr)
        logger.info("Driver presence check: Euclidean distance = %.4f", distance)
        
        return distance < 0.6
