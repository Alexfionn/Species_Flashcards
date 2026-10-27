# Species Flashcards

Täglich aus Arten in Notion druckbare Flashcards (A4, doppelseitig) erzeugen.

Einrichtung: siehe [ANLEITUNG.md](ANLEITUNG.md).

## Befehle

```
python src/check_setup.py        Notion-Verbindung und Properties prüfen
python src/main.py --demo        Beispiel-PDF ohne Notion  -> output/demo.pdf
python src/main.py --dry-run     Notion lesen, PDF bauen, nichts schreiben
python src/main.py               echter Lauf
```

## Aufbau

```
config.json                 IDs, Property-Namen, Modell
src/main.py                 Ablauf (8 Schritte, siehe Docstring)
src/notion_api.py           Notion lesen/schreiben/verschieben
src/enrich.py               fehlende Felder mit Claude ergänzen
src/images.py               Bilder zuschneiden
src/layout.py               PDF aus HTML/CSS (WeasyPrint)
src/check_setup.py          Einrichtung prüfen
assets/card.css             Kartenlayout
assets/fonts/               Poppins (OFL)
.github/workflows/daily.yml täglicher Lauf
```

## Ablauf eines Laufs

1. Collector lesen (älteste zuerst)
2. Arten ohne Namen oder Bild überspringen, Hinweis setzen
3. Nur volle Bögen à 8 Arten verarbeiten
4. Leere Felder mit Claude ergänzen (nie überschreiben)
5. Bilder laden und zuschneiden
6. PDF bauen
7. PDF in Study Calendar hochladen, Seite anlegen
8. Arten in den Index verschieben, Felder nachtragen

Bis Schritt 6 wird nichts in Notion geändert.
