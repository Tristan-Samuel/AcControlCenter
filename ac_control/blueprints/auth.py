"""Login, logout, optional public room registration."""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ac_control.extensions import db, limiter
from ac_control.models import ACSettings, RoomStatus, User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))

    if request.method == "POST":
        login_type = request.form.get("login_type", "password")
        user = None
        valid = False
        if login_type == "pin":
            user = User.query.filter_by(room_number=request.form.get("room_number")).first()
            valid = bool(user and user.check_pin(request.form.get("pin", "")))
        else:
            user = User.query.filter_by(username=request.form.get("username", "")).first()
            valid = bool(user and user.check_password(request.form.get("password", "")))

        if valid and user:
            login_user(user, remember="remember" in request.form)
            return redirect(url_for("auth.index"))
        flash("Invalid credentials. Please try again.", "error")
    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("rooms.dashboard"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if not current_app.config.get("ALLOW_PUBLIC_REGISTRATION"):
        flash("Public registration is disabled. Ask an administrator to create your account.", "error")
        return redirect(url_for("auth.login"))

    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))

    if request.method == "POST":
        password = request.form.get("password", "")
        if password != request.form.get("confirm_password"):
            flash("Passwords do not match", "error")
            return render_template("register.html")
        if User.query.filter_by(username=request.form.get("username")).first():
            flash("Username already exists", "error")
            return render_template("register.html")
        if User.query.filter_by(email=request.form.get("email")).first():
            flash("Email already exists", "error")
            return render_template("register.html")
        room_number = (request.form.get("room_number") or "").strip()
        if not room_number:
            flash("Room number is required", "error")
            return render_template("register.html")
        if User.query.filter_by(room_number=room_number).first():
            flash("Room number already registered", "error")
            return render_template("register.html")
        # Never honor a posted is_admin field.
        user = User(
            username=request.form.get("username"),
            email=request.form.get("email"),
            room_number=room_number,
            is_admin=False,
        )
        user.set_password(password)
        pin = request.form.get("pin") or ""
        if pin:
            if len(pin) != 4 or not pin.isdigit():
                flash("PIN must be exactly 4 digits", "error")
                return render_template("register.html")
            user.set_pin(pin)
        db.session.add(user)
        db.session.flush()
        db.session.add(ACSettings(room_number=room_number))
        db.session.add(RoomStatus(room_number=room_number))
        db.session.commit()
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("register.html")
