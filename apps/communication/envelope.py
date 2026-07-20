import hmac
import hashlib
import json
import time
from config import config

def sign_payload(msg_type: int, data: dict, timestamp: int = None) -> dict:
    """
    Wraps the data in a signed envelope:
    {
        "type": msg_type,
        "ts": timestamp,
        "vid": vehicle_id,
        "data": data,
        "sig": signature
    }
    """
    if timestamp is None:
        timestamp = int(time.time())
        
    vehicle_id = config.VEHICLE_ID
    psk_key = bytes.fromhex(config.DEVICE_PSK)
    
    # Deterministic compact JSON serialization
    serialized_data = json.dumps(data, separators=(',', ':'), sort_keys=True)
    
    # Message to sign: "{type}|{ts}|{vid}|{json_data}"
    sign_msg = f"{msg_type}|{timestamp}|{vehicle_id}|{serialized_data}".encode('utf-8')
    
    # Compute HMAC-SHA256
    sig = hmac.new(psk_key, sign_msg, hashlib.sha256).hexdigest()
    
    envelope = {
        "type": msg_type,
        "ts": timestamp,
        "vid": vehicle_id,
        "data": data,
        "sig": sig
    }
    return envelope

def verify_envelope(envelope: dict) -> bool:
    """
    Verifies the HMAC signature of an incoming envelope.
    """
    try:
        msg_type = envelope["type"]
        timestamp = envelope["ts"]
        vehicle_id = envelope["vid"]
        data = envelope["data"]
        sig = envelope["sig"]
        
        psk_key = bytes.fromhex(config.DEVICE_PSK)
        serialized_data = json.dumps(data, separators=(',', ':'), sort_keys=True)
        
        sign_msg = f"{msg_type}|{timestamp}|{vehicle_id}|{serialized_data}".encode('utf-8')
        expected_sig = hmac.new(psk_key, sign_msg, hashlib.sha256).hexdigest()
        
        return hmac.compare_digest(sig, expected_sig)
    except KeyError:
        return False
