from ac_control.models import User
from ac_control.temperature import celsius_to_fahrenheit, fahrenheit_to_celsius
from ac_control.services.policy import time_in_range
from datetime import time


def test_cannot_register_as_admin(client, app):
    response = client.post(
        "/register",
        data={
            "username": "hacker",
            "email": "hacker@example.com",
            "password": "pass1234",
            "confirm_password": "pass1234",
            "room_number": "99",
            "is_admin": "on",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        user = User.query.filter_by(username="hacker").first()
        assert user is not None
        assert user.is_admin is False
        assert user.room_number == "99"


def test_password_check_never_auto_upgrades(app):
    with app.app_context():
        user = User(username="u", email="u@example.com", is_admin=False, room_number="1")
        user.set_password("correct-horse")
        db_hash = user.password_hash
        assert user.check_password("correct-horse") is True
        assert user.check_password("wrong") is False
        assert user.password_hash == db_hash
        user.set_pin("2468")
        pin_hash = user.pin
        assert user.check_pin("2468") is True
        assert user.check_pin("0000") is False
        assert user.pin == pin_hash


def test_heartbeat_unauthorized_without_key(client, room_setup):
    response = client.post(
        "/api/v1/heartbeat",
        json={
            "room_number": "7",
            "window_state": "closed",
            "ac_state": "off",
            "temperature_c": 22.0,
        },
    )
    assert response.status_code == 401


def test_heartbeat_rejects_wrong_key(client, room_setup):
    response = client.post(
        "/api/v1/heartbeat",
        json={
            "room_number": "7",
            "window_state": "closed",
            "ac_state": "off",
            "temperature_c": 22.0,
        },
        headers={"X-API-Key": "not-the-key"},
    )
    assert response.status_code == 401


def test_heartbeat_window_open_schedules_shutoff(client, room_setup):
    response = client.post(
        "/api/v1/heartbeat",
        json={
            "room_number": "7",
            "window_state": "opened",
            "ac_state": "on",
            "temperature_c": 22.0,
        },
        headers={"X-API-Key": room_setup["api_key"]},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert "POWER_OFF" in body["commands"]
    assert body["ac_state"] == "off"


def test_time_in_range_midnight_wrap():
    start = time(22, 0)
    end = time(7, 0)
    assert time_in_range(start, end, time(23, 0)) is True
    assert time_in_range(start, end, time(3, 0)) is True
    assert time_in_range(start, end, time(12, 0)) is False
    assert time_in_range(time(7, 0), time(22, 0), time(12, 0)) is True


def test_celsius_fahrenheit_roundtrip():
    assert celsius_to_fahrenheit(0) == 32
    assert celsius_to_fahrenheit(100) == 212
    assert round(fahrenheit_to_celsius(68), 5) == 20
    assert fahrenheit_to_celsius(None) is None
    assert celsius_to_fahrenheit(None) is None
