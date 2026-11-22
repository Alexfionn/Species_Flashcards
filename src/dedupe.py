"""Remove duplicate species from the Species Index.

Two pages count as duplicates when their scientific name is the same
(case and extra spaces ignored). Of each group one page is kept:
the one with the most filled fields, and if that is a tie, the oldest.
The others are moved to the Notion trash (restorable for 30 days).

  python src/dedupe.py            dry run: only lists what would be removed
  python src/dedupe.py --apply    actually moves the duplicates to the trash
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import notion_api as notion   # noqa: E402

FIELDS = ("de", "taxon", "desc", "hab", "group", "printed")


def key(name: str) -> str:
    return " ".join(name.lower().split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="move duplicates to the trash")
    args = ap.parse_args()

    groups = defaultdict(list)
    for it in notion.query_index():
        if it["sci"]:
            groups[key(it["sci"])].append(it)

    removed = 0
    for items in groups.values():
        if len(items) < 2:
            continue
        # most filled fields first, then oldest
        items.sort(key=lambda it: (-sum(bool(it[f]) for f in FIELDS), it["created"]))
        keep, extra = items[0], items[1:]
        print(f"{keep['sci']}: keep 1, remove {len(extra)}")
        for it in extra:
            if args.apply:
                notion._patch(f"/pages/{it['id']}", {"in_trash": True})
            removed += 1

    if args.apply:
        print(f"Done: {removed} duplicates moved to the Notion trash.")
    else:
        print(f"Dry run: {removed} duplicates would be removed. Run with --apply to remove them.")


if __name__ == "__main__":
    main()
