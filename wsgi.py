"""Gunicorn / flask entrypoint: gunicorn --workers 1 --threads 8 wsgi:app"""

from dotenv import load_dotenv

load_dotenv()

from ac_control import create_app

app = create_app()
