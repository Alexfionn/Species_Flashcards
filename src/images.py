"""Bilder zuschneiden und verkleinern.

Ein Bild füllt den Rahmen (Querformat), zwei Bilder stehen nebeneinander (je Hochformat).
Zugeschnitten wird immer mittig; Ränder können dabei verloren gehen.
"""
import base64
import io
from pathlib import Path

from PIL import Image, ImageOps

# Innenfläche einer Karte: ca. 86 x 56 mm. Bei 300 dpi sind das rund 1016 x 661 px.
SINGLE = (1000, 650)     # ein Bild, Querformat
DOUBLE = (500, 650)      # zwei Bilder, je Hochformat
JPEG_QUALITY = 82


def _prepare(path: Path, size: tuple[int, int]) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)          # Handy-Fotos richtig drehen
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return ImageOps.fit(img, size, method=Image.LANCZOS, centering=(0.5, 0.5))


def to_data_uri(path: Path, size: tuple[int, int]) -> str:
    """Bild zuschneiden und als base64-JPEG für das HTML zurückgeben."""
    img = _prepare(path, size)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def save_resized(src: Path, dst: Path, max_edge: int = 900, quality: int = 80) -> Path:
    """Für die Lernseite: Bild drehen, auf max_edge verkleinern (nicht zuschneiden), als JPEG speichern."""
    img = ImageOps.exif_transpose(Image.open(src))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((max_edge, max_edge), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(dst, "JPEG", quality=quality, optimize=True, progressive=True)
    return dst


def card_images(paths: list[Path]) -> list[str]:
    """Liefert 1 oder 2 Data-URIs, passend zugeschnitten."""
    if not paths:
        return []
    if len(paths) == 1:
        return [to_data_uri(paths[0], SINGLE)]
    return [to_data_uri(p, DOUBLE) for p in paths[:2]]
