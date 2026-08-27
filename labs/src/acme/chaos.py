"""Lab 3 helper: controlled failure drills against the compose cluster.

  ┌─────────────────────────────────────────────────────────────────────┐
  │ SIMULATION NOTICE: stopping a docker-compose container approximates │
  │ a NODE failure on a single host. It does not reproduce AZ loss,     │
  │ network partitions, or correlated infrastructure failure. See       │
  │ labs/README.md - "what is simulated vs real".                       │
  └─────────────────────────────────────────────────────────────────────┘

Commands (also callable as functions):
  python -m acme.chaos status
  python -m acme.chaos kill weaviate-1
  python -m acme.chaos restore weaviate-1
  python -m acme.chaos write-drill          # ONE/QUORUM/ALL write+read matrix
  python -m acme.chaos convergence          # watch async-replication metrics

Safety rails:
  * only lab node names are accepted;
  * killing a second node while one is already down requires
    ``--allow-quorum-loss`` (that drill is instructor-led);
  * every subprocess call has a timeout.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import uuid as uuidlib
from dataclasses import dataclass
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table

from acme import schema
from acme.client import connect
from acme.config import LABS_ROOT, load_settings

console = Console()

COMPOSE_FILE: Path = LABS_ROOT / "platform" / "docker-compose.yaml"
SUBPROCESS_TIMEOUT = 60  # seconds
DRILL_DOC_TYPE = "chaos-drill"
DRILL_OBJECTS_PER_LEVEL = 20

SIMULATION_BANNER = (
    "[yellow bold]SIMULATION:[/yellow bold] single-host compose node stop ≈ node "
    "failure. It is NOT an AZ outage or a network partition."
)


def _allowed_nodes() -> list[str]:
    return load_settings().node_names


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    if not COMPOSE_FILE.exists():
        raise FileNotFoundError(
            f"compose file not found: {COMPOSE_FILE} - run from the labs checkout"
        )
    env_file = LABS_ROOT / ".env"
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE)]
    if env_file.exists():
        cmd += ["--env-file", str(env_file)]
    cmd += list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT, check=False
    )


def _running_nodes() -> set[str]:
    result = _compose("ps", "--services", "--status", "running")
    services = {s.strip() for s in result.stdout.splitlines() if s.strip()}
    return services.intersection(_allowed_nodes())


def kill_node(name: str, *, allow_quorum_loss: bool = False) -> None:
    """Stop one Weaviate node container (docker compose stop)."""
    nodes = _allowed_nodes()
    if name not in nodes:
        raise ValueError(f"{name!r} is not a lab node; allowed: {', '.join(nodes)}")
    running = _running_nodes()
    if name not in running:
        console.print(f"[yellow]{name} is already stopped.[/yellow]")
        return
    if len(running) < len(nodes) and not allow_quorum_loss:
        # one node already down; stopping another loses RAFT quorum (3 -> 1)
        raise RuntimeError(
            "Another node is already down. Killing a second node loses RAFT "
            "quorum (metadata plane freezes). This drill is instructor-led: "
            "re-run with --allow-quorum-loss if that is intentional."
        )
    console.print(SIMULATION_BANNER)
    console.print(f"[red]Stopping {name}…[/red]")
    result = _compose("stop", "-t", "10", name)
    if result.returncode != 0:
        raise RuntimeError(f"docker compose stop failed: {result.stderr.strip()}")
    console.print(
        f"[red bold]{name} is down.[/red bold] Restore with: "
        f"python -m acme.chaos restore {name}"
    )


def restore_node(name: str) -> None:
    """Start a previously stopped node and wait for readiness."""
    nodes = _allowed_nodes()
    if name not in nodes:
        raise ValueError(f"{name!r} is not a lab node; allowed: {', '.join(nodes)}")
    console.print(f"[green]Starting {name}…[/green]")
    result = _compose("start", name)
    if result.returncode != 0:
        raise RuntimeError(f"docker compose start failed: {result.stderr.strip()}")
    settings = load_settings()
    idx = nodes.index(name)
    url = f"http://{settings.weaviate_http_host}:{settings.node_http_ports[idx]}"
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/v1/.well-known/ready", timeout=3).status_code == 200:
                console.print(
                    f"[green bold]{name} is READY.[/green bold] Now watch "
                    "convergence: python -m acme.chaos convergence"
                )
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise TimeoutError(f"{name} did not become ready within 120s")


def status() -> None:
    running = _running_nodes()
    table = Table(title="lab cluster nodes")
    table.add_column("node")
    table.add_column("container")
    for name in _allowed_nodes():
        state = "[green]running[/green]" if name in running else "[red]stopped[/red]"
        table.add_row(name, state)
    console.print(table)


@dataclass
class DrillOutcome:
    level: str
    write_ok: int
    write_fail: int
    read_ok: int
    read_fail: int
    first_error: str


def write_during_failure() -> list[DrillOutcome]:
    """Attempt writes and reads at ONE / QUORUM / ALL; report per-level outcomes.

    Run this WHILE a node is down (after `chaos kill weaviate-1`) to observe
    the overlap rule with RF=3. Drill objects are tagged doc_type=chaos-drill
    and cleaned up afterwards (make reset also removes them).
    """
    from weaviate.classes.config import ConsistencyLevel
    from weaviate.classes.query import Filter

    console.print(SIMULATION_BANNER)
    levels = [
        ("ONE", ConsistencyLevel.ONE),
        ("QUORUM", ConsistencyLevel.QUORUM),
        ("ALL", ConsistencyLevel.ALL),
    ]
    outcomes: list[DrillOutcome] = []
    with connect() as client:
        base = client.collections.use(schema.COLLECTION_PRODUCT)
        for label, level in levels:
            handle = base.with_consistency_level(consistency_level=level)
            write_ok = write_fail = read_ok = read_fail = 0
            first_error = ""
            drill_uuids: list[str] = []
            for i in range(DRILL_OBJECTS_PER_LEVEL):
                obj_uuid = str(uuidlib.uuid4())
                try:
                    handle.data.insert(
                        properties={
                            "product_id": f"CHAOS-{label}-{i:03d}",
                            "title": f"chaos drill {label} {i}",
                            "description": "consistency drill object - safe to delete",
                            "category": "chaos",
                            "brand": "chaos",
                            "price": 0.0,
                            "tenant": "tenant-000",
                            "doc_type": DRILL_DOC_TYPE,
                            "vec_id": -1,
                        },
                        uuid=obj_uuid,
                        vector={schema.VECTOR_NAME: [0.0625] * schema.VECTOR_DIM},
                    )
                    write_ok += 1
                    drill_uuids.append(obj_uuid)
                except Exception as exc:  # noqa: BLE001 - the failure IS the datum
                    write_fail += 1
                    first_error = first_error or f"{type(exc).__name__}: {exc}"
            for obj_uuid in drill_uuids[:DRILL_OBJECTS_PER_LEVEL]:
                try:
                    if handle.query.fetch_object_by_id(obj_uuid) is not None:
                        read_ok += 1
                    else:
                        read_fail += 1
                except Exception as exc:  # noqa: BLE001
                    read_fail += 1
                    first_error = first_error or f"{type(exc).__name__}: {exc}"
            outcomes.append(
                DrillOutcome(label, write_ok, write_fail, read_ok, read_fail, first_error)
            )
        # best-effort cleanup (works fully once all nodes are back)
        try:
            base.data.delete_many(where=Filter.by_property("doc_type").equal(DRILL_DOC_TYPE))
        except Exception as exc:  # noqa: BLE001
            console.print(
                f"[yellow]cleanup deferred ({type(exc).__name__}) - "
                "make reset will remove drill objects[/yellow]"
            )

    table = Table(title="consistency drill (RF=3)")
    for col in ("level", "writes ok", "writes failed", "reads ok", "reads failed", "first error"):
        table.add_column(col, overflow="fold")
    for o in outcomes:
        table.add_row(
            o.level,
            str(o.write_ok),
            str(o.write_fail),
            str(o.read_ok),
            str(o.read_fail),
            o.first_error or "-",
        )
    console.print(table)
    return outcomes


def convergence_watch(timeout_s: float = 300.0, stable_polls: int = 3) -> bool:
    """Poll async-replication metrics until convergence (or timeout).

    Convergence heuristic: scheduler queue depth is 0 AND no objects were
    propagated between consecutive polls, for `stable_polls` polls in a row.
    """
    settings = load_settings()
    q = f"{settings.prometheus_url}/api/v1/query"

    def scalar(promql: str) -> float:
        resp = httpx.get(q, params={"query": promql}, timeout=10)
        resp.raise_for_status()
        result = resp.json().get("data", {}).get("result", [])
        return float(result[0]["value"][1]) if result else 0.0

    console.print(SIMULATION_BANNER)
    console.print("[cyan]Watching async replication (Ctrl-C to stop)…[/cyan]")
    stable = 0
    last_propagated = scalar("sum(async_replication_propagation_object_count)")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(5)
        queue_depth = scalar("sum(async_replication_scheduler_queue_depth)")
        propagated = scalar("sum(async_replication_propagation_object_count)")
        workers = scalar("sum(async_replication_scheduler_workers_active)")
        delta = propagated - last_propagated
        last_propagated = propagated
        console.print(
            f"  queue_depth={queue_depth:.0f} active_workers={workers:.0f} "
            f"objects_propagated_delta={delta:.0f}"
        )
        stable = stable + 1 if (queue_depth == 0 and delta == 0) else 0
        if stable >= stable_polls:
            console.print(
                "[green bold]Converged: no pending async-replication "
                "work for 3 consecutive polls.[/green bold]"
            )
            return True
    console.print(
        "[red]Timed out waiting for convergence - check Grafana / prometheus targets.[/red]"
    )
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acme Lab 3 chaos helper.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_kill = sub.add_parser("kill")
    p_kill.add_argument("node")
    p_kill.add_argument("--allow-quorum-loss", action="store_true")
    p_restore = sub.add_parser("restore")
    p_restore.add_argument("node")
    sub.add_parser("write-drill")
    p_conv = sub.add_parser("convergence")
    p_conv.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv)

    if args.cmd == "status":
        status()
    elif args.cmd == "kill":
        kill_node(args.node, allow_quorum_loss=args.allow_quorum_loss)
    elif args.cmd == "restore":
        restore_node(args.node)
    elif args.cmd == "write-drill":
        write_during_failure()
    elif args.cmd == "convergence":
        return 0 if convergence_watch(timeout_s=args.timeout) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
