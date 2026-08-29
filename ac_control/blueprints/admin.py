"""Administrator UI: rooms, policy, users, device keys, event logs."""

from __future__ import annotations

import csv
from datetime import datetime, time, timedelta
from functools import wraps
from io import StringIO

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ac_control.blueprints.rooms import _room_context
from ac_control.extensions import db
from ac_control.models import ACSettings, GlobalPolicy, RoomStatus, User, WindowEvent
from ac_control.services.ingest import get_or_create_policy, get_or_create_settings, get_or_create_status
from ac_control.services.mailer import send_email
from ac_control.temperature import celsius_to_fahrenheit, fahrenheit_to_celsius

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Administrator access required.", "error")
            return redirect(url_for("rooms.dashboard"))
        return fn(*args, **kwargs)

    return wrapper


@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    rooms = User.query.filter_by(is_admin=False).order_by(User.room_number).all()
    statuses = {row.room_number: row for row in RoomStatus.query.all()}
    return render_template("admin_dashboard.html", rooms=rooms, room_statuses=statuses)


@admin_bp.route("/rooms/<room_number>")
@login_required
@admin_required
def view_room(room_number):
    user = User.query.filter_by(room_number=room_number).first()
    if not user:
        flash("Room not found.", "error")
        return redirect(url_for("admin.dashboard"))
    return render_template("room_dashboard.html", **_room_context(room_number))


@admin_bp.route("/rooms/<room_number>/lock", methods=["POST"])
@login_required
@admin_required
def toggle_lock(room_number):
    settings = get_or_create_settings(room_number)
    settings.settings_locked = not settings.settings_locked
    db.session.commit()
    flash(
        f"Settings {'locked' if settings.settings_locked else 'unlocked'}.",
        "success",
    )
    return redirect(url_for("admin.view_room", room_number=room_number))


@admin_bp.route("/rooms/<room_number>/min-temp-lock", methods=["POST"])
@login_required
@admin_required
def toggle_min_temp_lock(room_number):
    settings = get_or_create_settings(room_number)
    settings.min_temp_locked = not settings.min_temp_locked
    db.session.commit()
    flash(
        f"Minimum temperature {'locked' if settings.min_temp_locked else 'unlocked'}.",
        "success",
    )
    return redirect(url_for("admin.view_room", room_number=room_number))


@admin_bp.route("/policy", methods=["GET", "POST"])
@login_required
@admin_required
def policy():
    policy_row = get_or_create_policy()
    if request.method == "POST":
        policy_row.policy_active = "policy_active" in request.form
        try:
            policy_row.min_allowed_temp = fahrenheit_to_celsius(
                float(request.form.get("min_allowed_temp", 64.4))
            )
            policy_row.max_allowed_temp = fahrenheit_to_celsius(
                float(request.form.get("max_allowed_temp", 78.8))
            )
            policy_row.conservation_threshold = fahrenheit_to_celsius(
                float(request.form.get("conservation_threshold", 75.2))
            )
        except (TypeError, ValueError):
            flash("Could not parse temperature values.", "error")
            return redirect(url_for("admin.policy"))
        policy_row.energy_conservation_active = "energy_conservation_active" in request.form
        policy_row.scheduled_shutoff_active = "scheduled_shutoff_active" in request.form
        policy_row.apply_shutoff_weekends = "apply_shutoff_weekends" in request.form
        policy_row.scheduled_shutoff_time = _parse_time(
            request.form.get("scheduled_shutoff_time"), time(22, 0)
        )
        policy_row.scheduled_startup_time = _parse_time(
            request.form.get("scheduled_startup_time"), time(7, 0)
        )
        db.session.commit()
        flash("Policy updated.", "success")
        return redirect(url_for("admin.policy"))

    rooms = User.query.filter_by(is_admin=False).all()
    statuses = {row.room_number: row for row in RoomStatus.query.all()}
    return render_template(
        "policy_management.html",
        policy=policy_row,
        rooms=rooms,
        room_statuses=statuses,
    )


@admin_bp.route("/users", methods=["GET", "POST"])
@login_required
@admin_required
def users():
    new_device_key = None
    new_room = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        room_number = (request.form.get("room_number") or "").strip()
        pin = (request.form.get("pin") or "").strip()
        if not username or not email or not password or not room_number:
            flash("Username, email, password, and room number are required.", "error")
        elif User.query.filter_by(username=username).first():
            flash("Username already exists.", "error")
        elif User.query.filter_by(email=email).first():
            flash("Email already exists.", "error")
        elif User.query.filter_by(room_number=room_number).first():
            flash("Room number already exists.", "error")
        elif pin and (len(pin) != 4 or not pin.isdigit()):
            flash("PIN must be exactly 4 digits.", "error")
        else:
            user = User(username=username, email=email, room_number=room_number, is_admin=False)
            user.set_password(password)
            if pin:
                user.set_pin(pin)
            raw_key = ACSettings.generate_device_key()
            settings = ACSettings(room_number=room_number)
            settings.set_device_key(raw_key)
            db.session.add(user)
            db.session.flush()
            db.session.add(settings)
            db.session.add(RoomStatus(room_number=room_number))
            db.session.commit()
            new_device_key = raw_key
            new_room = room_number
            flash(
                "Room user created. Copy the device API key now — it will not be shown again.",
                "success",
            )
    rooms = User.query.filter_by(is_admin=False).order_by(User.room_number).all()
    return render_template(
        "users.html",
        rooms=rooms,
        new_device_key=new_device_key,
        new_room=new_room,
    )


@admin_bp.route("/rooms/<room_number>/rotate-key", methods=["POST"])
@login_required
@admin_required
def rotate_key(room_number):
    settings = get_or_create_settings(room_number)
    get_or_create_status(room_number)
    raw_key = ACSettings.generate_device_key()
    settings.set_device_key(raw_key)
    db.session.commit()
    rooms = User.query.filter_by(is_admin=False).order_by(User.room_number).all()
    flash(f"New device key for room {room_number}. Copy it now.", "success")
    return render_template(
        "users.html",
        rooms=rooms,
        new_device_key=raw_key,
        new_room=room_number,
    )


@admin_bp.route("/events")
@login_required
@admin_required
def event_logs():
    page = request.args.get("page", 1, type=int)
    selected_room = request.args.get("room", "all")
    event_type = request.args.get("event_type", "all")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    query = _filtered_events(selected_room, event_type, date_from, date_to)
    per_page = 50
    total_events = query.count()
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    total_pages = max(1, (total_events + per_page - 1) // per_page)
    rooms = User.query.filter(User.room_number.isnot(None)).all()
    return render_template(
        "event_logs.html",
        events=pagination.items,
        total_events=total_events,
        page=page,
        total_pages=total_pages,
        rooms=rooms,
        selected_room=selected_room,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
    )


@admin_bp.route("/events/export")
@login_required
@admin_required
def export_events():
    selected_room = request.args.get("room", "all")
    event_type = request.args.get("event_type", "all")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    events = _filtered_events(selected_room, event_type, date_from, date_to).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "ID",
            "Room",
            "Timestamp",
            "Window State",
            "AC State",
            "Temperature (F)",
            "Policy Compliant",
            "Compliance Issue",
        ]
    )
    for event in events:
        temp_f = celsius_to_fahrenheit(event.temperature)
        writer.writerow(
            [
                event.id,
                event.room_number,
                event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                event.window_state,
                event.ac_state,
                f"{temp_f:.1f}" if temp_f is not None else "",
                "Yes" if event.policy_compliant else "No",
                event.compliance_issue or "",
            ]
        )
    filename = f"event_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@admin_bp.route("/test-email")
@login_required
@admin_required
def test_email():
    ok = send_email(
        "Test email from AC Control Center",
        current_user.email,
        "If you received this, mail is configured correctly.",
    )
    flash("Test email sent." if ok else "Mail is not configured or send failed.", "success" if ok else "error")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/guide")
@login_required
@admin_required
def admin_guide():
    return render_template("admin_guide.html")


def _parse_time(value: str | None, default: time) -> time:
    if not value:
        return default
    try:
        hours, minutes = map(int, value.split(":"))
        return time(hours, minutes)
    except (TypeError, ValueError):
        return default


def _filtered_events(selected_room, event_type, date_from, date_to):
    query = WindowEvent.query
    if selected_room != "all":
        query = query.filter_by(room_number=selected_room)
    if event_type == "window_opened":
        query = query.filter_by(window_state="opened")
    elif event_type == "window_closed":
        query = query.filter_by(window_state="closed")
    elif event_type == "ac_on":
        query = query.filter_by(ac_state="on")
    elif event_type == "ac_off":
        query = query.filter_by(ac_state="off")
    elif event_type == "policy_violation":
        query = query.filter_by(policy_compliant=False)
    if date_from:
        query = query.filter(WindowEvent.timestamp >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(WindowEvent.timestamp < end)
    return query.order_by(WindowEvent.timestamp.desc())
