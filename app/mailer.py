"""E-Mail-Versand per SMTP: Warteschlange mit Wiederholungen und die Mail-Vorlagen."""
from __future__ import annotations

import asyncio
import html
import logging
import smtplib
import socket
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .events import EVENT_TYPES, explain_exit_code

log = logging.getLogger("dmn.mailer")

RETRY_DELAYS = (20, 120)  # Sekunden bis zum 2. und 3. Versuch
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


class MailError(Exception):
    pass


def describe_error(exc: Exception) -> str:
    """Macht aus SMTP-/Netzwerkfehlern eine verständliche Meldung."""
    if isinstance(exc, MailError):
        return str(exc)
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "Anmeldung am SMTP-Server fehlgeschlagen – Benutzername und Passwort prüfen."
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return f"Der SMTP-Server unterstützt das nicht: {exc}"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "Der SMTP-Server hat die Empfängeradresse abgelehnt."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "Der SMTP-Server hat die Absenderadresse abgelehnt."
    if isinstance(exc, smtplib.SMTPResponseException):
        message = exc.smtp_error.decode("utf-8", "replace") if isinstance(exc.smtp_error, bytes) else exc.smtp_error
        return f"SMTP-Fehler {exc.smtp_code}: {message}"
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return "Der SMTP-Server hat die Verbindung getrennt – passen Port und Verschlüsselung zusammen?"
    if isinstance(exc, ssl.SSLCertVerificationError):
        return f"Das TLS-Zertifikat des Servers ist ungültig: {exc.verify_message}"
    if isinstance(exc, ssl.SSLError):
        return "TLS-Fehler – passen Port und Verschlüsselung zusammen?"
    if isinstance(exc, socket.gaierror):
        return "Der SMTP-Server wurde nicht gefunden (DNS)."
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "Zeitüberschreitung beim Verbinden mit dem SMTP-Server."
    if isinstance(exc, ConnectionRefusedError):
        return "Verbindung abgelehnt – Server und Port prüfen."
    return str(exc) or type(exc).__name__


def _format_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().strftime("%d.%m.%Y, %H:%M:%S Uhr (%Z)")


def _layout(color: str, badge: str, title: str, intro: str, rows: list[tuple[str, str]],
            logs: str, footer: str) -> str:
    e = html.escape
    row_html = "".join(
        f'<tr><td style="padding:10px 0;border-top:1px solid #e5e5ea;color:#6e6e73;'
        f'font-size:14px;width:38%;vertical-align:top">{e(label)}</td>'
        f'<td style="padding:10px 0;border-top:1px solid #e5e5ea;color:#1d1d1f;'
        f'font-size:14px;word-break:break-word">{e(value)}</td></tr>'
        for label, value in rows
    )
    logs_html = ""
    if logs:
        logs_html = (
            '<p style="margin:24px 0 8px;color:#6e6e73;font-size:13px;font-weight:600;'
            'text-transform:uppercase;letter-spacing:.04em">Letzte Log-Zeilen</p>'
            '<pre style="margin:0;padding:14px;background:#f5f5f7;border-radius:12px;color:#1d1d1f;'
            "font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
            f'white-space:pre-wrap;word-break:break-word">{e(logs)}</pre>'
        )
    return (
        '<!DOCTYPE html><html lang="de"><body style="margin:0;padding:0;background:#f5f5f7">'
        f'<div style="padding:32px 16px;background:#f5f5f7;font-family:{_FONT}">'
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
        'style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:18px">'
        '<tr><td style="padding:28px">'
        f'<span style="display:inline-block;padding:5px 12px;border-radius:999px;background:{color};'
        f'color:#ffffff;font-size:13px;font-weight:600">{e(badge)}</span>'
        f'<h1 style="margin:16px 0 6px;color:#1d1d1f;font-size:24px;line-height:1.2;'
        f'font-weight:700;word-break:break-word">{e(title)}</h1>'
        f'<p style="margin:0 0 20px;color:#6e6e73;font-size:15px;line-height:1.45">{e(intro)}</p>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">{row_html}</table>'
        f"{logs_html}"
        "</td></tr></table>"
        f'<p style="margin:16px 0 0;text-align:center;color:#86868b;font-size:12px">{e(footer)}</p>'
        "</div></body></html>"
    )


class Mailer:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings
        self._queue: asyncio.Queue = asyncio.Queue()
        self._tasks: set[asyncio.Task] = set()

    # -- Nachricht bauen -----------------------------------------------------

    def _base_message(self, subject: str, recipients: list[str]) -> EmailMessage:
        values = self.settings.all()
        sender = self.settings.sender()
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((values["smtp_from_name"], sender))
        message["To"] = ", ".join(recipients)
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2] or None)
        message["Auto-Submitted"] = "auto-generated"
        message["X-Mailer"] = "Docker Mail Notifier"
        return message

    def build_event_message(self, event: dict) -> EmailMessage:
        values = self.settings.all()
        meta = EVENT_TYPES[event["type"]]
        host = values["host_label"]
        code = event["exit_code"]

        subject = f'{meta["emoji"]} {event["container_name"]}: {meta["label"]}'
        if code is not None and event["type"] == "crash":
            subject += f" (Exit-Code {code})"
        if host:
            subject = f"[{host}] {subject}"

        rows = [("Container", event["container_name"])]
        if event["image"]:
            rows.append(("Image", event["image"]))
        if event["project"]:
            rows.append(("Compose-Projekt", event["project"]))
        if host:
            rows.append(("Host", host))
        rows.append(("Zeitpunkt", _format_time(event["ts"])))
        if code is not None:
            explanation = explain_exit_code(code)
            rows.append(("Exit-Code", f"{code} – {explanation}" if explanation else str(code)))
        if event["detail"]:
            rows.append(("Details", event["detail"]))
        rows.append(("Container-ID", event["container_id"][:12]))

        message = self._base_message(subject, values["recipients"])
        plain = [f'{meta["label"]}: {event["container_name"]}', "", meta["text"], ""]
        plain += [f"{label}: {value}" for label, value in rows]
        if event["logs"]:
            plain += ["", "Letzte Log-Zeilen:", event["logs"]]
        message.set_content("\n".join(plain))
        footer = "Gesendet von Docker Mail Notifier" + (f" auf {host}" if host else "")
        message.add_alternative(
            _layout(meta["color"], meta["label"], event["container_name"], meta["text"],
                    rows, event["logs"], footer),
            subtype="html",
        )
        return message

    def build_test_message(self, recipients: list[str]) -> EmailMessage:
        values = self.settings.all()
        host = values["host_label"]
        subject = "✅ Testnachricht von Docker Mail Notifier"
        if host:
            subject = f"[{host}] {subject}"
        intro = "Der E-Mail-Versand ist korrekt eingerichtet. Ab jetzt wirst du über Ereignisse deiner Container informiert."
        rows = [("SMTP-Server", f'{values["smtp_host"]}:{values["smtp_port"]}'),
                ("Zeitpunkt", _format_time(datetime.now().timestamp()))]
        message = self._base_message(subject, recipients)
        message.set_content("Es funktioniert!\n\n" + intro)
        message.add_alternative(
            _layout("#34c759", "Test erfolgreich", "Es funktioniert!", intro, rows, "",
                    "Gesendet von Docker Mail Notifier"),
            subtype="html",
        )
        return message

    # -- Senden --------------------------------------------------------------

    def _send_sync(self, message: EmailMessage) -> None:
        values = self.settings.all()
        if not values["smtp_host"]:
            raise MailError("Es ist kein SMTP-Server eingetragen.")
        if not self.settings.sender():
            raise MailError("Es ist keine Absenderadresse eingetragen.")
        context = ssl.create_default_context()
        if not values["smtp_verify_tls"]:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        host, port = values["smtp_host"], values["smtp_port"]
        if values["smtp_security"] == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        with server:
            server.ehlo()
            if values["smtp_security"] == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if values["smtp_user"]:
                server.login(values["smtp_user"], self.settings.smtp_password())
            server.send_message(message)

    async def send(self, message: EmailMessage) -> None:
        await asyncio.to_thread(self._send_sync, message)

    async def send_test(self, recipients: list[str]) -> None:
        await self.send(self.build_test_message(recipients))

    # -- Warteschlange -------------------------------------------------------

    def enqueue(self, event_id: int, attempt: int = 0) -> None:
        self._queue.put_nowait((event_id, attempt))

    async def run(self) -> None:
        while True:
            event_id, attempt = await self._queue.get()
            event = self.db.one("SELECT * FROM events WHERE id = ?", (event_id,))
            if not event:
                continue
            try:
                if not self.settings.all()["recipients"]:
                    raise MailError("Es ist kein Empfänger eingetragen.")
                await self.send(self.build_event_message(event))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = describe_error(exc)
                if attempt < len(RETRY_DELAYS):
                    log.warning("Mail für Ereignis %s fehlgeschlagen (%s) – neuer Versuch folgt",
                                event_id, error)
                    self._set_status(event_id, "pending", error)
                    self._retry_later(event_id, attempt)
                else:
                    log.error("Mail für Ereignis %s endgültig fehlgeschlagen: %s", event_id, error)
                    self._set_status(event_id, "failed", error)
            else:
                self._set_status(event_id, "sent", "")

    def _set_status(self, event_id: int, status: str, error: str) -> None:
        self.db.execute("UPDATE events SET mail_status = ?, mail_error = ? WHERE id = ?",
                        (status, error[:500], event_id))

    def _retry_later(self, event_id: int, attempt: int) -> None:
        async def later() -> None:
            await asyncio.sleep(RETRY_DELAYS[attempt])
            self.enqueue(event_id, attempt + 1)

        task = asyncio.ensure_future(later())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
