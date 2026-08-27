"""Loader for the deterministic Acme dataset (labs/data artifacts)."""

from __future__ import annotations

import gzip
import json
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
    """Load all artifacts; raise a friendly error when they are missing."""
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
