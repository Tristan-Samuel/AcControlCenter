from datetime import datetime, time
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    pin = db.Column(db.String(256))  # Store hashed PIN
    is_admin = db.Column(db.Boolean, default=False)
    room_number = db.Column(db.String(10), unique=True, nullable=True)  # Made nullable for admin users

    # Create the relationship to ACSettings
    acsettings = db.relationship("ACSettings", backref=db.backref("user", uselist=False), uselist=False)

    def __init__(self, username=None, email=None, room_number=None, is_admin=False):
        self.username = username
        self.email = email
        self.room_number = room_number
        self.is_admin = is_admin

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        try:
            return check_password_hash(self.password_hash, password)
        except:
            # Fallback for old password hashes
            self.set_password(password)
            return True

    def set_pin(self, pin):
        self.pin = generate_password_hash(pin, method='pbkdf2:sha256')

    def check_pin(self, pin):
        if not self.pin:
            return False
        try:
            return check_password_hash(self.pin, pin)
        except:
            # Fallback for old PINs
            self.set_pin(pin)
            return True

class GlobalPolicy(db.Model):
    """Global policies set by administrators for all rooms"""
    id = db.Column(db.Integer, primary_key=True)
    min_allowed_temp = db.Column(db.Float, default=18.0)  # Minimum allowed temperature setting
    max_allowed_temp = db.Column(db.Float, default=26.0)  # Maximum allowed temperature setting
    policy_active = db.Column(db.Boolean, default=True)    # Whether the policy is currently active
    
    # Scheduled shutoff times
    scheduled_shutoff_active = db.Column(db.Boolean, default=False)
    scheduled_shutoff_time = db.Column(db.Time, default=time(22, 0))  # 10 PM default
    scheduled_startup_time = db.Column(db.Time, default=time(7, 0))   # 7 AM default
    apply_shutoff_weekends = db.Column(db.Boolean, default=False)     # Whether to apply shutoff on weekends

    # Energy conservation policy
    energy_conservation_active = db.Column(db.Boolean, default=False)
    conservation_threshold = db.Column(db.Float, default=24.0)        # Temperature threshold for conservation mode

    def __init__(self):
        pass  # Use default values

class ACSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey('user.room_number'))
    max_temperature = db.Column(db.Float, default=24.0)
    auto_shutoff = db.Column(db.Boolean, default=True)
    shutoff_delay = db.Column(db.Integer, default=30)  # Delay in seconds before AC shuts off
    email_notifications = db.Column(db.Boolean, default=True)
    settings_locked = db.Column(db.Boolean, default=False)
    max_temp_locked = db.Column(db.Boolean, default=False)  # Locks max temperature separately
    force_on_enabled = db.Column(db.Boolean, default=True)  # Whether Force Turn ON is allowed for this room
    
    # Schedule override settings
    schedule_override = db.Column(db.Boolean, default=False)  # Whether this room is exempt from global schedule
    
    # Compliance metrics
    window_open_minutes = db.Column(db.Integer, default=0)    # Minutes with window open and AC on in the last 24 hours
    temperature_deviation = db.Column(db.Float, default=0.0)  # Average deviation from policy temperature
    compliance_score = db.Column(db.Float, default=100.0)     # Overall compliance score (0-100)

    def __init__(self, room_number=None):
        self.room_number = room_number

class WindowEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey('user.room_number'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    window_state = db.Column(db.String(10))  # 'opened' or 'closed'
    ac_state = db.Column(db.String(10))  # 'on' or 'off'
    temperature = db.Column(db.Float)
    # Additional fields for tracking policy compliance
    policy_compliant = db.Column(db.Boolean, default=True)
    compliance_issue = db.Column(db.String(100), nullable=True)

class PendingWindowEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey('user.room_number'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    window_state = db.Column(db.String(10))  # 'opened' or 'closed'
    ac_state = db.Column(db.String(10))  # 'on' or 'off'
    temperature = db.Column(db.Float)
    scheduled_action_time = db.Column(db.DateTime)  # When the action is scheduled to happen
    processed = db.Column(db.Boolean, default=False)  # Whether this event has been processed
    event_type = db.Column(db.String(20), default='window_open')  # Type of event (window_open, scheduled, etc.)

class RoomStatus(db.Model):
    """Current status of a room - updated continuously from events"""
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey('user.room_number'), unique=True)
    current_temperature = db.Column(db.Float, default=22.0)
    window_state = db.Column(db.String(10), default='closed')  # 'opened' or 'closed'
    ac_state = db.Column(db.String(10), default='off')  # 'on' or 'off'
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    has_pending_event = db.Column(db.Boolean, default=False)  # Whether there's a pending action for this room
    pending_event_time = db.Column(db.DateTime, nullable=True)  # When the pending action will occur
    
    # Temperature policy compliance tracking
    non_compliant_since = db.Column(db.DateTime, nullable=True)  # When temperature became non-compliant
    policy_violation_type = db.Column(db.String(50), nullable=True)  # Type of violation (too low, too high, etc.)
    
    def __init__(self, **kwargs):
        """Initialize a room status with kwargs support"""
        self.room_number = kwargs.get('room_number')
        
        if 'current_temperature' in kwargs:
            self.current_temperature = kwargs.get('current_temperature')
        
        if 'window_state' in kwargs:
            self.window_state = kwargs.get('window_state')
            
        if 'ac_state' in kwargs:
            self.ac_state = kwargs.get('ac_state')
            
        if 'last_updated' in kwargs:
            self.last_updated = kwargs.get('last_updated')
        else:
            self.last_updated = datetime.utcnow()
            
        self.has_pending_event = kwargs.get('has_pending_event', False)
        self.pending_event_time = kwargs.get('pending_event_time')

class SessionAtributes():
    def __init__(self, room_number, is_admin):
        self.room_number = room_number
        self.is_admin = is_admin