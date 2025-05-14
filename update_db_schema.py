"""
Database migration script to update schema with new fields and tables
"""
import os
import sys
import sqlite3
from datetime import datetime

# Get the database path
DB_PATH = "instance/ac_control.db"

def update_database():
    """Update the database schema with new columns and tables"""
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file {DB_PATH} not found")
        sys.exit(1)
        
    print(f"Updating database at {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Add new fields to existing tables
        
        # Update PendingWindowEvent table
        add_column_if_not_exists(cursor, "pending_window_event", "event_type", "TEXT DEFAULT 'window_open'")
        
        # Update WindowEvent table
        add_column_if_not_exists(cursor, "window_event", "policy_compliant", "BOOLEAN DEFAULT 1")
        add_column_if_not_exists(cursor, "window_event", "compliance_issue", "TEXT")
        
        # Update ACSettings table
        add_column_if_not_exists(cursor, "ac_settings", "schedule_override", "BOOLEAN DEFAULT 0")
        add_column_if_not_exists(cursor, "ac_settings", "window_open_minutes", "INTEGER DEFAULT 0")
        add_column_if_not_exists(cursor, "ac_settings", "temperature_deviation", "REAL DEFAULT 0.0")
        add_column_if_not_exists(cursor, "ac_settings", "compliance_score", "REAL DEFAULT 100.0")
        
        # Create new tables if they don't exist
        
        # GlobalPolicy table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_policy (
            id INTEGER PRIMARY KEY,
            min_allowed_temp REAL DEFAULT 18.0,
            max_allowed_temp REAL DEFAULT 26.0,
            policy_active BOOLEAN DEFAULT 1,
            scheduled_shutoff_active BOOLEAN DEFAULT 0,
            scheduled_shutoff_time TIME DEFAULT '22:00:00',
            scheduled_startup_time TIME DEFAULT '07:00:00',
            apply_shutoff_weekends BOOLEAN DEFAULT 0,
            energy_conservation_active BOOLEAN DEFAULT 0,
            conservation_threshold REAL DEFAULT 24.0
        )
        """)
        
        # RoomStatus table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS room_status (
            id INTEGER PRIMARY KEY,
            room_number TEXT UNIQUE,
            current_temperature REAL DEFAULT 22.0,
            window_state TEXT DEFAULT 'closed',
            ac_state TEXT DEFAULT 'off',
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            has_pending_event BOOLEAN DEFAULT 0,
            pending_event_time TIMESTAMP,
            FOREIGN KEY (room_number) REFERENCES user (room_number)
        )
        """)
        
        # Insert default GlobalPolicy if none exists
        cursor.execute("SELECT COUNT(*) FROM global_policy")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
            INSERT INTO global_policy (
                min_allowed_temp, max_allowed_temp, policy_active,
                scheduled_shutoff_active, scheduled_shutoff_time, scheduled_startup_time
            ) VALUES (
                18.0, 26.0, 1, 
                0, '22:00:00', '07:00:00'
            )
            """)
        
        # Initialize RoomStatus for all rooms that don't have it
        cursor.execute("""
        INSERT OR IGNORE INTO room_status (room_number)
        SELECT room_number FROM user WHERE room_number IS NOT NULL
        """)
        
        # Populate RoomStatus with the latest status for each room
        cursor.execute("""
        SELECT DISTINCT room_number FROM window_event
        """)
        rooms = cursor.fetchall()
        
        for room in rooms:
            room_number = room[0]
            # Get latest event for this room
            cursor.execute("""
            SELECT window_state, ac_state, temperature, timestamp
            FROM window_event 
            WHERE room_number = ? 
            ORDER BY timestamp DESC LIMIT 1
            """, (room_number,))
            
            latest = cursor.fetchone()
            if latest:
                window_state, ac_state, temperature, timestamp = latest
                # Update RoomStatus
                cursor.execute("""
                UPDATE room_status
                SET window_state = ?, ac_state = ?, current_temperature = ?, last_updated = ?
                WHERE room_number = ?
                """, (window_state, ac_state, temperature, timestamp, room_number))
        
        conn.commit()
        print("Database schema updated successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"Error updating database: {str(e)}")
        raise
    finally:
        conn.close()

def add_column_if_not_exists(cursor, table, column, column_type):
    """Add a column to a table if it doesn't already exist"""
    # Check if the column exists
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [info[1] for info in cursor.fetchall()]
    
    if column not in columns:
        print(f"Adding column {column} to table {table}")
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
        return True
    return False

if __name__ == "__main__":
    update_database()