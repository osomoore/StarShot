"""One-off cleanup: purge ship designs owned by accounts that no longer
exist, are soft-deleted, or are stale guests.

The player ship library (``.starshot/content/ship_designs/players/<uid>/``)
accumulates one folder per owner and is never swept automatically — accounts
deleted before ``delete_owner_designs`` was wired into account purging, and
any other orphaned owner ids, leave their designs behind forever. This scans
every owner folder, checks the owner against the v2 database, and removes
designs for owners that are gone, deleted, or guests.

Usage:
    python scripts/cleanup_orphaned_ship_designs.py            # dry run
    python scripts/cleanup_orphaned_ship_designs.py --apply    # actually delete
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from starshot.v2 import ship_designs  # noqa: E402
from starshot.v2.store import get_v2_store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--apply", action="store_true", help="Actually delete. Without this, only reports.")
    args = parser.parse_args(argv)

    store = get_v2_store()
    owner_ids = ship_designs.list_player_owner_ids()
    print(f"Scanning {len(owner_ids)} player ship-design owner folders...")

    to_purge: list[tuple[int, str]] = []
    for owner_id in owner_ids:
        user = store.get_user(owner_id)
        if user is None:
            reason = "no matching account"
        elif user.get("deleted_at"):
            reason = "account deleted"
        elif user.get("is_guest"):
            reason = "guest account"
        else:
            continue
        design_count = len(ship_designs.list_designs(owner_id))
        to_purge.append((owner_id, reason))
        print(f"  owner #{owner_id}: {design_count} design(s) - {reason}")

    if not to_purge:
        print("Nothing to clean up.")
        return 0

    print(f"\n{len(to_purge)} owner folder(s) to remove.")
    if not args.apply:
        print("Dry run only - re-run with --apply to delete.")
        return 0

    total_designs = 0
    for owner_id, _reason in to_purge:
        total_designs += ship_designs.delete_owner_designs(owner_id)
    print(f"Deleted {total_designs} design(s) across {len(to_purge)} owner folder(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
