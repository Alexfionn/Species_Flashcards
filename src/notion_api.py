"""Alles rund um Notion: lesen, hochladen, Seiten anlegen, verschieben.

Jede Funktion macht genau eine Sache. Die Logik, wann was passiert, steht in main.py.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from config import NOTION, PROPS, MAX_IMAGES, notion_token

BASE = "https://api.notion.com/v1"


# ---------------------------------------------------------------------------
# Datenstruktur für eine Art
# ---------------------------------------------------------------------------

@dataclass
class Species:
    page_id: str
    name_sci: str = ""
    name_de: str = ""
    taxon: str = ""
    description: str = ""
    habitat: str = ""
    image_urls: list = field(default_factory=list)
    group: str = ""                                     # Artgruppe (nur im Index)
    image_paths: list = field(default_factory=list)     # lokale Dateien nach dem Download
    ai_filled: list = field(default_factory=list)       # Felder, die Claude ergänzt hat
    problem: str = ""                                   # warum die Art nicht verarbeitet wird

    @property
    def ok(self) -> bool:
        return not self.problem


# ---------------------------------------------------------------------------
# HTTP-Grundlagen
# ---------------------------------------------------------------------------

def _headers(json_body=True):
    h = {
        "Authorization": f"Bearer {notion_token()}",
        "Notion-Version": NOTION["api_version"],
    }
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _request(method, path, retries=3, **kwargs):
    """Ein Request mit einfacher Wiederholung bei Rate-Limit (429) oder Serverfehlern."""
    url = path if path.startswith("http") else BASE + path
    for attempt in range(retries):
        r = requests.request(method, url, timeout=60, **kwargs)
        if r.status_code == 429 or r.status_code >= 500:
            wait = float(r.headers.get("Retry-After", 2 * (attempt + 1)))
            time.sleep(wait)
            continue
        if not r.ok:
            raise RuntimeError(f"Notion {method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json()
    raise RuntimeError(f"Notion {method} {path}: nach {retries} Versuchen aufgegeben")


def _get(path, **kw):
    return _request("GET", path, headers=_headers(), **kw)


def _post(path, body):
    return _request("POST", path, headers=_headers(), json=body)


def _patch(path, body):
    return _request("PATCH", path, headers=_headers(), json=body)


# ---------------------------------------------------------------------------
# Properties lesen und schreiben
# ---------------------------------------------------------------------------

def _plain_text(prop) -> str:
    """Holt den Text aus einer title- oder rich_text-Property."""
    if not prop:
        return ""
    parts = prop.get("title") or prop.get("rich_text") or []
    return "".join(p.get("plain_text", "") for p in parts).strip()


def _rich(text: str):
    return {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}


def _title(text: str):
    return {"title": [{"type": "text", "text": {"content": text[:2000]}}]}


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------

def get_bot_info() -> dict:
    """Infos zur Integration, inkl. Upload-Limit des Workspaces."""
    return _get("/users/me")


def get_data_source(ds_id: str) -> dict:
    return _get(f"/data_sources/{ds_id}")


def query_collector() -> list[Species]:
    """Alle Seiten im Collector, älteste zuerst."""
    body = {
        "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
        "page_size": 100,
    }
    results, cursor = [], None
    while True:
        if cursor:
            body["start_cursor"] = cursor
        data = _post(f"/data_sources/{NOTION['collector_id']}/query", body)
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    species = []
    for page in results:
        p = page.get("properties", {})
        species.append(Species(
            page_id=page["id"],
            name_sci=_plain_text(p.get(PROPS["name_sci"])),
            name_de=_plain_text(p.get(PROPS["name_de"])),
            taxon=_plain_text(p.get(PROPS["taxon"])),
            description=_plain_text(p.get(PROPS["description"])),
            habitat=_plain_text(p.get(PROPS["habitat"])),
        ))
    return species


def get_image_urls(page_id: str) -> list[str]:
    """Die ersten Bildblöcke einer Seite. Signierte URLs laufen nach ~1 h ab, also sofort laden."""
    urls, cursor = [], None
    while len(urls) < MAX_IMAGES:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        data = _get(f"/blocks/{page_id}/children", params=params)
        for block in data.get("results", []):
            if block.get("type") != "image":
                continue
            img = block["image"]
            url = (img.get("file") or img.get("external") or {}).get("url")
            if url:
                urls.append(url)
            if len(urls) >= MAX_IMAGES:
                break
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return urls


def download(url: str, target: Path) -> Path:
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    target.write_bytes(r.content)
    return target


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------

def set_note(page_id: str, text: str):
    """Hinweis-Feld im Collector setzen (oder leeren)."""
    _patch(f"/pages/{page_id}", {"properties": {PROPS["note"]: _rich(text)}})


def upload_file(path: Path, content_type="application/pdf") -> str:
    """Datei hochladen (einteilig, bis 20 MB). Gibt die file_upload-ID zurück."""
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > 20:
        raise RuntimeError(f"PDF ist {size_mb:.1f} MB gross. Einteiliger Upload geht nur bis 20 MB.")
    created = _post("/file_uploads", {"filename": path.name, "content_type": content_type})
    upload_id = created["id"]
    with open(path, "rb") as f:
        r = requests.post(
            f"{BASE}/file_uploads/{upload_id}/send",
            headers=_headers(json_body=False),
            files={"file": (path.name, f, content_type)},
            timeout=300,
        )
    if not r.ok:
        raise RuntimeError(f"Upload fehlgeschlagen: {r.status_code} {r.text[:300]}")
    return upload_id


def create_studyplan_page(title: str, date_iso: str, file_upload_id: str) -> str:
    """Neue Seite in der Study Calendar mit dem PDF als einzigem Block."""
    body = {
        "parent": {"type": "data_source_id", "data_source_id": NOTION["studyplan_id"]},
        "properties": {
            PROPS["studyplan_title"]: _title(title),
            PROPS["studyplan_date"]: {"date": {"start": date_iso}},
            PROPS["studyplan_module"]: {"select": {"name": PROPS["studyplan_module_value"]}},
        },
        "children": [{
            "object": "block",
            "type": "file",
            "file": {"type": "file_upload", "file_upload": {"id": file_upload_id}},
        }],
    }
    page = _post("/pages", body)
    return page.get("url", page["id"])


def create_collector_page(sp: Species, image_upload_ids: list[str]) -> str:
    """Neue Art im Collector anlegen, mit Bildern als Bildblöcke. Leere Felder bleiben leer."""
    props = {PROPS["name_sci"]: _title(sp.name_sci)}
    for key in ("name_de", "taxon", "description", "habitat"):
        value = getattr(sp, key)
        if value:
            props[PROPS[key]] = _rich(value)
    children = [{
        "object": "block",
        "type": "image",
        "image": {"type": "file_upload", "file_upload": {"id": uid}},
    } for uid in image_upload_ids]
    page = _post("/pages", {
        "parent": {"type": "data_source_id", "data_source_id": NOTION["collector_id"]},
        "properties": props,
        "children": children,
    })
    return page.get("url", page["id"])


def move_to_index(page_id: str):
    """Seite vom Collector in den Index verschieben. Bilder und Properties bleiben erhalten."""
    _post(f"/pages/{page_id}/move", {
        "parent": {"type": "data_source_id", "data_source_id": NOTION["index_id"]},
    })


def finalize_in_index(sp: Species, date_iso: str):
    """Nach dem Verschieben: ergänzte Felder, KI-Häkchen, Druckdatum und Gruppe setzen."""
    props = {
        PROPS["ai_filled"]: {"checkbox": bool(sp.ai_filled)},
        PROPS["printed_at"]: {"date": {"start": date_iso}},
    }
    for key in ("name_de", "taxon", "description", "habitat"):
        if key in sp.ai_filled:
            props[PROPS[key]] = _rich(getattr(sp, key))
    if sp.group and PROPS.get("group"):
        props[PROPS["group"]] = {"select": {"name": sp.group}}
    try:
        _patch(f"/pages/{sp.page_id}", {"properties": props})
    except RuntimeError:
        # Fehlt die Spalte "Gruppe" noch, soll der Druck trotzdem sauber abschliessen.
        if PROPS.get("group") in props:
            props.pop(PROPS["group"])
            _patch(f"/pages/{sp.page_id}", {"properties": props})
        else:
            raise


# ---------------------------------------------------------------------------
# Species Index (für die Lernseite)
# ---------------------------------------------------------------------------

def _select_name(prop) -> str:
    sel = (prop or {}).get("select") or {}
    return (sel.get("name") or "").strip()


def _date_start(prop) -> str:
    d = (prop or {}).get("date") or {}
    return d.get("start") or ""


def query_index() -> list[dict]:
    """Alle Arten im Index als einfache Dicts, inkl. letzter Änderung."""
    body = {"page_size": 100}
    results, cursor = [], None
    while True:
        if cursor:
            body["start_cursor"] = cursor
        data = _post(f"/data_sources/{NOTION['index_id']}/query", body)
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    out = []
    for page in results:
        p = page.get("properties", {})
        out.append({
            "id": page["id"],
            "edited": page.get("last_edited_time", ""),
            "created": page.get("created_time", ""),
            "sci": _plain_text(p.get(PROPS["name_sci"])),
            "de": _plain_text(p.get(PROPS["name_de"])),
            "taxon": _plain_text(p.get(PROPS["taxon"])),
            "desc": _plain_text(p.get(PROPS["description"])),
            "hab": _plain_text(p.get(PROPS["habitat"])),
            "group": _select_name(p.get(PROPS["group"])),
            "printed": _date_start(p.get(PROPS["printed_at"])),
        })
    return out


def set_group(page_id: str, group: str) -> str:
    """Gruppe im Index setzen. Gibt den neuen Änderungszeitpunkt zurück."""
    page = _patch(f"/pages/{page_id}", {"properties": {PROPS["group"]: {"select": {"name": group}}}})
    return page.get("last_edited_time", "")
