"""Collection definitions for the Acme labs.

Design decisions (all explicit - the labs do NOT rely on auto-schema, and the
cluster runs with ``AUTOSCHEMA_ENABLED=false``):

* Every property declares ``index_filterable`` / ``index_searchable``
  deliberately. Filterable-only keys (category, brand, doc_type, product_id)
  use FIELD tokenization and skip the searchable (BM25) index; free-text
  fields (title, description) are searchable. ``price`` adds the rangeable
  index because Lab 2 uses range filters.
* One named vector, ``content``, self-provided (vectors come from
  ``labs/data/vectors.npy``; no vectorizer module in the loop).
* ``AcmeProduct``      - HNSW, replication factor 3, 3 shards.
* ``AcmeProductMT``    - multi-tenant variant (24 named tenants).
* ``AcmeProductHFresh``- HFresh (GA in 1.38) with ``searchProbe`` set
  EXPLICITLY. Contradiction C-1 (VERSION_MATRIX.md): docs say the default is
  64, the v1.38.3 release notes raised it to 256 (#11955). We pin 256 so the
  lab never depends on which default the running binary ships.
* Replication factor is immutable via collection update; sharding params are
  immutable, full stop. That is a teaching point, not an accident.
"""

from __future__ import annotations

import os

from typing import Literal

from weaviate import WeaviateClient
from weaviate.classes.config import (
    Configure,
    DataType,
    Property,
    Tokenization,
    VectorDistances,
    VectorFilterStrategy,
)

VECTOR_NAME = "content"
VECTOR_DIM = 256

# LAB_COLLECTION overrides the benchmark target (managed-cloud mode: your
# team collection, e.g. LabTeam03). Local labs leave it unset.
COLLECTION_PRODUCT = os.environ.get("LAB_COLLECTION") or "AcmeProduct"
COLLECTION_MT = "AcmeProductMT"
COLLECTION_HFRESH = "AcmeProductHFresh"
COLLECTION_RQ8 = "AcmeProductRQ8"  # created on demand by the Lab 2 harness

LAB_COLLECTIONS: tuple[str, ...] = (
    COLLECTION_PRODUCT,
    COLLECTION_MT,
    COLLECTION_HFRESH,
    COLLECTION_RQ8,
)

REPLICATION_FACTOR = 3
SHARD_COUNT = 3
TENANT_COUNT = 24

# C-1: set explicitly; do not trust the (docs 64 vs release-notes 256) default.
HFRESH_SEARCH_PROBE = 256

QuantizerName = Literal["none", "rq8", "rq1"]


def tenant_names(count: int = TENANT_COUNT) -> list[str]:
    """Deterministic tenant names - must match labs/data/generate.py."""
    return [f"tenant-{i:03d}" for i in range(count)]


def product_properties() -> list[Property]:
    """Explicit property set shared by all Acme collections."""
    return [
        Property(
            name="product_id",
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            index_filterable=True,  # exact-match lookup key
            index_searchable=False,  # never BM25-searched
        ),
        Property(
            name="title",
            data_type=DataType.TEXT,
            tokenization=Tokenization.WORD,
            index_filterable=False,
            index_searchable=True,  # BM25 / hybrid target
        ),
        Property(
            name="description",
            data_type=DataType.TEXT,
            tokenization=Tokenization.WORD,
            index_filterable=False,
            index_searchable=True,  # BM25 / hybrid target
        ),
        Property(
            name="category",
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            index_filterable=True,  # primary facet; correlates with vector clusters
            index_searchable=False,
        ),
        Property(
            name="brand",
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            index_filterable=True,  # facet UNcorrelated with vectors (ACORN drill)
            index_searchable=False,
        ),
        Property(
            name="price",
            data_type=DataType.NUMBER,
            index_filterable=True,
            index_range_filters=True,  # range queries in Lab 2 filter preset
        ),
        Property(
            name="tenant",
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            index_filterable=True,  # kept in single-tenant collections for parity
            index_searchable=False,
        ),
        Property(
            name="doc_type",
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            index_filterable=True,
            index_searchable=False,
        ),
        Property(
            name="vec_id",
            data_type=DataType.INT,
            index_filterable=True,  # maps results back to ground-truth rows
        ),
    ]


def _hnsw_index_config(
    quantizer: QuantizerName = "none",
    filter_strategy: VectorFilterStrategy = VectorFilterStrategy.ACORN,
) -> object:
    """HNSW config. ef stays -1 (dynamic); efConstruction/maxConnections keep
    server defaults (128/32) - both IMMUTABLE after creation."""
    quantizer_config = None
    if quantizer == "rq8":
        quantizer_config = Configure.VectorIndex.Quantizer.rq(bits=8)
    elif quantizer == "rq1":
        quantizer_config = Configure.VectorIndex.Quantizer.rq(bits=1)
    return Configure.VectorIndex.hnsw(
        distance_metric=VectorDistances.COSINE,
        filter_strategy=filter_strategy,  # ACORN is the server default since 1.34
        quantizer=quantizer_config,
    )


def create_product_collection(
    client: WeaviateClient,
    name: str = COLLECTION_PRODUCT,
    *,
    quantizer: QuantizerName = "none",
    replication_factor: int = REPLICATION_FACTOR,
    shard_count: int = SHARD_COUNT,
) -> None:
    """Create the single-tenant HNSW collection (no-op if it exists)."""
    if client.collections.exists(name):
        return
    client.collections.create(
        name=name,
        description="Acme Retail catalog - synthetic lab data (see labs/data/README.md)",
        properties=product_properties(),
        vector_config=[
            Configure.Vectors.self_provided(
                name=VECTOR_NAME,
                vector_index_config=_hnsw_index_config(quantizer=quantizer),
            )
        ],
        # Immutable via collection update: factor changes require replica
        # movement (COPY) or a rebuild behind an alias.
        replication_config=Configure.replication(factor=replication_factor),
        # ALL sharding params are immutable after creation.
        sharding_config=Configure.sharding(desired_count=shard_count),
        inverted_index_config=Configure.inverted_index(
            index_timestamps=False,
            index_null_state=False,
            index_property_length=False,
        ),
    )


def create_mt_collection(
    client: WeaviateClient,
    name: str = COLLECTION_MT,
    *,
    replication_factor: int = REPLICATION_FACTOR,
) -> None:
    """Create the multi-tenant variant and its 24 named tenants (idempotent).

    Each tenant is its own shard with a dedicated vector index; per-tenant
    hash trees for async replication cost ~16 KB/tenant/node (height 10).
    """
    from weaviate.classes.tenants import Tenant

    if not client.collections.exists(name):
        client.collections.create(
            name=name,
            description="Acme Retail catalog - multi-tenant demo variant",
            properties=product_properties(),
            vector_config=[
                Configure.Vectors.self_provided(
                    name=VECTOR_NAME,
                    vector_index_config=_hnsw_index_config(),
                )
            ],
            replication_config=Configure.replication(factor=replication_factor),
            multi_tenancy_config=Configure.multi_tenancy(
                enabled=True,
                auto_tenant_creation=False,  # typo'd tenant names must FAIL, not fork data
                auto_tenant_activation=False,
            ),
        )
    collection = client.collections.use(name)
    existing = {t.name for t in collection.tenants.get().values()}
    missing = [Tenant(name=t) for t in tenant_names() if t not in existing]
    if missing:
        collection.tenants.create(missing)


def create_hfresh_collection(
    client: WeaviateClient,
    name: str = COLLECTION_HFRESH,
    *,
    replication_factor: int = REPLICATION_FACTOR,
) -> None:
    """Create the HFresh (disk-based, SPFresh-style) variant (no-op if exists).

    HFresh notes (r2 research, v1.38.3):
      * GA in 1.38 (preview in 1.36); RQ is built in and mandatory.
      * cosine / l2-squared only - dot product unsupported.
      * ``searchProbe`` pinned to 256 EXPLICITLY because of contradiction C-1:
        docs claim default 64; v1.38.3 release notes raised it to 256
        (weaviate/weaviate#11955). Never rely on that default in a lab.
    """
    if client.collections.exists(name):
        return
    client.collections.create(
        name=name,
        description="Acme Retail catalog - HFresh index variant (cost/memory drill)",
        properties=product_properties(),
        vector_config=[
            Configure.Vectors.self_provided(
                name=VECTOR_NAME,
                vector_index_config=Configure.VectorIndex.hfresh(
                    distance_metric=VectorDistances.COSINE,
                    search_probe=HFRESH_SEARCH_PROBE,  # C-1: explicit, not default
                ),
            )
        ],
        replication_config=Configure.replication(factor=replication_factor),
        sharding_config=Configure.sharding(desired_count=SHARD_COUNT),
    )


def ensure_baseline_collections(client: WeaviateClient) -> list[str]:
    """Create every baseline collection; returns the names touched."""
    create_product_collection(client)
    create_mt_collection(client)
    create_hfresh_collection(client)
    return [COLLECTION_PRODUCT, COLLECTION_MT, COLLECTION_HFRESH]
