"""Fake classroom nodes that speak the real heartbeat path.

SIMULATION_MODE drives this. Nothing here talks to GPIO or an ESP32.
Each tick reports door, temperature, and AC state through process_heartbeat,
then applies the IR commands the server queued, the same way firmware would.
"""

from __future__ import annotations

import logging
import math
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from flask import current_app

from ac_control.extensions import db
from ac_control.models import ACSettings, PendingDevice, RoomStatus, User, utc_now
from ac_control.services.commands import pop_commands
from ac_control.services.devices import upsert_pending
from ac_control.services.ingest import process_heartbeat

logger = logging.getLogger(__name__)

UNASSIGNED_MAC = "02:00:00:00:09:99"
_LOCK = threading.Lock()

ACTIONS = (
    ("open-door", "Open door"),
    ("close-door", "Close door"),
    ("window-open", "Open window"),
    ("window-close", "Close window"),
    ("remote-on", "Remote ON"),
    ("remote-off", "Remote OFF"),
    ("too-cold", "Too cold"),
    ("comfort", "Comfort temp"),
    ("disconnect", "Node offline"),
    ("reconnect", "Node online"),
    ("resume", "Resume script"),
)


@dataclass
class SimNode:
    room: str
    label: str
    blurb: str
    script: str
    period: int
    base_temp: float
    shutoff_delay: int
    buzz_on_open: bool
    mac: str
    temp_c: float
    door: str = "closed"
    window: str = "closed"
    ac: str = "on"
    connected: bool = True
    manual: bool = False
    ir_event: str | None = None
    reaction: str = "Waiting for the first heartbeat"
    buzz: bool = False
    last_rearm: float = field(default_factory=time.time)


_NODES: dict[str, SimNode] = {}
# (path, mtime_ns) of the login file already applied. Avoids hashing on every tick.
_LOGIN_SEEN: tuple[str, int] | None = None

_DEMO = (
    {
        "room": "101",
        "label": "Library",
        "blurb": "Door stays shut. The AC holds the setpoint.",
        "script": "steady",
        "period": 0,
        "temp": 22.4,
        "shutoff_delay": 30,
        "buzz": False,
        "door": "closed",
        "ac": "on",
    },
    {
        "room": "204",
        "label": "Science",
        "blurb": "Door cycles open. The Pi times the shutoff, then turns the AC back on when it closes.",
        "script": "door_cycle",
        "period": 60,
        "temp": 23.0,
        "shutoff_delay": 8,
        "buzz": False,
        "door": "closed",
        "ac": "on",
    },
    {
        "room": "312",
        "label": "Office",
        "blurb": "Room stays too cold. The Pi shuts the AC off, then a fake remote tries to turn it on again.",
        "script": "cold_fight",
        "period": 0,
        "temp": 16.0,
        "shutoff_delay": 30,
        "buzz": False,
        "door": "closed",
        "ac": "on",
    },
    {
        "room": "418",
        "label": "Art",
        "blurb": "Door sits open with the buzzer on. The Pi shuts the AC off, then the door closes briefly and it repeats.",
        "script": "door_hold",
        "period": 90,
        "temp": 24.0,
        "shutoff_delay": 10,
        "buzz": True,
        "door": "opened",
        "ac": "on",
    },
)


def _mac_for(room: str) -> str:
    number = int(room)
    return f"02:00:00:00:{(number >> 8) & 0xFF:02X}:{number & 0xFF:02X}"


def _login_path() -> Path:
    uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if uri.startswith("sqlite:///") and ":memory:" not in uri:
        raw = uri[len("sqlite:///") :]
        parent = Path(raw).expanduser()
        if not parent.is_absolute():
            parent = Path(current_app.instance_path) / parent
        return parent.parent / "simulation-login.txt"
    return Path(current_app.instance_path) / "simulation-login.txt"


def _write_login(password: str) -> None:
    path = _login_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "username: demo\n"
        f"password: {password}\n"
        "Edit the password line, then sign in again. The app reads this file.\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _read_login(path: Path) -> tuple[str, str] | None:
    """Username and password from simulation-login.txt.

    Accepts ``username:`` / ``password:`` lines, or two plain lines (username then password).
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("Could not read simulation login file %s", path)
        return None
    username = ""
    password = ""
    plain: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lower = stripped.lower()
        if lower.startswith("username:"):
            username = stripped.split(":", 1)[1].strip()
        elif lower.startswith("password:"):
            password = stripped.split(":", 1)[1].strip()
        elif ":" not in stripped:
            plain.append(stripped)
    if username and password:
        return username, password
    if not username and not password and len(plain) >= 2:
        return plain[0], plain[1]
    return None


def _demo_admin() -> User | None:
    by_email = User.query.filter_by(email="demo@localhost").first()
    if by_email is not None:
        return by_email
    return User.query.filter_by(username="demo").first()


def _apply_login(username: str, password: str) -> None:
    """Point the simulation admin at the username and password from the login file."""
    user = _demo_admin()
    if user is None:
        if User.query.filter_by(username=username).first():
            logger.warning("Username %s already exists; not creating the simulation admin", username)
            return
        user = User(username=username, email="demo@localhost", is_admin=True, room_number=None)
        db.session.add(user)
    elif user.username != username:
        taken = User.query.filter(User.username == username, User.id != user.id).first()
        if taken:
            logger.warning("Simulation login username %s is already taken", username)
        else:
            user.username = username
    user.is_admin = True
    if not user.check_password(password):
        user.set_password(password)
        logger.info("Updated simulation admin login from %s", _login_path())


def _sync_admin() -> None:
    """Create the demo admin, or copy simulation-login.txt onto that account.

    The file is the password source once it exists. Editing it and signing in
    again changes the login. ``SIMULATION_ADMIN_PASSWORD`` is only the initial
    password when the file is missing.
    """
    global _LOGIN_SEEN
    path = _login_path()
    if path.is_file():
        seen = (str(path.resolve()), path.stat().st_mtime_ns)
        if seen == _LOGIN_SEEN:
            return
        parsed = _read_login(path)
        if parsed is None:
            logger.warning(
                "No username and password in %s; demo login was left unchanged",
                path,
            )
            _LOGIN_SEEN = seen
            return
        _apply_login(*parsed)
        _LOGIN_SEEN = seen
        return

    password = (current_app.config.get("SIMULATION_ADMIN_PASSWORD") or "").strip()
    if not password:
        password = secrets.token_urlsafe(12)
    _apply_login("demo", password)
    _write_login(password)
    _LOGIN_SEEN = (str(path.resolve()), path.stat().st_mtime_ns)


def _seed_room(spec: dict) -> None:
    room = spec["room"]
    if User.query.filter_by(room_number=room).first():
        return
    username = f"room{room}"
    email = f"room{room}@demo.local"
    user = User(username=username, email=email, room_number=room, is_admin=False)
    user.set_password(secrets.token_urlsafe(18))
    raw_key = ACSettings.generate_device_key()
    settings = ACSettings(
        room_number=room,
        auto_shutoff=True,
        shutoff_delay=int(spec["shutoff_delay"]),
        email_notifications=False,
        buzz_on_open=bool(spec["buzz"]),
        min_temperature=20.0,
    )
    settings.set_device_key(raw_key)
    settings.device_mac = _mac_for(room)
    db.session.add(user)
    db.session.flush()
    db.session.add(settings)
    db.session.add(
        RoomStatus(
            room_number=room,
            current_temperature=float(spec["temp"]),
            set_temperature=20.0,
            door_state=spec["door"],
            window_state="closed",
            ac_state=spec["ac"],
        )
    )


def _seed_unassigned() -> None:
    if PendingDevice.query.filter_by(mac=UNASSIGNED_MAC).first():
        return
    upsert_pending(UNASSIGNED_MAC, "simulation/unassigned")


def _node_from_spec(spec: dict) -> SimNode:
    return SimNode(
        room=spec["room"],
        label=spec["label"],
        blurb=spec["blurb"],
        script=spec["script"],
        period=int(spec["period"]),
        base_temp=float(spec["temp"]),
        shutoff_delay=int(spec["shutoff_delay"]),
        buzz_on_open=bool(spec["buzz"]),
        mac=_mac_for(spec["room"]),
        temp_c=float(spec["temp"]),
        door=spec["door"],
        ac=spec["ac"],
    )


def _ensure_nodes() -> None:
    for spec in _DEMO:
        if spec["room"] not in _NODES and User.query.filter_by(room_number=spec["room"]).first():
            _NODES[spec["room"]] = _node_from_spec(spec)
    for user in User.query.filter(User.room_number.isnot(None)).all():
        room = user.room_number
        if room in _NODES:
            continue
        status = RoomStatus.query.filter_by(room_number=room).first()
        _NODES[room] = SimNode(
            room=room,
            label="Classroom",
            blurb="Extra room. Use the buttons, or Resume script for a steady heartbeat.",
            script="steady",
            period=0,
            base_temp=float(status.current_temperature) if status else 22.0,
            shutoff_delay=30,
            buzz_on_open=False,
            mac=_mac_for(room) if room.isdigit() else "02:00:00:00:00:01",
            temp_c=float(status.current_temperature) if status else 22.0,
            door=(status.door_state if status else "closed") or "closed",
            window=(status.window_state if status else "closed") or "closed",
            ac=(status.ac_state if status else "off") or "off",
        )


def ensure_demo() -> None:
    """Create the demo admin, four classrooms, and one unassigned MAC. Idempotent."""
    if not current_app.config.get("SIMULATION_MODE"):
        return
    with _LOCK:
        _sync_admin()
        for spec in _DEMO:
            _seed_room(spec)
        _seed_unassigned()
        db.session.commit()
        _ensure_nodes()


def _advance(node: SimNode, now: float) -> None:
    if node.manual or not node.connected:
        return
    phase = int(now) % node.period if node.period else 0
    if node.script == "steady":
        node.door = "closed"
        node.window = "closed"
        node.temp_c = round(node.base_temp + 0.3 * math.sin(now / 12.0), 1)
    elif node.script == "door_cycle":
        node.door = "opened" if phase >= 36 else "closed"
        node.temp_c = round(node.base_temp + (0.8 if node.door == "opened" else 0.0), 1)
    elif node.script == "door_hold":
        node.door = "closed" if phase < 18 else "opened"
        node.temp_c = node.base_temp
    elif node.script == "cold_fight":
        node.door = "closed"
        node.window = "closed"
        node.temp_c = 16.0
        if node.ac == "off" and now - node.last_rearm >= 45:
            node.ir_event = node.ir_event or "POWER"
            node.last_rearm = now


def _apply_commands(node: SimNode, commands: list[str]) -> None:
    for command in commands:
        if command == "POWER_OFF":
            node.ac = "off"
        elif command == "POWER_ON":
            node.ac = "on"
        elif command.startswith("SET_TEMP_"):
            try:
                node.base_temp = float(command.split("_")[-1])
            except ValueError:
                logger.warning("Bad setpoint command %s", command)


def _reaction(pre: list[str], result: dict, sent_ir: str | None) -> str:
    commands = list(pre) + list(result.get("commands") or [])
    bits: list[str] = []
    if "POWER_OFF" in commands:
        bits.append("Pi sent POWER_OFF")
    if "POWER_ON" in commands:
        bits.append("Pi sent POWER_ON")
    temps = [item for item in commands if item.startswith("SET_TEMP_")]
    if temps:
        bits.append(f"Pi sent setpoint {temps[-1].removeprefix('SET_TEMP_')}°C")
    if result.get("buzz"):
        bits.append("buzzer on")
    if sent_ir in {"POWER", "POWER_ON"} and "POWER_ON" not in commands:
        bits.append("Pi refused remote ON")
    if sent_ir == "POWER_OFF" and "POWER_OFF" not in commands:
        bits.append("Pi refused remote OFF")
    if result.get("has_pending_event"):
        bits.append("shutoff timer running")
    if not bits:
        bits.append("heartbeat ok, no command")
    return "; ".join(bits)


def _beat(node: SimNode) -> dict:
    if not node.connected:
        return {}
    sent_ir = node.ir_event
    pre = pop_commands(node.room)
    _apply_commands(node, pre)
    result = process_heartbeat(
        room_number=node.room,
        window_state=node.window,
        ac_state=node.ac,
        temperature_c=node.temp_c,
        door_state=node.door,
        ir_event=node.ir_event,
    )
    node.ir_event = None
    _apply_commands(node, list(result.get("commands") or []))
    node.buzz = bool(result.get("buzz"))
    node.reaction = _reaction(pre, result, sent_ir)
    return result


def tick(now: float | None = None) -> None:
    if not current_app.config.get("SIMULATION_MODE"):
        return
    ensure_demo()
    moment = time.time() if now is None else now
    with _LOCK:
        for node in list(_NODES.values()):
            try:
                _advance(node, moment)
                if node.connected:
                    _beat(node)
            except Exception:
                db.session.rollback()
                logger.exception("Simulation tick failed for room %s", node.room)


def apply_action(room: str, action: str, now: float | None = None) -> dict:
    if not current_app.config.get("SIMULATION_MODE"):
        raise ValueError("Simulation mode is off")
    known = {name for name, _label in ACTIONS}
    if action not in known:
        raise ValueError("Unknown simulation action")
    ensure_demo()
    with _LOCK:
        node = _NODES.get(str(room))
        if node is None:
            raise ValueError("Room is not in the simulation")
        if action == "resume":
            node.manual = False
            node.connected = True
            _advance(node, time.time() if now is None else now)
        else:
            node.manual = True
            if action == "open-door":
                node.door = "opened"
                node.connected = True
            elif action == "close-door":
                node.door = "closed"
                node.connected = True
            elif action == "window-open":
                node.window = "opened"
                node.connected = True
            elif action == "window-close":
                node.window = "closed"
                node.connected = True
            elif action == "remote-on":
                node.ir_event = "POWER"
                node.connected = True
            elif action == "remote-off":
                node.ir_event = "POWER_OFF"
                node.connected = True
            elif action == "too-cold":
                node.temp_c = 16.0
                node.connected = True
            elif action == "comfort":
                node.temp_c = 22.5
                node.connected = True
            elif action == "disconnect":
                node.connected = False
                status = RoomStatus.query.filter_by(room_number=node.room).first()
                if status:
                    stale = int(current_app.config.get("STALE_AFTER_SECONDS", 180))
                    status.last_updated = utc_now() - timedelta(seconds=stale + 30)
                    db.session.commit()
                node.reaction = "Node stopped heartbeating. Dashboard marks it stale."
                return room_view(node.room) or {}
            elif action == "reconnect":
                node.connected = True
        _beat(node)
        return room_view(node.room) or {}


def room_view(room: str) -> dict | None:
    node = _NODES.get(str(room))
    if node is None:
        return None
    return {
        "room": node.room,
        "label": node.label,
        "blurb": node.blurb,
        "script": node.script,
        "manual": node.manual,
        "connected": node.connected,
        "reaction": node.reaction,
        "buzz": node.buzz,
        "door": node.door,
        "ac": node.ac,
        "temperature_c": node.temp_c,
    }


def public_state() -> dict[str, dict]:
    if not current_app.config.get("SIMULATION_MODE"):
        return {}
    ensure_demo()
    with _LOCK:
        return {room: room_view(room) for room in sorted(_NODES)}


def reset_for_tests() -> None:
    """Drop in-memory nodes and the login-file cache. Tests only."""
    global _LOGIN_SEEN
    with _LOCK:
        _NODES.clear()
        _LOGIN_SEEN = None
        path = _login_path()
        if path.is_file():
            path.unlink()
