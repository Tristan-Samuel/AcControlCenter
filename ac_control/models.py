"""SQLAlchemy models. Passwords and PINs are hashed; failed checks never rewrite hashes."""

from __future__ import annotations

import secrets
from datetime import datetime, time, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ac_control.extensions import db


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


HASH_METHOD = "pbkdf2:sha256"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    pin = db.Column(db.String(256), nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    room_number = db.Column(db.String(10), unique=True, nullable=True)

    acsettings = db.relationship(
        "ACSettings",
        backref=db.backref("user", uselist=False),
        uselist=False,
        cascade="all, delete-orphan",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method=HASH_METHOD)

    def check_password(self, password: str) -> bool:
        if not self.password_hash or not password:
            return False
        return check_password_hash(self.password_hash, password)

    def set_pin(self, pin: str | None) -> None:
        if not pin:
            self.pin = None
            return
        self.pin = generate_password_hash(pin, method=HASH_METHOD)

    def check_pin(self, pin: str) -> bool:
        if not self.pin or not pin:
            return False
        return check_password_hash(self.pin, pin)


class GlobalPolicy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    min_allowed_temp = db.Column(db.Float, default=18.0, nullable=False)
    max_allowed_temp = db.Column(db.Float, default=26.0, nullable=False)
    policy_active = db.Column(db.Boolean, default=True, nullable=False)

    scheduled_shutoff_active = db.Column(db.Boolean, default=False, nullable=False)
    scheduled_shutoff_time = db.Column(db.Time, default=time(22, 0), nullable=False)
    scheduled_startup_time = db.Column(db.Time, default=time(7, 0), nullable=False)
    apply_shutoff_weekends = db.Column(db.Boolean, default=False, nullable=False)

    energy_conservation_active = db.Column(db.Boolean, default=False, nullable=False)
    conservation_threshold = db.Column(db.Float, default=24.0, nullable=False)


class ACSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey("user.room_number"), nullable=False)
    min_temperature = db.Column(db.Float, default=20.0, nullable=False)
    auto_shutoff = db.Column(db.Boolean, default=True, nullable=False)
    shutoff_delay = db.Column(db.Integer, default=30, nullable=False)
    email_notifications = db.Column(db.Boolean, default=True, nullable=False)
    settings_locked = db.Column(db.Boolean, default=False, nullable=False)
    min_temp_locked = db.Column(db.Boolean, default=False, nullable=False)
    force_on_enabled = db.Column(db.Boolean, default=True, nullable=False)
    schedule_override = db.Column(db.Boolean, default=False, nullable=False)

    window_open_minutes = db.Column(db.Integer, default=0, nullable=False)
    temperature_deviation = db.Column(db.Float, default=0.0, nullable=False)
    compliance_score = db.Column(db.Float, default=100.0, nullable=False)

    device_key_hash = db.Column(db.String(256), nullable=True)

    def set_device_key(self, raw_key: str) -> None:
        self.device_key_hash = generate_password_hash(raw_key, method=HASH_METHOD)

    def check_device_key(self, raw_key: str) -> bool:
        if not self.device_key_hash or not raw_key:
            return False
        return check_password_hash(self.device_key_hash, raw_key)

    @staticmethod
    def generate_device_key() -> str:
        return secrets.token_urlsafe(32)


class WindowEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey("user.room_number"), index=True)
    timestamp = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)
    window_state = db.Column(db.String(10), nullable=False)
    ac_state = db.Column(db.String(10), nullable=False)
    temperature = db.Column(db.Float, nullable=True)
    policy_compliant = db.Column(db.Boolean, default=True, nullable=False)
    compliance_issue = db.Column(db.String(200), nullable=True)


class PendingWindowEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey("user.room_number"), index=True)
    timestamp = db.Column(db.DateTime, default=utc_now, nullable=False)
    window_state = db.Column(db.String(10), nullable=True)
    ac_state = db.Column(db.String(10), nullable=True)
    temperature = db.Column(db.Float, nullable=True)
    scheduled_action_time = db.Column(db.DateTime, nullable=False, index=True)
    processed = db.Column(db.Boolean, default=False, nullable=False)
    event_type = db.Column(db.String(32), default="window_open", nullable=False)


class RoomStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(
        db.String(10), db.ForeignKey("user.room_number"), unique=True, nullable=False
    )
    current_temperature = db.Column(db.Float, default=22.0, nullable=False)
    window_state = db.Column(db.String(10), default="closed", nullable=False)
    ac_state = db.Column(db.String(10), default="off", nullable=False)
    last_updated = db.Column(db.DateTime, default=utc_now, nullable=False)
    has_pending_event = db.Column(db.Boolean, default=False, nullable=False)
    pending_event_time = db.Column(db.DateTime, nullable=True)
    non_compliant_since = db.Column(db.DateTime, nullable=True)
    policy_violation_type = db.Column(db.String(80), nullable=True)

    def is_stale(self, stale_after_seconds: int = 180) -> bool:
        if not self.last_updated:
            return True
        age = utc_now() - self.last_updated
        return age.total_seconds() > stale_after_seconds


class DeviceCommand(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), db.ForeignKey("user.room_number"), index=True, nullable=False)
    command = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    delivered = db.Column(db.Boolean, default=False, nullable=False, index=True)
