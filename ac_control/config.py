"""Environment-driven configuration. Secrets never have source-code defaults in production."""

from __future__ import annotations

import os
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "t", "on"}


class Config:
    SECRET_KEY = os.environ.get("SESSION_SECRET")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = _bool_env("MAIL_USE_TLS", True)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER") or os.environ.get(
        "MAIL_USERNAME"
    )

    USE_NGROK = _bool_env("USE_NGROK", False)
    NGROK_AUTHTOKEN = os.environ.get("NGROK_AUTHTOKEN")
    NGROK_DOMAIN = os.environ.get("NGROK_DOMAIN")
    PORT = int(os.environ.get("PORT", "5000"))

    ALLOW_PUBLIC_REGISTRATION = _bool_env("ALLOW_PUBLIC_REGISTRATION", False)
    PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "http")
    PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
    ENROLL_TOKEN = os.environ.get("ENROLL_TOKEN", "")
    STALE_AFTER_SECONDS = int(os.environ.get("STALE_AFTER_SECONDS", "180"))
    SCHEDULER_DISABLED = _bool_env("SCHEDULER_DISABLED", False)
    # Fake ESP32s that exercise the real heartbeat and policy path.
    SIMULATION_MODE = _bool_env("SIMULATION_MODE", False)
    SIMULATION_ADMIN_PASSWORD = os.environ.get("SIMULATION_ADMIN_PASSWORD", "")
    SIMULATION_TICK_SECONDS = int(os.environ.get("SIMULATION_TICK_SECONDS", "5"))

    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")


class DevelopmentConfig(Config):
    DEBUG = True
    SECRET_KEY = os.environ.get("SESSION_SECRET", "dev-only-not-for-production")


class ProductionConfig(Config):
    DEBUG = False

    def __init__(self) -> None:
        super().__init__()
        if not os.environ.get("SESSION_SECRET"):
            raise RuntimeError(
                "SESSION_SECRET must be set in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if self.USE_NGROK or self.PREFERRED_URL_SCHEME == "https":
            self.SESSION_COOKIE_SECURE = True
            self.PREFERRED_URL_SCHEME = "https"


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SCHEDULER_DISABLED = True
    ALLOW_PUBLIC_REGISTRATION = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    MAIL_DEFAULT_SENDER = "test@example.com"


def sqlite_uri(instance_path: str) -> str:
    env_uri = os.environ.get("DATABASE_URL")
    if env_uri:
        return env_uri
    db_file = Path(instance_path) / "ac_control.db"
    return f"sqlite:///{db_file}"


def select_config() -> type[Config] | Config:
    env = os.environ.get("FLASK_ENV", os.environ.get("APP_ENV", "development")).lower()
    if env in {"production", "prod"}:
        return ProductionConfig()
    if env in {"testing", "test"}:
        return TestingConfig
    return DevelopmentConfig
