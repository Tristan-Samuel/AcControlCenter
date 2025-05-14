from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from app import app, db, login_manager, mail
from models import User, ACSettings, WindowEvent, SessionAtributes, PendingWindowEvent, GlobalPolicy, RoomStatus
import random  # For mock temperature data
from datetime import datetime, timedelta


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
        login_type = request.form.get('login_type', 'password')

        if login_type == 'password':
            user = User.query.filter_by(
                username=request.form['username']).first()
            valid = user and user.check_password(request.form['password'])
        else:  # PIN login
            user = User.query.filter_by(
                room_number=request.form['room_number']).first()
            valid = user and user.check_pin(request.form['pin'])

        if valid:
            app.logger.debug(
                f"Login successful for user: {user.username}, is_admin: {user.is_admin}"
            )
            remember = 'remember' in request.form
            login_user(user, remember=remember)

            # Redirect based on user type
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('room_dashboard'))

        flash('Invalid credentials. Please try again.', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/admin_login', methods=['POST'])
def admin_login():
    room_number2 = request.form.get('room_number')
    settings = ACSettings.query.filter_by(room_number=room_number2).first()

    events = WindowEvent.query.filter_by(room_number=room_number2)\
        .order_by(WindowEvent.timestamp.desc()).limit(10).all()

    # Mock current temperature
    current_temp = random.uniform(20.0, 28.0)

    return render_template('room_dashboard.html',
                           is_admin=True,
                           room_number=room_number2,
                           settings=settings,
                           events=events,
                           current_temp=current_temp)


@app.route('/room_dashboard')
@login_required
def room_dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))

    app.logger.debug(
        f"Accessing room dashboard for user: {current_user.username}")
    settings = ACSettings.query.filter_by(
        room_number=current_user.room_number).first()
    if not settings:
        settings = ACSettings(room_number=current_user.room_number)
        db.session.add(settings)
        db.session.commit()

    events = WindowEvent.query.filter_by(room_number=current_user.room_number)\
        .order_by(WindowEvent.timestamp.desc()).limit(10).all()

    # Mock current temperature
    current_temp = random.uniform(20.0, 28.0)

    return render_template('room_dashboard.html',
                           room_number=current_user.room_number,
                           settings=settings,
                           events=events,
                           current_temp=current_temp)


@app.route('/toggle_lock/<room_number>', methods=['POST'])
@login_required
def toggle_lock(room_number):
    # Ensure only admin users can toggle settings
    if not current_user.is_admin:
        flash("You do not have permission to lock/unlock settings.", "danger")
        return redirect(url_for('room_dashboard', room_number=room_number))

    # Fetch AC settings for this room
    settings = ACSettings.query.filter_by(room_number=room_number).first()
    if not settings:
        flash("No settings found for this room.", "danger")
        return redirect(url_for('room_dashboard', room_number=room_number))

    # Toggle the lock state
    settings.settings_locked = not settings.settings_locked
    db.session.commit()

    flash(
        f"Settings {'locked' if settings.settings_locked else 'unlocked'} successfully.",
        "success")

    # For admin users, we need to use admin_login pattern instead of room_dashboard
    # to prevent auto-redirect to admin_dashboard
    if current_user.is_admin:
        return render_template(
            'room_dashboard.html',
            session_attributes=SessionAtributes(room_number, True),
            room_number=room_number,
            settings=settings,
            events=WindowEvent.query.filter_by(
                room_number=room_number).order_by(
                    WindowEvent.timestamp.desc()).limit(10).all(),
            current_temp=random.uniform(20.0, 28.0))
    else:
        return redirect(url_for('room_dashboard', room_number=room_number))


@app.route('/toggle_max_temp_lock/<room_number>', methods=['POST'])
@login_required
def toggle_max_temp_lock(room_number):
    # Ensure only admin users can toggle the max temp lock
    if not current_user.is_admin:
        flash("You do not have permission to lock/unlock the max temperature.",
              "danger")
        return redirect(url_for('room_dashboard', room_number=room_number))

    # Fetch AC settings for this room
    settings = ACSettings.query.filter_by(room_number=room_number).first()
    if not settings:
        flash("No settings found for this room.", "danger")
        return redirect(url_for('room_dashboard', room_number=room_number))

    # Toggle the max temp lock state
    settings.max_temp_locked = not settings.max_temp_locked
    db.session.commit()

    flash(
        f"Max temperature setting {'locked' if settings.max_temp_locked else 'unlocked'} successfully.",
        "success")

    # For admin users, we need to use admin_login pattern instead of room_dashboard
    # to prevent auto-redirect to admin_dashboard
    if current_user.is_admin:
        return render_template(
            'room_dashboard.html',
            session_attributes=SessionAtributes(room_number, True),
            room_number=room_number,
            settings=settings,
            events=WindowEvent.query.filter_by(
                room_number=room_number).order_by(
                    WindowEvent.timestamp.desc()).limit(10).all(),
            current_temp=random.uniform(20.0, 28.0))
    else:
        return redirect(url_for('room_dashboard', room_number=room_number))


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
    save_settings = False
    if request.form.get("save_settings", "").lower() == "true":
        save_settings = True
    is_admin = request.form.get('is_admin', 'false').lower() == 'true'
    room_number2 = request.form.get('room_number')

    if not request.form.get('room_number', "").isnumeric():
        room_number2 = current_user.room_number

    if not room_number2 and not is_admin:
        flash('Only room users or admins can update settings')
        return redirect(url_for('admin_dashboard'))

    settings = ACSettings.query.filter_by(room_number=room_number2).first()
    if not settings:
        settings = ACSettings(room_number=room_number2)
        db.session.add(settings)

    # Check if admin is forcing the settings
    force_update = request.form.get('force_update',
                                    default='false').lower() == 'true'

    try:
        if is_admin and force_update:
            # Admin is forcing settings
            if 'settings_locked' in request.form:
                settings.settings_locked = request.form[
                    'settings_locked'] == '1'
                flash('Settings access updated!', 'success')
            else:
                settings.max_temperature = float(
                    request.form['max_temperature'])
                settings.auto_shutoff = 'auto_shutoff' in request.form
                settings.shutoff_delay = int(request.form.get('shutoff_delay', 30))
                settings.email_notifications = 'email_notifications' in request.form
                flash('Settings enforced by admin!', 'success')
        elif room_number2:
            # Allow user to update settings if not forced
            try:
                settings.max_temperature = float(
                    request.form['max_temperature'])
            except Exception:
                pass

            try:
                settings.auto_shutoff = 'auto_shutoff' in request.form
            except Exception:
                pass
                
            try:
                settings.shutoff_delay = int(request.form.get('shutoff_delay', 30))
                # Ensure delay is within valid range
                if settings.shutoff_delay < 0:
                    settings.shutoff_delay = 0
                elif settings.shutoff_delay > 300:
                    settings.shutoff_delay = 300
            except Exception:
                pass

            try:
                settings.email_notifications = 'email_notifications' in request.form
            except Exception:
                pass

            flash('Settings updated successfully!', 'success')
        else:
            flash('Access denied.', 'error')
            return redirect(url_for('room_dashboard'))

        db.session.commit()
    except Exception as e:
        app.logger.error(f"Settings update error: {str(e)}")
        flash('Error updating settings. Please try again.', 'error')
        db.session.rollback()

    # Always redirect back to the room_dashboard
    return redirect(url_for('room_dashboard', room_number=room_number2))


@app.route('/log_window_event', methods=['POST'])
@login_required
def log_window_event():
    event = WindowEvent()
    event.room_number = current_user.room_number
    event.window_state = request.form['window_state']
    event.ac_state = request.form['ac_state']
    event.temperature = float(request.form['temperature'])
    
    db.session.add(event)
    db.session.commit()

    if event.window_state == 'opened' and event.ac_state == 'on':
        send_notification(current_user.email)

    return jsonify({'status': 'success'})


def send_notification(email):
    msg = Message('Window Open Alert',
                  sender='tristanstxbot@gmail.com',
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
            if User.query.filter_by(
                    room_number=request.form['room_number']).first():
                flash('Room number already registered')
                return render_template('register.html')

        # Create new user
        try:
            user = User(username=request.form['username'],
                        email=request.form['email'],
                        room_number=request.form['room_number']
                        if not 'is_admin' in request.form else None,
                        is_admin='is_admin' in request.form)
            user.set_password(request.form['password'])

            # Set PIN if provided
            pin = request.form.get('pin')
            if pin and len(pin) == 4:
                user.set_pin(pin)

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

    # Check if temperature exceeds max temperature setting
    settings = ACSettings.query.filter_by(room_number=room_number).first()
    user = User.query.filter_by(room_number=room_number).first()

    if settings and user and current_temp > settings.max_temperature and settings.email_notifications:
        # Import here to avoid circular imports
        from email_utils import send_temperature_alert
        send_temperature_alert(user.email, room_number, round(current_temp, 1))

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
        'max_temperature':
        settings.max_temperature,
        'auto_shutoff':
        settings.auto_shutoff,
        'email_notifications':
        settings.email_notifications,
        'window_state':
        latest_event.window_state if latest_event else 'unknown',
        'ac_state':
        latest_event.ac_state if latest_event else 'unknown'
    })


@app.route('/test_email', methods=['GET'])
@login_required
def test_email():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    from email_utils import send_email
    success = send_email("Test Email from AC Control System",
                         current_user.email,
                         "This is a test email from your AC Control System.")

    if success:
        flash("Test email sent successfully!", "success")
    else:
        flash("Failed to send test email. Check your email configuration.",
              "error")

    return redirect(url_for('admin_dashboard'))


@app.route('/force_ac_state/<room_number>/<state>', methods=['POST'])
@login_required
def force_ac_state(room_number, state):
    """Force AC to a specific state (on/off)"""
    # Authorize access - must be admin or the owner of the room
    if not current_user.is_admin and current_user.room_number != room_number:
        flash("You don't have permission to control this room's AC", "error")
        return redirect(url_for('index'))
    
    # Validate state parameter
    if state not in ['on', 'off']:
        flash("Invalid AC state requested", "error")
        return redirect(url_for('room_dashboard'))
    
    try:
        # Create a window event with the current window state but forced AC state
        latest_event = WindowEvent.query.filter_by(room_number=room_number)\
            .order_by(WindowEvent.timestamp.desc()).first()
        
        current_window_state = 'closed'  # Default if no previous events
        current_temp = 22.0  # Default temperature
        
        if latest_event:
            current_window_state = latest_event.window_state
            current_temp = latest_event.temperature
        
        # Create new event with forced AC state
        event = WindowEvent()
        event.room_number = room_number
        event.window_state = current_window_state
        event.ac_state = state
        event.temperature = current_temp
        
        db.session.add(event)
        db.session.commit()
        
        action = "turned on" if state == "on" else "turned off"
        flash(f"AC has been force {action}", "success")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error forcing AC state: {str(e)}")
        flash("Error changing AC state", "error")
    
    # Redirect to the appropriate dashboard
    if current_user.is_admin and current_user.room_number != room_number:
        # Admin accessing another room
        return redirect(url_for('admin_login', room_number=room_number))
    else:
        return redirect(url_for('room_dashboard'))


@app.route('/user_guide')
def user_guide():
    """Display the system user guide with detailed instructions"""
    return render_template('user_guide.html')


@app.route('/api/recent_events/<room_number>')
@login_required
def get_recent_events(room_number):
    # Authorize access - must be admin or the owner of the room
    if not current_user.is_admin and current_user.room_number != room_number:
        return jsonify({'error': 'Unauthorized'}), 403
        
    # Fetch latest events for this room (limit to 10)
    events = WindowEvent.query.filter_by(room_number=room_number)\
        .order_by(WindowEvent.timestamp.desc()).limit(10).all()
        
    # Format events for JSON response
    events_data = []
    for event in events:
        events_data.append({
            'id': event.id,
            'timestamp': event.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'window_state': event.window_state,
            'ac_state': event.ac_state,
            'temperature': event.temperature
        })
        
    return jsonify({'events': events_data})


@app.route('/receive_data', methods=['POST'])
def receive_data():
    """
    Receive window/AC data from clients and process it according to rules.
    This handles window state changes, enforces policy rules, and manages
    pending actions like delayed AC shutoff.
    """
    app.logger.info("Received data")
    
    # Check if the incoming request has JSON data
    if request.is_json:
        data = request.get_json()  # Parse the incoming JSON data
        room_number = data.get('room_number')
        window_state = data.get('window_state')
        ac_state = data.get('ac_state', 'off')
        temperature = data.get('temperature')
        
        # Validate room number
        if not room_number:
            return jsonify({"message": "Room number is required", "status": "error"}), 400
        
        # Get room settings
        settings = ACSettings.query.filter_by(room_number=room_number).first()
        if not settings:
            settings = ACSettings(room_number=room_number)
            db.session.add(settings)
            db.session.commit()

        # Get or create room status
        room_status = RoomStatus.query.filter_by(room_number=room_number).first()
        if not room_status:
            room_status = RoomStatus(
                room_number=room_number,
                current_temperature=float(temperature) if temperature else 22.0,
                window_state=window_state,
                ac_state=ac_state
            )
            db.session.add(room_status)
            db.session.commit()
            
        # Get global policy
        policy = GlobalPolicy.query.first()
        if not policy:
            policy = GlobalPolicy()
            db.session.add(policy)
            db.session.commit()

        app.logger.info(f"Received data: room={room_number}, window={window_state}, ac={ac_state}, temp={temperature}")
        
        # Log the window event and handle delayed actions
        try:
            # Get current temperature
            temp_value = float(temperature) if temperature else 22.0
            
            # Apply policy temperature limits if needed
            is_compliant = True
            compliance_issue = None
            
            if policy.policy_active:
                # Check if the temperature is within allowed range
                if temp_value < policy.min_allowed_temp:
                    compliance_issue = f"Temperature below minimum allowed ({policy.min_allowed_temp}°C)"
                    is_compliant = False
                elif temp_value > policy.max_allowed_temp:
                    compliance_issue = f"Temperature above maximum allowed ({policy.max_allowed_temp}°C)"
                    is_compliant = False
                
            # First check - if window is closed, should we cancel any pending shutoff events?
            if window_state == 'closed' and room_status.has_pending_event:
                # Cancel any pending shutoff events for this room
                pending_events = PendingWindowEvent.query.filter_by(
                    room_number=room_number, 
                    processed=False
                ).all()
                
                for pending in pending_events:
                    pending.processed = True  # Mark as processed (cancelled)
                
                # Update room status
                room_status.has_pending_event = False
                room_status.pending_event_time = None
                
                app.logger.info(f"Cancelled pending events for room {room_number} - window is now closed")
                
                # If AC is off, turn it back on
                if ac_state == 'off':
                    new_ac_state = 'on'
                    app.logger.info(f"Window closed. Turning AC back on for room {room_number}")
                else:
                    new_ac_state = ac_state
                    
                # Create window event
                event = WindowEvent()
                event.room_number = room_number
                event.window_state = window_state
                event.ac_state = new_ac_state
                event.temperature = temp_value
                event.policy_compliant = is_compliant
                event.compliance_issue = compliance_issue
                db.session.add(event)
                
                # Update room status
                room_status.window_state = window_state
                room_status.ac_state = new_ac_state
                room_status.current_temperature = temp_value
                room_status.last_updated = datetime.utcnow()
                
                db.session.commit()
                app.logger.info(f"Window event logged successfully: {event.id}")
                
            # Special handling for window opened while AC is on
            elif window_state == 'opened' and ac_state == 'on' and settings.auto_shutoff:
                # If there's a delay set, create a pending event
                if settings.shutoff_delay > 0:
                    # Calculate when the action should be taken
                    scheduled_time = datetime.utcnow() + timedelta(seconds=settings.shutoff_delay)
                    
                    # Create a pending event
                    pending_event = PendingWindowEvent()
                    pending_event.room_number = room_number
                    pending_event.window_state = window_state
                    pending_event.ac_state = ac_state
                    pending_event.temperature = temp_value
                    pending_event.scheduled_action_time = scheduled_time
                    pending_event.processed = False
                    pending_event.event_type = 'window_open'
                    
                    # Save the pending event
                    db.session.add(pending_event)
                    
                    # Update room status
                    room_status.window_state = window_state
                    room_status.ac_state = ac_state
                    room_status.current_temperature = temp_value
                    room_status.has_pending_event = True
                    room_status.pending_event_time = scheduled_time
                    room_status.last_updated = datetime.utcnow()
                    
                    # Log the current state (before any action is taken)
                    event = WindowEvent()
                    event.room_number = room_number
                    event.window_state = window_state
                    event.ac_state = ac_state  # Still on at this point
                    event.temperature = temp_value
                    event.policy_compliant = is_compliant
                    event.compliance_issue = compliance_issue
                    db.session.add(event)
                    
                    db.session.commit()
                    app.logger.info(f"Created pending event {pending_event.id} for room {room_number}, scheduled for {scheduled_time}")
                    app.logger.info(f"Window event logged successfully: {event.id}")
                    
                    # The AC will be turned off later by the scheduler
                    new_ac_state = ac_state  # Keep it on for now
                else:
                    # No delay, turn off AC immediately
                    event = WindowEvent()
                    event.room_number = room_number
                    event.window_state = window_state
                    event.ac_state = 'off'  # Turn off immediately
                    event.temperature = temp_value
                    event.policy_compliant = is_compliant
                    event.compliance_issue = compliance_issue
                    db.session.add(event)
                    
                    # Update room status
                    room_status.window_state = window_state
                    room_status.ac_state = 'off'
                    room_status.current_temperature = temp_value
                    room_status.has_pending_event = False
                    room_status.pending_event_time = None
                    room_status.last_updated = datetime.utcnow()
                    
                    db.session.commit()
                    app.logger.info(f"Window event logged successfully: {event.id}")
                    
                    # Send notification immediately if configured
                    if settings.email_notifications:
                        user = User.query.filter_by(room_number=room_number).first()
                        if user:
                            app.logger.info(f"Sending notification to {user.email}")
                            try:
                                send_notification(user.email)
                            except Exception as e:
                                app.logger.error(f"Error sending notification: {str(e)}")
                    
                    new_ac_state = 'off'  # Turn off immediately
            else:
                # Window closed - turn AC back on
                if window_state == 'closed' and ac_state == 'off':
                    app.logger.info(f"Window closed. Turning AC back on for room {room_number}")
                    new_ac_state = 'on'  # Turn AC on
                else:
                    # Regular event without special handling
                    new_ac_state = ac_state  # Keep current state
                
                # Create regular event
                event = WindowEvent()
                event.room_number = room_number
                event.window_state = window_state
                event.ac_state = new_ac_state
                event.temperature = temp_value
                event.policy_compliant = is_compliant
                event.compliance_issue = compliance_issue
                db.session.add(event)
                
                # Update room status
                room_status.window_state = window_state
                room_status.ac_state = new_ac_state
                room_status.current_temperature = temp_value
                room_status.last_updated = datetime.utcnow()
                
                db.session.commit()
                app.logger.info(f"Window event logged successfully: {event.id}")
                
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error processing event: {str(e)}")
            # Continue processing even if logging fails
            new_ac_state = ac_state  # Keep current state on error

        # Check if we need to enforce temperature limits
        ac_message = "AC state updated"
        if policy.policy_active and not is_compliant:
            ac_message = compliance_issue

        # Return a JSON response
        return jsonify({
            "message": "Data received and logged successfully",
            "ac_state": new_ac_state,
            "max_temperature": settings.max_temperature,
            "has_pending_event": room_status.has_pending_event,
            "pending_event_time": room_status.pending_event_time.isoformat() if room_status.pending_event_time else None,
            "is_compliant": is_compliant,
            "policy_message": ac_message
        }), 200
    else:
        return jsonify({
            "message": "Request must be JSON",
            "status": "error"
        }), 400
