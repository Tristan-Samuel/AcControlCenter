
from flask import current_app
from app import mail
from flask_mail import Message

def send_email(subject, recipients, body, html=None):
    """
    Send an email to one or more recipients
    
    Args:
        subject (str): Email subject
        recipients (list): List of recipient email addresses
        body (str): Plain text email body
        html (str, optional): HTML version of the email body
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        msg = Message(
            subject=subject,
            sender=current_app.config['MAIL_USERNAME'],
            recipients=recipients if isinstance(recipients, list) else [recipients]
        )
        msg.body = body
        if html:
            msg.html = html
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send email: {str(e)}")
        return False

def send_temperature_alert(email, room_number, temperature):
    """
    Send a temperature alert email
    
    Args:
        email (str): Recipient email address
        room_number (str): Room number
        temperature (float): Current temperature
    """
    subject = f"Temperature Alert - Room {room_number}"
    body = f"""
    Temperature Alert
    -----------------
    
    The temperature in Room {room_number} has reached {temperature}°C, which exceeds the maximum temperature setting.
    Please check your AC system.
    
    - AC Control System
    """
    
    return send_email(subject, email, body)
