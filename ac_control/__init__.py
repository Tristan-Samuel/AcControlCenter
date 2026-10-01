"""AC Control Center Flask application factory."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

from ac_control.config import TestingConfig, select_config, sqlite_uri
from ac_control.extensions import csrf, db, limiter, login_manager, mail
from ac_control.temperature import celsius_to_fahrenheit, format_temp_f


def create_app(config_object=None) -> Flask:
    load_dotenv()
    package_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    if config_object is None:
        config_object = select_config()
    if isinstance(config_object, type):
        app.config.from_object(config_object)
        if config_object is TestingConfig and not app.config.get("SQLALCHEMY_DATABASE_URI"):
            app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    else:
        app.config.from_object(config_object)

    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = sqlite_uri(app.instance_path)

    if app.config.get("USE_NGROK") or app.config.get("PREFERRED_URL_SCHEME") == "https":
        app.config.setdefault("SESSION_COOKIE_SECURE", True)

    _configure_logging(app)
    _init_extensions(app)
    _register_jinja(app)
    _register_blueprints(app)
    _register_health(app)
    _configure_sqlite(app)
    _create_schema(app)

    if not app.config.get("TESTING") and not app.config.get("SCHEDULER_DISABLED"):
        _start_scheduler(app)

    if app.config.get("USE_NGROK") and not app.config.get("TESTING"):
        from ac_control.ngrok import start_ngrok

        start_ngrok(app)

    return app


def _configure_logging(app: Flask) -> None:
    level = logging.DEBUG if app.debug else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app.logger.setLevel(level)


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    mail.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from ac_control.models import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def _register_jinja(app: Flask) -> None:
    app.jinja_env.filters["temp_f"] = format_temp_f
    app.jinja_env.globals["celsius_to_fahrenheit"] = celsius_to_fahrenheit

    @app.context_processor
    def _simulation_banner():
        return {"simulation_mode": bool(app.config.get("SIMULATION_MODE"))}


def _register_blueprints(app: Flask) -> None:
    from ac_control.blueprints.admin import admin_bp
    from ac_control.blueprints.auth import auth_bp
    from ac_control.blueprints.device import device_bp
    from ac_control.blueprints.rooms import rooms_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(device_bp)
    csrf.exempt(device_bp)


def _register_health(app: Flask) -> None:
    @app.get("/health")
    def health():
        from ac_control.ngrok import get_public_url

        public_url = (app.config.get("PUBLIC_BASE_URL") or "").strip() or get_public_url()
        return jsonify(
            {
                "ok": True,
                "public_url": public_url,
                "ngrok": get_public_url(),
                "simulation": bool(app.config.get("SIMULATION_MODE")),
            }
        )


def _configure_sqlite(app: Flask) -> None:
    from sqlalchemy import event

    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not str(uri).startswith("sqlite"):
        return

    with app.app_context():
        @event.listens_for(db.engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()


def _create_schema(app: Flask) -> None:
    from ac_control.models import GlobalPolicy, PendingDevice, RoomStatus, User  # noqa: F401

    with app.app_context():
        db.create_all()
        _migrate_sqlite_columns()
        if GlobalPolicy.query.first() is None:
            db.session.add(GlobalPolicy())
            db.session.commit()
        for user in User.query.filter(User.room_number.isnot(None)).all():
            if not RoomStatus.query.filter_by(room_number=user.room_number).first():
                db.session.add(RoomStatus(room_number=user.room_number))
        db.session.commit()


def _migrate_sqlite_columns() -> None:
    from sqlalchemy import inspect, text

    uri = str(db.engine.url)
    if not uri.startswith("sqlite"):
        return
    inspector = inspect(db.engine)
    additions = {
        "ac_settings": [
            ("device_mac", "VARCHAR(17)"),
            ("buzz_on_open", "BOOLEAN DEFAULT 0 NOT NULL"),
        ],
        "room_status": [
            ("set_temperature", "FLOAT DEFAULT 20.0 NOT NULL"),
            ("door_state", "VARCHAR(10) DEFAULT 'closed' NOT NULL"),
        ],
        "window_event": [
            ("door_state", "VARCHAR(10) DEFAULT 'closed'"),
        ],
        "pending_window_event": [
            ("door_state", "VARCHAR(10)"),
        ],
    }
    with db.engine.begin() as conn:
        for table, columns in additions.items():
            if table not in inspector.get_table_names():
                continue
            existing = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        conn.execute(
            text(
                "UPDATE room_status SET door_state = 'closed' WHERE door_state IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE room_status SET set_temperature = 20.0 WHERE set_temperature IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE window_event SET door_state = 'closed' WHERE door_state IS NULL"
            )
        )
        try:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_ac_settings_device_mac "
                    "ON ac_settings (device_mac)"
                )
            )
        except Exception:
            pass


def _start_scheduler(app: Flask) -> None:
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return
    from apscheduler.schedulers.background import BackgroundScheduler

    from ac_control.services.ingest import (
        check_scheduled_shutoffs,
        check_temperature_compliance,
        process_due_pending_events,
        update_compliance_metrics,
    )

    scheduler = BackgroundScheduler()

    def _job(fn):
        def wrapped():
            with app.app_context():
                fn()

        wrapped.__name__ = fn.__name__
        return wrapped

    scheduler.add_job(_job(process_due_pending_events), "interval", seconds=10)
    scheduler.add_job(_job(check_scheduled_shutoffs), "interval", minutes=5)
    scheduler.add_job(_job(update_compliance_metrics), "interval", hours=1)
    scheduler.add_job(_job(check_temperature_compliance), "interval", seconds=5)
    if app.config.get("SIMULATION_MODE"):
        from ac_control.services.simulation import ensure_demo, tick

        with app.app_context():
            ensure_demo()
        every = max(2, int(app.config.get("SIMULATION_TICK_SECONDS") or 5))
        scheduler.add_job(_job(tick), "interval", seconds=every, id="simulation")
    scheduler.start()
    app.extensions["scheduler"] = scheduler
