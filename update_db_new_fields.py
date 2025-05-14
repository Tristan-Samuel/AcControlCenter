"""
Database migration script to update schema with new compliance fields
"""
import sqlite3
import os


def update_database():
    """Update the database schema with new columns"""
    db_path = 'instance/ac_control.db'
    
    if not os.path.exists(db_path):
        print(f"Database file not found at {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Add new columns to RoomStatus table
    add_column_if_not_exists(cursor, 'room_status', 'non_compliant_since', 'DATETIME')
    add_column_if_not_exists(cursor, 'room_status', 'policy_violation_type', 'VARCHAR(50)')
    
    # Add the force_on_enabled column to ACSettings table
    add_column_if_not_exists(cursor, 'ac_settings', 'force_on_enabled', 'BOOLEAN', '1')
    
    conn.commit()
    conn.close()
    
    print("Database schema update completed successfully")
    return True


def add_column_if_not_exists(cursor, table, column, column_type, default=None):
    """Add a column to a table if it doesn't already exist"""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [info[1] for info in cursor.fetchall()]
    
    if column not in columns:
        if default is not None:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {column_type} DEFAULT {default}"
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"
        
        cursor.execute(sql)
        print(f"Added column {column} to table {table}")
    else:
        print(f"Column {column} already exists in table {table}")


if __name__ == "__main__":
    update_database()