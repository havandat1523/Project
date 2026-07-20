import sqlite3
import json
import time
from services.database import get_db_connection
from apps.communication.envelope import sign_payload
from services.logger import get_logger

logger = get_logger("Outbox")

def add_to_outbox(msg_type: int, data: dict, priority: int = 0) -> int:
    """
    Signs and saves a message into the local outbox.
    Limits telemetry (14) and seat status (13) records to 500.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = int(time.time())
    envelope = sign_payload(msg_type, data, timestamp)
    payload_json = json.dumps(envelope)
    
    try:
        # Save payload
        cursor.execute(
            "INSERT INTO outbox (type, payload_json, priority, created_at) VALUES (?, ?, ?, ?)",
            (msg_type, payload_json, priority, timestamp)
        )
        msg_id = cursor.lastrowid
        
        # Limit cache sizes for time-series streams (telemetry=14, seat_status=13)
        if msg_type in (13, 14):
            cursor.execute("SELECT COUNT(*) FROM outbox WHERE type = ? AND sent_at IS NULL", (msg_type,))
            count = cursor.fetchone()[0]
            if count > 500:
                # Remove oldest unsent records of this type
                limit = count - 500
                cursor.execute(
                    "DELETE FROM outbox WHERE id IN (SELECT id FROM outbox WHERE type = ? AND sent_at IS NULL ORDER BY created_at ASC LIMIT ?)",
                    (msg_type, limit)
                )
                logger.warning("Outbox limit exceeded for message type %d. Purged %d oldest unsent records.", msg_type, limit)
                
        conn.commit()
        logger.debug("Saved unsent message to outbox (ID: %d, Type: %d, Priority: %d)", msg_id, msg_type, priority)
        return msg_id
    except sqlite3.Error as e:
        logger.error("Failed to add message to outbox: %s", e)
        return -1
    finally:
        conn.close()

def get_pending_messages():
    """
    Returns all unsent messages ordered by priority DESC, then created_at ASC.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, type, payload_json, priority FROM outbox WHERE sent_at IS NULL ORDER BY priority DESC, created_at ASC")
        rows = cursor.fetchall()
        return [{"id": r["id"], "type": r["type"], "payload": json.loads(r["payload_json"])} for r in rows]
    except sqlite3.Error as e:
        logger.error("Error reading pending outbox: %s", e)
        return []
    finally:
        conn.close()

def mark_as_sent(msg_id: int):
    """
    Marks a message in the outbox as sent.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE outbox SET sent_at = ? WHERE id = ?", (int(time.time()), msg_id))
        conn.commit()
        logger.debug("Marked outbox message ID %d as sent", msg_id)
    except sqlite3.Error as e:
        logger.error("Error updating outbox message: %s", e)
    finally:
        conn.close()

def clean_sent_messages(days: int = 3):
    """
    Purges historical logs older than X days to save card space.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cutoff = int(time.time()) - (days * 86400)
    try:
        cursor.execute("DELETE FROM outbox WHERE sent_at IS NOT NULL AND sent_at < ?", (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
        if deleted > 0:
            logger.info("Purged %d archived messages older than %d days from outbox", deleted, days)
    except sqlite3.Error as e:
        logger.error("Error cleaning outbox: %s", e)
    finally:
        conn.close()
