"""Simulation mode drives the real heartbeat path with fake classrooms."""

from __future__ import annotations

from datetime import timedelta

from ac_control.extensions import db
from ac_control.models import ACSettings, PendingDevice, RoomStatus, User, utc_now
from ac_control.services.simulation import (
    UNASSIGNED_MAC,
    _login_path,
    apply_action,
    ensure_demo,
    reset_for_tests,
)


def _enable(app) -> None:
    app.config["SIMULATION_MODE"] = True
    app.config["SIMULATION_ADMIN_PASSWORD"] = "demo-pass"


def test_health_reports_simulation_off(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["simulation"] is False


def test_seed_creates_demo_school(app) -> None:
    _enable(app)
    with app.app_context():
        reset_for_tests()
        ensure_demo()
        admin = User.query.filter_by(username="demo").one()
        assert admin.is_admin
        assert admin.check_password("demo-pass")
        rooms = {row.room_number for row in User.query.filter(User.room_number.isnot(None))}
        assert rooms == {"101", "204", "312", "418"}
        art = ACSettings.query.filter_by(room_number="418").one()
        assert art.buzz_on_open is True
        assert art.email_notifications is False
        assert PendingDevice.query.filter_by(mac=UNASSIGNED_MAC).one()
        reset_for_tests()


def test_open_door_shutoff_then_resume(app) -> None:
    _enable(app)
    with app.app_context():
        reset_for_tests()
        ensure_demo()
        settings = ACSettings.query.filter_by(room_number="204").one()
        settings.shutoff_delay = 0
        db.session.commit()

        opened = apply_action("204", "open-door")
        assert "POWER_OFF" in opened["reaction"]
        status = RoomStatus.query.filter_by(room_number="204").one()
        assert status.ac_state == "off"
        assert status.door_state == "opened"

        refused = apply_action("204", "remote-on")
        assert "refused remote ON" in refused["reaction"]
        assert RoomStatus.query.filter_by(room_number="204").one().ac_state == "off"

        closed = apply_action("204", "close-door")
        assert "POWER_ON" in closed["reaction"]
        assert RoomStatus.query.filter_by(room_number="204").one().ac_state == "on"
        reset_for_tests()


def test_too_cold_shuts_the_unit_off(app) -> None:
    _enable(app)
    with app.app_context():
        reset_for_tests()
        ensure_demo()
        apply_action("312", "too-cold")
        status = RoomStatus.query.filter_by(room_number="312").one()
        status.non_compliant_since = utc_now() - timedelta(seconds=30)
        status.ac_state = "on"
        db.session.commit()
        view = apply_action("312", "too-cold")
        assert "POWER_OFF" in view["reaction"]
        assert RoomStatus.query.filter_by(room_number="312").one().ac_state == "off"
        reset_for_tests()


def test_disconnect_marks_room_stale(app) -> None:
    _enable(app)
    with app.app_context():
        reset_for_tests()
        ensure_demo()
        view = apply_action("101", "disconnect")
        assert view["connected"] is False
        status = RoomStatus.query.filter_by(room_number="101").one()
        assert status.is_stale(app.config["STALE_AFTER_SECONDS"])
        reset_for_tests()


def test_login_file_is_the_demo_password(app) -> None:
    _enable(app)
    with app.app_context():
        reset_for_tests()
        path = _login_path()
        path.write_text("username: demo\npassword: test\n", encoding="utf-8")
        ensure_demo()
        admin = User.query.filter_by(username="demo").one()
        assert admin.check_password("test")
        assert "password: test" in path.read_text(encoding="utf-8")
        reset_for_tests()


def test_plain_login_file_sets_demo_password(app) -> None:
    _enable(app)
    with app.app_context():
        reset_for_tests()
        _login_path().write_text("demo\ntest\n", encoding="utf-8")
        ensure_demo()
        assert User.query.filter_by(username="demo").one().check_password("test")
        reset_for_tests()


def test_editing_login_file_replaces_the_stored_password(app) -> None:
    _enable(app)
    with app.app_context():
        reset_for_tests()
        ensure_demo()
        assert User.query.filter_by(username="demo").one().check_password("demo-pass")
        path = _login_path()
        path.write_text("username: demo\npassword: test\n", encoding="utf-8")
        ensure_demo()
        admin = User.query.filter_by(username="demo").one()
        assert admin.check_password("test")
        assert admin.check_password("demo-pass") is False
        reset_for_tests()


def test_sign_in_uses_the_login_file(app, client) -> None:
    _enable(app)
    with app.app_context():
        reset_for_tests()
        _login_path().write_text("username: demo\npassword: test\n", encoding="utf-8")
    refused = client.post("/login", data={"username": "demo", "password": "demo-pass"})
    assert refused.status_code == 200
    response = client.post("/login", data={"username": "demo", "password": "test"})
    assert response.status_code == 302
    with app.app_context():
        reset_for_tests()


def test_simulation_action_requires_mode(app) -> None:
    app.config["SIMULATION_MODE"] = False
    with app.app_context():
        reset_for_tests()
        try:
            apply_action("101", "open-door")
        except ValueError as exc:
            assert "off" in str(exc)
        else:
            raise AssertionError("expected ValueError")
        reset_for_tests()
