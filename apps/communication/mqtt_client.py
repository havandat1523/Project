import paho.mqtt.client as mqtt
import json
import time
import threading
from config import config
from apps.communication.envelope import sign_payload, verify_envelope
from apps.communication.outbox_manager import add_to_outbox, get_pending_messages, mark_as_sent
from services.logger import get_logger

logger = get_logger("MQTT")

class MQTTClient:
    def __init__(self, callback_handler=None):
        """
        callback_handler is an object with methods to handle server responses:
        e.g., on_driver_login_ack(data), on_attendant_login_ack(data), on_server_command(data)
        """
        self.callback_handler = callback_handler
        self.client = mqtt.Client(client_id=f"vehicle_{config.VEHICLE_ID}")
        
        if config.MQTT_USERNAME:
            self.client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
            
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        
        self.is_connected = False
        self.running = False
        
        # Outbox thread
        self.outbox_thread = None
        
        # Topic Maps
        self.topic_map = {
            1: "driver/login",
            2: "driver/login/ack",
            3: "driver/logout",
            4: "driver/logout/ack",
            5: "driver/presence_violation",
            6: "attendant/login",
            7: "attendant/login/ack",
            8: "attendant/logout",
            9: "attendant/logout/ack",
            10: "attendant/presence_violation",
            11: "student/scan",
            12: "student/event",
            13: "seat/status",
            14: "telemetry",
            15: "emergency/sos",
            16: "emergency/child_alone",
            17: "driver/enroll",
            18: "driver/enroll/ack",
            19: "system/heartbeat",
            20: "command"
        }

    def start(self):
        self.running = True
        try:
            self.client.connect(config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT, keepalive=60)
            self.client.loop_start()
            logger.info("Connecting to MQTT Broker at %s:%d...", config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT)
        except Exception as e:
            logger.error("Failed to connect to MQTT broker: %s. Loop will automatically retry.", e)
            self.client.loop_start() # Client loop handles automatic reconnection
            
        # Start Outbox replay thread
        self.outbox_thread = threading.Thread(target=self.outbox_worker, daemon=True)
        self.outbox_thread.start()

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.is_connected = True
            logger.info("Connected to MQTT Broker successfully!")
            
            # Subscribe to Acks and Commands
            # Topics:
            # schoolbus/{vehicle_id}/driver/login/ack
            # schoolbus/{vehicle_id}/driver/logout/ack
            # schoolbus/{vehicle_id}/attendant/login/ack
            # schoolbus/{vehicle_id}/attendant/logout/ack
            # schoolbus/{vehicle_id}/driver/enroll/ack
            # schoolbus/{vehicle_id}/command
            base_topic = f"schoolbus/{config.VEHICLE_ID}"
            self.client.subscribe(f"{base_topic}/driver/+/ack")
            self.client.subscribe(f"{base_topic}/attendant/+/ack")
            self.client.subscribe(f"{base_topic}/command")
            logger.info("Subscribed to command & acknowledgement topics")
        else:
            logger.error("Connect failed with code %d", rc)

    def on_disconnect(self, client, userdata, rc):
        self.is_connected = False
        logger.warning("Disconnected from MQTT Broker (rc=%d)", rc)

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload_str = msg.payload.decode("utf-8")
        logger.debug("Received MQTT message: %s -> %s", topic, payload_str)
        
        try:
            envelope = json.loads(payload_str)
            # Verify signature
            if not verify_envelope(envelope):
                logger.warning("Received invalid signature on topic %s! Dropping message.", topic)
                return
                
            msg_type = envelope["type"]
            data = envelope["data"]
            
            # Route to callback handlers
            if msg_type == 2: # driver_login_response
                if self.callback_handler and hasattr(self.callback_handler, "on_driver_login_ack"):
                    self.callback_handler.on_driver_login_ack(data)
            elif msg_type == 4: # driver_logout_response
                if self.callback_handler and hasattr(self.callback_handler, "on_driver_logout_ack"):
                    self.callback_handler.on_driver_logout_ack(data)
            elif msg_type == 7: # attendant_login_response
                if self.callback_handler and hasattr(self.callback_handler, "on_attendant_login_ack"):
                    self.callback_handler.on_attendant_login_ack(data)
            elif msg_type == 9: # attendant_logout_response
                if self.callback_handler and hasattr(self.callback_handler, "on_attendant_logout_ack"):
                    self.callback_handler.on_attendant_logout_ack(data)
            elif msg_type == 18: # driver_enroll_ack
                if self.callback_handler and hasattr(self.callback_handler, "on_driver_enroll_ack"):
                    self.callback_handler.on_driver_enroll_ack(data)
            elif msg_type == 20: # server command
                if self.callback_handler and hasattr(self.callback_handler, "on_server_command"):
                    self.callback_handler.on_server_command(data)
                    
        except Exception as e:
            logger.error("Error processing MQTT message: %s", e)

    def publish_message(self, msg_type: int, data: dict, priority: int = 0) -> bool:
        """
        Publishes message.
        If offline and type is cacheable (5,10,11,12,13,14,19), stores in Outbox and returns True.
        If offline and type is NOT cacheable (login/logout/enroll requests), returns False.
        """
        # Determine caching eligibility (interactive credentials are NOT cached)
        interactive_types = (1, 3, 6, 8, 17) # login, logout, enroll
        
        if not self.is_connected:
            if msg_type in interactive_types:
                logger.warning("Offline: Cannot publish interactive message type %d", msg_type)
                return False
            else:
                # Add to local outbox cache
                add_to_outbox(msg_type, data, priority)
                return True
                
        # We are online, sign envelope and publish directly
        envelope = sign_payload(msg_type, data)
        sub_topic = self.topic_map.get(msg_type, "system/unknown")
        full_topic = f"schoolbus/{config.VEHICLE_ID}/{sub_topic}"
        
        # QoS level selection
        qos = 1
        if msg_type in (15, 16): # Emergency / SOS
            qos = 2
            
        try:
            info = self.client.publish(full_topic, json.dumps(envelope), qos=qos)
            info.wait_for_publish() # Wait for ACK
            logger.info("Published message type %d to %s", msg_type, full_topic)
            return True
        except Exception as e:
            logger.error("Error publishing message directly: %s", e)
            if msg_type not in interactive_types:
                add_to_outbox(msg_type, data, priority)
                return True
            return False

    def outbox_worker(self):
        """
        Background worker that polls SQLite outbox and publishes pending entries when online.
        """
        logger.info("MQTT Outbox replay thread started.")
        while self.running:
            if self.is_connected:
                pending = get_pending_messages()
                if pending:
                    logger.info("Found %d pending messages in offline outbox. Starting replay...", len(pending))
                    for msg in pending:
                        if not self.is_connected:
                            break
                            
                        # Add replay flag to bypass 30s timestamp anti-replay check
                        payload = msg["payload"]
                        payload["data"]["is_replay"] = True
                        
                        sub_topic = self.topic_map.get(msg["type"], "system/unknown")
                        full_topic = f"schoolbus/{config.VEHICLE_ID}/{sub_topic}"
                        
                        qos = 1
                        if msg["type"] in (15, 16):
                            qos = 2
                            
                        try:
                            info = self.client.publish(full_topic, json.dumps(payload), qos=qos)
                            info.wait_for_publish(timeout=5)
                            mark_as_sent(msg["id"])
                            # Small delay to prevent network spamming
                            time.sleep(0.1)
                        except Exception as e:
                            logger.error("Failed to replay outbox ID %d: %s. Retrying later...", msg["id"], e)
                            break
            
            # Poll every 5 seconds for connection check and replay
            time.sleep(5)

    def stop(self):
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("MQTT Client stopped.")
