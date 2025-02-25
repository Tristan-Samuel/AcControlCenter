from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    is_admin = db.Column(db.Boolean, default=False)
    room_number = db.Column(db.String(10), unique=True, nullable=True)  # Made nullable for admin users
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ACSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey('user.room_number'))
    max_temperature = db.Column(db.Float, default=24.0)
    auto_shutoff = db.Column(db.Boolean, default=True)
    email_notifications = db.Column(db.Boolean, default=True)

class WindowEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey('user.room_number'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    window_state = db.Column(db.String(10))  # 'opened' or 'closed'
    ac_state = db.Column(db.String(10))  # 'on' or 'off'
    temperature = db.Column(db.Float)