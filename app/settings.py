"""Einstellungen: in der Datenbank gespeichert, optional durch Umgebungsvariablen überschrieben."""
from __future__ import annotations

import copy
import json
import re

from . import config
from .db import Database
from .events import EVENT_TYPES
from .security import SecretBox

EMAIL_RE = re.compile(r"^[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+$")
SECURITY_MODES = ("starttls", "ssl", "none")
_SECURITY_ALIASES = {"tls": "ssl", "smtps": "ssl", "plain": "none", "off": "none"}

DEFAULTS: dict = {
    "notifications_enabled": True,
    "host_label": "",
    "recipients": [],
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_security": "starttls",
    "smtp_verify_tls": True,
    "smtp_user": "",
    "smtp_from": "",
    "smtp_from_name": "Docker Mail Notifier",
    "notify": {key: meta["default"] for key, meta in EVENT_TYPES.items()},
    "cooldown_minutes": 5,
    "log_lines": 30,
    "retention_days": 90,
    "muted": [],
}

# Einstellung -> Umgebungsvariable. Gesetzte Variablen haben Vorrang und sperren das Feld.
ENV_OVERRIDES = {
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_security": "SMTP_SECURITY",
    "smtp_user": "SMTP_USER",
    "smtp_password": "SMTP_PASSWORD",
    "smtp_from": "SMTP_FROM",
    "recipients": "MAIL_TO",
    "host_label": "HOST_LABEL",
}

_PASSWORD_KEY = "smtp_password_enc"


class SettingsError(ValueError):
    pass


def parse_recipients(value) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,;\s]+", value)
    if not isinstance(value, list):
        raise SettingsError("Empfänger müssen als Liste angegeben werden.")
    result: list[str] = []
    for item in value:
        address = str(item).strip()
        if not address:
            continue
        if len(address) > 254 or not EMAIL_RE.match(address):
            raise SettingsError(f"„{address}“ ist keine gültige E-Mail-Adresse.")
        if address not in result:
            result.append(address)
    if len(result) > 20:
        raise SettingsError("Maximal 20 Empfänger möglich.")
    return result


def _text(value, limit: int, name: str) -> str:
    text = str(value).strip()
    if len(text) > limit or re.search(r"[\x00-\x1f\x7f]", text):
        raise SettingsError(f"Ungültiger Wert für {name}.")
    return text


def _integer(value, low: int, high: int, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{name} muss eine Zahl sein.") from None
    if not low <= number <= high:
        raise SettingsError(f"{name} muss zwischen {low} und {high} liegen.")
    return number


class Settings:
    def __init__(self, db: Database, box: SecretBox):
        self.db = db
        self.box = box
        self._stored: dict | None = None
        self._env = self._read_env()

    # -- Laden ---------------------------------------------------------------

    @staticmethod
    def _read_env() -> dict:
        values: dict = {}
        for key, var in ENV_OVERRIDES.items():
            raw = config.env(var)
            if not raw:
                continue
            try:
                if key == "smtp_port":
                    values[key] = _integer(raw, 1, 65535, var)
                elif key == "smtp_security":
                    mode = _SECURITY_ALIASES.get(raw.lower(), raw.lower())
                    if mode not in SECURITY_MODES:
                        raise SettingsError(f"{var} muss starttls, ssl oder none sein.")
                    values[key] = mode
                elif key == "recipients":
                    values[key] = parse_recipients(raw)
                else:
                    values[key] = raw
            except SettingsError as exc:
                raise SystemExit(f"Ungültige Umgebungsvariable {var}: {exc}") from None
        return values

    def _load(self) -> dict:
        if self._stored is None:
            stored = copy.deepcopy(DEFAULTS)
            for row in self.db.query("SELECT key, value FROM settings"):
                if row["key"] not in DEFAULTS:
                    continue
                try:
                    value = json.loads(row["value"])
                except ValueError:
                    continue
                if row["key"] == "notify" and isinstance(value, dict):
                    stored["notify"].update({k: bool(v) for k, v in value.items() if k in EVENT_TYPES})
                else:
                    stored[row["key"]] = value
            self._stored = stored
        return self._stored

    def _save(self, key: str, value) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
        self._stored = None

    # -- Lesen ---------------------------------------------------------------

    def all(self) -> dict:
        """Wirksame Einstellungen (ohne Passwort)."""
        values = copy.deepcopy(self._load())
        for key, value in self._env.items():
            if key != "smtp_password":
                values[key] = value
        return values

    def locked(self) -> list[str]:
        return sorted(self._env)

    def smtp_password(self) -> str:
        if "smtp_password" in self._env:
            return self._env["smtp_password"]
        token = self.db.scalar("SELECT value FROM settings WHERE key = ?", (_PASSWORD_KEY,))
        if not token:
            return ""
        return self.box.decrypt(token) or ""

    def password_state(self) -> str:
        """'env', 'set', 'unreadable' (Schlüssel geändert) oder 'empty'."""
        if "smtp_password" in self._env:
            return "env"
        token = self.db.scalar("SELECT value FROM settings WHERE key = ?", (_PASSWORD_KEY,))
        if not token:
            return "empty"
        return "set" if self.box.decrypt(token) is not None else "unreadable"

    def sender(self) -> str:
        values = self.all()
        if values["smtp_from"]:
            return values["smtp_from"]
        return values["smtp_user"] if EMAIL_RE.match(values["smtp_user"]) else ""

    def mail_ready(self) -> bool:
        values = self.all()
        return bool(values["smtp_host"] and values["recipients"] and self.sender())

    def public(self) -> dict:
        values = self.all()
        state = self.password_state()
        values.update(
            smtp_password_set=state in ("env", "set"),
            smtp_password_unreadable=state == "unreadable",
            locked=self.locked(),
            secret_source=self.box.source,
            mail_ready=self.mail_ready(),
            sender=self.sender(),
        )
        return values

    # -- Schreiben -----------------------------------------------------------

    def update(self, patch: dict) -> None:
        if not isinstance(patch, dict):
            raise SettingsError("Ungültige Anfrage.")
        clean: dict = {}
        for key, value in patch.items():
            if key in self._env:
                continue  # per Umgebungsvariable festgelegt
            if key == "notifications_enabled" or key == "smtp_verify_tls":
                clean[key] = bool(value)
            elif key == "host_label":
                clean[key] = _text(value, 60, "den Host-Namen")
            elif key == "recipients":
                clean[key] = parse_recipients(value)
            elif key == "smtp_host":
                host = _text(value, 255, "den SMTP-Server")
                if host and not re.match(r"^[A-Za-z0-9._:\-\[\]]+$", host):
                    raise SettingsError("Der SMTP-Server enthält ungültige Zeichen.")
                clean[key] = host
            elif key == "smtp_port":
                clean[key] = _integer(value, 1, 65535, "Der Port")
            elif key == "smtp_security":
                if value not in SECURITY_MODES:
                    raise SettingsError("Unbekannte Verschlüsselungsart.")
                clean[key] = value
            elif key == "smtp_user":
                clean[key] = _text(value, 255, "den Benutzernamen")
            elif key == "smtp_from":
                sender = _text(value, 254, "die Absenderadresse")
                if sender and not EMAIL_RE.match(sender):
                    raise SettingsError("Die Absenderadresse ist keine gültige E-Mail-Adresse.")
                clean[key] = sender
            elif key == "smtp_from_name":
                clean[key] = _text(value, 80, "den Absendernamen")
            elif key == "notify":
                if not isinstance(value, dict):
                    raise SettingsError("Ungültige Anfrage.")
                notify = dict(self._load()["notify"])
                notify.update({k: bool(v) for k, v in value.items() if k in EVENT_TYPES})
                clean[key] = notify
            elif key == "cooldown_minutes":
                clean[key] = _integer(value, 0, 1440, "Die Sperrzeit")
            elif key == "log_lines":
                clean[key] = _integer(value, 0, 200, "Die Anzahl der Log-Zeilen")
            elif key == "retention_days":
                clean[key] = _integer(value, 0, 3650, "Die Aufbewahrungsdauer")
            elif key == "muted":
                if not isinstance(value, list):
                    raise SettingsError("Ungültige Anfrage.")
                clean[key] = sorted({_text(v, 255, "den Containernamen") for v in value if str(v).strip()})

        for key, value in clean.items():
            self._save(key, value)

        if "smtp_password" not in self._env:
            if patch.get("smtp_password_clear"):
                self.db.execute("DELETE FROM settings WHERE key = ?", (_PASSWORD_KEY,))
            password = patch.get("smtp_password")
            if isinstance(password, str) and password:
                if len(password) > 1024:
                    raise SettingsError("Das Passwort ist zu lang.")
                self.db.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (_PASSWORD_KEY, self.box.encrypt(password)),
                )

    def set_muted(self, name: str, muted: bool) -> None:
        names = set(self._load()["muted"])
        if muted:
            names.add(name)
        else:
            names.discard(name)
        self.update({"muted": sorted(names)})
