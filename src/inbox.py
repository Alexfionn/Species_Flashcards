"""Überträgt Einträge aus der iPhone-App in den Species collector.

Die App legt pro Art einen Ordner an:
    inbox/<id>/1.jpg, 2.jpg (optional), entry.json (immer zuletzt)

Dieses Skript lädt die Bilder zu Notion hoch, legt die Seite im Collector an
und löscht den Ordner danach. Ein Ordner ohne entry.json wird ignoriert
(die App ist dann noch am Hochladen). Ein fehlgeschlagener Eintrag bleibt liegen
und wird beim nächsten Lauf erneut versucht.

  python src/inbox.py
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import ROOT          # noqa: E402
import notion_api as notion      # noqa: E402
from notion_api import Species   # noqa: E402

INBOX = ROOT / "inbox"


def process(folder: Path) -> str:
    entry = json.loads((folder / "entry.json").read_text(encoding="utf-8"))
    name = (entry.get("name_sci") or "").strip()
    if not name:
        raise ValueError("entry.json ohne wissenschaftlichen Namen")

    sp = Species(
        page_id="",
        name_sci=name,
        name_de=(entry.get("name_de") or "").strip(),
        taxon=(entry.get("taxon") or "").strip(),
        description=(entry.get("description") or "").strip(),
        habitat=(entry.get("habitat") or "").strip(),
    )

    upload_ids = []
    for img_name in entry.get("images", [])[:2]:
        path = folder / img_name
        if path.exists():
            upload_ids.append(notion.upload_file(path, content_type="image/jpeg"))

    return notion.create_collector_page(sp, upload_ids)


def main():
    if not INBOX.exists():
        print("Inbox leer.")
        return
    folders = sorted(p for p in INBOX.iterdir() if p.is_dir() and (p / "entry.json").exists())
    if not folders:
        print("Keine fertigen Einträge.")
        return

    failed = 0
    for folder in folders:
        try:
            url = process(folder)
            shutil.rmtree(folder)
            print(f"ok   {folder.name} -> {url}")
        except Exception as e:      # ein Fehler soll die anderen Einträge nicht blockieren
            failed += 1
            print(f"FEHLER {folder.name}: {e}")

    if failed:
        print(f"{failed} Eintrag/Einträge fehlgeschlagen. Sie bleiben in der Inbox.")
        sys.exit(1)


if __name__ == "__main__":
    main()
