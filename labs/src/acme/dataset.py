"""Loader for the deterministic Acme dataset (labs/data artifacts)."""

from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from acme.config import DATA_DIR

ARTIFACTS = ("vectors.npy", "queries.npy", "ground_truth.npy", "objects.jsonl.gz")


class DatasetMissingError(RuntimeError):
    """Raised when labs/data artifacts have not been generated."""


@dataclass(frozen=True)
class LabDataset:
    """In-memory view of the generated artifacts (index-aligned by row)."""

    vectors: npt.NDArray[np.float32]  # (N, DIM) unit-normalized
    queries: npt.NDArray[np.float32]  # (Q, DIM) unit-normalized
    ground_truth: npt.NDArray[np.int32]  # (Q, K) exact top-K row ids
    objects: list[dict[str, Any]]  # row i <-> vectors[i] (obj["vec_id"] == i)
    manifest: dict[str, Any]

    @property
    def count(self) -> int:
        return int(self.vectors.shape[0])

    @property
    def dim(self) -> int:
        return int(self.vectors.shape[1])


def load_dataset(data_dir: Path = DATA_DIR) -> LabDataset:
    """Load all artifacts; raise a friendly error when they are missing.

    With LAB_DATASET_PROFILE=wcd (managed-cloud labs), the dataset is
    regenerated deterministically in memory instead - see below.
    """
    if (os.environ.get("LAB_DATASET_PROFILE") or "").strip().lower() == "wcd":
        return _generate_wcd_dataset()
    missing = [name for name in ARTIFACTS if not (data_dir / name).exists()]
    if missing:
        raise DatasetMissingError(
            f"Missing dataset artifacts in {data_dir}: {', '.join(missing)}. "
            "Generate them with: python3 labs/data/generate.py"
        )
    vectors = np.load(data_dir / "vectors.npy")
    queries = np.load(data_dir / "queries.npy")
    ground_truth = np.load(data_dir / "ground_truth.npy")
    with gzip.open(data_dir / "objects.jsonl.gz", "rt", encoding="utf-8") as f:
        objects = [json.loads(line) for line in f]
    manifest_path = data_dir / "manifest.json"
    manifest: dict[str, Any] = (
        json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    )
    if len(objects) != vectors.shape[0]:
        raise DatasetMissingError(
            f"Artifact mismatch: {len(objects)} objects vs {vectors.shape[0]} vectors. "
            "Regenerate with: python3 labs/data/generate.py"
        )
    return LabDataset(
        vectors=vectors.astype(np.float32, copy=False),
        queries=queries.astype(np.float32, copy=False),
        ground_truth=ground_truth.astype(np.int32, copy=False),
        objects=objects,
        manifest=manifest,
    )


# --------------------------------------------------------------------------
# Managed-cloud (WCD) dataset profile
# --------------------------------------------------------------------------
# The managed-cloud lab collections (LabTeamNN) were seeded from this exact
# deterministic generator (same seed, same parameters) rather than from the
# repo artifacts. LAB_DATASET_PROFILE=wcd regenerates it in memory (~2 s),
# so recall numbers on the cloud collections are measured against the true
# exact ground truth. Do not edit constants: they are part of the seeded
# data's identity.
WCD_SEED = 20260713
WCD_DIM = 256
WCD_N_OBJECTS = 50_000
WCD_N_QUERIES = 200
WCD_CATEGORIES = [
    "apparel", "footwear", "electronics", "home", "beauty", "sports",
    "toys", "grocery", "office", "outdoor", "jewelry", "media",
    "garden", "auto", "pet", "baby", "health", "tools", "travel",
    "music", "art", "craft", "party", "seasonal", "clearance",
    "premium", "basics", "vintage", "eco", "tech-acc", "kitchen", "bath",
]  # 32 cluster centers, one per category


def _generate_wcd_dataset(n: int = WCD_N_OBJECTS, seed: int = WCD_SEED) -> LabDataset:
    """Regenerate the dataset the cloud collections were seeded with."""
    rng = np.random.default_rng(seed)
    centers = rng.normal(0, 1.0, size=(len(WCD_CATEGORIES), WCD_DIM)).astype(np.float32)
    cats = rng.integers(0, len(WCD_CATEGORIES), size=n)
    vecs = centers[cats] + rng.normal(0, 0.35, size=(n, WCD_DIM)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    qcats = rng.integers(0, len(WCD_CATEGORIES), size=WCD_N_QUERIES)
    queries = centers[qcats] + rng.normal(0, 0.35, size=(WCD_N_QUERIES, WCD_DIM)).astype(np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    gt = np.argsort(-(queries @ vecs.T), axis=1)[:, :100].astype(np.int64)
    objects = [
        {
            "product_id": f"NOV-{i:07d}",
            "title": f"{WCD_CATEGORIES[cats[i]].title()} item {i}",
            "category": WCD_CATEGORIES[int(cats[i])],
            "price": round(float(5 + (i % 300) * 1.37), 2),
            "vec_id": int(i),
        }
        for i in range(n)
    ]
    return LabDataset(
        vectors=vecs.astype(np.float32, copy=False),
        queries=queries.astype(np.float32, copy=False),
        ground_truth=gt.astype(np.int32, copy=False),
        objects=objects,
        manifest={"profile": "wcd", "seed": seed, "n": n, "dim": WCD_DIM},
    )
