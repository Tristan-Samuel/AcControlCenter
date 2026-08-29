"""Optional ngrok tunnel for off-campus / cross-VLAN classroom Pis."""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_public_url: str | None = None
_monitor_started = False


def get_public_url() -> str | None:
    return _public_url


def start_ngrok(app) -> str | None:
    global _public_url, _monitor_started
    token = app.config.get("NGROK_AUTHTOKEN")
    domain = app.config.get("NGROK_DOMAIN")
    port = int(app.config.get("PORT", 5000))

    if not token:
        logger.warning("USE_NGROK is set but NGROK_AUTHTOKEN is missing")
        return None

    try:
        from pyngrok import ngrok
    except ImportError:
        logger.error("pyngrok is not installed; cannot start tunnel")
        return None

    ngrok.set_auth_token(token)
    kwargs: dict = {"addr": str(port), "proto": "http"}
    if domain:
        kwargs["domain"] = domain

    try:
        tunnel = ngrok.connect(**kwargs)
    except Exception:
        logger.exception("Failed to start ngrok tunnel")
        return None

    url = getattr(tunnel, "public_url", None)
    if url and url.startswith("http://"):
        url = url.replace("http://", "https://", 1)
    _public_url = url
    app.config["NGROK_URL"] = url
    logger.info("Ngrok tunnel: %s -> local port %s", url, port)

    if not _monitor_started:
        _monitor_started = True
        thread = threading.Thread(target=_monitor, args=(app, kwargs), daemon=True)
        thread.start()
    return url


def _monitor(app, connect_kwargs: dict) -> None:
    global _public_url
    from pyngrok import ngrok

    while True:
        time.sleep(30)
        try:
            tunnels = ngrok.get_tunnels()
            if tunnels:
                continue
            logger.warning("Ngrok tunnel missing; reconnecting")
            tunnel = ngrok.connect(**connect_kwargs)
            url = getattr(tunnel, "public_url", None)
            if url and url.startswith("http://"):
                url = url.replace("http://", "https://", 1)
            _public_url = url
            with app.app_context():
                app.config["NGROK_URL"] = url
        except Exception:
            logger.exception("Ngrok monitor error")
