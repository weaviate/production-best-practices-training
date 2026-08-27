"""Dataset generator determinism + ground-truth exactness (offline, no cluster).

Small-scale regeneration keeps the suite fast; full-scale hashes are pinned
separately in labs/data/manifest.json and asserted in
``test_full_scale_manifest_hashes_recorded``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import generate as gen  # labs/data/generate.py (path added in conftest)

SMALL = {"count": 800, "dim": 32, "n_centers": 8, "n_queries": 12, "k": 20, "n_tenants": 6}

# Pinned hashes for the DEFAULT full-scale dataset (seed 20260713, 50k x 256).
# If generate.py changes behavior, this test must be updated deliberately.
FULL_SCALE_SHA256 = {
    "vectors.npy": "d701e2b53548f31e1a96b9aa441e5692154470c3a13254eac6215935366ef0be",
    "queries.npy": "9166591c80e63cdda2ccac9280936c5dd356c8ade6c4626b093858e8ba2ddf2a",
    "ground_truth.npy": "48b3f41261eb6a5670e9f5dc024668b06e40db13736d36fde03dab80cd8505d2",
    "objects.jsonl.gz": "d47db90d041caffe93fe92c3f235c3b1591cbeb1a18b78c85625ead5bf725eee",
}


def test_regeneration_is_byte_identical(tmp_path: Path) -> None:
    m1 = gen.generate(tmp_path / "a", seed=123, **SMALL)
    m2 = gen.generate(tmp_path / "b", seed=123, **SMALL)
    for name in m1["artifacts"]:
        assert m1["artifacts"][name]["sha256"] == m2["artifacts"][name]["sha256"], name


def test_different_seed_changes_output(tmp_path: Path) -> None:
    m1 = gen.generate(tmp_path / "a", seed=1, **SMALL)
    m2 = gen.generate(tmp_path / "b", seed=2, **SMALL)
    assert m1["artifacts"]["vectors.npy"]["sha256"] != m2["artifacts"]["vectors.npy"]["sha256"]


def test_ground_truth_is_exact(tmp_path: Path) -> None:
    gen.generate(tmp_path, seed=7, **SMALL)
    vectors = np.load(tmp_path / "vectors.npy")
    queries = np.load(tmp_path / "queries.npy")
    gt = np.load(tmp_path / "ground_truth.npy")
    assert gt.shape == (SMALL["n_queries"], SMALL["k"])
    for qi in range(queries.shape[0]):
        sims = vectors.astype(np.float64) @ queries[qi].astype(np.float64)
        expected = set(np.argsort(-sims)[: SMALL["k"]].tolist())
        assert set(gt[qi].tolist()) == expected, f"query {qi} ground truth wrong"


def test_vectors_unit_normalized(tmp_path: Path) -> None:
    gen.generate(tmp_path, seed=7, **SMALL)
    for name in ("vectors.npy", "queries.npy"):
        arr = np.load(tmp_path / name)
        assert arr.dtype == np.float32
        norms = np.linalg.norm(arr.astype(np.float64), axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5), name


def test_objects_align_with_vectors(tmp_path: Path) -> None:
    import gzip

    gen.generate(tmp_path, seed=7, **SMALL)
    with gzip.open(tmp_path / "objects.jsonl.gz", "rt", encoding="utf-8") as f:
        objects = [json.loads(line) for line in f]
    assert len(objects) == SMALL["count"]
    for i, obj in enumerate(objects[:50]):
        assert obj["vec_id"] == i
        assert obj["product_id"] == f"MER-{i:06d}"
        assert obj["category"] in gen.CATEGORIES
        assert obj["tenant"].startswith("tenant-")
        assert obj["doc_type"] in ("product", "support-doc")
        assert obj["price"] > 0


def test_tenant_names_deterministic() -> None:
    assert gen.make_tenants(3) == ["tenant-000", "tenant-001", "tenant-002"]
    assert len(gen.make_tenants(24)) == 24


def test_full_scale_manifest_hashes_recorded() -> None:
    """The committed manifest must match the pinned full-scale hashes."""
    manifest_path = Path(__file__).resolve().parents[1] / "data" / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("full-scale dataset not generated (run python3 data/generate.py)")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("seed") != gen.DEFAULT_SEED or manifest.get("count") != gen.DEFAULT_COUNT:
        pytest.skip("manifest was generated with non-default parameters")
    for name, sha in FULL_SCALE_SHA256.items():
        assert manifest["artifacts"][name]["sha256"] == sha, (
            f"{name} hash drifted - if generate.py changed intentionally, "
            "update FULL_SCALE_SHA256 and data/README.md"
        )
