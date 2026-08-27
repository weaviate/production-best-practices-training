"""Connection factory for the Acme lab cluster (v4 client only).

Connection reuse guidance
-------------------------
* Create ONE client per process and reuse it; each client owns HTTP and gRPC
  connection pools, and setup/teardown is not free.
* Always close it: prefer the context manager (``with connect() as client:``).
  A client method called after close raises ``WeaviateClosedClientError``.
* Collection handles from ``client.collections.use(name)`` are cheap, local,
  and involve no network call - create them freely.
* Thread-safety: queries via a shared client are fine, but the batching
  machinery is NOT thread-safe - never share one ``batch`` context between
  threads (docs: "No two threads can use the same client.batch object").

v3 APIs (``weaviate.Client(...)``) are forbidden in this codebase - that
constructor is the canonical tell of hallucinated/out-of-date code.
"""

from __future__ import annotations

import weaviate
from weaviate import WeaviateClient
from weaviate.classes.init import AdditionalConfig, Auth, Timeout

from acme.config import LabSettings, load_settings

# Timeout budgets (seconds): fail fast on connect, allow slow analytic
# queries, allow long server-side batch flushes.
DEFAULT_TIMEOUT = Timeout(init=10, query=30, insert=120)


def connect(
    settings: LabSettings | None = None,
    *,
    api_key: str | None = None,
    timeout: Timeout = DEFAULT_TIMEOUT,
) -> WeaviateClient:
    """Connect to the lab cluster's first node (root key by default).

    Returns a connected ``WeaviateClient``; use it as a context manager::

        with connect() as client:
            products = client.collections.use("AcmeProduct")

    Raises ``weaviate.exceptions.WeaviateStartUpError`` when the cluster is
    unreachable (run ``make up`` first) and ``RuntimeError`` when placeholder
    API keys are still configured.
    """
    settings = settings or load_settings()
    if settings.is_cloud:
        # Managed Weaviate Cloud: TLS on 443 for both HTTP and gRPC.
        return weaviate.connect_to_weaviate_cloud(
            cluster_url=settings.weaviate_cloud_url,
            auth_credentials=Auth.api_key(
                api_key or settings.weaviate_api_key or settings.weaviate_api_key_root
            ),
            additional_config=AdditionalConfig(timeout=timeout),
        )
    if settings.using_placeholder_keys():
        raise RuntimeError(
            "Refusing to connect with placeholder API keys. "
            "Copy labs/.env.example to labs/.env and rotate WEAVIATE_API_KEY_*."
        )
    return weaviate.connect_to_custom(
        http_host=settings.weaviate_http_host,
        http_port=settings.weaviate_http_port,
        http_secure=False,  # lab-only: TLS terminates at a proxy in production
        grpc_host=settings.weaviate_grpc_host,
        grpc_port=settings.weaviate_grpc_port,
        grpc_secure=False,
        auth_credentials=Auth.api_key(api_key or settings.weaviate_api_key_root),
        additional_config=AdditionalConfig(timeout=timeout),
    )


def connect_readonly(settings: LabSettings | None = None) -> WeaviateClient:
    """Connect with the read-only key (participant-facing query paths)."""
    settings = settings or load_settings()
    return connect(settings, api_key=settings.weaviate_api_key_readonly)


def connect_to_node(
    node_index: int,
    settings: LabSettings | None = None,
    *,
    timeout: Timeout = DEFAULT_TIMEOUT,
) -> WeaviateClient:
    """Connect to a specific node (0-based) - used by chaos/verify tooling.

    Any node can coordinate any request (leaderless data plane); pinning a
    node makes failure drills observable and repeatable.
    """
    settings = settings or load_settings()
    http_ports = settings.node_http_ports
    grpc_ports = settings.node_grpc_ports
    if not (0 <= node_index < len(http_ports)):
        raise ValueError(f"node_index {node_index} out of range (have {len(http_ports)} nodes)")
    if settings.using_placeholder_keys():
        raise RuntimeError(
            "Refusing to connect with placeholder API keys - rotate labs/.env first."
        )
    return weaviate.connect_to_custom(
        http_host=settings.weaviate_http_host,
        http_port=http_ports[node_index],
        http_secure=False,
        grpc_host=settings.weaviate_grpc_host,
        grpc_port=grpc_ports[node_index],
        grpc_secure=False,
        auth_credentials=Auth.api_key(settings.weaviate_api_key_root),
        additional_config=AdditionalConfig(timeout=timeout),
    )
