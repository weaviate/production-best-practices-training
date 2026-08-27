"""Idempotent lab reset: drop lab collections, clean aliases, re-seed baseline.

Safe to run any number of times, at any point in any lab. Only touches
collections owned by the labs (``Acme*`` + the incident scratch space) -
it will never delete anything else.

Run:  python -m acme.reset [--no-seed]
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console

from acme import schema, seed
from acme.client import connect

console = Console(stderr=True)

# Everything reset is allowed to delete. Nothing else, ever.
OWNED_COLLECTIONS: tuple[str, ...] = (
    *schema.LAB_COLLECTIONS,
    "IncidentScratch",  # created only by the instructor incident injector
)
OWNED_ALIAS_PREFIX = "Acme"


def teardown() -> list[str]:
    """Delete lab-owned aliases and collections; returns what was removed."""
    removed: list[str] = []
    with connect() as client:
        # Aliases first: deleting a collection does NOT delete its aliases
        # (dangling aliases are a documented footgun - see r3 §9).
        try:
            aliases = client.alias.list_all()
        except Exception as exc:  # noqa: BLE001 - alias API optional for teardown
            console.print(f"[yellow]alias listing unavailable ({exc}); skipping[/yellow]")
            aliases = {}
        for alias_name in list(aliases):
            if str(alias_name).startswith(OWNED_ALIAS_PREFIX):
                client.alias.delete(alias_name=str(alias_name))
                removed.append(f"alias:{alias_name}")
        for name in OWNED_COLLECTIONS:
            if client.collections.exists(name):
                client.collections.delete(name)
                removed.append(f"collection:{name}")
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset the Acme lab state.")
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="teardown only; skip re-seeding the baseline dataset",
    )
    args = parser.parse_args(argv)

    removed = teardown()
    if removed:
        console.print(f"[cyan]Removed:[/cyan] {', '.join(removed)}")
    else:
        console.print("[cyan]Nothing to remove (already clean).[/cyan]")

    if args.no_seed:
        console.print("[green]Reset complete (teardown only).[/green]")
        return 0

    console.print("[cyan]Re-seeding baseline…[/cyan]")
    rc = seed.main(["--target", "all"])
    if rc == 0:
        console.print("[green bold]Reset complete - baseline restored.[/green bold]")
    return rc


if __name__ == "__main__":
    sys.exit(main())
