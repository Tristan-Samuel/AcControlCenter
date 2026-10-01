"""ESP32 identity: MAC normalization, enroll/claim, API-key auth."""

from __future__ import annotations

import re
import secrets
from typing import Any

from flask import current_app, jsonify, request

from ac_control.extensions import db
from ac_control.models import ACSettings, PendingDevice, RoomStatus, utc_now


_HEX = re.compile(r"[^0-9A-Fa-f]")


def normalize_mac(raw: str | None) -> str | None:
    if not raw:
        return None
    hex_only = _HEX.sub("", str(raw)).upper()
    if len(hex_only) != 12:
        return None
    return ":".join(hex_only[i : i + 2] for i in range(0, 12, 2))


def mac_from_request(data: dict | None = None) -> str | None:
    payload = data if data is not None else (request.get_json(silent=True) or {})
    return normalize_mac(
        request.headers.get("X-Device-Mac")
        or payload.get("mac")
        or payload.get("device_mac")
    )


def api_key_from_request() -> str:
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "")
    if api_key.lower().startswith("bearer "):
        api_key = api_key[7:].strip()
    return api_key


def enroll_token_ok(data: dict | None = None) -> bool:
    expected = (current_app.config.get("ENROLL_TOKEN") or "").strip()
    if not expected:
        return True
    payload = data if data is not None else (request.get_json(silent=True) or {})
    got = (
        request.headers.get("X-Enroll-Token")
        or payload.get("enroll_token")
        or ""
    )
    got = str(got)
    if len(got) != len(expected):
        return False
    return secrets.compare_digest(got, expected)


def upsert_pending(mac: str, firmware_info: str | None = None) -> PendingDevice:
    pending = PendingDevice.query.filter_by(mac=mac).first()
    now = utc_now()
    if pending:
        pending.last_seen = now
        if firmware_info:
            pending.firmware_info = firmware_info[:200]
        return pending
    pending = PendingDevice(
        mac=mac,
        first_seen=now,
        last_seen=now,
        firmware_info=(firmware_info or "")[:200] if firmware_info else None,
    )
    db.session.add(pending)
    return pending


def settings_for_mac(mac: str) -> ACSettings | None:
    return ACSettings.query.filter_by(device_mac=mac).first()


def claim_pending_device(mac: str, room_number: str) -> str:
    """Bind a MAC to a room, issue a fresh API key, and leave it for the next enroll poll."""
    mac = normalize_mac(mac)
    if not mac:
        raise ValueError("Invalid MAC address")
    settings = ACSettings.query.filter_by(room_number=room_number).first()
    if not settings:
        raise ValueError(f"Room {room_number} not found")

    other = ACSettings.query.filter(
        ACSettings.device_mac == mac,
        ACSettings.room_number != room_number,
    ).first()
    if other:
        other.device_mac = None

    raw_key = ACSettings.generate_device_key()
    settings.set_device_key(raw_key)
    settings.device_mac = mac

    pending = upsert_pending(mac)
    pending.assigned_room = room_number
    pending.issued_api_key = raw_key
    pending.last_seen = utc_now()
    return raw_key


def bind_mac_to_room(mac: str, room_number: str, issue_key: bool = True) -> str | None:
    mac = normalize_mac(mac)
    if not mac:
        raise ValueError("Invalid MAC address")
    settings = ACSettings.query.filter_by(room_number=room_number).first()
    if not settings:
        raise ValueError(f"Room {room_number} not found")
    other = ACSettings.query.filter(
        ACSettings.device_mac == mac,
        ACSettings.room_number != room_number,
    ).first()
    if other:
        other.device_mac = None
    settings.device_mac = mac
    raw_key = None
    if issue_key:
        raw_key = ACSettings.generate_device_key()
        settings.set_device_key(raw_key)
        pending = upsert_pending(mac)
        pending.assigned_room = room_number
        pending.issued_api_key = raw_key
    return raw_key


def collect_issued_key(mac: str) -> tuple[str | None, str | None]:
    """Return (room_number, api_key). api_key is only present once after a claim."""
    settings = settings_for_mac(mac)
    pending = PendingDevice.query.filter_by(mac=mac).first()
    if not settings:
        return None, None
    room_number = settings.room_number
    api_key = None
    if pending and pending.issued_api_key:
        api_key = pending.issued_api_key
        pending.issued_api_key = None
        pending.assigned_room = room_number
    return room_number, api_key


def enroll_response(mac: str, firmware_info: str | None = None) -> dict[str, Any]:
    upsert_pending(mac, firmware_info)
    settings = settings_for_mac(mac)
    if not settings:
        db.session.commit()
        return {
            "assigned": False,
            "status": "pending",
            "mac": mac,
        }
    room_number, api_key = collect_issued_key(mac)
    db.session.commit()
    payload: dict[str, Any] = {
        "assigned": True,
        "status": "claimed" if api_key else "claimed",
        "mac": mac,
        "room_number": settings.room_number,
        "api_key": api_key,
    }
    if not api_key:
        payload["has_key"] = True
    return payload


def authenticate_device(
    room_number: str | None = None,
    mac: str | None = None,
) -> tuple[ACSettings | None, tuple | None]:
    """Look up the room by MAC (preferred) or room_number, then verify X-API-Key."""
    api_key = api_key_from_request()
    mac = normalize_mac(mac) if mac else None
    room_number = (room_number or "").strip()
    if not api_key:
        return None, (jsonify({"error": "Missing X-API-Key"}), 401)
    if not mac and not room_number:
        return None, (jsonify({"error": "Missing mac or room_number"}), 401)

    if mac:
        by_mac = settings_for_mac(mac)
        if by_mac:
            if not by_mac.check_device_key(api_key):
                return None, (jsonify({"error": "Invalid device credentials"}), 401)
            pending = PendingDevice.query.filter_by(mac=mac).first()
            if pending:
                pending.last_seen = utc_now()
            return by_mac, None

    if room_number:
        settings = ACSettings.query.filter_by(room_number=room_number).first()
        if not settings or not settings.check_device_key(api_key):
            return None, (jsonify({"error": "Invalid device credentials"}), 401)
        if mac:
            occupied = settings_for_mac(mac)
            if occupied and occupied.room_number != room_number:
                return None, (
                    jsonify({"error": "MAC is already bound to another room"}),
                    409,
                )
            settings.device_mac = mac
            upsert_pending(mac).assigned_room = room_number
        return settings, None

    return None, (jsonify({"error": "Unknown device"}), 401)


def pending_unassigned() -> list[PendingDevice]:
    bound = {
        row.device_mac
        for row in ACSettings.query.filter(ACSettings.device_mac.isnot(None)).all()
    }
    rows = PendingDevice.query.order_by(PendingDevice.last_seen.desc()).all()
    return [row for row in rows if row.mac not in bound]


def touch_room_seen(room_number: str) -> None:
    status = RoomStatus.query.filter_by(room_number=room_number).first()
    if status:
        status.last_updated = utc_now()
