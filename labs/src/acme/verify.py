"""Preflight verification for the Acme lab cluster.

Runs a fixed checklist and prints PASS/FAIL per check plus a summary; the
exit code is 0 only when every non-skipped check passes. Participants run
this as ``make verify`` before every lab.

Checks:
  1. /v1/meta version matches the pin (1.38.3)
  2. /v1/.well-known/ready returns 200 on ALL nodes
  3. /v1/nodes reports the expected node count, all HEALTHY
  4. async vector-index queue is drained (seed has settled)
  5. collection counts match the dataset manifest
  6. a sample near_vector query returns k results
  7. Prometheus is up and scraping all Weaviate nodes

Run:  python -m acme.verify [--skip-data] [--mt-count N]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from rich.console import Console
from rich.table import Table

from acme import schema
from acme.client import connect
from acme.config import LabSettings, load_settings
from acme.dataset import load_dataset
from acme.seed import DEFAULT_MT_COUNT

console = Console()

HTTP_TIMEOUT = 10.0  # seconds per REST probe


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _headers(settings: LabSettings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.weaviate_api_key_root}"}


def check_meta_version(settings: LabSettings) -> CheckResult:
    url = f"http://{settings.weaviate_http_host}:{settings.weaviate_http_port}/v1/meta"
    resp = httpx.get(url, headers=_headers(settings), timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    version = str(resp.json().get("version", "unknown"))
    ok = version == settings.weaviate_expected_version
    return CheckResult(
        "server version",
        ok,
        f"got {version}, expected {settings.weaviate_expected_version}",
    )


def check_all_nodes_ready(settings: LabSettings) -> CheckResult:
    statuses: list[str] = []
    all_ok = True
    for url in settings.node_http_urls():
        try:
            resp = httpx.get(f"{url}/v1/.well-known/ready", timeout=HTTP_TIMEOUT)
            ok = resp.status_code == 200
        except httpx.HTTPError as exc:
            ok = False
            statuses.append(f"{url}: {type(exc).__name__}")
        else:
            statuses.append(f"{url}: {resp.status_code}")
        all_ok = all_ok and ok
    return CheckResult("readiness (all nodes)", all_ok, "; ".join(statuses))


def check_node_count(settings: LabSettings) -> CheckResult:
    url = f"http://{settings.weaviate_http_host}:{settings.weaviate_http_port}/v1/nodes"
    resp = httpx.get(url, headers=_headers(settings), timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    nodes = resp.json().get("nodes", [])
    healthy = [n for n in nodes if n.get("status") == "HEALTHY"]
    ok = len(nodes) == settings.node_count and len(healthy) == settings.node_count
    return CheckResult(
        "node count / health",
        ok,
        f"{len(nodes)} nodes ({len(healthy)} HEALTHY), expected {settings.node_count}",
    )


def check_index_queue_drained(settings: LabSettings) -> CheckResult:
    """ASYNC_INDEXING=true means vector-search visibility lags writes; the
    queue must be empty before any benchmark number means anything."""
    url = (
        f"http://{settings.weaviate_http_host}:{settings.weaviate_http_port}"
        "/v1/nodes?output=verbose"
    )
    resp = httpx.get(url, headers=_headers(settings), timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    backlog = 0
    for node in resp.json().get("nodes", []):
        for shard in node.get("shards") or []:
            backlog += int(shard.get("vectorQueueLength", 0) or 0)
    return CheckResult(
        "vector index queue drained",
        backlog == 0,
        f"total queued vectors: {backlog}" + ("" if backlog == 0 else " (wait and re-run verify)"),
    )


def check_collection_counts(settings: LabSettings, mt_count: int) -> CheckResult:
    ds = load_dataset()
    expected = {
        schema.COLLECTION_PRODUCT: ds.count,
        schema.COLLECTION_HFRESH: ds.count,
        schema.COLLECTION_MT: min(mt_count, ds.count),
    }
    details: list[str] = []
    all_ok = True
    with connect(settings) as client:
        for name, want in expected.items():
            if not client.collections.exists(name):
                details.append(f"{name}: MISSING")
                all_ok = False
                continue
            collection = client.collections.use(name)
            if name == schema.COLLECTION_MT:
                got = 0
                for tenant in collection.tenants.get():
                    agg = collection.with_tenant(tenant).aggregate.over_all(total_count=True)
                    got += int(agg.total_count or 0)
            else:
                agg = collection.aggregate.over_all(total_count=True)
                got = int(agg.total_count or 0)
            ok = got == want
            all_ok = all_ok and ok
            details.append(f"{name}: {got}/{want}")
    return CheckResult("collection counts", all_ok, "; ".join(details))


def check_sample_query(settings: LabSettings, k: int = 10) -> CheckResult:
    ds = load_dataset()
    with connect(settings) as client:
        collection = client.collections.use(schema.COLLECTION_PRODUCT)
        result = collection.query.near_vector(
            near_vector=ds.queries[0].tolist(),
            target_vector=schema.VECTOR_NAME,
            limit=k,
        )
    got = len(result.objects)
    return CheckResult("sample query", got == k, f"near_vector returned {got}/{k}")


def check_prometheus(settings: LabSettings) -> CheckResult:
    ready = httpx.get(f"{settings.prometheus_url}/-/ready", timeout=HTTP_TIMEOUT)
    if ready.status_code != 200:
        return CheckResult("prometheus", False, f"/-/ready returned {ready.status_code}")
    resp = httpx.get(
        f"{settings.prometheus_url}/api/v1/query",
        params={"query": 'up{job="weaviate"}'},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json().get("data", {}).get("result", [])
    up = sum(1 for r in results if r.get("value", ["", "0"])[1] == "1")
    ok = up >= settings.node_count
    return CheckResult("prometheus", ok, f"{up}/{settings.node_count} weaviate targets up")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Acme lab cluster.")
    parser.add_argument(
        "--skip-data",
        action="store_true",
        help="skip collection-count and sample-query checks (pre-seed verify)",
    )
    parser.add_argument("--mt-count", type=int, default=DEFAULT_MT_COUNT)
    args = parser.parse_args(argv)

    settings = load_settings()
    checks: list[tuple[str, Callable[[], CheckResult]]] = [
        ("server version", lambda: check_meta_version(settings)),
        ("readiness", lambda: check_all_nodes_ready(settings)),
        ("node count", lambda: check_node_count(settings)),
        ("index queue", lambda: check_index_queue_drained(settings)),
    ]
    if not args.skip_data:
        checks += [
            ("counts", lambda: check_collection_counts(settings, args.mt_count)),
            ("sample query", lambda: check_sample_query(settings)),
        ]
    checks.append(("prometheus", lambda: check_prometheus(settings)))

    results: list[CheckResult] = []
    for label, fn in checks:
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001 - each probe failure is a FAIL row
            results.append(CheckResult(label, False, f"{type(exc).__name__}: {exc}"))

    table = Table(title="Acme preflight")
    table.add_column("check")
    table.add_column("result")
    table.add_column("detail", overflow="fold")
    for r in results:
        table.add_row(
            r.name,
            "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]",
            r.detail,
        )
    console.print(table)

    failed = [r for r in results if not r.passed]
    if failed:
        console.print(
            f"[red bold]{len(failed)}/{len(results)} checks FAILED.[/red bold] "
            "See labs/README.md troubleshooting table."
        )
        return 1
    console.print(f"[green bold]All {len(results)} checks passed.[/green bold]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
