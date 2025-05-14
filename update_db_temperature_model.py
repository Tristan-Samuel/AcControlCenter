"""
Database migration script to update schema for AC cooling model change
"""
import os
import sqlite3
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)

def update_database():
    """Update the database schema to change max_temperature to min_temperature"""
    db_path = os.path.join("instance", "ac_control.db")
    
    if not os.path.exists(db_path):
        logging.error(f"Database file not found at {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # First, check if the max_temperature column exists
        cursor.execute("PRAGMA table_info(ac_settings)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if "max_temperature" in column_names and "min_temperature" not in column_names:
            # Rename max_temperature to min_temperature
            logging.info("Renaming max_temperature to min_temperature...")
            
            # SQLite doesn't directly support column renaming, so we need to:
            # 1. Create a new table with the desired schema
            # 2. Copy data from the old table
            # 3. Drop the old table
            # 4. Rename the new table to the original name
            
            # Create a new table with min_temperature instead of max_temperature
            cursor.execute("""
                CREATE TABLE ac_settings_new (
                    id INTEGER PRIMARY KEY,
                    room_number VARCHAR(10),
                    min_temperature FLOAT DEFAULT 68.0,
                    auto_shutoff BOOLEAN DEFAULT 1,
                    shutoff_delay INTEGER DEFAULT 30,
                    email_notifications BOOLEAN DEFAULT 1,
                    settings_locked BOOLEAN DEFAULT 0,
                    min_temp_locked BOOLEAN DEFAULT 0,
                    force_on_enabled BOOLEAN DEFAULT 1,
                    schedule_override BOOLEAN DEFAULT 0,
                    window_open_minutes INTEGER DEFAULT 0,
                    temperature_deviation FLOAT DEFAULT 0.0,
                    compliance_score FLOAT DEFAULT 100.0,
                    FOREIGN KEY (room_number) REFERENCES user (room_number)
                )
            """)
            
            # Copy data from the old table, renaming max_temperature to min_temperature
            cursor.execute("""
                INSERT INTO ac_settings_new
                SELECT 
                    id, 
                    room_number, 
                    max_temperature, 
                    auto_shutoff, 
                    shutoff_delay, 
                    email_notifications, 
                    settings_locked, 
                    max_temp_locked AS min_temp_locked, 
                    force_on_enabled,
                    schedule_override,
                    window_open_minutes,
                    temperature_deviation,
                    compliance_score
                FROM ac_settings
            """)
            
            # Drop the old table
            cursor.execute("DROP TABLE ac_settings")
            
            # Rename the new table to the original name
            cursor.execute("ALTER TABLE ac_settings_new RENAME TO ac_settings")
            
            logging.info("Database schema updated successfully")
        else:
            if "min_temperature" in column_names:
                logging.info("Column min_temperature already exists. No changes needed.")
            else:
                logging.error("Expected column max_temperature not found in ac_settings table.")
        
        conn.commit()
        return True
    
    except Exception as e:
        conn.rollback()
        logging.error(f"Error updating database: {str(e)}")
        return False
    
    finally:
        conn.close()

if __name__ == "__main__":
    if update_database():
        print("Database migration completed successfully")
    else:
        print("Database migration failed")