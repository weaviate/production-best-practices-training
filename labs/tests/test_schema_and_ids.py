"""Schema definitions + deterministic-ID tests.

These import ``weaviate`` (types only, no cluster) and skip cleanly when the
client library is not installed (e.g. before ``make bootstrap``).
"""

from __future__ import annotations

import pytest

weaviate = pytest.importorskip("weaviate", reason="weaviate-client not installed")
pytest.importorskip("rich", reason="rich not installed")

from acme import schema  # noqa: E402
from acme.seed import product_uuid  # noqa: E402


def test_product_uuid_deterministic() -> None:
    a = product_uuid("MER-000123")
    b = product_uuid("MER-000123")
    c = product_uuid("MER-000124")
    assert a == b, "same input must yield the same UUID (idempotent imports)"
    assert a != c
    # RFC 4122 UUIDv5 shape
    assert len(a) == 36 and a.count("-") == 4


def test_product_uuid_matches_generate_uuid5() -> None:
    from weaviate.util import generate_uuid5

    assert product_uuid("MER-000001") == str(generate_uuid5("MER-000001"))


def test_tenant_names_match_dataset_convention() -> None:
    names = schema.tenant_names()
    assert len(names) == schema.TENANT_COUNT == 24
    assert names[0] == "tenant-000"
    assert names[-1] == "tenant-023"


def test_property_index_flags_are_deliberate() -> None:
    props = {p.name: p for p in schema.product_properties()}
    expected_names = {
        "product_id",
        "title",
        "description",
        "category",
        "brand",
        "price",
        "tenant",
        "doc_type",
        "vec_id",
    }
    assert set(props) == expected_names

    # searchable free-text fields
    assert props["title"].indexSearchable is True
    assert props["description"].indexSearchable is True
    # filter-only keys must NOT pay for a BM25 index
    for name in ("product_id", "category", "brand", "doc_type"):
        assert props[name].indexFilterable is True, name
        assert props[name].indexSearchable is False, name
    # price supports range filters
    assert props["price"].indexRangeFilters is True


def test_lab_collection_names_stable() -> None:
    assert schema.COLLECTION_PRODUCT == "AcmeProduct"
    assert schema.COLLECTION_MT == "AcmeProductMT"
    assert schema.COLLECTION_HFRESH == "AcmeProductHFresh"
    assert schema.HFRESH_SEARCH_PROBE == 256  # C-1: explicit, never default
