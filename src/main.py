"""Täglicher Lauf: Collector -> Ergänzen -> PDF -> Study Calendar -> Index.

Modi:
  python src/main.py              echter Lauf (schreibt in Notion)
  python src/main.py --dry-run    liest Notion und baut das PDF, schreibt NICHTS in Notion
  python src/main.py --demo       ganz ohne Notion und ohne KI: Beispielkarten -> output/demo.pdf
  python src/main.py --no-ai      wie echter Lauf, aber ohne Claude (leere Felder bleiben leer)

Die Schritte 1 bis 6 ändern nichts in Notion. Erst wenn das PDF sicher in der
Study Calendar liegt, werden die Arten verschoben.
"""
import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import OUTPUT, CARDS_PER_SHEET, TITLE_FORMAT   # noqa: E402
import notion_api as notion                                   # noqa: E402
from notion_api import Species                                # noqa: E402
from layout import build_pdf                                  # noqa: E402


def log(msg: str):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Schritt 1 + 2: lesen und prüfen
# ---------------------------------------------------------------------------

def collect(workdir: Path) -> tuple[list[Species], list[Species]]:
    """Gibt (gültige Arten, Arten mit Problem) zurück. Lädt die Bilder der gültigen Arten."""
    all_species = notion.query_collector()
    log(f"Collector: {len(all_species)} Seiten gefunden")

    good, bad = [], []
    for sp in all_species:
        if not sp.name_sci:
            sp.problem = "Kein wissenschaftlicher Name"
            bad.append(sp)
            continue
        sp.image_urls = notion.get_image_urls(sp.page_id)
        if not sp.image_urls:
            sp.problem = "Kein Bild in der Seite"
            bad.append(sp)
            continue
        good.append(sp)
    return good, bad


def download_images(species: list[Species], workdir: Path):
    for i, sp in enumerate(species):
        for j, url in enumerate(sp.image_urls):
            ext = ".jpg"
            for cand in (".png", ".jpeg", ".jpg", ".webp", ".gif"):
                if cand in url.split("?")[0].lower():
                    ext = cand
                    break
            target = workdir / f"{i:02d}_{j}{ext}"
            notion.download(url, target)
            sp.image_paths.append(str(target))


# ---------------------------------------------------------------------------
# Demo-Daten (ohne Notion)
# ---------------------------------------------------------------------------

def demo_species(workdir: Path) -> list[Species]:
    from PIL import Image, ImageDraw
    names = [
        ("Bryopsida", "Fissidens taxifolius", "Eibenblättriges Schwertmoos", "Abgeflacht, Rippe als Stachelspitze", "Feuchte Waldböden, Mitteleuropa"),
        ("Dryopteridaceae", "Dryopteris filix-mas", "Echter Wurmfarn", "Lanzettlich, 1,5-fach gefiedert", "Wälder, ganz Europa"),
        ("Aspleniaceae", "Asplenium scolopendrium", "Hirschzunge", "Blätter ungeteilt, Sori strichförmig", "Schattige Schluchtwälder"),
        ("Coleoptera", "Carabus auronitens", "Goldglänzender Laufkäfer", "Metallisch grün, rote Beine", "Laub- und Bergwälder"),
        ("Artiodactyla", "Cervus elaphus", "Rothirsch", "Grösstes Wildtier, Geweih", "Wälder, Alpen, Mittelland"),
        ("Passeriformes", "Erithacus rubecula", "Rotkehlchen", "Orangerote Brust, rund", "Wälder, Gärten, Hecken"),
        ("Basidiomycota", "Amanita muscaria", "Fliegenpilz", "Roter Hut mit weissen Flocken", "Unter Birken und Fichten"),
        ("Flechte", "Xanthoria parietina", "Gewöhnliche Gelbflechte", "Gelb-orange, blattförmig", "Rinde, Mauern, nährstoffreich"),
    ]
    out = []
    for i, (taxon, sci, de, desc, hab) in enumerate(names):
        sp = Species(page_id=f"demo-{i}", name_sci=sci, name_de=de, taxon=taxon,
                     description=desc, habitat=hab)
        n_images = 2 if i % 3 == 1 else 1
        for j in range(n_images):
            img = Image.new("RGB", (1200, 900), (60 + 20 * i, 120 + 10 * j, 70))
            d = ImageDraw.Draw(img)
            d.ellipse((200, 150, 1000, 750), fill=(140 + 10 * i, 190, 110))
            d.text((40, 40), f"{sci}  (Bild {j + 1})", fill=(255, 255, 255))
            p = workdir / f"demo_{i}_{j}.jpg"
            img.save(p, "JPEG", quality=85)
            sp.image_paths.append(str(p))
        if i == 2:
            sp.ai_filled = ["taxon"]
        out.append(sp)
    return out


# ---------------------------------------------------------------------------
# Hauptablauf
# ---------------------------------------------------------------------------

def run(mode: str, use_ai: bool):
    today = date.today()
    date_iso = today.isoformat()
    workdir = OUTPUT / "work"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    if mode == "demo":
        species = demo_species(workdir)
        pdf = build_pdf(species, OUTPUT / "demo.pdf")
        log(f"Demo-PDF erstellt: {pdf}")
        return

    # 1 + 2: lesen, prüfen
    good, bad = collect(workdir)
    for sp in bad:
        log(f"  übersprungen: {sp.name_sci or sp.page_id} -> {sp.problem}")
        if mode == "run":
            notion.set_note(sp.page_id, sp.problem)

    # 3: Bögen zählen
    n_sheets = len(good) // CARDS_PER_SHEET
    if n_sheets == 0:
        log(f"{len(good)} gültige Arten, es braucht {CARDS_PER_SHEET}. Nichts zu tun.")
        return
    selected = good[: n_sheets * CARDS_PER_SHEET]
    log(f"{len(good)} gültige Arten -> {n_sheets} Bogen/Bögen mit {len(selected)} Arten")

    # 4: ergänzen
    if use_ai:
        from enrich import enrich
        enrich(selected)
        dropped = [s for s in selected if not s.ok]
        for sp in dropped:
            log(f"  zurückgestellt: {sp.name_sci} -> {sp.problem}")
            if mode == "run":
                notion.set_note(sp.page_id, sp.problem)
        selected = [s for s in selected if s.ok]
        # Nach dem Zurückstellen können es wieder zu wenige sein
        n_sheets = len(selected) // CARDS_PER_SHEET
        if n_sheets == 0:
            log("Nach der KI-Prüfung bleiben zu wenige Arten übrig. Nichts zu tun.")
            return
        selected = selected[: n_sheets * CARDS_PER_SHEET]
        for sp in selected:
            if sp.ai_filled:
                log(f"  KI ergänzt bei {sp.name_sci}: {', '.join(sp.ai_filled)}")

    # 5: Bilder laden
    download_images(selected, workdir)

    # 6: PDF
    pdf_name = f"flashcards_{date_iso}.pdf"
    pdf = build_pdf(selected, OUTPUT / pdf_name)
    log(f"PDF erstellt: {pdf} ({pdf.stat().st_size / 1024:.0f} KB)")

    if mode == "dry-run":
        log("Testlauf: nichts in Notion geändert.")
        return

    # 7: Study Calendar
    upload_id = notion.upload_file(pdf)
    title = TITLE_FORMAT.format(date=today.strftime("%d.%m.%Y"))
    url = notion.create_studyplan_page(title, date_iso, upload_id)
    log(f"Study-Calendar-Seite angelegt: {url}")

    # 8: verschieben und abschliessen
    for sp in selected:
        notion.move_to_index(sp.page_id)
        notion.finalize_in_index(sp, date_iso)
        log(f"  -> Index: {sp.name_sci}")
    log("Fertig.")


def main():
    ap = argparse.ArgumentParser(description="Species Flashcards")
    ap.add_argument("--demo", action="store_true", help="ohne Notion, ohne KI, Beispielkarten")
    ap.add_argument("--dry-run", action="store_true", help="liest Notion, schreibt nichts")
    ap.add_argument("--no-ai", action="store_true", help="ohne Claude-Ergänzung")
    args = ap.parse_args()
    mode = "demo" if args.demo else ("dry-run" if args.dry_run else "run")
    run(mode, use_ai=not args.no_ai)


if __name__ == "__main__":
    main()
