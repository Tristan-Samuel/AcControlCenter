from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from app import app, db, login_manager, mail
from models import User, ACSettings, WindowEvent
import random  # For mock temperature data
from datetime import datetime

@login_manager.user_loader
def load_user(id):
    return db.session.get(User, int(id))

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('room_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            app.logger.debug(f"Login successful for user: {user.username}, is_admin: {user.is_admin}")
            remember = 'remember' in request.form
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('index'))
        flash('Invalid username or password. Please try again.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/room_dashboard')
@login_required
def room_dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))

    app.logger.debug(f"Accessing room dashboard for user: {current_user.username}")
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

@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('room_dashboard'))

    rooms = User.query.filter_by(is_admin=False).all()
    return render_template('admin_dashboard.html', rooms=rooms)

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    if not current_user.room_number:
        flash('Only room users can update settings')
        return redirect(url_for('admin_dashboard'))

    settings = ACSettings.query.filter_by(room_number=current_user.room_number).first()
    if not settings:
        settings = ACSettings(room_number=current_user.room_number)
        db.session.add(settings)

    try:
        settings.max_temperature = float(request.form['max_temperature'])
        settings.auto_shutoff = 'auto_shutoff' in request.form
        settings.email_notifications = 'email_notifications' in request.form
        db.session.commit()
        flash('Settings updated successfully!', 'success')
    except Exception as e:
        app.logger.error(f"Settings update error: {str(e)}")
        flash('Error updating settings. Please try again.', 'error')
        db.session.rollback()

    return redirect(url_for('room_dashboard'))

@app.route('/log_window_event', methods=['POST'])
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

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

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
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Registration error: {str(e)}")
            flash('An error occurred during registration. Please try again.')

    return render_template('register.html')


@app.route('/api/temperature/<room_number>')
@login_required
def get_temperature(room_number):
    if not current_user.is_admin and current_user.room_number != room_number:
        return jsonify({'error': 'Unauthorized'}), 403

    # For now, generate mock temperature data
    # This will be replaced with actual sensor data from Raspberry Pi
    current_temp = random.uniform(20.0, 28.0)
    return jsonify({
        'temperature': round(current_temp, 1),
        'timestamp': datetime.utcnow().isoformat()
    })

@app.route('/api/room_status/<room_number>')
@login_required
def get_room_status(room_number):
    if not current_user.is_admin and current_user.room_number != room_number:
        return jsonify({'error': 'Unauthorized'}), 403

    settings = ACSettings.query.filter_by(room_number=room_number).first()
    if not settings:
        return jsonify({'error': 'Room not found'}), 404

    # Get latest window event
    latest_event = WindowEvent.query.filter_by(room_number=room_number)\
        .order_by(WindowEvent.timestamp.desc()).first()

    return jsonify({
        'max_temperature': settings.max_temperature,
        'auto_shutoff': settings.auto_shutoff,
        'email_notifications': settings.email_notifications,
        'window_state': latest_event.window_state if latest_event else 'unknown',
        'ac_state': latest_event.ac_state if latest_event else 'unknown'
    })