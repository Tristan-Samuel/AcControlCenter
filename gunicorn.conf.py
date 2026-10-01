"""Gunicorn for the home Pi. One worker so the scheduler and simulation are not duplicated."""

bind = "127.0.0.1:5091"
workers = 1
threads = 8
timeout = 60
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
