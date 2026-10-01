from ac_control.models import ACSettings, PendingDevice, RoomStatus
from ac_control.services.devices import claim_pending_device, normalize_mac


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
        from ac_control.models import User

        user = User.query.filter_by(username="hacker").first()
        assert user is not None
        assert user.is_admin is False
        assert user.room_number == "99"


def test_password_check_never_auto_upgrades(app):
    from ac_control.models import User

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
            "door_state": "closed",
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
            "door_state": "closed",
            "ac_state": "off",
            "temperature_c": 22.0,
        },
        headers={"X-API-Key": "not-the-key"},
    )
    assert response.status_code == 401


def test_heartbeat_door_open_schedules_shutoff(client, room_setup):
    response = client.post(
        "/api/v1/heartbeat",
        json={
            "room_number": "7",
            "door_state": "opened",
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
    assert body["door_state"] == "opened"
    assert body["buzz"] is False


def test_window_state_does_not_drive_shutoff(client, room_setup):
    response = client.post(
        "/api/v1/heartbeat",
        json={
            "room_number": "7",
            "window_state": "opened",
            "door_state": "closed",
            "ac_state": "on",
            "temperature_c": 22.0,
        },
        headers={"X-API-Key": room_setup["api_key"]},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert "POWER_OFF" not in (body["commands"] or [])
    assert body["ac_state"] == "on"


def test_normalize_mac():
    assert normalize_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("aabbccddeeff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("nope") is None


def test_enroll_and_claim_by_mac(client, app, room_setup):
    mac = "AA:BB:CC:DD:00:07"
    pending = client.post("/api/v1/enroll", json={"mac": mac, "firmware": "test/1"})
    assert pending.status_code == 200
    body = pending.get_json()
    assert body["assigned"] is False
    assert body["status"] == "pending"

    with app.app_context():
        raw_key = claim_pending_device(mac, "7")
        from ac_control.extensions import db

        db.session.commit()
        row = PendingDevice.query.filter_by(mac=mac).first()
        assert row.assigned_room == "7"
        settings = ACSettings.query.filter_by(room_number="7").first()
        assert settings.device_mac == mac

    claimed = client.post("/api/v1/enroll", json={"mac": mac})
    assert claimed.status_code == 200
    claimed_body = claimed.get_json()
    assert claimed_body["assigned"] is True
    assert claimed_body["room_number"] == "7"
    assert claimed_body["api_key"] == raw_key

    second = client.post("/api/v1/enroll", json={"mac": mac})
    assert second.get_json()["api_key"] is None

    hb = client.post(
        "/api/v1/heartbeat",
        json={
            "mac": mac,
            "door_state": "closed",
            "ac_state": "off",
            "temperature_c": 22.0,
        },
        headers={"X-API-Key": raw_key, "X-Device-Mac": mac},
    )
    assert hb.status_code == 200
    assert hb.get_json()["success"] is True


def test_heartbeat_power_on_includes_last_setpoint(client, app, room_setup):
    with app.app_context():
        status = RoomStatus.query.filter_by(room_number="7").first()
        status.set_temperature = 23.0
        from ac_control.extensions import db

        db.session.commit()

    response = client.post(
        "/api/v1/heartbeat",
        json={
            "room_number": "7",
            "door_state": "closed",
            "ac_state": "off",
            "temperature_c": 22.0,
            "ir_event": "POWER",
        },
        headers={"X-API-Key": room_setup["api_key"]},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert "POWER_ON" in body["commands"]
    assert "SET_TEMP_23" in body["commands"]
    assert body["set_temperature_c"] == 23.0


def test_buzz_on_open_without_shutoff(client, app, room_setup):
    with app.app_context():
        settings = ACSettings.query.filter_by(room_number="7").first()
        settings.auto_shutoff = False
        settings.buzz_on_open = True
        from ac_control.extensions import db

        db.session.commit()

    response = client.post(
        "/api/v1/heartbeat",
        json={
            "room_number": "7",
            "door_state": "opened",
            "ac_state": "on",
            "temperature_c": 22.0,
        },
        headers={"X-API-Key": room_setup["api_key"]},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["buzz"] is True
    assert "POWER_OFF" not in (body["commands"] or [])
    assert body["ac_state"] == "on"


def test_check_command_denies_power_when_door_open(client, room_setup):
    response = client.post(
        "/api/v1/check-command",
        json={
            "room_number": "7",
            "command": "POWER",
            "door_state": "opened",
            "ac_state": "off",
            "temperature": 22.0,
        },
        headers={"X-API-Key": room_setup["api_key"]},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["allowed"] is False
    assert "door" in body["reason"].lower()


def test_bind_mac_from_heartbeat(client, app, room_setup):
    mac = "02:00:00:00:00:07"
    response = client.post(
        "/api/v1/heartbeat",
        json={
            "room_number": "7",
            "mac": mac,
            "door_state": "closed",
            "ac_state": "on",
            "temperature_c": 22.0,
        },
        headers={"X-API-Key": room_setup["api_key"]},
    )
    assert response.status_code == 200
    with app.app_context():
        settings = ACSettings.query.filter_by(room_number="7").first()
        assert settings.device_mac == normalize_mac(mac)


def test_enroll_rejects_bad_token(client, app):
    app.config["ENROLL_TOKEN"] = "school-secret"
    response = client.post("/api/v1/enroll", json={"mac": "AA:BB:CC:DD:EE:00"})
    assert response.status_code == 401
    ok = client.post(
        "/api/v1/enroll",
        json={"mac": "AA:BB:CC:DD:EE:00", "enroll_token": "school-secret"},
    )
    assert ok.status_code == 200
    assert ok.get_json()["assigned"] is False


def test_admin_users_page_renders(client, admin_user, room_setup):
    client.post(
        "/login",
        data={"username": "admin", "password": "secret", "login_type": "password"},
        follow_redirects=True,
    )
    response = client.get("/admin/users")
    assert response.status_code == 200
    assert b"Room users" in response.data
    assert b"ESP32 MAC" in response.data


def test_room_dashboard_shows_door_and_setpoint(client, room_setup):
    client.post(
        "/login",
        data={"username": "room7", "password": "room-secret", "login_type": "password"},
        follow_redirects=True,
    )
    response = client.get("/room")
    assert response.status_code == 200
    assert b"Door:" in response.data
    assert b"Setpoint" in response.data
    assert b"ESP32" in response.data



def test_time_in_range_midnight_wrap():
    from ac_control.services.policy import time_in_range
    from datetime import time

    start = time(22, 0)
    end = time(7, 0)
    assert time_in_range(start, end, time(23, 0)) is True
    assert time_in_range(start, end, time(3, 0)) is True
    assert time_in_range(start, end, time(12, 0)) is False
    assert time_in_range(time(7, 0), time(22, 0), time(12, 0)) is True


def test_celsius_fahrenheit_roundtrip():
    from ac_control.temperature import celsius_to_fahrenheit, fahrenheit_to_celsius

    assert celsius_to_fahrenheit(0) == 32
    assert celsius_to_fahrenheit(100) == 212
    assert round(fahrenheit_to_celsius(68), 5) == 20
    assert fahrenheit_to_celsius(None) is None
    assert celsius_to_fahrenheit(None) is None

