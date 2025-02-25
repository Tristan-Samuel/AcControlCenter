from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from datetime import datetime
from app import db, login_manager, mail
from models import User, ACSettings, WindowEvent
import random  # For mock temperature data
import logging

# Create main blueprint
main = Blueprint('main', __name__)

@login_manager.user_loader
def load_user(id):
    return db.session.get(User, int(id))

@main.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.user_management'))
        return redirect(url_for('main.room_dashboard'))
    return redirect(url_for('main.login'))

@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            if not user.is_active and not user.is_admin:
                flash('Your account has been deactivated. Please contact an administrator.')
                return redirect(url_for('main.login'))

            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('main.index'))
        flash('Invalid username or password')
    return render_template('login.html')

@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.index'))

@main.route('/room_dashboard')
@login_required
def room_dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin.dashboard'))

    settings = ACSettings.query.filter_by(room_number=current_user.room_number).first()
    if not settings:
        settings = ACSettings(room_number=current_user.room_number)
        db.session.add(settings)
        db.session.commit()

    events = WindowEvent.query.filter_by(room_number=current_user.room_number)\
        .order_by(WindowEvent.timestamp.desc()).limit(10).all()

    # Mock current temperature
    current_temp = random.uniform(20.0, 28.0)

    return render_template('room_dashboard.html',
                         settings=settings,
                         events=events,
                         current_temp=current_temp)

@main.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    settings = ACSettings.query.filter_by(room_number=current_user.room_number).first()
    settings.max_temperature = float(request.form['max_temperature'])
    settings.auto_shutoff = 'auto_shutoff' in request.form
    settings.email_notifications = 'email_notifications' in request.form
    db.session.commit()
    return redirect(url_for('main.room_dashboard'))

@main.route('/log_window_event', methods=['POST'])
@login_required
def log_window_event():
    event = WindowEvent(
        room_number=current_user.room_number,
        window_state=request.form['window_state'],
        ac_state=request.form['ac_state'],
        temperature=float(request.form['temperature'])
    )
    db.session.add(event)
    db.session.commit()

    if event.window_state == 'opened' and event.ac_state == 'on':
        send_notification(current_user.email)

    return jsonify({'status': 'success'})

def send_notification(email):
    msg = Message('Window Open Alert',
                 sender='noreply@accontrol.com',
                 recipients=[email])
    msg.body = 'Warning: Window has been opened while AC is running!'
    mail.send(msg)

@main.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        if request.form['password'] != request.form['confirm_password']:
            flash('Passwords do not match')
            return render_template('register.html')

        # Check if username, email, or room number already exists
        if User.query.filter_by(username=request.form['username']).first():
            flash('Username already exists')
            return render_template('register.html')

        if User.query.filter_by(email=request.form['email']).first():
            flash('Email already exists')
            return render_template('register.html')

        # Only check room number uniqueness for non-admin users
        if not 'is_admin' in request.form:
            if User.query.filter_by(room_number=request.form['room_number']).first():
                flash('Room number already registered')
                return render_template('register.html')

        # Create new user
        try:
            user = User(
                username=request.form['username'],
                email=request.form['email'],
                room_number=request.form['room_number'] if not 'is_admin' in request.form else None,
                is_admin='is_admin' in request.form
            )
            user.set_password(request.form['password'])

            db.session.add(user)
            db.session.commit()

            # Create default AC settings for the room
            if not user.is_admin and user.room_number:
                settings = ACSettings(room_number=user.room_number)
                db.session.add(settings)
                db.session.commit()

            flash('Registration successful! Please login.')
            return redirect(url_for('main.login'))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Registration error: {str(e)}")
            flash('An error occurred during registration. Please try again.')

    return render_template('register.html')