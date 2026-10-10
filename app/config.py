"""Konfiguration über Umgebungsvariablen."""
from __future__ import annotations

import os
from pathlib import Path


def env(name: str, default: str = "") -> str:
    """Liest NAME oder – für Docker Secrets – den Inhalt der Datei aus NAME_FILE."""
    file = os.environ.get(name + "_FILE")
    if file:
        try:
            return Path(file).read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
PORT = int(os.environ.get("PORT", "8080") or 8080)
DOCKER_HOST = os.environ.get("DOCKER_HOST", "").strip() or "unix:///var/run/docker.sock"

# Schlüssel, mit dem das SMTP-Passwort in der Datenbank verschlüsselt wird.
# Ohne Angabe wird einer erzeugt und im Datenverzeichnis abgelegt.
SECRET_KEY = env("SECRET_KEY")

# Optional: Admin-Konto beim ersten Start anlegen (sonst Einrichtung im Browser).
ADMIN_USER = env("ADMIN_USER") or "admin"
ADMIN_PASSWORD = env("ADMIN_PASSWORD")

# Hinter einem Reverse Proxy: X-Forwarded-For/-Proto auswerten.
TRUST_PROXY = env_bool("TRUST_PROXY")
# Session-Cookie nur über HTTPS senden (wird bei HTTPS-Aufrufen automatisch gesetzt).
COOKIE_SECURE = env_bool("COOKIE_SECURE")
