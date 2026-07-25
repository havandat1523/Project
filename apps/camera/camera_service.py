import cv2
import time
import numpy as np
import subprocess
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage
from services.logger import get_logger

logger = get_logger("Camera")

try:
    import face_recognition
    FACE_REC_AVAILABLE = True
    logger.info("face_recognition library loaded successfully")
except ImportError:
    FACE_REC_AVAILABLE = False
    logger.warning("face_recognition library not found. Biometric face encoding will be SIMULATED.")

class CameraService(QThread):
    # Emits frame to UI for streaming
    frame_received = pyqtSignal(QImage)
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.cap = None
        self.latest_frame = None
        import threading
        self.lock = threading.Lock()
        
        # RTSP Streaming fields
        self.streaming_process = None
        self.stream_host = None
        self.stream_port = None
        self.is_streaming = False

    def try_open_camera(self):
        """
        Attempts to open camera with V4L2 backend to avoid OpenCV GStreamer memory allocation bugs on Raspberry Pi.
        Tests if a frame can actually be read.
        """
        candidates = [
            (0, cv2.CAP_V4L2),
            (1, cv2.CAP_V4L2),
            (0, cv2.CAP_ANY),
            (1, cv2.CAP_ANY)
        ]
        
        for idx, api in candidates:
            try:
                cap = cv2.VideoCapture(idx, api)
                if cap and cap.isOpened():
                    # Test reading a frame to verify it actually yields pixels
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        logger.info("Successfully opened camera at index %d (API: %s)", idx, "V4L2" if api == cv2.CAP_V4L2 else "ANY")
                        return cap
                    cap.release()
            except Exception as e:
                logger.debug("Failed to open camera index %d with API %s: %s", idx, api, e)
                
        return None

    def run(self):
        self.running = True
        self.cap = self.try_open_camera()
        
        if not self.cap:
            logger.error("Could not open hardware camera. Emitting SIMULATED video frames.")
            self.run_simulation()
            return
            
        logger.info("Camera stream started.")
        failed_count = 0
        while self.running:
            ret, frame = self.cap.read()
            if not ret or frame is None:
                failed_count += 1
                if failed_count > 30: # ~1 second of consecutive read failures
                    logger.error("Camera frame read failed repeatedly. Switching to SIMULATION mode.")
                    break
                time.sleep(0.03)
                continue
                
            failed_count = 0
                
            with self.lock:
                self.latest_frame = frame.copy()
                
            # If streaming is enabled, write frame to FFmpeg subprocess
            if self.is_streaming and self.streaming_process:
                try:
                    # Resize to 640x480 for streaming consistency
                    stream_frame = cv2.resize(frame, (640, 480))
                    self.streaming_process.stdin.write(stream_frame.tobytes())
                except Exception as e:
                    logger.error("Error writing frame to stream process: %s", e)
                    self.stop_streaming()

            # Convert frame to QImage for UI
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
            self.frame_received.emit(q_img.copy())
            
            # Limit to ~30 FPS
            time.sleep(0.03)
            
        if self.cap:
            self.cap.release()
            self.cap = None
        self.stop_streaming()

        if self.running:
            self.run_simulation()
        else:
            logger.info("Camera stream stopped.")

    def run_simulation(self):
        """
        Generates dummy frames when no camera is present.
        """
        h, w, ch = 480, 640, 3
        counter = 0
        while self.running:
            # Create a nice dark gradient frame with rotating text
            frame = np.zeros((h, w, ch), dtype=np.uint8)
            cv2.rectangle(frame, (10, 10), (w-10, h-10), (20, 20, 35), -1)
            cv2.putText(frame, "Webcam Stream [SIMULATOR]", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.putText(frame, f"Frame Count: {counter}", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 255, 100), 1)
            
            # Draw a blinking cursor
            if (counter // 15) % 2 == 0:
                cv2.circle(frame, (350, 143), 6, (0, 255, 0), -1)
                
            with self.lock:
                self.latest_frame = frame.copy()

            # If streaming is enabled, write frame to FFmpeg subprocess
            if self.is_streaming and self.streaming_process:
                try:
                    self.streaming_process.stdin.write(frame.tobytes())
                except Exception as e:
                    logger.error("Error writing simulated frame to stream process: %s", e)
                    self.stop_streaming()
                
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            q_img = QImage(rgb_image.data, w, h, ch * w, QImage.Format_RGB888)
            self.frame_received.emit(q_img.copy())
            
            time.sleep(0.03)
            counter += 1
        
        self.stop_streaming()

    def start_streaming(self, host, port):
        if self.is_streaming:
            self.stop_streaming()
            
        self.stream_host = host
        self.stream_port = port
        rtsp_url = f"rtsp://{host}:{port}/picam"
        
        cmd = [
            'ffmpeg',
            '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-s', '640x480',
            '-r', '15',
            '-i', '-',
            '-vcodec', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-f', 'rtsp',
            rtsp_url
        ]
        
        try:
            # Launch FFmpeg process with stdin piping
            self.streaming_process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            self.is_streaming = True
            logger.info("Started RTSP streaming to: %s", rtsp_url)
            return rtsp_url
        except Exception as e:
            logger.error("Failed to start FFmpeg subprocess: %s", e)
            self.is_streaming = False
            self.streaming_process = None
            return None

    def stop_streaming(self):
        if self.streaming_process:
            logger.info("Stopping RTSP streaming process...")
            try:
                self.streaming_process.stdin.close()
                self.streaming_process.terminate()
                self.streaming_process.wait(timeout=2)
            except Exception as e:
                logger.error("Error stopping streaming subprocess: %s", e)
            self.streaming_process = None
        self.is_streaming = False

    def capture_face_vector(self):
        """
        Attempts to crop the latest frame and extract the 128-dimensional face encoding vector.
        """
        with self.lock:
            if self.latest_frame is None:
                logger.warning("No frame captured to encode")
                return None
            frame = self.latest_frame.copy()
            
        if not FACE_REC_AVAILABLE:
            # Simulate face vector: list of 128 floating points
            logger.info("Simulating 128-dimensional face encoding vector...")
            time.sleep(0.5) # Simulate encoding delay
            return (np.random.rand(128) * 2 - 1).tolist()
            
        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Detect faces
        face_locations = face_recognition.face_locations(rgb_frame)
        if not face_locations:
            logger.warning("No face detected in the frame")
            return None
            
        # Get face encodings
        encodings = face_recognition.face_encodings(rgb_frame, face_locations)
        if not encodings:
            logger.warning("Failed to encode detected face")
            return None
            
        # Return first face vector as list
        vector = encodings[0].tolist()
        logger.info("Successfully encoded face vector (%d dimensions)", len(vector))
        return vector

    def stop(self):
        self.running = False
        self.wait()
