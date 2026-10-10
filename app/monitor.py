"""Liest Docker-Ereignisse und macht daraus verständliche Meldungen.

Docker meldet nur rohe Zustandswechsel (kill, die, start, restart …). Hier wird
daraus abgeleitet, *warum* etwas passiert ist:

* ``die`` kurz nach einem ``kill``      -> jemand hat den Container gestoppt
* ``die`` mit Exit-Code != 0 ohne kill  -> Absturz
* ``start`` kurz nach einem Absturz bei
  gesetzter Restart-Richtlinie          -> automatischer Neustart
* ``kill, die, start, restart``         -> ein einziger manueller Neustart
* gestoppt und gleich darauf ein neuer
  Container mit demselben Namen         -> neu erstellt (Redeploy eines Stacks)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass

from .events import EVENT_TYPES, LOG_TYPES

log = logging.getLogger("dmn.monitor")

# Signale, die einen Container normalerweise nicht beenden (HUP, USR1, USR2, WINCH).
_HARMLESS_SIGNALS = {"1", "10", "12", "28", "SIGHUP", "SIGUSR1", "SIGUSR2", "SIGWINCH"}
_AUTO_POLICIES = ("always", "unless-stopped", "on-failure")
IGNORE_LABEL = "mail-notifier.ignore"


@dataclass
class ContainerEvent:
    id: str
    name: str
    image: str
    project: str
    ts: float
    label_muted: bool


class Monitor:
    KILL_WINDOW = 90.0  # so lange gilt ein "die" nach einem "kill" als gewollt
    OOM_WINDOW = 30.0
    AUTO_RESTART_WINDOW = 180.0
    RECREATE_WINDOW = 120.0  # so lange gilt ein gleichnamiger neuer Container als Ersatz
    STOP_DELAY = 6.0  # Wartezeit, ob auf ein Stoppen ein Start folgt (= Neustart)
    START_DELAY = 3.0

    def __init__(self, docker, db, settings, mailer):
        self.docker = docker
        self.db = db
        self.settings = settings
        self.mailer = mailer
        self.connected = False
        self.error = ""
        self.docker_version = ""
        self._kills: dict[str, float] = {}
        self._ooms: dict[str, float] = {}
        self._dies: dict[str, tuple[float, str]] = {}
        self._stopped: dict[str, tuple[float, str, str]] = {}  # Name -> (Zeit, ID, Image)
        self._unhealthy: set[str] = set()
        self._pending: dict[str, dict] = {}
        self._throttle: dict[tuple[str, str], float] = {}
        self._seen: deque = deque(maxlen=512)
        self._since: str | None = None
        self._tasks: set[asyncio.Task] = set()

    # -- Verbindung ----------------------------------------------------------

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                version = await self.docker.version()
                self.docker_version = str(version.get("Version", ""))
                await self._sync_health()
                if not self.connected:
                    log.info("Mit Docker %s verbunden (%s)", self.docker_version, self.docker.docker_host)
                self.connected, self.error, backoff = True, "", 1.0
                async for raw in self.docker.events(self._since):
                    try:
                        await self.handle(raw)
                    except Exception:  # ein kaputtes Ereignis darf die Überwachung nicht beenden
                        log.exception("Ereignis konnte nicht verarbeitet werden")
                # Stream wurde sauber geschlossen (z. B. Timeout eines Socket-Proxys):
                # gleich neu verbinden, dank "since" geht dabei nichts verloren.
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.connected or not self.error:
                    log.warning("Keine Verbindung zu Docker: %s", exc or type(exc).__name__)
                self.connected = False
                self.error = str(exc) or type(exc).__name__
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15.0)

    async def _sync_health(self) -> None:
        """Merkt sich bereits kranke Container, damit ihre Genesung gemeldet wird."""
        containers = await self.docker.list_containers()
        self._unhealthy = {c["Id"] for c in containers if "(unhealthy)" in c.get("Status", "")}

    # -- Ereignisse ----------------------------------------------------------

    async def handle(self, raw: dict) -> None:
        if raw.get("Type", "container") != "container":
            return
        action = str(raw.get("Action") or raw.get("status") or "")
        actor = raw.get("Actor") or {}
        attrs = actor.get("Attributes") or {}
        cid = str(actor.get("ID") or raw.get("id") or "")
        if not cid or not action:
            return

        nano = raw.get("timeNano") or int(raw.get("time", time.time())) * 10**9
        key = (nano, cid, action)
        if key in self._seen:
            return
        self._seen.append(key)
        self._since = f"{nano // 10**9}.{nano % 10**9:09d}"

        event = ContainerEvent(
            id=cid,
            name=str(attrs.get("name") or cid[:12]),
            image=str(attrs.get("image") or raw.get("from") or ""),
            project=str(attrs.get("com.docker.compose.project") or ""),
            ts=nano / 1e9,
            label_muted=str(attrs.get(IGNORE_LABEL, "")).lower() in ("1", "true", "yes"),
        )

        if action == "kill":
            if str(attrs.get("signal", "")) not in _HARMLESS_SIGNALS:
                self._kills[cid] = event.ts
        elif action == "oom":
            if event.ts - self._ooms.get(cid, float("-inf")) > self.OOM_WINDOW:
                await self.emit("oom", event)
            self._ooms[cid] = event.ts
        elif action == "die":
            await self._on_die(event, attrs)
        elif action == "start":
            await self._on_start(event)
        elif action == "restart":
            self._cancel_pending(cid)
            self._dies.pop(cid, None)
            await self.emit("restart", event)
        elif action.startswith("health_status"):
            status = action.partition(":")[2].strip()
            if status == "unhealthy" and cid not in self._unhealthy:
                self._unhealthy.add(cid)
                await self.emit("unhealthy", event, detail=await self._health_output(cid))
            elif status == "healthy" and cid in self._unhealthy:
                self._unhealthy.discard(cid)
                await self.emit("healthy", event)
        elif action == "destroy":
            for state in (self._kills, self._ooms, self._dies):
                state.pop(cid, None)
            self._unhealthy.discard(cid)

    async def _on_die(self, event: ContainerEvent, attrs: dict) -> None:
        try:
            code = int(attrs.get("exitCode", ""))
        except (TypeError, ValueError):
            code = None
        self._unhealthy.discard(event.id)
        killed_at = self._kills.pop(event.id, None)

        if killed_at is not None and event.ts - killed_at <= self.KILL_WINDOW:
            # Gewollt beendet. Kurz warten: folgt gleich ein Start, war es ein Neustart.
            self._dies[event.id] = (event.ts, "stop")
            self._stopped = {name: old for name, old in self._stopped.items()
                             if event.ts - old[0] <= self.RECREATE_WINDOW}
            self._stopped[event.name] = (event.ts, event.id, event.image)
            self._cancel_pending(event.id)
            self._pending[event.id] = {"stop": (event, code), "start": None, "timer": None}
            self._schedule_flush(event.id, self.STOP_DELAY)
        elif code == 0:
            self._dies[event.id] = (event.ts, "exit")
            await self.emit("exit", event, exit_code=0)
        else:
            self._dies[event.id] = (event.ts, "crash")
            after_oom = event.ts - self._ooms.get(event.id, float("-inf")) <= self.OOM_WINDOW
            await self.emit("crash", event, exit_code=code, merged=after_oom)

    async def _on_start(self, event: ContainerEvent) -> None:
        replaced = self._stopped.pop(event.name, None)
        pending = self._pending.get(event.id)
        if pending and pending["start"] is None:
            pending["start"] = event
            self._schedule_flush(event.id, self.START_DELAY)
            return

        # Compose/Portainer ersetzen beim Redeploy den Container: der alte wird gestoppt
        # und gelöscht, ein neuer mit gleichem Namen (aber anderer ID) gestartet.
        if replaced and replaced[1] != event.id and event.ts - replaced[0] <= self.RECREATE_WINDOW:
            self._cancel_pending(replaced[1])  # das Stoppen des alten nicht extra melden
            self._dies.pop(replaced[1], None)
            changed = replaced[2] and event.image and replaced[2] != event.image
            await self.emit("recreate", event,
                            detail=f"Image: {replaced[2]} → {event.image}" if changed else "")
            return

        died = self._dies.pop(event.id, None)
        if died and died[1] in ("crash", "exit") and event.ts - died[0] <= self.AUTO_RESTART_WINDOW:
            policy, count = await self._restart_policy(event.id)
            if policy in _AUTO_POLICIES and (policy != "on-failure" or died[1] == "crash"):
                detail = f"Restart-Richtlinie „{policy}“"
                if count:
                    detail += f" · {count}. automatischer Neustart"
                await self.emit("auto_restart", event, detail=detail)
                return
        await self.emit("start", event)

    # -- Stoppen + Starten zu "Neustart" zusammenfassen ------------------------

    def _cancel_pending(self, cid: str) -> None:
        pending = self._pending.pop(cid, None)
        if pending and pending["timer"]:
            pending["timer"].cancel()

    def _schedule_flush(self, cid: str, delay: float) -> None:
        pending = self._pending[cid]
        if pending["timer"]:
            pending["timer"].cancel()
        loop = asyncio.get_running_loop()
        pending["timer"] = loop.call_later(delay, self._spawn_flush, cid, pending)

    def _spawn_flush(self, cid: str, pending: dict) -> None:
        task = asyncio.ensure_future(self._flush(cid, pending))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _flush(self, cid: str, pending: dict) -> None:
        if self._pending.get(cid) is pending:
            del self._pending[cid]
        event, code = pending["stop"]
        await self.emit("stop", event, exit_code=code)
        if pending["start"]:
            self._dies.pop(cid, None)
            await self.emit("start", pending["start"])

    # -- Zusatzinformationen aus Docker ---------------------------------------

    async def _restart_policy(self, cid: str) -> tuple[str, int]:
        try:
            data = await self.docker.inspect(cid)
            policy = ((data.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name") or "no"
            return str(policy), int(data.get("RestartCount") or 0)
        except Exception:
            return "no", 0

    async def _health_output(self, cid: str) -> str:
        try:
            data = await self.docker.inspect(cid)
            entries = (((data.get("State") or {}).get("Health") or {}).get("Log")) or []
            output = str(entries[-1].get("Output", "")).strip() if entries else ""
            return output[:500]
        except Exception:
            return ""

    # -- Speichern und Benachrichtigen ----------------------------------------

    def _mail_status(self, type_: str, event: ContainerEvent, values: dict, merged: bool) -> str:
        if merged:
            return "merged"
        if not values["notifications_enabled"]:
            return "paused"
        if not values["notify"].get(type_):
            return "disabled"
        if event.label_muted or event.name in values["muted"]:
            return "muted"
        if not self.settings.mail_ready():
            return "unconfigured"
        cooldown = values["cooldown_minutes"] * 60
        key = (event.name, type_)
        now = time.monotonic()
        if cooldown and now - self._throttle.get(key, float("-inf")) < cooldown:
            return "throttled"
        self._throttle[key] = now
        return "pending"

    async def emit(self, type_: str, event: ContainerEvent, exit_code: int | None = None,
                   detail: str = "", merged: bool = False) -> int:
        values = self.settings.all()
        logs = ""
        if type_ in LOG_TYPES and values["log_lines"] > 0 and not merged:
            try:
                logs = await self.docker.logs(event.id, values["log_lines"])
            except Exception:
                logs = ""
        status = self._mail_status(type_, event, values, merged)
        cursor = self.db.execute(
            "INSERT INTO events (ts, type, container_id, container_name, image, project, "
            "exit_code, detail, logs, mail_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (int(event.ts), type_, event.id, event.name, event.image, event.project,
             exit_code, detail, logs, status),
        )
        event_id = int(cursor.lastrowid)
        log.info("%s: %s%s [%s]", event.name, EVENT_TYPES[type_]["label"],
                 f" (Exit-Code {exit_code})" if exit_code is not None else "", status)
        if status == "pending":
            self.mailer.enqueue(event_id)
        return event_id
