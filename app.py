import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from sqlalchemy.orm import DeclarativeBase
from apscheduler.schedulers.background import BackgroundScheduler

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class Base(DeclarativeBase):
    pass
 
db: SQLAlchemy = SQLAlchemy(model_class=Base)
login_manager: LoginManager = LoginManager()
mail = Mail()
scheduler = BackgroundScheduler()

# Create the app
app: Flask = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev_key")

# Configure database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ac_control.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Configure email
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')

# Initialize extensions
db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = "login" # type: ignore
mail.init_app(app)

# Import routes after app initialization
from routes import *  # noqa

def check_pending_window_events():
    """
    Check for pending window events and process them if their delay time has elapsed
    """
    with app.app_context():
        from models import PendingWindowEvent, WindowEvent
        from datetime import datetime
        import logging
        
        # Get all pending events that haven't been processed yet and their scheduled time has passed
        pending_events = PendingWindowEvent.query.filter_by(processed=False) \
            .filter(PendingWindowEvent.scheduled_action_time <= datetime.utcnow()) \
            .all()
        
        for event in pending_events:
            try:
                # Create a WindowEvent from the pending event
                final_event = WindowEvent()
                final_event.room_number = event.room_number
                final_event.window_state = event.window_state
                final_event.ac_state = 'off' if event.ac_state == 'on' else event.ac_state  # Turn off AC
                final_event.temperature = event.temperature
                
                # Add and commit the final event
                db.session.add(final_event)
                
                # Mark pending event as processed
                event.processed = True
                db.session.commit()
                
                logging.info(f"Processed pending event {event.id} for room {event.room_number}")
                
                # If notification is needed, you could trigger it here
                from routes import send_notification
                from models import User, ACSettings
                
                user = User.query.filter_by(room_number=event.room_number).first()
                settings = ACSettings.query.filter_by(room_number=event.room_number).first()
                
                if user and settings and settings.email_notifications:
                    try:
                        send_notification(user.email)
                        logging.info(f"Sent delayed notification to {user.email}")
                    except Exception as e:
                        logging.error(f"Failed to send notification: {str(e)}")
                        
            except Exception as e:
                db.session.rollback()
                logging.error(f"Error processing pending event {event.id}: {str(e)}")

# Start scheduler
scheduler.add_job(check_pending_window_events, 'interval', seconds=10)  # Check every 10 seconds
scheduler.start()

with app.app_context():
    # Import models to ensure they're registered with SQLAlchemy
    from models import User, ACSettings, WindowEvent, PendingWindowEvent  # noqa
    db.create_all()