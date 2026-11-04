"""Camada HTTP minima e injetavel. Nao faz retry: quem chama decide."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class TransportError(Exception):
    """Falha sem resposta HTTP utilizavel. `timed_out` indica que o pedido PODE ter chegado ao servidor."""

    def __init__(self, message: str, timed_out: bool = False):
        super().__init__(message)
        self.timed_out = timed_out


@dataclass
class Response:
    status: int
    body: Any  # JSON decodificado, ou texto quando nao for JSON, ou None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Transport(Protocol):
    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None,
                body: bytes | None = None, timeout: float = 30.0) -> Response: ...


class UrllibTransport:
    def request(self, method, url, *, headers=None, body=None, timeout=30.0) -> Response:
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return Response(resp.status, _decode(resp.read()))
        except urllib.error.HTTPError as e:
            return Response(e.code, _decode(e.read()))
        except (socket.timeout, TimeoutError) as e:
            raise TransportError("timeout", timed_out=True) from e
        except urllib.error.URLError as e:
            timed = isinstance(e.reason, (socket.timeout, TimeoutError))
            raise TransportError(f"falha de rede: {type(e.reason).__name__}", timed_out=timed) from e


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return text
