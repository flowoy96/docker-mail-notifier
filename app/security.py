"""Passwort-Hashing, Sitzungen, Login-Bremse und Verschlüsselung gespeicherter Geheimnisse."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .db import Database

SESSION_COOKIE = "dmn_session"
SESSION_TTL = 12 * 3600
SESSION_TTL_REMEMBER = 30 * 86400
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=256 * n * r, dklen=32
    )


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


# Wird geprüft, wenn es den Benutzer nicht gibt – so dauert die Antwort gleich lang.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


class SecretBox:
    """Verschlüsselt Werte (SMTP-Passwort) vor dem Speichern in der Datenbank.

    Der Schlüssel stammt aus SECRET_KEY. Fehlt die Variable, wird ein Schlüssel
    erzeugt und neben der Datenbank abgelegt – das schützt dann nur noch davor,
    dass das Passwort im Klartext in der Datenbank steht.
    """

    def __init__(self, data_dir: Path, secret_key: str = ""):
        if secret_key:
            raw = hashlib.sha256(b"docker-mail-notifier:v1:" + secret_key.encode("utf-8")).digest()
            self.source = "env"
        else:
            key_file = data_dir / "secret.key"
            if key_file.exists():
                raw = base64.urlsafe_b64decode(key_file.read_text().strip())
            else:
                raw = os.urandom(32)
                data_dir.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(key_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as fh:
                    fh.write(base64.urlsafe_b64encode(raw).decode("ascii"))
            self.source = "file"
        self._fernet = Fernet(base64.urlsafe_b64encode(raw))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str | None:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None


class LoginLimiter:
    """Sperrt eine IP nach zu vielen Fehlversuchen vorübergehend."""

    MAX_FAILURES = 5
    WINDOW = 15 * 60

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}

    def _recent(self, ip: str) -> list[float]:
        cutoff = time.monotonic() - self.WINDOW
        recent = [t for t in self._failures.get(ip, []) if t > cutoff]
        if recent:
            self._failures[ip] = recent
        else:
            self._failures.pop(ip, None)
        return recent

    def blocked_for(self, ip: str) -> float:
        recent = self._recent(ip)
        if len(recent) < self.MAX_FAILURES:
            return 0.0
        return max(0.0, recent[0] + self.WINDOW - time.monotonic())

    def fail(self, ip: str) -> None:
        self._failures.setdefault(ip, []).append(time.monotonic())

    def reset(self, ip: str) -> None:
        self._failures.pop(ip, None)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Database, user_id: int, remember: bool) -> tuple[str, int]:
    """Legt eine Sitzung an und gibt (Token, Lebensdauer in Sekunden) zurück."""
    token = secrets.token_urlsafe(32)
    ttl = SESSION_TTL_REMEMBER if remember else SESSION_TTL
    now = int(time.time())
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), user_id, now, now + ttl),
    )
    return token, ttl


def session_user(db: Database, token: str | None) -> dict | None:
    if not token:
        return None
    return db.one(
        "SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ?",
        (_token_hash(token), int(time.time())),
    )


def delete_session(db: Database, token: str | None) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def delete_user_sessions(db: Database, user_id: int) -> None:
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def create_user(db: Database, username: str, password: str) -> int:
    cur = db.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, hash_password(password), int(time.time())),
    )
    return int(cur.lastrowid)
