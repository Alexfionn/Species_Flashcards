"""Fehlende Felder mit der Claude API ergänzen.

Regeln:
- Nur leere Felder werden gefüllt. Eigene Einträge werden nie überschrieben.
- Taxon-Ebene je Gruppe (immer lateinisch):
    Moose -> Klasse, übrige Pflanzen (inkl. Farne) -> Familie,
    Pilze -> Stamm (Phylum), Flechten -> "Flechte",
    Gliederfüsser -> Ordnung, Wirbeltiere -> Ordnung, alles andere -> Ordnung.
- Unbekannter wissenschaftlicher Name -> die Art wird nicht geraten, sondern markiert.
"""
import json
import re

import anthropic

from config import CLAUDE_MODEL, anthropic_key
from notion_api import Species

FIELDS = ("name_de", "taxon", "description", "habitat")

SYSTEM = """Du bist ein präziser Taxonomie-Assistent für Lernkarten (Studium Biologie, Schweiz).
Du bekommst eine Liste von Arten mit ihrem wissenschaftlichen Namen und teils schon ausgefüllten Feldern.
Ergänze NUR Felder, die leer sind. Antworte ausschliesslich mit JSON, ohne Erklärungen.

Regeln für "taxon" (immer der lateinische Name, nie deutsch):
- Moose (Bryophyta, Marchantiophyta, Anthocerotophyta): die KLASSE (z. B. Bryopsida, Jungermanniopsida)
- Farne und alle anderen Pflanzen: die FAMILIE (z. B. Dryopteridaceae, Rosaceae)
- Pilze: der STAMM / das Phylum (z. B. Basidiomycota, Ascomycota)
- Flechten: genau das Wort "Flechte"
- Gliederfüsser (Arthropoda): die ORDNUNG (z. B. Coleoptera, Araneae)
- Wirbeltiere: die ORDNUNG (z. B. Passeriformes, Artiodactyla)
- Alle übrigen Tiere: die ORDNUNG

Weitere Regeln:
- "name_de": der gebräuchliche deutsche Name. Gibt es keinen etablierten, schreibe "".
- "description": höchstens 5 Wörter, Merkmale zum Erkennen im Feld. Kein Punkt am Ende.
- "habitat": allgemeiner Lebensraum oder Verbreitung, höchstens 6 Wörter (z. B. "Feuchte Wälder, Mitteleuropa").
- Kennst du den wissenschaftlichen Namen nicht sicher (Tippfehler, unbekannt, mehrdeutig), setze "unknown": true
  und lasse alle Felder leer. Rate nie.

Antwortformat (ein Objekt pro Eingabe-Art, gleiche Reihenfolge, Schlüssel = wissenschaftlicher Name wie eingegeben):
{"<name_sci>": {"name_de": "...", "taxon": "...", "description": "...", "habitat": "...", "unknown": false}, ...}
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text


BATCH_SIZE = 8          # Arten pro Anfrage; kleine Gruppen -> Antwort wird nie abgeschnitten
MAX_TOKENS = 4096


def _ask(client, group: list[Species]) -> dict:
    """Eine Anfrage an Claude für eine kleine Gruppe von Arten. Bei kaputter Antwort einmal wiederholen."""
    payload = [{
        "name_sci": s.name_sci,
        "name_de": s.name_de, "taxon": s.taxon,
        "description": s.description, "habitat": s.habitat,
    } for s in group]
    content = json.dumps(payload, ensure_ascii=False, indent=1)

    last_error = ""
    for attempt in range(2):
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        if getattr(msg, "stop_reason", "") == "max_tokens":
            last_error = "Antwort wurde abgeschnitten (max_tokens erreicht)"
            continue
        try:
            return json.loads(_strip_fences(raw))
        except json.JSONDecodeError as e:
            last_error = f"keine gültige JSON-Antwort: {e}"
    raise RuntimeError(f"Claude-Ergänzung fehlgeschlagen: {last_error}")


def enrich(species: list[Species]) -> list[Species]:
    """Füllt leere Felder. Arten mit unbekanntem Namen bekommen ein Problem gesetzt."""
    todo = [s for s in species if s.ok and any(not getattr(s, f) for f in FIELDS)]
    if not todo:
        return species

    client = anthropic.Anthropic(api_key=anthropic_key())
    answer = {}
    for i in range(0, len(todo), BATCH_SIZE):
        answer.update(_ask(client, todo[i:i + BATCH_SIZE]))

    for s in todo:
        data = answer.get(s.name_sci)
        if not isinstance(data, dict):
            s.problem = "KI hat für diesen Namen keine Antwort geliefert"
            continue
        if data.get("unknown"):
            s.problem = "KI kennt den wissenschaftlichen Namen nicht. Bitte Schreibweise prüfen."
            continue
        for f in FIELDS:
            if not getattr(s, f):
                value = str(data.get(f, "") or "").strip()
                if value:
                    setattr(s, f, value)
                    s.ai_filled.append(f)
    return species
