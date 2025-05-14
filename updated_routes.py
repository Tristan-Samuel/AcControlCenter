"""
Toggle Lock Route with Fahrenheit support
"""

# Updated version of toggle_lock route with Fahrenheit temperature conversion
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
        # Get room status for temperature
        room_status = RoomStatus.query.filter_by(room_number=room_number).first()
        current_temp = room_status.current_temperature if room_status else 22.0
        
        # Convert to Fahrenheit for display
        from temperature_utils import celsius_to_fahrenheit
        current_temp_f = celsius_to_fahrenheit(current_temp)
        
        return render_template(
            'room_dashboard.html',
            session_attributes=SessionAtributes(room_number, True),
            room_number=room_number,
            settings=settings,
            room_status=room_status,
            events=WindowEvent.query.filter_by(
                room_number=room_number).order_by(
                    WindowEvent.timestamp.desc()).limit(10).all(),
            current_temp=current_temp,
            current_temp_f=current_temp_f)
    else:
        return redirect(url_for('room_dashboard', room_number=room_number))


# Updated version of toggle_max_temp_lock route with Fahrenheit temperature conversion
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
        # Get room status for temperature
        room_status = RoomStatus.query.filter_by(room_number=room_number).first()
        current_temp = room_status.current_temperature if room_status else 22.0
        
        # Convert to Fahrenheit for display
        from temperature_utils import celsius_to_fahrenheit
        current_temp_f = celsius_to_fahrenheit(current_temp)
        
        return render_template(
            'room_dashboard.html',
            session_attributes=SessionAtributes(room_number, True),
            room_number=room_number,
            settings=settings,
            room_status=room_status,
            events=WindowEvent.query.filter_by(
                room_number=room_number).order_by(
                    WindowEvent.timestamp.desc()).limit(10).all(),
            current_temp=current_temp,
            current_temp_f=current_temp_f)
    else:
        return redirect(url_for('room_dashboard', room_number=room_number))