import sqlite3
import os
import json
from services.logger import get_logger

logger = get_logger("Database")

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "local_cache.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Create Outbox Table for Offline Messages Queue
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            sent_at INTEGER DEFAULT NULL
        )
    """)
    
    # 2. Create Local Face Cache for offline verification
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS face_cache (
            user_id TEXT PRIMARY KEY,
            user_type TEXT NOT NULL, -- 'driver' or 'attendant'
            full_name TEXT,
            face_vector_json TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("Local SQLite database initialized successfully at %s", DB_PATH)

init_db()
