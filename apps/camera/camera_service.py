import cv2
import time
import numpy as np
import subprocess
import queue
import threading
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage
from services.logger import get_logger

logger = get_logger("Camera")

FACE_REC_AVAILABLE = None  # Lazy loading flag

def is_face_rec_available():
    global FACE_REC_AVAILABLE
    if FACE_REC_AVAILABLE is None:
        try:
            import face_recognition
            FACE_REC_AVAILABLE = True
            logger.info("face_recognition library loaded successfully")
        except ImportError:
            FACE_REC_AVAILABLE = False
            logger.warning("face_recognition library not found. Biometric face encoding will be SIMULATED.")
    return FACE_REC_AVAILABLE

try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
    logger.info("Picamera2 library loaded successfully for Raspberry Pi CSI Camera")
except ImportError:
    PICAMERA2_AVAILABLE = False
    logger.info("Picamera2 library not found. Will use OpenCV / libcamerasrc pipeline.")

class CameraService(QThread):
    # Emits frame to UI for streaming
    frame_received = pyqtSignal(QImage)
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.cap = None
        self.picam2 = None
        self.latest_frame = None
        self.lock = threading.Lock()
        
        # RTSP Streaming fields
        self.streaming_process = None
        self.stream_host = None
        self.stream_port = None
        self.is_streaming = False
        self.stream_queue = queue.Queue(maxsize=2)
        self.stream_thread = None

    def try_open_camera(self):
        """
        Attempts to open camera with OpenCV V4L2 / default index at 640x480 resolution.
        Tests if a frame can actually be read.
        """
        candidates = [
            (0, cv2.CAP_V4L2),
            (0, cv2.CAP_ANY),
            (1, cv2.CAP_V4L2),
            (1, cv2.CAP_ANY),
        ]
        
        for source, api in candidates:
            try:
                cap = cv2.VideoCapture(source, api)
                if cap and cap.isOpened():
                    # Explicitly set 640x480 resolution BEFORE reading to prevent 2560x1600 buffer allocation failure
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        logger.info("Successfully opened camera at index %d (API: %s)", source, api)
                        return cap
                    cap.release()
            except Exception as e:
                logger.debug("Failed to open camera index %d: %s", source, e)
                
        return None

    def run(self):
        self.running = True

        import os
        ld_preload = os.environ.get("LD_PRELOAD", "")
        is_libcamerify = "libcamera" in ld_preload or "v4l2" in ld_preload

        # 1. If Picamera2 is available AND not running under libcamerify, use Picamera2 first (Native Pi CSI Camera)
        if PICAMERA2_AVAILABLE and not is_libcamerify:
            try:
                logger.info("Attempting to initialize Picamera2 (Pi CSI Camera)...")
                self.picam2 = Picamera2()
                config = self.picam2.create_video_configuration(main={"size": (640, 480), "format": "BGR888"})
                self.picam2.configure(config)
                self.picam2.start()
                logger.info("Picamera2 started successfully!")
                self.run_picamera2()
                return
            except Exception as e:
                logger.warning("Failed to start Picamera2: %s. Trying OpenCV capture...", e)
                if hasattr(self, "picam2") and self.picam2:
                    try:
                        self.picam2.stop()
                        self.picam2.close()
                    except Exception:
                        pass
                self.picam2 = None

        # 2. Try OpenCV capture (for USB webcams OR when running under libcamerify)
        self.cap = self.try_open_camera()
        if self.cap:
            logger.info("Camera stream started via OpenCV (libcamerify=%s).", is_libcamerify)
            self.run_opencv()
            return

        # 3. If all hardware camera methods failed, fall back to simulation
        logger.error("Could not open hardware camera. Emitting SIMULATED video frames.")
        self.run_simulation()

    def run_opencv(self):
        failed_count = 0
        while self.running:
            ret, frame = self.cap.read()
            if not ret or frame is None or frame.size == 0:
                failed_count += 1
                if failed_count > 30: # ~1 second of consecutive read failures
                    logger.error("Camera frame read failed repeatedly. Switching to SIMULATION mode.")
                    break
                time.sleep(0.03)
                continue
                
            failed_count = 0
                
            with self.lock:
                self.latest_frame = frame.copy()
                
            # If streaming is enabled, push frame to non-blocking worker queue
            self._push_stream_frame(frame)

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

    def run_picamera2(self):
        failed_count = 0
        while self.running:
            try:
                # Capture frame array directly from Pi CSI Camera
                frame = self.picam2.capture_array()
                if frame is None or frame.size == 0:
                    failed_count += 1
                    if failed_count > 30:
                        logger.error("Picamera2 frame read failed repeatedly. Switching to SIMULATION mode.")
                        break
                    time.sleep(0.03)
                    continue

                failed_count = 0
                with self.lock:
                    self.latest_frame = frame.copy()

                # If streaming is enabled, push frame to non-blocking worker queue
                self._push_stream_frame(frame)

                rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
                self.frame_received.emit(q_img.copy())

                time.sleep(0.03)
            except Exception as e:
                logger.error("Error capturing frame from Picamera2: %s", e)
                failed_count += 1
                if failed_count > 30:
                    break
                time.sleep(0.03)

        try:
            self.picam2.stop()
            self.picam2.close()
        except Exception:
            pass
        self.picam2 = None
        self.stop_streaming()

        if self.running:
            self.run_simulation()
        else:
            logger.info("Picamera2 stream stopped.")

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

            # If streaming is enabled, push frame to non-blocking worker queue
            self._push_stream_frame(frame)
                
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            q_img = QImage(rgb_image.data, w, h, ch * w, QImage.Format_RGB888)
            self.frame_received.emit(q_img.copy())
            
            time.sleep(0.03)
            counter += 1
        
        self.stop_streaming()

    def _push_stream_frame(self, frame):
        if self.is_streaming and hasattr(self, 'stream_queue'):
            try:
                stream_frame = cv2.resize(frame, (640, 480))
                if self.stream_queue.full():
                    try:
                        self.stream_queue.get_nowait()
                    except queue.Empty:
                        pass
                self.stream_queue.put_nowait(stream_frame)
            except Exception:
                pass

    def _stream_worker_loop(self):
        logger.info("Streaming background worker started.")
        while self.is_streaming and self.streaming_process:
            try:
                frame = self.stream_queue.get(timeout=0.2)
                if self.streaming_process and self.streaming_process.stdin:
                    self.streaming_process.stdin.write(frame.tobytes())
                    self.streaming_process.stdin.flush()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error("Error writing frame to stream process: %s", e)
                self.stop_streaming()
                break
        logger.info("Streaming background worker finished.")

from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class MJPEGStreamHandler(BaseHTTPRequestHandler):
    camera_service = None
    
    def do_GET(self):
        if self.path in ('/video_feed', '/'):
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            while MJPEGStreamHandler.camera_service and MJPEGStreamHandler.camera_service.is_streaming:
                frame = MJPEGStreamHandler.camera_service.get_latest_frame()
                if frame is not None:
                    ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                    if ret:
                        try:
                            self.wfile.write(b'--frame\r\n')
                            self.send_header('Content-type', 'image/jpeg')
                            self.send_header('Content-length', len(jpeg))
                            self.end_headers()
                            self.wfile.write(jpeg.tobytes())
                            self.wfile.write(b'\r\n')
                        except Exception:
                            break
                time.sleep(0.05)
        else:
            self.send_error(404)
            
    def log_message(self, format, *args):
        pass

    def start_streaming(self, protocol="http", host="192.168.137.1", port=8080):
        if self.is_streaming:
            self.stop_streaming()
            
        if protocol in ("rtp", "rtsp"):
            rtp_url = f"rtsp://{host}:{port}/live/bus_cam" if protocol == "rtsp" else f"rtp://{host}:{port}"
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
                '-f', 'rtsp' if protocol == "rtsp" else 'rtp',
                rtp_url
            ]
            try:
                self.streaming_process = subprocess.Popen(
                    cmd, 
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.is_streaming = True
                self.stream_thread = threading.Thread(target=self._stream_worker_loop, daemon=True)
                self.stream_thread.start()
                logger.info("Started %s (RTP/H264) video stream to %s", protocol.upper(), rtp_url)
                return rtp_url
            except Exception as e:
                logger.error("Failed to start %s FFmpeg stream: %s. Falling back to HTTP stream...", protocol.upper(), e)

        # HTTP Stream Default / Fallback
        try:
            MJPEGStreamHandler.camera_service = self
            self.http_server = ThreadedHTTPServer(('0.0.0.0', port), MJPEGStreamHandler)
            self.is_streaming = True
            
            self.server_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
            self.server_thread.start()
            
            stream_url = f"http://192.168.137.103:{port}/video_feed"
            logger.info("Started HTTP MJPEG video stream on %s", stream_url)
            return stream_url
        except Exception as e:
            logger.error("Failed to start HTTP video stream: %s", e)
            self.is_streaming = False
            return None

    def stop_streaming(self):
        self.is_streaming = False
        if hasattr(self, "streaming_process") and self.streaming_process:
            try:
                if self.streaming_process.stdin:
                    self.streaming_process.stdin.close()
                self.streaming_process.terminate()
                self.streaming_process.wait(timeout=2)
            except Exception:
                pass
            self.streaming_process = None

        if hasattr(self, "http_server") and self.http_server:
            try:
                self.http_server.shutdown()
                self.http_server.server_close()
            except Exception:
                pass
            self.http_server = None
        logger.info("Video stream stopped.")

    def get_latest_frame(self):
        with self.lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
            return None

    def capture_face_vector(self):
        """
        Attempts to crop the latest frame and extract the 128-dimensional face encoding vector.
        """
        with self.lock:
            if self.latest_frame is None:
                logger.warning("No frame captured to encode")
                return None
            frame = self.latest_frame.copy()
            
        if not is_face_rec_available():
            # Simulate face vector: list of 128 floating points
            logger.info("Simulating 128-dimensional face encoding vector...")
            time.sleep(0.5) # Simulate encoding delay
            return (np.random.rand(128) * 2 - 1).tolist()
            
        import face_recognition
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
        if hasattr(self, "picam2") and self.picam2:
            try:
                self.picam2.stop()
                self.picam2.close()
            except Exception:
                pass
            self.picam2 = None
        self.wait()

class FaceVectorWorker(QThread):
    vector_ready = pyqtSignal(object)  # Emits vector list or None

    def __init__(self, camera_service):
        super().__init__()
        self.camera_service = camera_service

    def run(self):
        vector = self.camera_service.capture_face_vector()
        self.vector_ready.emit(vector)
