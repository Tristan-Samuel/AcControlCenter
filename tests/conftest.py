from __future__ import annotations

import pytest

from ac_control import create_app
from ac_control.config import TestingConfig
from ac_control.extensions import db
from ac_control.models import ACSettings, RoomStatus, User


@pytest.fixture()
def app():
    application = create_app(TestingConfig)
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_user(app):
    with app.app_context():
        user = User(username="admin", email="admin@example.com", is_admin=True)
        user.set_password("secret")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture()
def room_setup(app):
    with app.app_context():
        user = User(
            username="room7",
            email="room7@example.com",
            room_number="7",
            is_admin=False,
        )
        user.set_password("room-secret")
        user.set_pin("1234")
        raw_key = ACSettings.generate_device_key()
        settings = ACSettings(room_number="7", auto_shutoff=True, shutoff_delay=0)
        settings.set_device_key(raw_key)
        db.session.add(user)
        db.session.flush()
        db.session.add(settings)
        db.session.add(RoomStatus(room_number="7"))
        db.session.commit()
        return {"api_key": raw_key, "room": "7"}
