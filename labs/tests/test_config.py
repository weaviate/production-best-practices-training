"""LabSettings loader tests (offline)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acme.config import LabSettings


def make_settings(**overrides: object) -> LabSettings:
    """Construct settings ignoring any local labs/.env file."""
    return LabSettings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_defaults_are_sane() -> None:
    s = make_settings()
    assert s.weaviate_http_port == 8080
    assert s.weaviate_grpc_port == 50051
    assert s.node_count == 3
    assert s.node_http_ports == [8080, 8081, 8082]
    assert s.node_grpc_ports == [50051, 50052, 50053]
    assert s.node_names == ["weaviate-0", "weaviate-1", "weaviate-2"]
    assert s.weaviate_expected_version == "1.38.3"


def test_placeholder_keys_detected() -> None:
    s = make_settings()
    assert s.using_placeholder_keys() is True
    s2 = make_settings(
        weaviate_api_key_root="a-rotated-key",
        weaviate_api_key_readonly="another-rotated-key",
    )
    assert s2.using_placeholder_keys() is False


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEAVIATE_HTTP_PORT", "18080")
    monkeypatch.setenv("WEAVIATE_NODE_HTTP_PORTS", "18080,18081")
    monkeypatch.setenv("WEAVIATE_NODES", "n0,n1")
    s = make_settings()
    assert s.weaviate_http_port == 18080
    assert s.node_http_ports == [18080, 18081]
    assert s.node_names == ["n0", "n1"]
    assert s.node_count == 2


def test_invalid_port_list_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(weaviate_node_http_ports="8080,notaport")
    with pytest.raises(ValidationError):
        make_settings(weaviate_node_http_ports="0,70000")
    with pytest.raises(ValidationError):
        make_settings(weaviate_node_http_ports="")


def test_node_http_urls() -> None:
    s = make_settings()
    assert s.node_http_urls() == [
        "http://localhost:8080",
        "http://localhost:8081",
        "http://localhost:8082",
    ]
