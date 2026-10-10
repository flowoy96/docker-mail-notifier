"""Prüft, dass Docker-Ereignisfolgen richtig gedeutet werden.

Ausführen:  python -m unittest discover -s tests
"""
import asyncio
import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.docker_client import demux_logs
from app.monitor import Monitor
from app.security import SecretBox, hash_password, verify_password
from app.settings import Settings, SettingsError

CID = "c" * 64


class FakeDocker:
    docker_host = "fake"

    def __init__(self, policy="no"):
        self.policy = policy

    async def inspect(self, cid):
        return {"HostConfig": {"RestartPolicy": {"Name": self.policy}}, "RestartCount": 3,
                "State": {"Health": {"Log": [{"Output": "curl: (7) connection refused"}]}}}

    async def logs(self, cid, tail):
        return "Traceback …\nBoom"


class FakeMailer:
    def __init__(self):
        self.queued = []

    def enqueue(self, event_id, attempt=0):
        self.queued.append(event_id)


class MonitorTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)
        self.db = Database(path / "test.db")
        self.settings = Settings(self.db, SecretBox(path))
        self.settings.update({"smtp_host": "smtp.example.com", "smtp_from": "a@example.com",
                              "recipients": "b@example.com", "cooldown_minutes": 0})
        self.mailer = FakeMailer()
        self.docker = FakeDocker()
        self.monitor = Monitor(self.docker, self.db, self.settings, self.mailer)
        self.monitor.STOP_DELAY = 0.15
        self.monitor.START_DELAY = 0.1
        self.clock = 1_700_000_000 * 10**9

    async def asyncTearDown(self):
        self.db.close()
        self.tmp.cleanup()

    async def send(self, action, seconds=1.0, **attrs):
        self.clock += int(seconds * 10**9)
        await self.monitor.handle({
            "Type": "container", "Action": action, "timeNano": self.clock,
            "Actor": {"ID": CID, "Attributes": {"name": "web", "image": "nginx", **attrs}},
        })

    def rows(self):
        return [(r["type"], r["mail_status"]) for r in self.db.query("SELECT * FROM events ORDER BY id")]

    async def test_crash_sends_mail_with_logs(self):
        await self.send("die", exitCode="137")
        self.assertEqual(self.rows(), [("crash", "pending")])
        event = self.db.one("SELECT * FROM events")
        self.assertEqual(event["exit_code"], 137)
        self.assertIn("Boom", event["logs"])
        self.assertEqual(len(self.mailer.queued), 1)

    async def test_crash_then_auto_restart(self):
        self.docker.policy = "unless-stopped"
        await self.send("die", exitCode="1")
        await self.send("start")
        self.assertEqual(self.rows(), [("crash", "pending"), ("auto_restart", "pending")])

    async def test_start_after_crash_without_policy_is_plain_start(self):
        await self.send("die", exitCode="1")
        await self.send("start")
        self.assertEqual(self.rows(), [("crash", "pending"), ("start", "disabled")])

    async def test_manual_stop(self):
        await self.send("kill", signal="15")
        await self.send("die", exitCode="143")
        self.assertEqual(self.rows(), [])  # wartet, ob ein Start folgt
        await asyncio.sleep(0.3)
        self.assertEqual(self.rows(), [("stop", "disabled")])

    async def test_manual_restart_is_one_event(self):
        await self.send("kill", signal="15")
        await self.send("die", exitCode="0")
        await self.send("start", 0.5)
        await self.send("restart", 0.01)
        await asyncio.sleep(0.3)
        self.assertEqual(self.rows(), [("restart", "pending")])

    async def test_stop_then_manual_start(self):
        await self.send("kill", signal="15")
        await self.send("die", exitCode="0")
        await self.send("start")
        await asyncio.sleep(0.3)
        self.assertEqual(self.rows(), [("stop", "disabled"), ("start", "disabled")])

    async def test_harmless_signal_does_not_hide_crash(self):
        await self.send("kill", signal="1")
        await self.send("die", exitCode="2")
        self.assertEqual(self.rows(), [("crash", "pending")])

    async def test_clean_exit(self):
        await self.send("die", exitCode="0")
        self.assertEqual(self.rows(), [("exit", "disabled")])

    async def test_oom_is_reported_once(self):
        await self.send("oom")
        await self.send("die", exitCode="137")
        self.assertEqual(self.rows(), [("oom", "pending"), ("crash", "merged")])

    async def test_health_cycle(self):
        await self.send("health_status: healthy")  # war nie krank -> keine Meldung
        await self.send("health_status: unhealthy")
        await self.send("health_status: unhealthy")
        await self.send("health_status: healthy")
        self.assertEqual(self.rows(), [("unhealthy", "pending"), ("healthy", "pending")])
        self.assertIn("connection refused", self.db.one("SELECT detail FROM events")["detail"])

    async def test_duplicate_event_is_ignored(self):
        await self.send("die", exitCode="1")
        await self.send("die", 0, exitCode="1")
        self.assertEqual(len(self.rows()), 1)

    async def test_cooldown_throttles_second_mail(self):
        self.settings.update({"cooldown_minutes": 5})
        await self.send("die", exitCode="1")
        await self.send("die", exitCode="1")
        self.assertEqual(self.rows(), [("crash", "pending"), ("crash", "throttled")])

    async def test_muted_container_and_label(self):
        self.settings.set_muted("web", True)
        await self.send("die", exitCode="1")
        self.settings.set_muted("web", False)
        await self.send("die", **{"exitCode": "1", "mail-notifier.ignore": "true"})
        self.assertEqual(self.rows(), [("crash", "muted"), ("crash", "muted")])

    async def test_paused_and_unconfigured(self):
        self.settings.update({"notifications_enabled": False})
        await self.send("die", exitCode="1")
        self.settings.update({"notifications_enabled": True, "recipients": ""})
        await self.send("die", exitCode="1")
        self.assertEqual(self.rows(), [("crash", "paused"), ("crash", "unconfigured")])


class HelpersTest(unittest.TestCase):
    def test_password_hash(self):
        stored = hash_password("geheim-1234")
        self.assertTrue(verify_password("geheim-1234", stored))
        self.assertFalse(verify_password("falsch", stored))
        self.assertFalse(verify_password("geheim-1234", "kaputt"))

    def test_secret_box_roundtrip_and_wrong_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = SecretBox(Path(tmp), "schluessel-a")
            token = box.encrypt("smtp-passwort")
            self.assertNotIn("smtp-passwort", token)
            self.assertEqual(box.decrypt(token), "smtp-passwort")
            self.assertIsNone(SecretBox(Path(tmp), "schluessel-b").decrypt(token))

    def test_smtp_password_is_stored_encrypted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            settings = Settings(db, SecretBox(Path(tmp)))
            settings.update({"smtp_password": "streng-geheim"})
            self.assertEqual(settings.smtp_password(), "streng-geheim")
            self.assertNotIn("streng-geheim", str(db.query("SELECT * FROM settings")))
            self.assertNotIn("streng-geheim", str(settings.public()))
            db.close()

    def test_settings_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            settings = Settings(db, SecretBox(Path(tmp)))
            for patch in ({"recipients": "kein-at"}, {"smtp_port": 0}, {"smtp_security": "x"},
                          {"smtp_from": "a@b.de\r\nBcc: x@y.de"}, {"host_label": "a\nb"}):
                with self.assertRaises(SettingsError):
                    settings.update(patch)
            settings.update({"recipients": "a@b.de; c@d.de, a@b.de"})
            self.assertEqual(settings.all()["recipients"], ["a@b.de", "c@d.de"])
            db.close()

    def test_demux_logs(self):
        frame = lambda stream, data: bytes([stream, 0, 0, 0]) + len(data).to_bytes(4, "big") + data
        raw = frame(1, b"hallo\n") + frame(2, b"\x1b[31mfehler\x1b[0m\n")
        self.assertEqual(demux_logs(raw), "hallo\nfehler")
        self.assertEqual(demux_logs(b"tty ausgabe\r\n"), "tty ausgabe")


if __name__ == "__main__":
    unittest.main()
