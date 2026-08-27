"""Lab 2 benchmark harness: recall@10 + latency percentiles + throughput.

Methodology (enforced, not suggested):

* WARM-UP phase before any measured trial (caches, connection pools, JIT'd
  code paths all lie to cold benchmarks).
* N repeated trials over the full 200-query set; latencies pooled across
  trials, recall averaged.
* ONE VARIABLE AT A TIME: you pick a *preset*, not free-form knobs. Every
  preset differs from ``baseline`` in exactly one dimension:
      baseline         HNSW, no quantization, unfiltered, ef=-1 (dynamic)
      rq8              same, but RQ-8 quantization (separate collection)
      ef-sweep         same collection, ef swept over fixed values
      hfresh           HFresh index instead of HNSW
      filter-strategy  brand-filtered queries, ACORN vs SWEEPING
* Machine-readable JSON output with a config fingerprint + environment
  capture, so results can be compared and disputed later.

Recall is computed against the EXACT brute-force ground truth shipped in
labs/data (and recomputed exactly, in-process, for filtered queries).

Run:  python -m acme.bench --preset baseline [--trials 3] [--concurrency 8]
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from rich.console import Console
from rich.table import Table
from weaviate import WeaviateClient
from weaviate.classes.config import Reconfigure, VectorFilterStrategy
from weaviate.classes.query import Filter
from weaviate.collections import Collection

from acme import schema
from acme.client import connect
from acme.config import LABS_ROOT, load_settings
from acme.dataset import LabDataset, load_dataset
from acme.reconfig import update_content_vector_index
from acme.seed import seed_single_collection

console = Console()

K = 10
DEFAULT_TRIALS = 3
DEFAULT_WARMUP = 40
DEFAULT_CONCURRENCY = 8
EF_SWEEP_VALUES: tuple[int, ...] = (16, 32, 64, 128, 256)
RESULTS_DIR = LABS_ROOT / "results"

PRESETS: tuple[str, ...] = ("baseline", "rq8", "ef-sweep", "hfresh", "filter-strategy")


@dataclass
class VariantResult:
    """One measured configuration (a preset may produce several, e.g. ef-sweep)."""

    variant: str
    recall_at_10: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    throughput_qps: float
    error_count: int
    trials: int
    queries_per_trial: int
    latencies_ms_count: int = 0
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _percentiles(latencies_ms: list[float]) -> tuple[float, float, float]:
    arr = np.asarray(latencies_ms, dtype=np.float64)
    p50, p95, p99 = (float(np.percentile(arr, q)) for q in (50, 95, 99))
    return p50, p95, p99


def _query_once(
    collection: Collection,
    query_vec: list[float],
    flt: Any | None,
) -> tuple[list[int], float]:
    """Run one near_vector query; returns (vec_ids, latency_ms)."""
    t0 = time.perf_counter()
    result = collection.query.near_vector(
        near_vector=query_vec,
        target_vector=schema.VECTOR_NAME,
        limit=K,
        filters=flt,
        return_properties=["vec_id"],
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0
    ids = [int(o.properties["vec_id"]) for o in result.objects]
    return ids, latency_ms


def _filtered_ground_truth(
    ds: LabDataset, brands: list[str], query_brands: list[str]
) -> npt.NDArray[np.int32]:
    """Exact top-K per query restricted to that query's brand (numpy, exact)."""
    brand_arr = np.asarray(brands)
    gt = np.zeros((ds.queries.shape[0], K), dtype=np.int32)
    v64 = ds.vectors.astype(np.float64)
    for qi, brand in enumerate(query_brands):
        mask = brand_arr == brand
        candidates = np.flatnonzero(mask)
        sims = v64[candidates] @ ds.queries[qi].astype(np.float64)
        order = np.argsort(-sims, kind="stable")[:K]
        gt[qi] = candidates[order].astype(np.int32)
    return gt


def run_variant(
    collection: Collection,
    ds: LabDataset,
    variant: str,
    *,
    trials: int,
    warmup: int,
    concurrency: int,
    filters_per_query: list[Any] | None = None,
    ground_truth: npt.NDArray[np.int32] | None = None,
    notes: str = "",
    extra: dict[str, Any] | None = None,
) -> VariantResult:
    """Warm up, then run `trials` full passes over the query set."""
    gt = ground_truth if ground_truth is not None else ds.ground_truth[:, :K]
    n_queries = ds.queries.shape[0]
    query_vecs = [q.tolist() for q in ds.queries]
    flts: list[Any | None] = (
        filters_per_query if filters_per_query is not None else [None] * n_queries
    )

    # --- warm-up (not measured; errors here will resurface in trials) ---
    for qi in range(min(warmup, n_queries)):
        with contextlib.suppress(Exception):
            _query_once(collection, query_vecs[qi], flts[qi])

    latencies: list[float] = []
    recalls: list[float] = []
    errors = 0
    wall_start = time.perf_counter()

    def one(qi: int) -> tuple[float | None, float | None]:
        try:
            ids, latency = _query_once(collection, query_vecs[qi], flts[qi])
        except Exception:  # noqa: BLE001 - counted, benchmark continues
            return None, None
        truth = set(gt[qi].tolist())
        recall = len(truth.intersection(ids)) / float(K)
        return latency, recall

    for _trial in range(trials):
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for latency, recall in pool.map(one, range(n_queries)):
                if latency is None or recall is None:
                    errors += 1
                else:
                    latencies.append(latency)
                    recalls.append(recall)

    wall = time.perf_counter() - wall_start
    if not latencies:
        raise RuntimeError(
            f"variant {variant!r}: every query failed ({errors} errors) - "
            "is the cluster up and seeded? Run: make verify"
        )
    p50, p95, p99 = _percentiles(latencies)
    return VariantResult(
        variant=variant,
        recall_at_10=float(np.mean(recalls)),
        p50_ms=round(p50, 2),
        p95_ms=round(p95, 2),
        p99_ms=round(p99, 2),
        throughput_qps=round(len(latencies) / wall, 1),
        error_count=errors,
        trials=trials,
        queries_per_trial=n_queries,
        latencies_ms_count=len(latencies),
        notes=notes,
        extra=extra or {},
    )


def _ensure_rq8(client: WeaviateClient, ds: LabDataset) -> None:
    """Create + seed the RQ-8 collection if missing (one-time, ~1 min)."""
    if client.collections.exists(schema.COLLECTION_RQ8):
        return
    console.print("[cyan]Creating and seeding AcmeProductRQ8 (one-time)…[/cyan]")
    schema.create_product_collection(client, schema.COLLECTION_RQ8, quantizer="rq8")
    failures = seed_single_collection(client, schema.COLLECTION_RQ8, ds)
    if failures:
        raise RuntimeError(f"RQ8 seeding failed for {len(failures)} objects")
    _wait_for_queue_drain(client)


def _wait_for_queue_drain(client: WeaviateClient, timeout_s: float = 600.0) -> None:
    """Block until async vector indexing has caught up (or time out loudly)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        backlog = 0
        for node in client.cluster.nodes(output="verbose"):
            for shard in node.shards or []:
                backlog += int(getattr(shard, "vector_queue_length", 0) or 0)
        if backlog == 0:
            return
        console.print(f"[yellow]index queue backlog: {backlog} - waiting…[/yellow]")
        time.sleep(5)
    raise TimeoutError(f"vector index queue not drained within {timeout_s}s")


def run_preset(preset: str, *, trials: int, warmup: int, concurrency: int) -> dict[str, Any]:
    ds = load_dataset()
    settings = load_settings()
    variants: list[VariantResult] = []

    with connect() as client:
        server_version = str(client.get_meta().get("version", "unknown"))
        _wait_for_queue_drain(client, timeout_s=120)

        if preset == "baseline":
            collection = client.collections.use(schema.COLLECTION_PRODUCT)
            variants.append(
                run_variant(
                    collection,
                    ds,
                    "baseline-hnsw",
                    trials=trials,
                    warmup=warmup,
                    concurrency=concurrency,
                    notes="HNSW, no quantization, ef=-1 (dynamic), unfiltered",
                )
            )

        elif preset == "rq8":
            _ensure_rq8(client, ds)
            collection = client.collections.use(schema.COLLECTION_RQ8)
            variants.append(
                run_variant(
                    collection,
                    ds,
                    "rq8",
                    trials=trials,
                    warmup=warmup,
                    concurrency=concurrency,
                    notes="HNSW + RQ-8 (4x compression, rescoring on)",
                )
            )

        elif preset == "ef-sweep":
            collection = client.collections.use(schema.COLLECTION_PRODUCT)
            try:
                for ef in EF_SWEEP_VALUES:
                    update_content_vector_index(
                        collection,
                        lambda ef=ef: Reconfigure.VectorIndex.hnsw(ef=ef),
                        verify_attr="ef",
                        expect=ef,
                    )
                    variants.append(
                        run_variant(
                            collection,
                            ds,
                            f"ef={ef}",
                            trials=trials,
                            warmup=warmup,
                            concurrency=concurrency,
                            notes="ef is hot-mutable; efConstruction/maxConnections are NOT",
                            extra={"ef": ef},
                        )
                    )
            finally:
                # Always restore dynamic ef so later labs see baseline behavior.
                update_content_vector_index(
                    collection,
                    lambda: Reconfigure.VectorIndex.hnsw(ef=-1),
                    verify_attr="ef",
                    expect=-1,
                )

        elif preset == "hfresh":
            collection = client.collections.use(schema.COLLECTION_HFRESH)
            variants.append(
                run_variant(
                    collection,
                    ds,
                    "hfresh",
                    trials=trials,
                    warmup=warmup,
                    concurrency=concurrency,
                    notes=f"HFresh, searchProbe={schema.HFRESH_SEARCH_PROBE} "
                    "(explicit - C-1), RQ built-in",
                )
            )

        elif preset == "filter-strategy":
            collection = client.collections.use(schema.COLLECTION_PRODUCT)
            brands = [str(o["brand"]) for o in ds.objects]
            # Per-query brand = brand of that query's true nearest neighbor,
            # so filters are non-empty; brand is uncorrelated with the vector
            # clusters (that is where ACORN shines - see r2 §5).
            query_brands = [
                brands[int(ds.ground_truth[qi, 0])] for qi in range(ds.queries.shape[0])
            ]
            gt = _filtered_ground_truth(ds, brands, query_brands)
            flts = [Filter.by_property("brand").equal(b) for b in query_brands]
            try:
                for strategy in (VectorFilterStrategy.ACORN, VectorFilterStrategy.SWEEPING):
                    update_content_vector_index(
                        collection,
                        lambda strategy=strategy: Reconfigure.VectorIndex.hnsw(
                            filter_strategy=strategy
                        ),
                        verify_attr="filter_strategy",
                        expect=strategy,
                    )
                    variants.append(
                        run_variant(
                            collection,
                            ds,
                            f"filter-{strategy.value}",
                            trials=trials,
                            warmup=warmup,
                            concurrency=concurrency,
                            filters_per_query=flts,
                            ground_truth=gt,
                            notes="brand-filtered near_vector; exact filtered "
                            "ground truth recomputed in-process",
                            extra={"filter_strategy": str(strategy.value)},
                        )
                    )
            finally:
                update_content_vector_index(
                    collection,
                    lambda: Reconfigure.VectorIndex.hnsw(
                        filter_strategy=VectorFilterStrategy.ACORN
                    ),
                    verify_attr="filter_strategy",
                    expect=VectorFilterStrategy.ACORN,
                )
        else:
            raise ValueError(f"unknown preset {preset!r}; choose from {PRESETS}")

    run_config = {
        "preset": preset,
        "k": K,
        "trials": trials,
        "warmup": warmup,
        "concurrency": concurrency,
        "dataset_manifest": ds.manifest.get("artifacts", {}),
        "dataset_seed": ds.manifest.get("seed"),
    }
    fingerprint = hashlib.sha256(json.dumps(run_config, sort_keys=True).encode()).hexdigest()[:16]

    return {
        "schema_version": 1,
        "config_fingerprint": fingerprint,
        "config": run_config,
        "environment": {
            "timestamp_utc": datetime.now(tz=UTC).isoformat(),
            "server_version": server_version,
            "expected_server_version": settings.weaviate_expected_version,
            "client": "weaviate-client==4.22.0",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "node_count": settings.node_count,
        },
        "caveat": (
            "Lab dataset is 50k x 256-dim on a single-host 3-node cluster; "
            "absolute numbers do NOT transfer to production scale. Compare "
            "deltas between variants, not absolute latencies."
        ),
        "results": [vars(v) for v in variants],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acme Lab 2 benchmark harness.")
    parser.add_argument("--preset", choices=PRESETS, required=True)
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output JSON path (default: labs/results/bench-<preset>-<ts>.json)",
    )
    args = parser.parse_args(argv)

    report = run_preset(
        args.preset,
        trials=args.trials,
        warmup=args.warmup,
        concurrency=args.concurrency,
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or RESULTS_DIR / f"bench-{args.preset}-{ts}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")

    table = Table(title=f"preset: {args.preset}  (fingerprint {report['config_fingerprint']})")
    for col in ("variant", "recall@10", "p50 ms", "p95 ms", "p99 ms", "qps", "errors"):
        table.add_column(col)
    for r in report["results"]:
        table.add_row(
            r["variant"],
            f"{r['recall_at_10']:.4f}",
            f"{r['p50_ms']}",
            f"{r['p95_ms']}",
            f"{r['p99_ms']}",
            f"{r['throughput_qps']}",
            str(r["error_count"]),
        )
    console.print(table)
    console.print(f"[green]Results written to {out}[/green]")
    console.print(f"[yellow]{report['caveat']}[/yellow]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
