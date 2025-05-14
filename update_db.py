"""
Script to update the database schema with the new columns and tables
"""
import os
import sqlite3
import sys

def update_database():
    """Update the database schema with new columns and tables"""
    db_path = 'instance/ac_control.db'
    
    if not os.path.exists(db_path):
        print(f"Database file not found at {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Add force_on_enabled column to ACSettings table
        add_column_if_not_exists(cursor, 'ac_settings', 'force_on_enabled', 'BOOLEAN DEFAULT 1')
        
        # Add non_compliant_since and policy_violation_type columns to RoomStatus table
        add_column_if_not_exists(cursor, 'room_status', 'non_compliant_since', 'TIMESTAMP')
        add_column_if_not_exists(cursor, 'room_status', 'policy_violation_type', 'VARCHAR(50)')
        
        conn.commit()
        print("Database updated successfully!")
    except Exception as e:
        conn.rollback()
        print(f"Error updating database: {e}")
    finally:
        conn.close()

def add_column_if_not_exists(cursor, table, column, column_type):
    """Add a column to a table if it doesn't already exist"""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [info[1] for info in cursor.fetchall()]
    
    if column not in columns:
        print(f"Adding column {column} to {table}")
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    else:
        print(f"Column {column} already exists in {table}")

if __name__ == "__main__":
    update_database()