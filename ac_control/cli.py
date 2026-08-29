"""CLI: create-admin, create-room, rotate-device-key."""

from __future__ import annotations

import argparse
import getpass
import sys

from ac_control import create_app
from ac_control.extensions import db
from ac_control.models import ACSettings, RoomStatus, User
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

    rotate = sub.add_parser("rotate-device-key", help="Issue a new device API key for a room")
    rotate.add_argument("--room", required=True)

    args = parser.parse_args(argv)
    app = create_app()
    with app.app_context():
        if args.command == "create-admin":
            return _create_admin(args)
        if args.command == "create-room":
            return _create_room(args)
        if args.command == "rotate-device-key":
            return _rotate(args)
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
    db.session.add(user)
    db.session.flush()
    db.session.add(settings)
    db.session.add(RoomStatus(room_number=args.room))
    db.session.commit()
    print(f"Room {args.room} created.")
    print(f"DEVICE_API_KEY={raw_key}")
    print("Store this on the classroom Pi. It will not be shown again.")
    return 0


def _rotate(args) -> int:
    settings = ACSettings.query.filter_by(room_number=args.room).first()
    if not settings:
        print("Room settings not found", file=sys.stderr)
        return 1
    get_or_create_status(args.room)
    raw_key = ACSettings.generate_device_key()
    settings.set_device_key(raw_key)
    db.session.commit()
    print(f"DEVICE_API_KEY={raw_key}")
    print("Update the classroom Pi env file and restart ac-client.service.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
