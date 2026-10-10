"""Web-Anwendung: JSON-API und Auslieferung der Oberfläche."""
from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import math
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__, config, security
from .db import Database
from .docker_client import DockerClient
from .events import EVENT_TYPES, explain_exit_code
from .mailer import Mailer, describe_error
from .monitor import IGNORE_LABEL, Monitor
from .settings import Settings, SettingsError, parse_recipients

log = logging.getLogger("dmn.web")
STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace("{{v}}", __version__)

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


class Services:
    def __init__(self) -> None:
        self.db = Database(config.DATA_DIR / "notifier.db")
        self.box = security.SecretBox(config.DATA_DIR, config.SECRET_KEY)
        self.settings = Settings(self.db, self.box)
        self.docker = DockerClient(config.DOCKER_HOST)
        self.mailer = Mailer(self.db, self.settings)
        self.monitor = Monitor(self.docker, self.db, self.settings, self.mailer)
        self.limiter = security.LoginLimiter()

    def has_users(self) -> bool:
        return bool(self.db.scalar("SELECT COUNT(*) FROM users"))

    def cleanup(self) -> None:
        now = int(time.time())
        self.db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        days = self.settings.all()["retention_days"]
        if days:
            self.db.execute("DELETE FROM events WHERE ts < ?", (now - days * 86400,))


async def _housekeeping(svc: Services) -> None:
    while True:
        try:
            svc.cleanup()
        except Exception:
            log.exception("Aufräumen fehlgeschlagen")
        await asyncio.sleep(3600)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    svc = Services()
    app.state.svc = svc
    if not svc.has_users() and config.ADMIN_PASSWORD:
        if len(config.ADMIN_PASSWORD) < security.MIN_PASSWORD_LENGTH:
            raise SystemExit(f"ADMIN_PASSWORD braucht mindestens {security.MIN_PASSWORD_LENGTH} Zeichen.")
        security.create_user(svc.db, config.ADMIN_USER, config.ADMIN_PASSWORD)
        log.info("Admin-Konto „%s“ aus ADMIN_PASSWORD angelegt", config.ADMIN_USER)
    # Mails, die beim letzten Beenden noch in der Warteschlange hingen.
    svc.db.execute(
        "UPDATE events SET mail_status = 'failed', mail_error = ? WHERE mail_status = 'pending'",
        ("Versand durch Neustart des Notifiers abgebrochen.",),
    )
    if svc.box.source == "file":
        log.info("SECRET_KEY ist nicht gesetzt – Schlüssel liegt in %s", config.DATA_DIR / "secret.key")
    log.info("Docker Mail Notifier %s läuft auf Port %s", __version__, config.PORT)
    tasks = [
        asyncio.create_task(svc.monitor.run()),
        asyncio.create_task(svc.mailer.run()),
        asyncio.create_task(_housekeeping(svc)),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await svc.docker.close()
        svc.db.close()


# -- Hilfsfunktionen ---------------------------------------------------------


def _svc(request: Request) -> Services:
    return request.app.state.svc


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        raise ApiError(400, "Ungültige Anfrage.") from None
    if not isinstance(data, dict):
        raise ApiError(400, "Ungültige Anfrage.")
    return data


def _set_session(response: Response, request: Request, user_id: int, remember: bool) -> None:
    token, ttl = security.create_session(_svc(request).db, user_id, remember)
    response.set_cookie(
        security.SESSION_COOKIE,
        token,
        max_age=ttl if remember else None,
        httponly=True,
        samesite="strict",
        secure=config.COOKIE_SECURE or request.url.scheme == "https",
        path="/",
    )


def _check_new_password(password: str) -> None:
    if len(password) < security.MIN_PASSWORD_LENGTH:
        raise ApiError(400, f"Das Passwort braucht mindestens {security.MIN_PASSWORD_LENGTH} Zeichen.")
    if len(password) > security.MAX_PASSWORD_LENGTH:
        raise ApiError(400, "Das Passwort ist zu lang.")


def endpoint(auth: bool = True):
    """Fehlerbehandlung, CSRF-Schutz und Login-Prüfung für API-Routen."""

    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(request: Request) -> Response:
            try:
                # Der eigene Header erzwingt bei fremden Seiten einen CORS-Preflight,
                # der scheitert – zusammen mit SameSite=Strict der CSRF-Schutz.
                if request.method not in ("GET", "HEAD") and request.headers.get("x-requested-with") != "dmn":
                    raise ApiError(403, "Anfrage abgelehnt.")
                if auth:
                    user = security.session_user(_svc(request).db, request.cookies.get(security.SESSION_COOKIE))
                    if not user:
                        raise ApiError(401, "Nicht angemeldet.")
                    request.state.user = user
                response = await handler(request)
            except ApiError as exc:
                response = JSONResponse({"error": exc.message}, status_code=exc.status)
            except SettingsError as exc:
                response = JSONResponse({"error": str(exc)}, status_code=400)
            response.headers["Cache-Control"] = "no-store"
            return response

        return wrapper

    return decorator


# -- Anmeldung ---------------------------------------------------------------


@endpoint(auth=False)
async def api_state(request: Request) -> Response:
    svc = _svc(request)
    user = security.session_user(svc.db, request.cookies.get(security.SESSION_COOKIE))
    data: dict = {"setup_required": not svc.has_users(), "authenticated": bool(user)}
    if user:
        data.update(
            username=user["username"],
            version=__version__,
            event_types=[{"key": k, "label": m["label"], "hint": m["hint"]} for k, m in EVENT_TYPES.items()],
        )
    return JSONResponse(data)


@endpoint(auth=False)
async def api_setup(request: Request) -> Response:
    svc = _svc(request)
    if svc.has_users():
        raise ApiError(409, "Die Einrichtung ist bereits abgeschlossen.")
    data = await _body(request)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not 2 <= len(username) <= 64 or not username.isprintable():
        raise ApiError(400, "Der Benutzername braucht 2 bis 64 Zeichen.")
    _check_new_password(password)
    password_hash = await asyncio.to_thread(security.hash_password, password)
    if svc.has_users():  # jemand war währenddessen schneller
        raise ApiError(409, "Die Einrichtung ist bereits abgeschlossen.")
    cursor = svc.db.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, password_hash, int(time.time())),
    )
    log.info("Admin-Konto „%s“ über die Weboberfläche angelegt", username)
    response = JSONResponse({"ok": True})
    _set_session(response, request, int(cursor.lastrowid), remember=False)
    return response


@endpoint(auth=False)
async def api_login(request: Request) -> Response:
    svc = _svc(request)
    ip = _client_ip(request)
    wait = svc.limiter.blocked_for(ip)
    if wait:
        minutes = max(1, math.ceil(wait / 60))
        raise ApiError(429, f"Zu viele Fehlversuche. Bitte in {minutes} Minuten erneut versuchen.")
    data = await _body(request)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))[: security.MAX_PASSWORD_LENGTH]
    user = svc.db.one("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
    valid = await asyncio.to_thread(
        security.verify_password, password, user["password_hash"] if user else security.DUMMY_HASH
    )
    if not user or not valid:
        svc.limiter.fail(ip)
        log.warning("Fehlgeschlagene Anmeldung von %s", ip)
        raise ApiError(401, "Benutzername oder Passwort ist falsch.")
    svc.limiter.reset(ip)
    response = JSONResponse({"ok": True})
    _set_session(response, request, user["id"], remember=bool(data.get("remember")))
    return response


@endpoint()
async def api_logout(request: Request) -> Response:
    security.delete_session(_svc(request).db, request.cookies.get(security.SESSION_COOKIE))
    response = JSONResponse({"ok": True})
    response.delete_cookie(security.SESSION_COOKIE, path="/")
    return response


@endpoint()
async def api_password(request: Request) -> Response:
    svc = _svc(request)
    data = await _body(request)
    new = str(data.get("new", ""))
    _check_new_password(new)
    user = svc.db.one("SELECT id, password_hash FROM users WHERE id = ?", (request.state.user["id"],))
    current = str(data.get("current", ""))[: security.MAX_PASSWORD_LENGTH]
    if not user or not await asyncio.to_thread(security.verify_password, current, user["password_hash"]):
        raise ApiError(400, "Das aktuelle Passwort ist falsch.")
    password_hash = await asyncio.to_thread(security.hash_password, new)
    svc.db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user["id"]))
    # Alle Geräte abmelden und dieses neu anmelden.
    security.delete_user_sessions(svc.db, user["id"])
    response = JSONResponse({"ok": True})
    _set_session(response, request, user["id"], remember=False)
    return response


# -- Übersicht, Container, Verlauf -------------------------------------------

_EVENT_COLUMNS = "id, ts, type, container_name, image, project, exit_code, detail, mail_status"


def _health(status: str) -> str:
    if "(unhealthy)" in status:
        return "unhealthy"
    if "(healthy)" in status:
        return "healthy"
    if "(health: starting)" in status:
        return "starting"
    return ""


async def _containers(svc: Services) -> list[dict]:
    muted = set(svc.settings.all()["muted"])
    result = []
    for item in await svc.docker.list_containers():
        names = item.get("Names") or []
        name = names[0].lstrip("/") if names else item.get("Id", "")[:12]
        labels = item.get("Labels") or {}
        status = item.get("Status", "")
        result.append({
            "id": item.get("Id", "")[:12],
            "name": name,
            "image": item.get("Image", ""),
            "state": item.get("State", ""),
            "status": status,
            "health": _health(status),
            "project": labels.get("com.docker.compose.project", ""),
            "muted": name in muted,
            "label_muted": str(labels.get(IGNORE_LABEL, "")).lower() in ("1", "true", "yes"),
        })
    result.sort(key=lambda c: (c["state"] != "running", c["name"].lower()))
    return result


@endpoint()
async def api_overview(request: Request) -> Response:
    svc = _svc(request)
    containers: list[dict] = []
    connected = svc.monitor.connected
    if connected:
        try:
            containers = await _containers(svc)
        except Exception:
            connected = False
    since = int(time.time()) - 86400
    values = svc.settings.all()
    return JSONResponse({
        "docker": {
            "connected": connected,
            "version": svc.monitor.docker_version,
            "error": "" if connected else svc.monitor.error,
        },
        "counts": {
            "running": sum(1 for c in containers if c["state"] == "running"),
            "stopped": sum(1 for c in containers if c["state"] != "running"),
            "unhealthy": sum(1 for c in containers if c["health"] == "unhealthy"),
            "total": len(containers),
            "events_24h": svc.db.scalar("SELECT COUNT(*) FROM events WHERE ts >= ?", (since,)),
            "problems_24h": svc.db.scalar(
                "SELECT COUNT(*) FROM events WHERE ts >= ? AND type IN ('crash', 'oom', 'unhealthy')", (since,)
            ),
            "mails_24h": svc.db.scalar(
                "SELECT COUNT(*) FROM events WHERE ts >= ? AND mail_status = 'sent'", (since,)
            ),
        },
        "mail": {
            "ready": svc.settings.mail_ready(),
            "enabled": values["notifications_enabled"],
            "recipients": values["recipients"],
        },
        "recent": svc.db.query(f"SELECT {_EVENT_COLUMNS} FROM events ORDER BY id DESC LIMIT 6"),
    })


@endpoint()
async def api_containers(request: Request) -> Response:
    svc = _svc(request)
    try:
        return JSONResponse({"containers": await _containers(svc)})
    except Exception as exc:
        raise ApiError(503, f"Docker ist nicht erreichbar: {exc or type(exc).__name__}") from None


@endpoint()
async def api_container_mute(request: Request) -> Response:
    data = await _body(request)
    name = str(data.get("name", "")).strip()
    if not name:
        raise ApiError(400, "Containername fehlt.")
    _svc(request).settings.set_muted(name, bool(data.get("muted")))
    return JSONResponse({"ok": True})


@endpoint()
async def api_events(request: Request) -> Response:
    svc = _svc(request)
    params = request.query_params
    where, args = [], []
    types = [t for t in params.get("types", "").split(",") if t in EVENT_TYPES]
    if types:
        where.append(f"type IN ({','.join('?' * len(types))})")
        args += types
    query = params.get("q", "").strip()[:100]
    if query:
        like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(container_name LIKE ? ESCAPE '\\' OR image LIKE ? ESCAPE '\\')")
        args += [like, like]
    try:
        before = int(params.get("before", "0"))
        limit = max(1, min(200, int(params.get("limit", "50"))))
    except ValueError:
        raise ApiError(400, "Ungültige Anfrage.") from None
    if before > 0:
        where.append("id < ?")
        args.append(before)
    sql = f"SELECT {_EVENT_COLUMNS} FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = svc.db.query(sql + " ORDER BY id DESC LIMIT ?", tuple(args + [limit + 1]))
    return JSONResponse({"events": rows[:limit], "has_more": len(rows) > limit})


@endpoint()
async def api_events_clear(request: Request) -> Response:
    _svc(request).db.execute("DELETE FROM events")
    return JSONResponse({"ok": True})


def _event_or_404(request: Request) -> dict:
    event = _svc(request).db.one("SELECT * FROM events WHERE id = ?", (request.path_params["id"],))
    if not event:
        raise ApiError(404, "Ereignis nicht gefunden.")
    return event


@endpoint()
async def api_event(request: Request) -> Response:
    event = _event_or_404(request)
    event["exit_code_text"] = explain_exit_code(event["exit_code"])
    return JSONResponse(event)


@endpoint()
async def api_event_resend(request: Request) -> Response:
    svc = _svc(request)
    event = _event_or_404(request)
    if not svc.settings.mail_ready():
        raise ApiError(400, "Der E-Mail-Versand ist noch nicht vollständig eingerichtet.")
    try:
        await svc.mailer.send(svc.mailer.build_event_message(event))
    except Exception as exc:
        raise ApiError(502, describe_error(exc)) from None
    svc.db.execute("UPDATE events SET mail_status = 'sent', mail_error = '' WHERE id = ?", (event["id"],))
    return JSONResponse({"ok": True})


# -- Einstellungen -----------------------------------------------------------


@endpoint()
async def api_settings_get(request: Request) -> Response:
    return JSONResponse(_svc(request).settings.public())


@endpoint()
async def api_settings_put(request: Request) -> Response:
    svc = _svc(request)
    svc.settings.update(await _body(request))
    return JSONResponse(svc.settings.public())


@endpoint()
async def api_test_mail(request: Request) -> Response:
    svc = _svc(request)
    data = await _body(request)
    recipients = parse_recipients(data.get("to") or svc.settings.all()["recipients"])
    if not recipients:
        raise ApiError(400, "Bitte zuerst einen Empfänger eintragen.")
    try:
        await svc.mailer.send_test(recipients)
    except Exception as exc:
        raise ApiError(502, describe_error(exc)) from None
    return JSONResponse({"ok": True, "recipients": recipients})


# -- Seiten ------------------------------------------------------------------


async def index(request: Request) -> Response:
    return HTMLResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})


async def healthz(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


class RevalidatedStaticFiles(StaticFiles):
    """Statische Dateien immer per ETag gegenprüfen – nach einem Update gibt es so keine alten Skripte."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend((k.lower().encode(), v.encode()) for k, v in SECURITY_HEADERS.items())
            await send(message)

        await self.app(scope, receive, send_with_headers)


routes = [
    Route("/", index),
    Route("/healthz", healthz),
    Route("/api/state", api_state),
    Route("/api/setup", api_setup, methods=["POST"]),
    Route("/api/login", api_login, methods=["POST"]),
    Route("/api/logout", api_logout, methods=["POST"]),
    Route("/api/password", api_password, methods=["POST"]),
    Route("/api/overview", api_overview),
    Route("/api/containers", api_containers),
    Route("/api/containers/mute", api_container_mute, methods=["POST"]),
    Route("/api/events", api_events, methods=["GET"]),
    Route("/api/events", api_events_clear, methods=["DELETE"]),
    Route("/api/events/{id:int}", api_event),
    Route("/api/events/{id:int}/resend", api_event_resend, methods=["POST"]),
    Route("/api/settings", api_settings_get, methods=["GET"]),
    Route("/api/settings", api_settings_put, methods=["PUT"]),
    Route("/api/test-mail", api_test_mail, methods=["POST"]),
    Mount("/static", RevalidatedStaticFiles(directory=str(STATIC_DIR)), name="static"),
]

app = Starlette(routes=routes, lifespan=lifespan)
app.add_middleware(SecurityHeaders)
