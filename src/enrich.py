"""Fehlende Felder mit der Claude API ergänzen.

Regeln:
- Nur leere Felder werden gefüllt. Eigene Einträge werden nie überschrieben.
- Taxon-Ebene je Gruppe (immer lateinisch):
    Moose -> Klasse, übrige Pflanzen (inkl. Farne) -> Familie,
    Pilze -> Stamm (Phylum), Flechten -> "Flechte",
    Gliederfüsser -> Ordnung, Wirbeltiere -> Ordnung, alles andere -> Ordnung.
- Zusätzlich die Artgruppe (Liste in config.json, "groups") für die Lernseite.
- Unbekannter wissenschaftlicher Name -> die Art wird nicht geraten, sondern markiert.
"""
import json
import re

import anthropic

from config import CLAUDE_MODEL, GROUPS, anthropic_key
from notion_api import Species

FIELDS = ("name_de", "taxon", "description", "habitat")

BATCH_SIZE = 8          # Arten pro Anfrage; kleine Gruppen -> Antwort wird nie abgeschnitten
GROUP_BATCH_SIZE = 20   # nur Gruppen: kurze Antworten, darum grössere Gruppen
MAX_TOKENS = 4096


def _group_rules() -> str:
    lines = [f'- "{name}": {desc}' for name, desc in GROUPS.items()]
    return "\n".join(lines)


def _system_full() -> str:
    return f"""Du bist ein präziser Taxonomie-Assistent für Lernkarten (Studium Biologie, Schweiz).
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

Regeln für "group": genau EINER dieser Namen, wörtlich, immer ausfüllen:
{_group_rules()}

Weitere Regeln:
- "name_de": der gebräuchliche deutsche Name. Gibt es keinen etablierten, schreibe "".
- "description": höchstens 5 Wörter, Merkmale zum Erkennen im Feld. Kein Punkt am Ende.
- "habitat": allgemeiner Lebensraum oder Verbreitung, höchstens 6 Wörter (z. B. "Feuchte Wälder, Mitteleuropa").
- Kennst du den wissenschaftlichen Namen nicht sicher (Tippfehler, unbekannt, mehrdeutig), setze "unknown": true
  und lasse alle Felder leer. Rate nie.

Antwortformat (ein Objekt pro Eingabe-Art, Schlüssel = wissenschaftlicher Name wie eingegeben):
{{"<name_sci>": {{"name_de": "...", "taxon": "...", "description": "...", "habitat": "...", "group": "...", "unknown": false}}, ...}}
"""


def _system_groups() -> str:
    return f"""Du ordnest Arten einer Artgruppe zu (Lernkarten, Studium Biologie).
Wähle für jede Art genau EINEN dieser Namen, wörtlich:
{_group_rules()}

Bist du unsicher oder kennst die Art nicht, schreibe "".
Antworte ausschliesslich mit JSON, Schlüssel = wissenschaftlicher Name wie eingegeben:
{{"<name_sci>": "<Gruppe>", ...}}
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text


def _call(client, system: str, payload: list) -> dict:
    """Eine Anfrage an Claude. Bei abgeschnittener oder kaputter Antwort einmal wiederholen."""
    content = json.dumps(payload, ensure_ascii=False, indent=1)
    last_error = ""
    for _ in range(2):
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
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
    raise RuntimeError(f"Claude-Anfrage fehlgeschlagen: {last_error}")


def valid_group(value) -> str:
    """Nur Gruppen aus der Liste zulassen (Gross-/Kleinschreibung egal)."""
    value = str(value or "").strip()
    for name in GROUPS:
        if value.lower() == name.lower():
            return name
    return ""


def enrich(species: list[Species]) -> list[Species]:
    """Füllt leere Felder und bestimmt die Gruppe. Unbekannte Namen bekommen ein Problem gesetzt."""
    todo = [s for s in species
            if s.ok and (any(not getattr(s, f) for f in FIELDS) or not s.group)]
    if not todo:
        return species

    client = anthropic.Anthropic(api_key=anthropic_key())
    answer = {}
    for i in range(0, len(todo), BATCH_SIZE):
        group = todo[i:i + BATCH_SIZE]
        payload = [{"name_sci": s.name_sci, "name_de": s.name_de, "taxon": s.taxon,
                    "description": s.description, "habitat": s.habitat} for s in group]
        answer.update(_call(client, _system_full(), payload))

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
        if not s.group:
            s.group = valid_group(data.get("group"))   # zählt nicht als "KI-ergänzt"
    return species


def assign_groups(items: list[dict]) -> dict:
    """Für den Deck-Build: {name_sci: gruppe} für Arten ohne Gruppe. Ungültige Antworten -> ""."""
    if not items:
        return {}
    client = anthropic.Anthropic(api_key=anthropic_key())
    result = {}
    for i in range(0, len(items), GROUP_BATCH_SIZE):
        chunk = items[i:i + GROUP_BATCH_SIZE]
        payload = [{"name_sci": it["sci"], "taxon": it.get("taxon", "")} for it in chunk]
        answer = _call(client, _system_groups(), payload)
        for it in chunk:
            result[it["sci"]] = valid_group(answer.get(it["sci"]))
    return result
