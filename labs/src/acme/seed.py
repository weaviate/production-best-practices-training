"""Seed the Acme lab cluster from the deterministic dataset.

Ingestion contract (this is course doctrine, not incidental code):

* SERVER-SIDE BATCHING via ``collection.batch.stream()`` - the server tells
  the client the ideal next send size (EMA backpressure); no manual batch
  size tuning. GA: server 1.36+, python client 4.20+.
* DETERMINISTIC IDs via ``generate_uuid5(product_id)`` - re-runs are
  idempotent upserts, and retrying ``failed_objects`` can never duplicate.
* FAILED-OBJECT CAPTURE - after each stream closes, ``batch.failed_objects``
  is inspected; ANY failure makes the process exit non-zero and print a
  sample. Silent partial imports are how benchmark lies begin.

Run:  python -m acme.seed [--target all|product|hfresh|mt] [--mt-count N]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from typing import Any

import numpy as np
import numpy.typing as npt
from rich.console import Console
from rich.progress import Progress
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.util import generate_uuid5

from acme import schema
from acme.client import connect
from acme.dataset import LabDataset, load_dataset

console = Console(stderr=True)

# Abort a stream early if the error counter blows past this (misconfiguration,
# not transient flakiness - e.g. schema mismatch fails every object).
MAX_ERRORS_BEFORE_ABORT = 50
DEFAULT_MT_COUNT = 12_000  # objects seeded into the MT variant (keeps lab timeboxes)


def product_uuid(product_id: str) -> str:
    """Deterministic UUIDv5 for a Acme product id (idempotent imports)."""
    return str(generate_uuid5(product_id))


def _stream_objects(
    collection: Collection,
    objects: list[dict[str, Any]],
    vectors: npt.NDArray[np.float32],
    *,
    progress: Progress | None = None,
    task_label: str = "seeding",
) -> list[str]:
    """Import objects via server-side batching; return failure descriptions."""
    task = progress.add_task(task_label, total=len(objects)) if progress else None
    with collection.batch.stream() as batch:
        for obj in objects:
            batch.add_object(
                properties=obj,
                uuid=product_uuid(str(obj["product_id"])),
                vector={schema.VECTOR_NAME: vectors[int(obj["vec_id"])].tolist()},
            )
            if progress is not None and task is not None:
                progress.advance(task)
            if batch.number_errors > MAX_ERRORS_BEFORE_ABORT:
                console.print(
                    f"[red]Aborting stream: {batch.number_errors} errors "
                    f"(> {MAX_ERRORS_BEFORE_ABORT}) - fix the cause, then re-run "
                    "(deterministic IDs make re-runs safe).[/red]"
                )
                break
    # failed_objects reset when a new batching context opens - copy them now.
    failures = [f"uuid={fo.object_.uuid} err={fo.message}" for fo in list(batch.failed_objects)]
    return failures


def seed_single_collection(
    client: WeaviateClient,
    name: str,
    ds: LabDataset,
    *,
    progress: Progress | None = None,
) -> list[str]:
    collection = client.collections.use(name)
    return _stream_objects(
        collection, ds.objects, ds.vectors, progress=progress, task_label=f"[cyan]{name}"
    )


def seed_mt_collection(
    client: WeaviateClient,
    ds: LabDataset,
    *,
    mt_count: int = DEFAULT_MT_COUNT,
    progress: Progress | None = None,
) -> list[str]:
    """Seed the MT variant: one server-side stream per tenant.

    The batching machinery is not shareable across tenant handles; grouping by
    tenant also mirrors how per-tenant ingestion actually arrives in a SaaS.
    """
    collection = client.collections.use(schema.COLLECTION_MT)
    subset = ds.objects[:mt_count]
    by_tenant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in subset:
        by_tenant[str(obj["tenant"])].append(obj)
    failures: list[str] = []
    for tenant, objs in sorted(by_tenant.items()):
        tenant_handle = collection.with_tenant(tenant)
        failures.extend(
            _stream_objects(
                tenant_handle,
                objs,
                ds.vectors,
                progress=progress,
                task_label=f"[magenta]{schema.COLLECTION_MT}/{tenant}",
            )
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the Acme lab cluster.")
    parser.add_argument(
        "--target",
        choices=("all", "product", "hfresh", "mt"),
        default="all",
        help="which collection(s) to seed (default: all)",
    )
    parser.add_argument("--mt-count", type=int, default=DEFAULT_MT_COUNT)
    args = parser.parse_args(argv)

    ds = load_dataset()
    console.print(
        f"[bold]Acme seed[/bold]: {ds.count} objects, dim={ds.dim}, "
        f"seed={ds.manifest.get('seed', 'unknown')}"
    )

    failures: list[str] = []
    with connect() as client:
        schema.ensure_baseline_collections(client)
        with Progress(console=console) as progress:
            if args.target in ("all", "product"):
                failures += seed_single_collection(
                    client, schema.COLLECTION_PRODUCT, ds, progress=progress
                )
            if args.target in ("all", "hfresh"):
                failures += seed_single_collection(
                    client, schema.COLLECTION_HFRESH, ds, progress=progress
                )
            if args.target in ("all", "mt"):
                failures += seed_mt_collection(
                    client, ds, mt_count=args.mt_count, progress=progress
                )

    if failures:
        console.print(f"[red bold]SEED FAILED: {len(failures)} object(s) were rejected.[/red bold]")
        for line in failures[:10]:
            console.print(f"[red]  {line}[/red]")
        if len(failures) > 10:
            console.print(f"[red]  … and {len(failures) - 10} more[/red]")
        console.print(
            "[yellow]Re-running seed is safe: deterministic UUIDs make imports "
            "idempotent. Fix the cause first (see errors above).[/yellow]"
        )
        return 1

    console.print("[green bold]Seed complete - zero failed objects.[/green bold]")
    console.print("Next: python -m acme.verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
