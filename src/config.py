"""Lädt config.json und die Secrets aus der Umgebung (oder aus einer .env-Datei)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"


def _load_dotenv():
    """Liest eine .env-Datei im Repo-Root, falls vorhanden. Setzt nur Werte, die noch fehlen."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

with open(ROOT / "config.json", encoding="utf-8") as f:
    CONFIG = json.load(f)

NOTION = CONFIG["notion"]
PROPS = CONFIG["properties"]
CARDS_PER_SHEET = int(CONFIG.get("cards_per_sheet", 8))
MAX_IMAGES = int(CONFIG.get("max_images_per_card", 2))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", CONFIG.get("claude_model", "claude-sonnet-5-5"))
TITLE_FORMAT = CONFIG.get("studyplan_title_format", "Flashcards {date}")


def notion_token() -> str:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise SystemExit("NOTION_TOKEN fehlt. In .env eintragen oder als GitHub-Secret setzen.")
    return token


def anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY fehlt. In .env eintragen oder als GitHub-Secret setzen.")
    return key
