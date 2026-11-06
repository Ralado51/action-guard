"""Configuracao por variaveis de ambiente. Valores secretos nunca sao versionados nem impressos."""
from __future__ import annotations

import os
from dataclasses import dataclass

AGENT_API_BASE = "https://api.salesforce.com/einstein/ai-agent/v1"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class SalesforceConfig:
    my_domain: str            # SF_LOGIN_URL (My Domain), sem barra final
    api_version: str          # SF_API_VERSION, ex.: "68.0"
    agent_id: str             # SF_AGENT_ID
    client_id: str = ""       # SF_CLIENT_ID
    client_secret: str = ""   # SF_CLIENT_SECRET (nunca em repr/log)
    agent_api_base: str = AGENT_API_BASE
    agent_timeout_seconds: float = 180.0
    rest_timeout_seconds: float = 30.0

    def __repr__(self) -> str:  # evita vazar o segredo em logs/tracebacks
        return (f"SalesforceConfig(my_domain={self.my_domain!r}, api_version={self.api_version!r}, "
                f"agent_id={self.agent_id!r}, client_id={'<set>' if self.client_id else '<empty>'}, "
                f"client_secret={'<set>' if self.client_secret else '<empty>'})")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "SalesforceConfig":
        env = os.environ if env is None else env
        missing = [k for k in ("SF_LOGIN_URL", "SF_API_VERSION", "SF_AGENT_ID", "SF_CLIENT_ID", "SF_CLIENT_SECRET")
                   if not env.get(k)]
        if missing:
            raise ConfigError("missing environment variables: " + ", ".join(missing))
        domain = env["SF_LOGIN_URL"].rstrip("/")
        if not domain.startswith("https://"):
            raise ConfigError("SF_LOGIN_URL must start with https://")
        version = env["SF_API_VERSION"].lstrip("v")
        return cls(my_domain=domain, api_version=version, agent_id=env["SF_AGENT_ID"],
                   client_id=env["SF_CLIENT_ID"], client_secret=env["SF_CLIENT_SECRET"])
