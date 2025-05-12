from datetime import datetime
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
        self.password_hash = generate_password_hash(password, method='sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_pin(self, pin):
        self.pin = generate_password_hash(pin, method='sha256')

    def check_pin(self, pin):
        if not self.pin:
            return False
        return check_password_hash(self.pin, pin)

class ACSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey('user.room_number'))
    max_temperature = db.Column(db.Float, default=24.0)
    auto_shutoff = db.Column(db.Boolean, default=True)
    email_notifications = db.Column(db.Boolean, default=True)
    settings_locked = db.Column(db.Boolean, default=False)
    max_temp_locked = db.Column(db.Boolean, default=False)  # Locks max temperature separately
    
    def __init__(self, room_number=None):
        self.room_number = room_number

class WindowEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey('user.room_number'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    window_state = db.Column(db.String(10))  # 'opened' or 'closed'
    ac_state = db.Column(db.String(10))  # 'on' or 'off'
    temperature = db.Column(db.Float)

class SessionAtributes():
    def __init__(self, room_number, is_admin):
        self.room_number = room_number
        self.is_admin = is_admin