import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from sqlalchemy.orm import DeclarativeBase

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class Base(DeclarativeBase):
    pass
 
db: SQLAlchemy = SQLAlchemy(model_class=Base)
login_manager: LoginManager = LoginManager()
mail = Mail()

# Create the app
app: Flask = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev_key")

# Configure database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ac_control.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Configure email
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')

# Initialize extensions
db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = "login" # type: ignore
mail.init_app(app)

# Import routes after app initialization
from routes import *  # noqa

with app.app_context():
    # Import models to ensure they're registered with SQLAlchemy
    from models import User, ACSettings, WindowEvent  # noqa
    db.create_all()