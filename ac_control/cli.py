"""CLI: create-admin, create-room, rotate-device-key, bind-mac."""

from __future__ import annotations

import argparse
import getpass
import sys

from ac_control import create_app
from ac_control.extensions import db
from ac_control.models import ACSettings, RoomStatus, User
from ac_control.services.devices import bind_mac_to_room, claim_pending_device, normalize_mac
from ac_control.services.ingest import get_or_create_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ac-control", description="AC Control Center admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="Create the first administrator")
    admin.add_argument("--username", required=True)
    admin.add_argument("--email", required=True)
    admin.add_argument("--password", help="If omitted, prompt on stdin")

    room = sub.add_parser("create-room", help="Create a classroom user and device API key")
    room.add_argument("--room", required=True)
    room.add_argument("--username", required=True)
    room.add_argument("--email", required=True)
    room.add_argument("--password", help="If omitted, prompt on stdin")
    room.add_argument("--pin", default="")
    room.add_argument("--mac", default="", help="Optional ESP32 MAC to bind immediately")

    rotate = sub.add_parser("rotate-device-key", help="Issue a new device API key for a room")
    rotate.add_argument("--room", required=True)

    bind = sub.add_parser("bind-mac", help="Bind an ESP32 MAC address to a room")
    bind.add_argument("--room", required=True)
    bind.add_argument("--mac", required=True)
    bind.add_argument(
        "--no-issue-key",
        action="store_true",
        help="Bind MAC without rotating the API key",
    )

    args = parser.parse_args(argv)
    app = create_app()
    with app.app_context():
        if args.command == "create-admin":
            return _create_admin(args)
        if args.command == "create-room":
            return _create_room(args)
        if args.command == "rotate-device-key":
            return _rotate(args)
        if args.command == "bind-mac":
            return _bind_mac(args)
    return 1


def _password(value: str | None) -> str:
    if value:
        return value
    return getpass.getpass("Password: ")


def _create_admin(args) -> int:
    if User.query.filter_by(username=args.username).first():
        print("Username already exists", file=sys.stderr)
        return 1
    if User.query.filter_by(email=args.email).first():
        print("Email already exists", file=sys.stderr)
        return 1
    user = User(username=args.username, email=args.email, is_admin=True, room_number=None)
    user.set_password(_password(args.password))
    db.session.add(user)
    db.session.commit()
    print(f"Admin {args.username} created.")
    return 0


def _create_room(args) -> int:
    if User.query.filter_by(username=args.username).first():
        print("Username already exists", file=sys.stderr)
        return 1
    if User.query.filter_by(email=args.email).first():
        print("Email already exists", file=sys.stderr)
        return 1
    if User.query.filter_by(room_number=args.room).first():
        print("Room already exists", file=sys.stderr)
        return 1
    user = User(
        username=args.username,
        email=args.email,
        room_number=args.room,
        is_admin=False,
    )
    user.set_password(_password(args.password))
    if args.pin:
        user.set_pin(args.pin)
    raw_key = ACSettings.generate_device_key()
    settings = ACSettings(room_number=args.room)
    settings.set_device_key(raw_key)
    mac = normalize_mac(args.mac) if args.mac else None
    if args.mac and not mac:
        print("Invalid MAC address", file=sys.stderr)
        return 1
    if mac:
        settings.device_mac = mac
    db.session.add(user)
    db.session.flush()
    db.session.add(settings)
    db.session.add(RoomStatus(room_number=args.room, set_temperature=settings.min_temperature))
    db.session.commit()
    print(f"Room {args.room} created.")
    if mac:
        print(f"DEVICE_MAC={mac}")
    print(f"DEVICE_API_KEY={raw_key}")
    print("Store this on the classroom ESP32 (or let enroll collect it after bind-mac). It will not be shown again.")
    return 0


def _rotate(args) -> int:
    settings = ACSettings.query.filter_by(room_number=args.room).first()
    if not settings:
        print("Room settings not found", file=sys.stderr)
        return 1
    get_or_create_status(args.room)
    raw_key = ACSettings.generate_device_key()
    settings.set_device_key(raw_key)
    if settings.device_mac:
        from ac_control.services.devices import upsert_pending

        pending = upsert_pending(settings.device_mac)
        pending.assigned_room = args.room
        pending.issued_api_key = raw_key
    db.session.commit()
    print(f"DEVICE_API_KEY={raw_key}")
    print("Update the ESP32 (or wait for the next enroll poll).")
    return 0


def _bind_mac(args) -> int:
    try:
        if args.no_issue_key:
            bind_mac_to_room(args.mac, args.room, issue_key=False)
            db.session.commit()
            print(f"Bound {normalize_mac(args.mac)} to room {args.room} (key unchanged).")
            return 0
        raw_key = claim_pending_device(args.mac, args.room)
        db.session.commit()
        print(f"Bound {normalize_mac(args.mac)} to room {args.room}.")
        print(f"DEVICE_API_KEY={raw_key}")
        print("The ESP32 will receive this key on its next enroll poll (once).")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
