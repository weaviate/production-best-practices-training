"""Named-vector-safe vector-index reconfiguration with read-back verification.

Why this exists (technical-review finding M-3): our collections define a
*named* vector (``content``). Depending on the client/server pair, the legacy
``config.update(vector_index_config=...)`` form may not target a named
vector's index. Guessing silently is unacceptable in a lab whose whole point
is evidence, so this helper:

1. tries the named-vector update path first, then the legacy path;
2. **verifies by read-back** that the intended attribute actually changed,
   and raises ``ReconfigError`` if no path took effect (visible failure,
   never a silent no-op).

Live-cluster verification of which path applies on server 1.38.3 + client
4.22.0 is tracked in labs/PENDING_VALIDATION.md (item M-3).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from weaviate.classes.config import Reconfigure
from weaviate.collections import Collection

VECTOR_NAME = "content"


class ReconfigError(RuntimeError):
    """Raised when a vector-index reconfiguration did not take effect."""


def _read_index_attr(collection: Collection, attr: str) -> Any:
    cfg = collection.config.get()
    vcfgs = getattr(cfg, "vector_config", None) or {}
    if VECTOR_NAME in vcfgs:
        vic = vcfgs[VECTOR_NAME].vector_index_config
    else:  # legacy single-vector layout
        vic = cfg.vector_index_config
    return getattr(vic, attr, None)


def update_content_vector_index(
    collection: Collection,
    make_vic: Callable[[], Any],
    *,
    verify_attr: str,
    expect: Any,
) -> str:
    """Apply ``make_vic()`` (a ``Reconfigure.VectorIndex.*`` payload) to the
    ``content`` named vector; return which path applied.

    ``verify_attr``/``expect``: attribute read back from the live config that
    proves the change landed (e.g. ``("ef", 128)``). ``expect=None`` skips the
    equality check but still requires the attribute to exist.
    """
    errors: list[str] = []

    # Path 1: named-vector update (preferred for vector_config collections).
    vectors_ns = getattr(Reconfigure, "Vectors", None)
    if vectors_ns is not None and hasattr(vectors_ns, "update"):
        try:
            collection.config.update(
                vector_config=vectors_ns.update(name=VECTOR_NAME, vector_index_config=make_vic())
            )
            got = _read_index_attr(collection, verify_attr)
            if expect is None or got == expect:
                return "named-vector"
            errors.append(f"named-vector path applied but read-back {verify_attr}={got!r}")
        except Exception as exc:  # noqa: BLE001 - collected and re-raised below
            errors.append(f"named-vector path failed: {exc}")

    # Path 2: legacy kwarg.
    try:
        collection.config.update(vector_index_config=make_vic())
        got = _read_index_attr(collection, verify_attr)
        if expect is None or got == expect:
            return "legacy"
        errors.append(f"legacy path applied but read-back {verify_attr}={got!r}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"legacy path failed: {exc}")

    raise ReconfigError(
        "vector-index reconfiguration did not take effect on named vector "
        f"'{VECTOR_NAME}' (expected {verify_attr}={expect!r}). Tried: " + " | ".join(errors)
    )
