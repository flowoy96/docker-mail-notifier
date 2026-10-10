"""Minimaler, rein lesender Client für die Docker-Engine-API (Unix-Socket oder TCP)."""
from __future__ import annotations

import json
import re
from typing import AsyncIterator

import httpx

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_MAX_LOG_BYTES = 16 * 1024


def demux_logs(raw: bytes) -> str:
    """Wandelt den Log-Stream von Docker in Text um.

    Ohne TTY liefert Docker Frames mit 8-Byte-Header (Stream-Typ, 3 Nullbytes,
    Länge). Mit TTY kommt der rohe Text.
    """
    if len(raw) >= 8 and raw[0] in (0, 1, 2) and raw[1:4] == b"\x00\x00\x00":
        out = bytearray()
        pos = 0
        while pos + 8 <= len(raw):
            size = int.from_bytes(raw[pos + 4 : pos + 8], "big")
            out += raw[pos + 8 : pos + 8 + size]
            pos += 8 + size
        raw = bytes(out)
    text = raw[-_MAX_LOG_BYTES:].decode("utf-8", "replace")
    text = _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in text if ch in "\n\t" or ch >= " ").strip("\n")


class DockerClient:
    def __init__(self, docker_host: str):
        self.docker_host = docker_host
        timeout = httpx.Timeout(10.0)
        if docker_host.startswith("unix://"):
            transport = httpx.AsyncHTTPTransport(uds=docker_host[len("unix://") :])
            self._client = httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=timeout)
        else:
            base = re.sub(r"^tcp://", "http://", docker_host)
            self._client = httpx.AsyncClient(base_url=base, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **params) -> httpx.Response:
        response = await self._client.get(path, params=params or None)
        response.raise_for_status()
        return response

    async def version(self) -> dict:
        return (await self._get("/version")).json()

    async def list_containers(self) -> list[dict]:
        return (await self._get("/containers/json", all="true")).json()

    async def inspect(self, container_id: str) -> dict:
        return (await self._get(f"/containers/{container_id}/json")).json()

    async def logs(self, container_id: str, tail: int) -> str:
        response = await self._get(
            f"/containers/{container_id}/logs", stdout="true", stderr="true", tail=str(tail)
        )
        return demux_logs(response.content)

    async def events(self, since: str | None = None) -> AsyncIterator[dict]:
        """Streamt Container-Ereignisse; endet, wenn die Verbindung geschlossen wird."""
        params = {"filters": json.dumps({"type": ["container"]})}
        if since:
            params["since"] = since
        timeout = httpx.Timeout(10.0, read=None)
        async with self._client.stream("GET", "/events", params=params, timeout=timeout) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
