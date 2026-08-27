"""Shared test fixtures. Unit tests run fully offline; tests marked
``integration`` need a live lab cluster and skip themselves otherwise."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

LABS_ROOT = Path(__file__).resolve().parents[1]
# Make `acme` and the data generator importable without an install step.
sys.path.insert(0, str(LABS_ROOT / "src"))
sys.path.insert(0, str(LABS_ROOT / "data"))


def _cluster_reachable() -> bool:
    try:
        import httpx

        resp = httpx.get("http://localhost:8080/v1/.well-known/ready", timeout=2.0)
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False
    return resp.status_code == 200


@pytest.fixture(scope="session")
def cluster() -> None:
    """Skip integration tests when no cluster is reachable."""
    if not _cluster_reachable():
        pytest.skip("lab cluster not reachable on localhost:8080 - run `make up`")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-attach the cluster fixture requirement to integration tests."""
    for item in items:
        if item.get_closest_marker("integration"):
            item.fixturenames.append("cluster")  # type: ignore[attr-defined]
