"""Baut die Lernseite aus dem Species Index.

Ablauf:
  1. Index lesen
  2. Fehlende Gruppen mit Claude nachtragen und in Notion zurückschreiben
  3. Bilder neuer oder geänderter Arten laden und verkleinern (Rest kommt aus dem Cache)
  4. public/ bauen: Lernseite aus site/, Bilder in img/, species.json

Notion-Bildlinks laufen nach etwa einer Stunde ab. Darum werden die Bilder kopiert.

  python src/deck.py            normaler Lauf
  python src/deck.py --no-ai    ohne Claude (Arten ohne Gruppe landen in "Ohne Gruppe")
"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import DECK, DECK_CACHE, GROUPS, PUBLIC, SITE   # noqa: E402
import notion_api as notion                                  # noqa: E402
from images import save_resized                              # noqa: E402

NO_GROUP = "Ohne Gruppe"
IMG_CACHE = DECK_CACHE / "img"
MANIFEST = DECK_CACHE / "manifest.json"


def log(msg: str):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Schritt 2: Gruppen
# ---------------------------------------------------------------------------

def fill_groups(items: list[dict], manifest: dict):
    missing = [it for it in items if it["sci"] and not it["group"]]
    if not missing:
        return
    from enrich import assign_groups
    log(f"{len(missing)} Arten ohne Gruppe -> Claude")
    answer = assign_groups(missing)
    for it in missing:
        group = answer.get(it["sci"], "")
        if not group:
            log(f"  keine eindeutige Gruppe: {it['sci']}")
            continue
        old_edited = it["edited"]
        try:
            new_edited = notion.set_group(it["id"], group)
        except RuntimeError as e:
            log(f"  Gruppe nicht gespeichert ({it['sci']}): {e}")
            continue
        it["group"] = group
        if new_edited:
            it["edited"] = new_edited
            # Eigene Änderung soll keinen neuen Bild-Download auslösen
            entry = manifest.get(it["id"])
            if entry and entry.get("edited") == old_edited:
                entry["edited"] = new_edited
        log(f"  {it['sci']} -> {group}")


# ---------------------------------------------------------------------------
# Schritt 3: Bilder
# ---------------------------------------------------------------------------

def _file_name(page_id: str, n: int, edited: str) -> str:
    tag = hashlib.sha1(edited.encode()).hexdigest()[:8]     # neuer Name nach Änderung -> kein alter Browser-Cache
    return f"{page_id.replace('-', '')}_{n}_{tag}.jpg"


def fetch_images(it: dict) -> list[str]:
    urls = notion.get_image_urls(it["id"])
    files = []
    with tempfile.TemporaryDirectory() as tmp:
        for n, url in enumerate(urls, start=1):
            raw = notion.download(url, Path(tmp) / f"raw_{n}")
            name = _file_name(it["id"], n, it["edited"])
            save_resized(raw, IMG_CACHE / name,
                         max_edge=int(DECK.get("image_max_edge", 900)),
                         quality=int(DECK.get("image_quality", 80)))
            files.append(name)
    return files


def update_images(items: list[dict], manifest: dict) -> dict:
    IMG_CACHE.mkdir(parents=True, exist_ok=True)
    new_manifest, loaded, reused = {}, 0, 0
    for it in items:
        if not it["sci"]:
            continue
        entry = manifest.get(it["id"])
        cached_ok = (entry and entry.get("edited") == it["edited"]
                     and all((IMG_CACHE / f).exists() for f in entry.get("images", [])))
        if cached_ok:
            files = entry["images"]
            reused += 1
        else:
            try:
                files = fetch_images(it)
                loaded += 1
            except Exception as e:      # ein kaputtes Bild soll den Lauf nicht stoppen
                log(f"  Bilder fehlgeschlagen ({it['sci']}): {e}")
                files = entry.get("images", []) if entry else []
        new_manifest[it["id"]] = {"edited": it["edited"], "images": files}

    keep = {f for e in new_manifest.values() for f in e["images"]}
    removed = 0
    for f in IMG_CACHE.iterdir():
        if f.name not in keep:
            f.unlink()
            removed += 1
    log(f"Bilder: {loaded} Arten neu geladen, {reused} aus dem Cache, {removed} alte Dateien entfernt")
    return new_manifest


# ---------------------------------------------------------------------------
# Schritt 4: Seite bauen
# ---------------------------------------------------------------------------

def build_public(items: list[dict], manifest: dict):
    cards, no_image = [], []
    for it in items:
        if not it["sci"]:
            continue
        files = manifest.get(it["id"], {}).get("images", [])
        if not files:
            no_image.append(it["sci"])
            continue
        cards.append({
            "id": it["id"].replace("-", "")[-12:],
            "sci": it["sci"], "de": it["de"], "taxon": it["taxon"],
            "desc": it["desc"], "hab": it["hab"],
            "group": it["group"] or NO_GROUP,
            "added": (it["printed"] or it["created"])[:10],
            "images": [f"img/{f}" for f in files],
        })
    cards.sort(key=lambda c: c["sci"].lower())
    if no_image:
        log(f"Ohne Bild, nicht in der Lernseite: {', '.join(no_image)}")

    groups = [g for g in GROUPS]
    if any(c["group"] == NO_GROUP for c in cards):
        groups.append(NO_GROUP)

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    shutil.copytree(SITE, PUBLIC)
    shutil.copytree(IMG_CACHE, PUBLIC / "img")
    data = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "new_days": int(DECK.get("new_days", 14)),
        "groups": groups,
        "species": cards,
    }
    (PUBLIC / "species.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (PUBLIC / ".nojekyll").write_text("")
    log(f"Lernseite gebaut: {len(cards)} Arten in {PUBLIC}")


def main():
    ap = argparse.ArgumentParser(description="Lernseite aus dem Species Index bauen")
    ap.add_argument("--no-ai", action="store_true", help="keine Gruppen mit Claude nachtragen")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    items = notion.query_index()
    log(f"Species Index: {len(items)} Seiten")

    if not args.no_ai:
        fill_groups(items, manifest)
    manifest = update_images(items, manifest)
    DECK_CACHE.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    build_public(items, manifest)


if __name__ == "__main__":
    main()
