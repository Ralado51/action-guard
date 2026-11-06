"""Configuracao do planner por ambiente. A chave nunca aparece em repr, erros ou logs."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .errors import PlannerError

DEFAULT_BASE_URL = "https://api.vultrinference.com/v1"


@dataclass(frozen=True)
class PlannerConfig:
    api_key: str = field(repr=False)
    model: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 60.0
    max_tokens: int = 2000
    max_calls: int = 2            # orcamento TOTAL de chamadas HTTP por operacao (geracao + correcao + retries)
    retry_backoff_seconds: float = 1.0

    def __repr__(self) -> str:
        return f"PlannerConfig(model={self.model!r}, base_url={self.base_url!r}, api_key=<{'set' if self.api_key else 'empty'}>)"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "PlannerConfig":
        env = os.environ if env is None else env
        missing = [k for k in ("VULTR_INFERENCE_API_KEY", "VULTR_INFERENCE_MODEL") if not env.get(k)]
        if missing:
            raise PlannerError("config", message="Variaveis ausentes: " + ", ".join(missing))
        base = (env.get("VULTR_INFERENCE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        if not base.startswith("https://"):
            raise PlannerError("config", message="VULTR_INFERENCE_BASE_URL deve comecar com https://")
        extra: dict[str, float | int] = {}
        # Modelos com raciocinio gastam tokens antes da resposta; o limite precisa ser ajustavel sem mudar codigo.
        for var, key, kind, lo, hi in (("VULTR_INFERENCE_MAX_TOKENS", "max_tokens", int, 256, 32000),
                                       ("VULTR_INFERENCE_TIMEOUT_SECONDS", "timeout_seconds", float, 5.0, 600.0)):
            raw = env.get(var)
            if raw:
                try:
                    val = kind(raw)
                except ValueError:
                    raise PlannerError("config", message=f"{var} deve ser numerico") from None
                if not lo <= val <= hi:
                    raise PlannerError("config", message=f"{var} fora do intervalo {lo}..{hi}")
                extra[key] = val
        return cls(api_key=env["VULTR_INFERENCE_API_KEY"], model=env["VULTR_INFERENCE_MODEL"], base_url=base, **extra)
