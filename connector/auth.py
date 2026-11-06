"""OAuth Client Credentials da External Client App."""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

from .config import SalesforceConfig
from .transport import Transport, TransportError


class AuthError(Exception):
    """Mensagem sem segredos."""


@dataclass
class Token:
    access_token: str = field(repr=False)
    instance_url: str = ""


def get_token(cfg: SalesforceConfig, transport: Transport) -> Token:
    form = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cfg.client_id,
                                   "client_secret": cfg.client_secret}).encode()
    try:
        resp = transport.request("POST", f"{cfg.my_domain}/services/oauth2/token",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"},
                                 body=form, timeout=cfg.rest_timeout_seconds)
    except TransportError as e:
        raise AuthError(f"failed to obtain a token: {e}") from e
    if not resp.ok or not isinstance(resp.body, dict) or not resp.body.get("access_token"):
        code = resp.body.get("error") if isinstance(resp.body, dict) else None
        raise AuthError(f"OAuth recusado (HTTP {resp.status}, error={code})")
    return Token(resp.body["access_token"], resp.body.get("instance_url", cfg.my_domain))
