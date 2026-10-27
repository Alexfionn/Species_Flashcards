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


def _font_size(sp: Species) -> float:
    """Schrift verkleinern, wenn der Text für die Karte zu lang ist."""
    lines = [sp.taxon, sp.name_sci, sp.name_de, sp.description, sp.habitat]
    longest = max((len(x or "") for x in lines), default=0)
    total = sum(len(x or "") for x in lines)
    size = 11.5
    if longest > 30 or total > 110:
        size = 10.5
    if longest > 38 or total > 140:
        size = 9.5
    if longest > 46 or total > 170:
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
    size = _font_size(sp)
    parts = [
        f'<div class="taxon">{_esc(sp.taxon)}</div>',
        f'<div class="sci">{_esc(sp.name_sci)}</div>',
    ]
    if sp.name_de:
        parts.append(f'<div class="de">({_esc(sp.name_de)})</div>')
    if sp.description:
        parts.append(f'<div class="desc">{_esc(sp.description)}</div>')
    if sp.habitat:
        parts.append(f'<div class="hab">{_esc(sp.habitat)}</div>')
    body = "".join(parts)
    return (f'<div class="card"><div class="card-inner">'
            f'<div class="text" style="font-size:{size}pt">{body}</div></div></div>')


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
