"""Wartungsbefehle, z. B.  docker exec docker-mail-notifier python -m app.cli reset-admin"""
from __future__ import annotations

import sys

from . import config
from .db import Database


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "reset-admin":
        db = Database(config.DATA_DIR / "notifier.db")
        db.execute("DELETE FROM sessions")
        db.execute("DELETE FROM users")
        print("Admin-Konto gelöscht. Beim nächsten Aufruf der Weboberfläche kann ein neues angelegt werden.")
        return 0
    print("Verwendung: python -m app.cli reset-admin")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
