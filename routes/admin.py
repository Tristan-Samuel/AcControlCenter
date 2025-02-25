from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from models import User, ACSettings
from functools import wraps

# Create admin blueprint
admin = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('You need to be an admin to access this page.')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@admin.route('/users')
@login_required
@admin_required
def user_management():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/user_management.html', users=users)

@admin.route('/users/<int:user_id>/update', methods=['POST'])
@login_required
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.is_admin and user.id == current_user.id:
        flash('Cannot modify your own admin account.')
        return redirect(url_for('admin.user_management'))

    if request.form.get('email'):
        email_exists = User.query.filter(User.email == request.form['email'], 
                                    User.id != user_id).first()
        if email_exists:
            flash('Email already exists')
            return redirect(url_for('admin.user_management'))
        user.email = request.form['email']

    if not user.is_admin and request.form.get('room_number'):
        room_exists = User.query.filter(User.room_number == request.form['room_number'], 
                                    User.id != user_id).first()
        if room_exists:
            flash('Room number already exists')
            return redirect(url_for('admin.user_management'))
        user.room_number = request.form['room_number']

    if request.form.get('new_password'):
        user.set_password(request.form['new_password'])

    try:
        db.session.commit()
        flash('User updated successfully')
    except Exception as e:
        db.session.rollback()
        flash('Error updating user')

    return redirect(url_for('admin.user_management'))

@admin.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_user_status(user_id):
    user = User.query.get_or_404(user_id)

    if user.is_admin:
        flash('Cannot deactivate admin accounts')
        return redirect(url_for('admin.user_management'))

    user.is_active = not user.is_active
    db.session.commit()

    flash(f'User {"activated" if user.is_active else "deactivated"} successfully')
    return redirect(url_for('admin.user_management'))