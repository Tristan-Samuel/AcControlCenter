from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from app import app, db, login_manager, mail
from models import User, ACSettings, WindowEvent
import random  # For mock temperature data

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
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid username or password')
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
    settings = ACSettings.query.filter_by(room_number=current_user.room_number).first()
    settings.max_temperature = float(request.form['max_temperature'])
    settings.auto_shutoff = 'auto_shutoff' in request.form
    settings.email_notifications = 'email_notifications' in request.form
    db.session.commit()
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
