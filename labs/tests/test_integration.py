"""Integration tests - require a running, seeded lab cluster (`make up seed`).

Skipped automatically when localhost:8080 is unreachable (see conftest.py).
Run explicitly with:  pytest -m integration
"""

from __future__ import annotations

import pytest

pytest.importorskip("weaviate", reason="weaviate-client not installed")

pytestmark = pytest.mark.integration


@pytest.mark.timeout(60)
def test_meta_version_matches_pin() -> None:
    from acme.client import connect
    from acme.config import load_settings

    with connect() as client:
        version = str(client.get_meta().get("version"))
    assert version == load_settings().weaviate_expected_version


@pytest.mark.timeout(120)
def test_verify_preflight_passes() -> None:
    from acme import verify

    assert verify.main([]) == 0


@pytest.mark.timeout(300)
def test_seed_is_idempotent_and_query_returns_k() -> None:
    """Re-seeding must not change counts (deterministic UUIDs = upserts)."""
    from acme import schema, seed
    from acme.client import connect
    from acme.dataset import load_dataset

    ds = load_dataset()
    assert seed.main(["--target", "product"]) == 0
    with connect() as client:
        collection = client.collections.use(schema.COLLECTION_PRODUCT)
        agg = collection.aggregate.over_all(total_count=True)
        assert int(agg.total_count or 0) == ds.count
        result = collection.query.near_vector(
            near_vector=ds.queries[0].tolist(),
            target_vector=schema.VECTOR_NAME,
            limit=10,
        )
        assert len(result.objects) == 10


@pytest.mark.timeout(600)
def test_bench_baseline_happy_path(tmp_path: object) -> None:
    from acme import bench

    report = bench.run_preset("baseline", trials=1, warmup=5, concurrency=4)
    assert report["results"], "bench produced no variants"
    r = report["results"][0]
    assert 0.0 <= r["recall_at_10"] <= 1.0
    assert r["error_count"] == 0
    assert r["p95_ms"] > 0
