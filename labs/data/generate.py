#!/usr/bin/env python3
"""Acme synthetic catalog generator.

Fully synthetic, deterministic dataset for the "Advanced: Production Best
Practices with Weaviate" labs. No external data sources, no licensing
constraints — everything below is generated from a fixed seed with the
Python stdlib and numpy only. Safe to redistribute.

Artifacts written to the output directory:

* ``vectors.npy``       — (N, DIM) float32, unit-normalized object vectors
* ``queries.npy``       — (Q, DIM) float32, unit-normalized query vectors
* ``ground_truth.npy``  — (Q, K) int32, EXACT brute-force top-K neighbor row
                          indices (cosine == dot product on unit vectors)
* ``objects.jsonl.gz``  — one JSON object per line (gzip mtime pinned to 0
                          so output is byte-identical across reruns)
* ``manifest.json``     — generation parameters + sha256 of every artifact

Vector structure: a seeded Gaussian mixture with one cluster center per
product category (default 32 centers), so nearest-neighbor structure is
meaningful (neighbors overwhelmingly share a category) and filtered-search
experiments have real selectivity to work with. Queries are drawn near
cluster centers with lower noise than the objects.

Run:  python3 generate.py [--out-dir DIR] [--count N] [--seed S] ...
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_SEED = 20260713
DEFAULT_COUNT = 50_000
DEFAULT_DIM = 256
DEFAULT_CENTERS = 32
DEFAULT_QUERIES = 200
DEFAULT_K = 100
DEFAULT_TENANTS = 24

# 32 categories — one Gaussian-mixture center each (index-aligned).
CATEGORIES: tuple[str, ...] = (
    "headphones",
    "keyboards",
    "monitors",
    "laptops",
    "tablets",
    "phones",
    "cameras",
    "drones",
    "speakers",
    "microphones",
    "routers",
    "storage",
    "wearables",
    "printers",
    "projectors",
    "gaming-consoles",
    "chargers",
    "cables",
    "desks",
    "chairs",
    "lighting",
    "smart-home",
    "networking",
    "security-cams",
    "e-readers",
    "gps-devices",
    "car-audio",
    "tv-video",
    "audio-interfaces",
    "vr-headsets",
    "power-banks",
    "docking-stations",
)

BRANDS: tuple[str, ...] = (
    "Northwind",
    "Auralux",
    "Vektra",
    "Bluepeak",
    "Cindercraft",
    "Dynaflow",
    "Ebonite",
    "Fluxline",
    "Gravitas",
    "Helioform",
    "Ionix",
    "Juniper Labs",
    "Kestrel",
    "Lumenware",
    "Mistral",
    "Nocturne",
    "Orbital",
    "Pinnacle",
    "Quartzon",
    "Ridgeline",
    "Solstice",
    "Tundra",
    "Umbra",
    "Vantage",
    "Westwood",
    "Xenith",
    "Yellowtail",
    "Zephyr",
    "Argon",
    "Basalt",
    "Copperfield",
    "Driftwood",
    "Emberline",
    "Foxglove",
    "Granite",
    "Harborlight",
    "Ironvale",
    "Jadecore",
    "Kilnworth",
    "Larkspur",
)

ADJECTIVES: tuple[str, ...] = (
    "Pro",
    "Max",
    "Ultra",
    "Lite",
    "Compact",
    "Studio",
    "Elite",
    "Prime",
    "Air",
    "Core",
    "Flex",
    "Edge",
    "Neo",
    "Plus",
    "Mini",
    "Fusion",
)

DESCRIPTION_TEMPLATES: tuple[str, ...] = (
    "The {brand} {title} sets a new bar for {category} with {feat1} and "
    "{feat2}. Designed for daily production use, it ships with {feat3} "
    "and a {warranty}-year warranty.",
    "Meet the {title} from {brand}: a {category} workhorse combining "
    "{feat1} with {feat2}. Field-tested for reliability, it includes "
    "{feat3} out of the box.",
    "{brand}'s {title} rethinks what {category} can do. Highlights "
    "include {feat1}, {feat2}, and {feat3}. Backed by a {warranty}-year "
    "warranty and same-day support.",
    "Built for teams that depend on their {category}, the {title} pairs "
    "{feat1} with {feat2}. {brand} adds {feat3} and a {warranty}-year "
    "service plan.",
)

SUPPORT_TEMPLATES: tuple[str, ...] = (
    "Troubleshooting guide for the {brand} {title}: if the device fails to "
    "pair, reset the {category} module, verify firmware {fw}, and re-run "
    "setup. Escalate to tier 2 if {feat1} remains unavailable.",
    "Setup instructions for {brand} {title}: unbox, charge fully, install "
    "firmware {fw}, then enable {feat1}. Known issue: {feat2} may need a "
    "restart after first sync.",
    "Warranty and returns policy for the {title} ({category}): {warranty}-"
    "year coverage including {feat1}. Contact support with your order ID "
    "before shipping a return.",
)

FEATURES: tuple[str, ...] = (
    "adaptive noise shaping",
    "a machined aluminum chassis",
    "48-hour battery life",
    "hot-swappable components",
    "USB-C fast charge",
    "multipoint wireless pairing",
    "an ambient light sensor",
    "tool-free assembly",
    "IP67 water resistance",
    "a low-latency mode",
    "onboard DSP profiles",
    "modular expansion bays",
    "silent operation",
    "energy-star certified power draw",
    "a color-accurate panel",
    "self-healing firmware",
    "encrypted local storage",
    "dual-band telemetry",
)


def make_tenants(n_tenants: int) -> list[str]:
    """Deterministic tenant names: tenant-000 … tenant-NNN."""
    return [f"tenant-{i:03d}" for i in range(n_tenants)]


def build_vectors(
    rng: np.random.Generator, count: int, dim: int, n_centers: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (unit vectors float32 (count, dim), assignments (count,), centers)."""
    centers = rng.normal(size=(n_centers, dim))
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)

    # Slightly skewed category popularity for realistic filter selectivity.
    weights = rng.dirichlet(np.full(n_centers, 4.0))
    assignments = rng.choice(n_centers, size=count, p=weights)

    # Noise scale is per-dimension; expected noise NORM is scale * sqrt(dim).
    # 0.055 * sqrt(256) ~= 0.88 vs unit-norm centers: clusters are clearly
    # separated (meaningful NN structure) but not trivially tight.
    noise = rng.normal(scale=0.055, size=(count, dim))
    vectors = centers[assignments] + noise
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors.astype(np.float32), assignments.astype(np.int32), centers


def build_queries(
    rng: np.random.Generator,
    centers: np.ndarray,
    n_queries: int,
    dim: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Query vectors drawn near cluster centers (lower noise than objects)."""
    q_assign = rng.choice(centers.shape[0], size=n_queries)
    # Queries sit closer to centers than objects do (0.04 * sqrt(256) ~= 0.64).
    noise = rng.normal(scale=0.04, size=(n_queries, dim))
    queries = centers[q_assign] + noise
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    return queries.astype(np.float32), q_assign.astype(np.int32)


def brute_force_ground_truth(queries: np.ndarray, vectors: np.ndarray, k: int) -> np.ndarray:
    """EXACT top-k by cosine similarity (dot product — all vectors unit norm)."""
    sims = queries.astype(np.float64) @ vectors.astype(np.float64).T
    # argsort descending, exact (no approximation anywhere).
    top = np.argsort(-sims, axis=1, kind="stable")[:, :k]
    return top.astype(np.int32)


def build_objects(
    rng: np.random.Generator,
    assignments: np.ndarray,
    tenants: list[str],
) -> list[dict[str, Any]]:
    count: int = int(assignments.shape[0])
    brand_idx = rng.integers(0, len(BRANDS), size=count)
    adj_idx = rng.integers(0, len(ADJECTIVES), size=count)
    model_no = rng.integers(100, 999, size=count)
    tmpl_idx = rng.integers(0, len(DESCRIPTION_TEMPLATES), size=count)
    sup_idx = rng.integers(0, len(SUPPORT_TEMPLATES), size=count)
    feat_idx = rng.integers(0, len(FEATURES), size=(count, 3))
    warranty = rng.integers(1, 6, size=count)
    fw_minor = rng.integers(0, 30, size=count)
    is_support = rng.random(count) < 0.15  # 15% support docs, 85% products
    prices = np.round(np.exp(rng.normal(4.2, 0.8, size=count)) + 9.0, 2)
    tenant_idx = rng.integers(0, len(tenants), size=count)

    objects: list[dict[str, Any]] = []
    for i in range(count):
        category = CATEGORIES[int(assignments[i])]
        brand = BRANDS[int(brand_idx[i])]
        title = (
            f"{ADJECTIVES[int(adj_idx[i])]} {category.replace('-', ' ').title()} {int(model_no[i])}"
        )
        f1, f2, f3 = (FEATURES[int(j)] for j in feat_idx[i])
        if is_support[i]:
            doc_type = "support-doc"
            description = SUPPORT_TEMPLATES[int(sup_idx[i])].format(
                brand=brand,
                title=title,
                category=category,
                warranty=int(warranty[i]),
                fw=f"2.{int(fw_minor[i])}.1",
                feat1=f1,
                feat2=f2,
            )
        else:
            doc_type = "product"
            description = DESCRIPTION_TEMPLATES[int(tmpl_idx[i])].format(
                brand=brand,
                title=title,
                category=category,
                warranty=int(warranty[i]),
                feat1=f1,
                feat2=f2,
                feat3=f3,
            )
        objects.append(
            {
                "vec_id": i,
                "product_id": f"MER-{i:06d}",
                "title": f"{brand} {title}",
                "description": description,
                "category": category,
                "brand": brand,
                "price": float(prices[i]),
                "tenant": tenants[int(tenant_idx[i])],
                "doc_type": doc_type,
            }
        )
    return objects


def write_jsonl_gz(path: Path, objects: list[dict[str, Any]]) -> None:
    """Byte-stable gzip: filename empty, mtime pinned to 0."""
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0) as gz:
        for obj in objects:
            gz.write(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode())
            gz.write(b"\n")
    path.write_bytes(buf.getvalue())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def generate(
    out_dir: Path,
    *,
    seed: int = DEFAULT_SEED,
    count: int = DEFAULT_COUNT,
    dim: int = DEFAULT_DIM,
    n_centers: int = DEFAULT_CENTERS,
    n_queries: int = DEFAULT_QUERIES,
    k: int = DEFAULT_K,
    n_tenants: int = DEFAULT_TENANTS,
) -> dict[str, Any]:
    """Generate all artifacts; returns the manifest dict."""
    if n_centers > len(CATEGORIES):
        raise ValueError(f"n_centers must be <= {len(CATEGORIES)}")
    if k > count:
        raise ValueError("k cannot exceed object count")

    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    rng = np.random.default_rng(seed)

    vectors, assignments, centers = build_vectors(rng, count, dim, n_centers)
    queries, _ = build_queries(rng, centers, n_queries, dim)
    ground_truth = brute_force_ground_truth(queries, vectors, k)
    tenants = make_tenants(n_tenants)
    objects = build_objects(rng, assignments, tenants)

    np.save(out_dir / "vectors.npy", vectors)
    np.save(out_dir / "queries.npy", queries)
    np.save(out_dir / "ground_truth.npy", ground_truth)
    write_jsonl_gz(out_dir / "objects.jsonl.gz", objects)

    elapsed = time.monotonic() - t0
    artifacts = ["vectors.npy", "queries.npy", "ground_truth.npy", "objects.jsonl.gz"]
    manifest: dict[str, Any] = {
        "generator": "labs/data/generate.py",
        "provenance": "fully synthetic; no external data sources; safe to redistribute",
        "seed": seed,
        "count": count,
        "dim": dim,
        "n_centers": n_centers,
        "n_queries": n_queries,
        "k": k,
        "n_tenants": n_tenants,
        "categories": len(CATEGORIES),
        "generation_seconds": round(elapsed, 2),
        "artifacts": {
            name: {
                "sha256": sha256_file(out_dir / name),
                "bytes": (out_dir / name).stat().st_size,
            }
            for name in artifacts
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    parser.add_argument("--centers", type=int, default=DEFAULT_CENTERS)
    parser.add_argument("--queries", type=int, default=DEFAULT_QUERIES)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--tenants", type=int, default=DEFAULT_TENANTS)
    args = parser.parse_args(argv)

    manifest = generate(
        args.out_dir,
        seed=args.seed,
        count=args.count,
        dim=args.dim,
        n_centers=args.centers,
        n_queries=args.queries,
        k=args.k,
        n_tenants=args.tenants,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
