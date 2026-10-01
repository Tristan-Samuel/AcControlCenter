"""Authenticated classroom-ESP32 API. CSRF-exempt; requires X-API-Key except enroll."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ac_control.extensions import db
from ac_control.models import GlobalPolicy, RoomStatus, utc_now
from ac_control.services.commands import pop_commands
from ac_control.services.devices import (
    authenticate_device,
    enroll_response,
    enroll_token_ok,
    mac_from_request,
)
from ac_control.services.ingest import process_heartbeat
from ac_control.services.remote import evaluate_remote_command

device_bp = Blueprint("device", __name__, url_prefix="/api/v1")


def _payload() -> dict:
    return request.get_json(silent=True) or {}


@device_bp.route("/enroll", methods=["POST"])
def enroll():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    data = _payload()
    if not enroll_token_ok(data):
        return jsonify({"error": "Invalid enroll token"}), 401
    mac = mac_from_request(data)
    if not mac:
        return jsonify({"error": "Invalid or missing mac"}), 400
    firmware_info = str(data.get("firmware") or data.get("firmware_info") or "")[:200]
    return jsonify(enroll_response(mac, firmware_info or None))


@device_bp.route("/heartbeat", methods=["POST"])
def heartbeat():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    data = _payload()
    mac = mac_from_request(data)
    room_number = str(data.get("room_number") or "").strip()
    settings, error = authenticate_device(room_number=room_number, mac=mac)
    if error:
        return error
    room_number = settings.room_number
    door_state = data.get("door_state")
    if not door_state:
        door_state = "closed"
    window_state = str(data.get("window_state") or "closed")
    try:
        temperature_c = float(data.get("temperature_c", data.get("temperature", 22.0)))
        result = process_heartbeat(
            room_number=room_number,
            window_state=window_state,
            ac_state=str(data.get("ac_state", "off")),
            temperature_c=temperature_c,
            door_state=str(door_state),
            ir_event=data.get("ir_event") or None,
        )
        return jsonify(result)
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to process heartbeat"}), 500


@device_bp.route("/check-command", methods=["POST"])
def check_command():
    if not request.is_json:
        return jsonify({"allowed": False, "reason": "Request must be JSON"}), 400
    data = _payload()
    mac = mac_from_request(data)
    room_number = str(data.get("room_number") or "").strip()
    settings, error = authenticate_device(room_number=room_number, mac=mac)
    if error:
        return error
    room_number = settings.room_number
    command = data.get("command")
    door_state = str(data.get("door_state") or "closed").lower()
    ac_state = str(data.get("ac_state", "")).lower()
    try:
        temperature = float(data.get("temperature", 22.0))
    except (TypeError, ValueError):
        temperature = 22.0
    status = RoomStatus.query.filter_by(room_number=room_number).first()
    set_temperature = status.set_temperature if status else settings.min_temperature
    if data.get("set_temperature_c") is not None:
        try:
            set_temperature = float(data["set_temperature_c"])
        except (TypeError, ValueError):
            pass
    if not command:
        return jsonify({"allowed": False, "reason": "Missing command"}), 400

    policy = GlobalPolicy.query.first()
    verdict = evaluate_remote_command(
        settings=settings,
        command=command,
        door_state=door_state,
        ac_state=ac_state,
        temperature=temperature,
        set_temperature=set_temperature or 20.0,
        policy=policy,
    )
    if status and verdict.get("allowed"):
        cmd = str(command).upper()
        if cmd in {"TEMP_UP", "TEMP_DOWN"} and verdict.get("set_temperature_c") is not None:
            status.set_temperature = float(verdict["set_temperature_c"])
        elif cmd.startswith("SET_TEMP_"):
            try:
                status.set_temperature = float(cmd.split("_")[-1])
            except ValueError:
                pass
    db.session.commit()
    return jsonify(verdict)


@device_bp.route("/commands", methods=["POST"])
def drain_commands():
    """Optional poll without a full heartbeat — still requires the device key."""
    data = _payload()
    mac = mac_from_request(data)
    room_number = str(data.get("room_number") or request.args.get("room_number") or "").strip()
    settings, error = authenticate_device(room_number=room_number, mac=mac)
    if error:
        return error
    room_number = settings.room_number
    commands = pop_commands(room_number)
    status = RoomStatus.query.filter_by(room_number=room_number).first()
    buzz = False
    if status:
        status.last_updated = utc_now()
        if settings.buzz_on_open and status.door_state == "opened":
            buzz = True
    db.session.commit()
    return jsonify(
        {
            "commands": commands,
            "server_time": utc_now().isoformat(),
            "set_temperature_c": status.set_temperature if status else None,
            "buzz": buzz,
        }
    )
