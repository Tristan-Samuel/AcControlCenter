"""
Script to update the database schema with the new columns and tables
"""
from app import app, db
import os

def update_database():
    with app.app_context():
        # Drop all tables
        db.drop_all()
        
        # Import models to ensure they're registered with SQLAlchemy
        from models import User, ACSettings, WindowEvent, PendingWindowEvent
        
        # Recreate all tables
        db.create_all()
        
        print("Database schema has been updated!")
        print("New tables and columns created:")
        print("- Added 'shutoff_delay' column to ACSettings")
        print("- Added PendingWindowEvent table for delayed AC shutoffs")

if __name__ == "__main__":
    update_database()