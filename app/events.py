"""Ereignistypen, die erkannt, im Verlauf gespeichert und gemeldet werden."""
from __future__ import annotations

# Reihenfolge = Reihenfolge in den Einstellungen.
EVENT_TYPES: dict[str, dict] = {
    "crash": {
        "label": "Abgestürzt",
        "hint": "Container wurde unerwartet mit Fehlercode beendet",
        "text": "Der Container wurde unerwartet beendet.",
        "emoji": "🔴",
        "color": "#ff3b30",
        "default": True,
    },
    "oom": {
        "label": "Speicherlimit überschritten",
        "hint": "Der Kernel hat einen Prozess wegen Speichermangel beendet (OOM)",
        "text": "Der Kernel hat einen Prozess des Containers wegen Speichermangel beendet (OOM-Kill).",
        "emoji": "🟣",
        "color": "#af52de",
        "default": True,
    },
    "auto_restart": {
        "label": "Automatisch neu gestartet",
        "hint": "Docker hat den Container per Restart-Richtlinie neu gestartet",
        "text": "Docker hat den Container nach dem Beenden automatisch neu gestartet.",
        "emoji": "🟠",
        "color": "#ff9500",
        "default": True,
    },
    "restart": {
        "label": "Manuell neu gestartet",
        "hint": "Neustart über Docker, Portainer oder Compose",
        "text": "Der Container wurde manuell neu gestartet.",
        "emoji": "🔵",
        "color": "#007aff",
        "default": True,
    },
    "unhealthy": {
        "label": "Healthcheck fehlgeschlagen",
        "hint": "Container meldet den Status „unhealthy“",
        "text": "Der Healthcheck des Containers schlägt fehl – er läuft, arbeitet aber nicht korrekt.",
        "emoji": "🟡",
        "color": "#ff2d55",
        "default": True,
    },
    "healthy": {
        "label": "Wieder gesund",
        "hint": "Healthcheck ist nach einem Fehler wieder erfolgreich",
        "text": "Der Healthcheck des Containers ist wieder erfolgreich.",
        "emoji": "🟢",
        "color": "#34c759",
        "default": True,
    },
    "stop": {
        "label": "Gestoppt",
        "hint": "Container wurde manuell gestoppt oder beendet",
        "text": "Der Container wurde gestoppt.",
        "emoji": "⚪",
        "color": "#8e8e93",
        "default": False,
    },
    "exit": {
        "label": "Regulär beendet",
        "hint": "Container hat sich selbst mit Exit-Code 0 beendet",
        "text": "Der Container hat sich regulär beendet (Exit-Code 0).",
        "emoji": "⚪",
        "color": "#5856d6",
        "default": False,
    },
    "start": {
        "label": "Gestartet",
        "hint": "Container wurde gestartet",
        "text": "Der Container wurde gestartet.",
        "emoji": "🟢",
        "color": "#30b0c7",
        "default": False,
    },
}

# Für diese Typen werden die letzten Log-Zeilen des Containers mitgeschickt.
LOG_TYPES = ("crash", "oom", "unhealthy")

_EXIT_CODES = {
    1: "allgemeiner Fehler der Anwendung",
    2: "falsche Verwendung / ungültige Argumente",
    125: "Docker konnte den Container nicht starten",
    126: "Befehl ist nicht ausführbar",
    127: "Befehl nicht gefunden",
    130: "SIGINT – abgebrochen (Strg+C)",
    134: "SIGABRT – Anwendung hat abgebrochen",
    137: "SIGKILL – hart beendet, häufig wegen Speichermangel",
    139: "SIGSEGV – Speicherzugriffsfehler",
    143: "SIGTERM – zum Beenden aufgefordert",
}


def explain_exit_code(code: int | None) -> str:
    if code is None:
        return ""
    if code in _EXIT_CODES:
        return _EXIT_CODES[code]
    if 128 < code < 160:
        return f"durch Signal {code - 128} beendet"
    return ""
