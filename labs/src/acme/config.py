"""Validated environment loader for the Acme labs.

Single source of configuration truth for every module in this package.
Values come from the process environment, with `labs/.env` (copied from
`.env.example`) loaded automatically when present.

Usage:
    from acme.config import LabSettings, load_settings
    settings = load_settings()
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# labs/ directory (this file lives at labs/src/acme/config.py).
LABS_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = LABS_ROOT / "data"
PLACEHOLDER_PREFIX = "change-me"


class LabSettings(BaseSettings):
    """Typed view of labs/.env - see labs/.env.example for documentation."""

    model_config = SettingsConfigDict(
        env_file=str(LABS_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Weaviate connectivity ---------------------------------------------
    weaviate_http_host: str = Field(default="localhost")
    weaviate_http_port: int = Field(default=8080, ge=1, le=65535)
    weaviate_grpc_host: str = Field(default="localhost")
    weaviate_grpc_port: int = Field(default=50051, ge=1, le=65535)
    weaviate_node_http_ports: str = Field(default="8080,8081,8082")
    weaviate_node_grpc_ports: str = Field(default="50051,50052,50053")
    weaviate_nodes: str = Field(default="weaviate-0,weaviate-1,weaviate-2")

    # --- Auth ----------------------------------------------------------------
    weaviate_api_key_root: str = Field(default=f"{PLACEHOLDER_PREFIX}-root-key")
    weaviate_api_key_readonly: str = Field(default=f"{PLACEHOLDER_PREFIX}-readonly-key")

    # --- Observability ---------------------------------------------------------
    prometheus_url: str = Field(default="http://localhost:9090")
    grafana_url: str = Field(default="http://localhost:3000")

    # --- Expectations -----------------------------------------------------------
    weaviate_expected_version: str = Field(default="1.38.3")

    @field_validator("weaviate_node_http_ports", "weaviate_node_grpc_ports")
    @classmethod
    def _validate_port_list(cls, value: str) -> str:
        ports = [p.strip() for p in value.split(",") if p.strip()]
        if not ports:
            raise ValueError("port list must not be empty")
        for p in ports:
            if not p.isdigit() or not (1 <= int(p) <= 65535):
                raise ValueError(f"invalid port in list: {p!r}")
        return value

    @field_validator("weaviate_nodes")
    @classmethod
    def _validate_nodes(cls, value: str) -> str:
        nodes = [n.strip() for n in value.split(",") if n.strip()]
        if len(nodes) < 1:
            raise ValueError("node list must not be empty")
        return value

    # --- Derived helpers -----------------------------------------------------

    @property
    def node_http_ports(self) -> list[int]:
        return [int(p) for p in self.weaviate_node_http_ports.split(",") if p.strip()]

    @property
    def node_grpc_ports(self) -> list[int]:
        return [int(p) for p in self.weaviate_node_grpc_ports.split(",") if p.strip()]

    @property
    def node_names(self) -> list[str]:
        return [n.strip() for n in self.weaviate_nodes.split(",") if n.strip()]

    @property
    def node_count(self) -> int:
        return len(self.node_names)

    def node_http_urls(self) -> list[str]:
        return [f"http://{self.weaviate_http_host}:{port}" for port in self.node_http_ports]

    def using_placeholder_keys(self) -> bool:
        """True if any API key is still a repo placeholder (refuse to seed)."""
        return self.weaviate_api_key_root.startswith(
            PLACEHOLDER_PREFIX
        ) or self.weaviate_api_key_readonly.startswith(PLACEHOLDER_PREFIX)


@lru_cache(maxsize=1)
def load_settings() -> LabSettings:
    """Load (and cache) settings from environment + labs/.env."""
    return LabSettings()


def main() -> int:
    """`python -m acme.config` - print the effective (redacted) config."""
    s = load_settings()
    redacted = s.model_dump()
    for key in ("weaviate_api_key_root", "weaviate_api_key_readonly"):
        val = redacted[key]
        redacted[key] = val[:4] + "…" if len(val) > 4 else "…"
    width = max(len(k) for k in redacted)
    for key, value in sorted(redacted.items()):
        print(f"{key:<{width}}  {value}")
    if s.using_placeholder_keys():
        print(
            "\nWARNING: placeholder API keys detected - copy .env.example to .env "
            "and rotate WEAVIATE_API_KEY_* before running labs."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
