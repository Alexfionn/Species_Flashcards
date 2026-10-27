"""Baut aus einer Liste von Arten ein PDF: pro 8 Arten eine Vorder- und eine Rückseite.

Spiegelung: Auf der Rückseite tauschen links und rechts die Plätze. Das passt zum
Duplexdruck mit "an langer Kante wenden".
"""
import html
from pathlib import Path

from weasyprint import HTML

from config import ASSETS, CARDS_PER_SHEET
from images import card_images
from notion_api import Species

SLOT_W, SLOT_H = 105.0, 74.25     # mm, Viertel einer A4-Seite
ROWS, COLS = 4, 2


def _esc(s: str) -> str:
    return html.escape(s or "")


def _name_sizes(sp: Species) -> tuple[float, float]:
    """Artnamen bleiben gross. Nur sehr lange Namen (z. B. Unterarten) werden leicht kleiner."""
    sci = 14.0 if len(sp.name_sci) <= 28 else 12.5
    de = 12.0 if len(sp.name_de or "") <= 32 else 11.0
    return sci, de


def _detail_size(sp: Species) -> float:
    """Taxon, Kurzbeschreibung und Vorkommen dürfen kleiner werden. Lange Zeilen brechen um."""
    lines = [sp.taxon, sp.description, sp.habitat]
    longest = max((len(x or "") for x in lines), default=0)
    total = sum(len(x or "") for x in lines)
    size = 10.0
    if longest > 40 or total > 90:
        size = 9.0
    if longest > 55 or total > 120:
        size = 8.5
    return size


def _front_card(sp: Species) -> str:
    uris = card_images([Path(p) for p in sp.image_paths])
    if not uris:
        inner = '<div class="empty"></div>'
    else:
        cls = "one" if len(uris) == 1 else "two"
        imgs = "".join(f'<img src="{u}" alt="">' for u in uris)
        inner = f'<div class="images {cls}">{imgs}</div>'
    return f'<div class="card"><div class="card-inner">{inner}</div></div>'


def _back_card(sp: Species) -> str:
    sci_size, de_size = _name_sizes(sp)
    small = _detail_size(sp)
    parts = [
        f'<div class="taxon" style="font-size:{small}pt">{_esc(sp.taxon)}</div>',
        f'<div class="sci" style="font-size:{sci_size}pt">{_esc(sp.name_sci)}</div>',
    ]
    if sp.name_de:
        parts.append(f'<div class="de" style="font-size:{de_size}pt">({_esc(sp.name_de)})</div>')
    if sp.description:
        parts.append(f'<div class="desc" style="font-size:{small}pt">{_esc(sp.description)}</div>')
    if sp.habitat:
        parts.append(f'<div class="hab" style="font-size:{small}pt">{_esc(sp.habitat)}</div>')
    body = "".join(parts)
    return (f'<div class="card"><div class="card-inner">'
            f'<div class="text">{body}</div></div></div>')


def _sheet(cards: list[str], mirrored: bool) -> str:
    """Ordnet 8 Karten im Raster an. mirrored=True tauscht die Spalten."""
    out = ['<div class="sheet">', '<div class="cut-v"></div>']
    for r in range(1, ROWS):
        out.append(f'<div class="cut-h" style="top:{r * SLOT_H}mm"></div>')
    for i, card in enumerate(cards):
        r, c = divmod(i, COLS)
        if mirrored:
            c = COLS - 1 - c
        out.append(f'<div class="slot" style="left:{c * SLOT_W}mm; top:{r * SLOT_H}mm">{card}</div>')
    out.append("</div>")
    return "".join(out)


def build_html(species: list[Species]) -> str:
    sheets = []
    for start in range(0, len(species), CARDS_PER_SHEET):
        batch = species[start:start + CARDS_PER_SHEET]
        sheets.append(_sheet([_front_card(s) for s in batch], mirrored=False))
        sheets.append(_sheet([_back_card(s) for s in batch], mirrored=True))
    return ('<!doctype html><html><head><meta charset="utf-8">'
            '<link rel="stylesheet" href="card.css"></head><body>'
            + "".join(sheets) + "</body></html>")


def build_pdf(species: list[Species], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    html_text = build_html(species)
    HTML(string=html_text, base_url=str(ASSETS) + "/").write_pdf(str(target))
    return target
