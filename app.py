import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from sqlalchemy.orm import DeclarativeBase
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, time, timedelta

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
from check_command_endpoint import *  # Import the check_command endpoint

def check_pending_window_events():
    """
    Check for pending window events and process them if their delay time has elapsed
    """
    with app.app_context():
        from models import PendingWindowEvent, WindowEvent, RoomStatus
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
                
                # Update room status
                room_status = RoomStatus.query.filter_by(room_number=event.room_number).first()
                if not room_status:
                    room_status = RoomStatus(
                        room_number=event.room_number,
                        current_temperature=event.temperature,
                        window_state=event.window_state,
                        ac_state='off' if event.ac_state == 'on' else event.ac_state
                    )
                    db.session.add(room_status)
                else:
                    room_status.window_state = event.window_state
                    room_status.ac_state = 'off' if event.ac_state == 'on' else event.ac_state
                    room_status.current_temperature = event.temperature
                    room_status.has_pending_event = False
                    room_status.pending_event_time = None
                    room_status.last_updated = datetime.utcnow()
                
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

def check_scheduled_shutoffs():
    """Check for scheduled AC shutoffs based on global policy"""
    with app.app_context():
        from models import GlobalPolicy, ACSettings, User, PendingWindowEvent, RoomStatus
        
        now = datetime.now()
        current_time = now.time()
        
        # Skip on weekends if policy says so
        if now.weekday() >= 5:  # 5=Saturday, 6=Sunday
            policy = GlobalPolicy.query.first()
            if policy and policy.scheduled_shutoff_active and not policy.apply_shutoff_weekends:
                return
        
        # Get the global policy
        policy = GlobalPolicy.query.first()
        if not policy or not policy.scheduled_shutoff_active:
            return
            
        # Time to shut off ACs?
        if time_in_range(policy.scheduled_startup_time, policy.scheduled_shutoff_time, current_time):
            # It's during active hours - make sure ACs are allowed to run
            logging.info("During active hours - no shutoff needed")
            return
        else:
            # It's outside active hours - schedule shutoff for any active ACs
            logging.info("Outside active hours - checking for ACs to shut off")
            
            # Find all rooms with AC currently on
            room_statuses = RoomStatus.query.filter_by(ac_state='on').all()
            
            for status in room_statuses:
                # Skip rooms with schedule override
                ac_setting = ACSettings.query.filter_by(room_number=status.room_number).first()
                if ac_setting and ac_setting.schedule_override:
                    continue
                    
                # Create a pending event to shut off this room's AC
                logging.info(f"Scheduling shutoff for room {status.room_number} due to global schedule")
                pending = PendingWindowEvent()
                pending.room_number = status.room_number
                pending.window_state = status.window_state
                pending.ac_state = status.ac_state
                pending.temperature = status.current_temperature
                pending.scheduled_action_time = datetime.utcnow() + timedelta(seconds=30)  # 30 second grace period
                pending.processed = False
                pending.event_type = 'scheduled_shutoff'
                
                # Update room status
                status.has_pending_event = True
                status.pending_event_time = pending.scheduled_action_time
                
                # Save changes
                db.session.add(pending)
                db.session.commit()

def update_compliance_metrics():
    """Update compliance metrics for all rooms"""
    with app.app_context():
        from models import ACSettings, WindowEvent, GlobalPolicy, User
        
        # Get policy
        policy = GlobalPolicy.query.first()
        if not policy:
            return
            
        # Get all rooms
        rooms = User.query.filter(User.room_number != None).all()
        
        for room in rooms:
            try:
                # Get settings for this room
                settings = ACSettings.query.filter_by(room_number=room.room_number).first()
                if not settings:
                    continue
                
                # Calculate window_open_minutes (time with window open and AC on)
                one_day_ago = datetime.utcnow() - timedelta(days=1)
                window_open_events = WindowEvent.query.filter(
                    WindowEvent.room_number == room.room_number,
                    WindowEvent.timestamp >= one_day_ago,
                    WindowEvent.window_state == 'opened',
                    WindowEvent.ac_state == 'on'
                ).all()
                
                # Rough estimate - each event represents about 1 minute
                window_open_minutes = len(window_open_events)
                
                # Calculate temperature deviation
                # Get the average difference between room temperature and policy limits
                temp_events = WindowEvent.query.filter(
                    WindowEvent.room_number == room.room_number,
                    WindowEvent.timestamp >= one_day_ago
                ).all()
                
                total_deviation = 0.0
                event_count = len(temp_events)
                
                if event_count > 0:
                    for event in temp_events:
                        # Calculate how far the temperature is from the acceptable range
                        if event.temperature < policy.min_allowed_temp:
                            deviation = policy.min_allowed_temp - event.temperature
                        elif event.temperature > policy.max_allowed_temp:
                            deviation = event.temperature - policy.max_allowed_temp
                        else:
                            deviation = 0.0
                        total_deviation += deviation
                    
                    avg_deviation = total_deviation / event_count
                else:
                    avg_deviation = 0.0
                
                # Calculate compliance score (100 is perfect, lower is worse)
                # Formula: start with 100, subtract penalties
                compliance_score = 100.0
                
                # Penalty for window open minutes
                window_penalty = min(50, window_open_minutes * 0.5)  # Max 50 point penalty
                
                # Penalty for temperature deviation
                temp_penalty = min(50, avg_deviation * 10)  # Max 50 point penalty
                
                compliance_score -= (window_penalty + temp_penalty)
                compliance_score = max(0, compliance_score)  # Ensure it doesn't go negative
                
                # Update settings
                settings.window_open_minutes = window_open_minutes
                settings.temperature_deviation = avg_deviation
                settings.compliance_score = compliance_score
                
                # Save changes
                db.session.commit()
                logging.info(f"Updated compliance metrics for room {room.room_number}: score={compliance_score}")
                
            except Exception as e:
                db.session.rollback()
                logging.error(f"Error updating compliance for room {room.room_number}: {str(e)}")

def time_in_range(start, end, current):
    """Returns whether current is in the range [start, end]"""
    # Handle the case where a period crosses midnight
    if start <= end:
        return start <= current <= end
    else:
        return start <= current or current <= end
        
def check_temperature_compliance():
    """Check temperature compliance with policy and schedule auto-shutoff if violation persists"""
    with app.app_context():
        from models import RoomStatus, GlobalPolicy, PendingWindowEvent, ACSettings, User
        
        # Get the global policy
        policy = GlobalPolicy.query.first()
        if not policy or not policy.policy_active:
            return
            
        # Get all rooms with AC turned on
        rooms_with_ac_on = RoomStatus.query.filter_by(ac_state='on').all()
        
        for room in rooms_with_ac_on:
            # Skip rooms with pending events
            if room.has_pending_event:
                continue
                
            # Check if temperature violates policy - for AC systems we're concerned with cooling too much
            is_compliant = True
            compliance_issue = None
            
            if room.current_temperature < policy.min_allowed_temp:
                # Temperature too cold - this is our main concern for AC systems
                is_compliant = False
                from temperature_utils import celsius_to_fahrenheit
                min_temp_f = celsius_to_fahrenheit(policy.min_allowed_temp)
                current_temp_f = celsius_to_fahrenheit(room.current_temperature)
                compliance_issue = f"Temperature too cold: {current_temp_f:.1f}°F (min: {min_temp_f:.1f}°F)"
            
            # Handle compliance status change
            if not is_compliant:
                # If this is a new violation, mark the start time
                if room.non_compliant_since is None:
                    room.non_compliant_since = datetime.utcnow()
                    room.policy_violation_type = compliance_issue
                    db.session.commit()
                    logging.info(f"Room {room.room_number} temperature non-compliant: {compliance_issue}")
                else:
                    # Check if violation has persisted for 10 seconds
                    violation_time = datetime.utcnow() - room.non_compliant_since
                    if violation_time.total_seconds() >= 10 and not room.has_pending_event:
                        # Schedule an AC shutoff
                        room.has_pending_event = True
                        scheduled_time = datetime.utcnow() + timedelta(seconds=1)  # Almost immediate
                        room.pending_event_time = scheduled_time
                        
                        # Create pending event
                        pending_event = PendingWindowEvent()
                        pending_event.room_number = room.room_number
                        pending_event.window_state = room.window_state
                        pending_event.ac_state = room.ac_state
                        pending_event.temperature = room.current_temperature
                        pending_event.scheduled_action_time = scheduled_time
                        pending_event.event_type = 'temperature_violation'
                        db.session.add(pending_event)
                        db.session.commit()
                        
                        logging.info(f"Scheduled AC shutoff for room {room.room_number} due to temperature policy violation")
            else:
                # Reset compliance tracking if temperature is now compliant
                if room.non_compliant_since is not None:
                    room.non_compliant_since = None
                    room.policy_violation_type = None
                    db.session.commit()
                    logging.info(f"Room {room.room_number} temperature now compliant")

# Start scheduler
scheduler.add_job(check_pending_window_events, 'interval', seconds=10)  # Check every 10 seconds
scheduler.add_job(check_scheduled_shutoffs, 'interval', minutes=5)  # Check every 5 minutes
scheduler.add_job(update_compliance_metrics, 'interval', hours=1)  # Update metrics hourly
scheduler.add_job(check_temperature_compliance, 'interval', seconds=5)  # Check temperature compliance every 5 seconds
scheduler.start()

with app.app_context():
    # Import models to ensure they're registered with SQLAlchemy
    from models import User, ACSettings, WindowEvent, PendingWindowEvent, GlobalPolicy, RoomStatus  # noqa
    
    # Create all tables
    db.create_all()
    
    # Initialize a default global policy if one doesn't exist
    policy = GlobalPolicy.query.first()
    if not policy:
        policy = GlobalPolicy()
        db.session.add(policy)
        db.session.commit()
        logging.info("Created default global policy")
    
    # Initialize RoomStatus for all existing rooms
    users = User.query.filter(User.room_number != None).all()
    for user in users:
        status = RoomStatus.query.filter_by(room_number=user.room_number).first()
        if not status:
            # Get latest event for this room
            latest_event = WindowEvent.query.filter_by(room_number=user.room_number).order_by(WindowEvent.timestamp.desc()).first()
            
            # Create initial status
            status = RoomStatus(room_number=user.room_number)
            if latest_event:
                status.window_state = latest_event.window_state
                status.ac_state = latest_event.ac_state
                status.current_temperature = latest_event.temperature
                
            db.session.add(status)
            logging.info(f"Created initial status for room {user.room_number}")
    
    db.session.commit()