from flask import request, jsonify
from app import app, db
from models import ACSettings, RoomStatus, GlobalPolicy
from datetime import datetime
from routes import time_in_range


@app.route('/api/check_command', methods=['POST'])
def check_command():
    """
    Advanced API to check if a command should be allowed, 
    and provide alternative actions if needed.
    This is called by Raspberry Pi clients before executing commands.
    """
    if not request.is_json:
        return jsonify({'allowed': False, 'reason': 'Request must be JSON'}), 400
    
    data = request.json
    room_number = data.get('room_number')
    command = data.get('command')
    window_state = data.get('window_state')
    ac_state = data.get('ac_state')
    temperature = data.get('temperature')
    
    if not room_number or not command:
        return jsonify({'allowed': False, 'reason': 'Missing required fields'}), 400
    
    # Get the room's settings
    settings = ACSettings.query.filter_by(room_number=room_number).first()
    room_status = RoomStatus.query.filter_by(room_number=room_number).first()
    
    if not settings or not room_status:
        return jsonify({'allowed': False, 'reason': 'Room not found'}), 404
    
    # Get the global policy
    policy = GlobalPolicy.query.first()
    
    # Check if settings are locked by admin (no commands allowed)
    if settings.settings_locked:
        return jsonify({
            'allowed': False,
            'reason': 'Room settings locked by administrator',
            'alternative_action': 'REPORT_STATUS'
        })
    
    # Check if this is a power-on command with window open
    if command == 'POWER' and window_state == 'opened' and ac_state == 'off':
        return jsonify({
            'allowed': False,
            'reason': 'Cannot turn on AC while window is open',
            'alternative_action': 'REPORT_STATUS'
        })
    
    # Check if this is a prohibited temperature change
    if command == 'TEMP_DOWN':
        # Calculate new temperature after command
        new_temp = temperature - 1
        
        if new_temp < policy.min_allowed_temp:
            return jsonify({
                'allowed': False,
                'reason': f'Temperature cannot be set below {policy.min_allowed_temp}°C',
                'alternative_action': f'SET_TEMP_{int(policy.min_allowed_temp)}'
            })
    
    if command == 'TEMP_UP':
        # Calculate new temperature after command
        new_temp = temperature + 1
        
        if new_temp > policy.max_allowed_temp:
            return jsonify({
                'allowed': False,
                'reason': f'Temperature cannot be set above {policy.max_allowed_temp}°C',
                'alternative_action': f'SET_TEMP_{int(policy.max_allowed_temp)}'
            })
    
    # Check if it's scheduled shutoff time
    if policy.scheduled_shutoff_active and command == 'POWER' and ac_state == 'off':
        current_time = datetime.now().time()
        # If current time is in the shutoff range and it's not exempt
        if time_in_range(policy.scheduled_shutoff_time, policy.scheduled_startup_time, current_time) and not settings.schedule_override:
            return jsonify({
                'allowed': False,
                'reason': 'AC usage not allowed during scheduled shutoff hours',
                'alternative_action': 'REPORT_STATUS'
            })
    
    # All checks passed, command is allowed
    return jsonify({
        'allowed': True,
        'policy_status': 'compliant'
    })