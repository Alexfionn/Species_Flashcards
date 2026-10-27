"""Prüft, ob Token, IDs und Properties in Notion stimmen. Ändert nichts.

  python src/check_setup.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import NOTION, PROPS   # noqa: E402
import notion_api as notion         # noqa: E402

OK, BAD = "  ok   ", "  FEHLT"


def check_ds(label, ds_id, expected: dict[str, str]) -> bool:
    """expected: {property_name: type}"""
    print(f"\n{label}")
    try:
        ds = notion.get_data_source(ds_id)
    except Exception as e:
        print(f"{BAD} Data Source nicht erreichbar: {ds_id}")
        print(f"         {e}")
        print("         -> ID prüfen (config.json) und Integration mit der Database verbinden.")
        return False
    title = "".join(t.get("plain_text", "") for t in ds.get("title", []))
    print(f"{OK} erreichbar: \"{title}\"")
    schema = ds.get("properties", {})
    all_good = True
    for name, typ in expected.items():
        prop = schema.get(name)
        if not prop:
            print(f"{BAD} Property \"{name}\" (Typ {typ})")
            all_good = False
        elif prop.get("type") != typ:
            print(f"{BAD} Property \"{name}\" hat Typ {prop.get('type')}, erwartet {typ}")
            all_good = False
        else:
            print(f"{OK} \"{name}\"")
    return all_good, schema


def main():
    print("Verbindung zu Notion ...")
    try:
        me = notion.get_bot_info()
    except Exception as e:
        print(f"{BAD} Token ungültig oder keine Verbindung: {e}")
        sys.exit(1)
    limit = me.get("bot", {}).get("workspace_limits", {}).get("max_file_upload_size_in_bytes")
    print(f"{OK} Integration \"{me.get('name')}\", Upload-Limit: "
          f"{(limit or 0) / 1024 / 1024:.0f} MB")

    core = {
        PROPS["name_sci"]: "title",
        PROPS["name_de"]: "rich_text",
        PROPS["taxon"]: "rich_text",
        PROPS["description"]: "rich_text",
        PROPS["habitat"]: "rich_text",
    }
    ok = True
    r = check_ds("Species collector", NOTION["collector_id"], {**core, PROPS["note"]: "rich_text"})
    ok &= bool(r if isinstance(r, bool) else r[0])

    r = check_ds("Species Index", NOTION["index_id"],
                 {**core, PROPS["ai_filled"]: "checkbox", PROPS["printed_at"]: "date"})
    ok &= bool(r if isinstance(r, bool) else r[0])

    r = check_ds("Study Calendar", NOTION["studyplan_id"], {
        PROPS["studyplan_title"]: "title",
        PROPS["studyplan_date"]: "date",
        PROPS["studyplan_module"]: "select",
    })
    if not isinstance(r, bool):
        good, schema = r
        ok &= good
        options = [o["name"] for o in schema.get(PROPS["studyplan_module"], {})
                   .get("select", {}).get("options", [])]
        want = PROPS["studyplan_module_value"]
        if want in options:
            print(f"{OK} Option \"{want}\" bei Module vorhanden")
        else:
            print(f"{BAD} Option \"{want}\" bei Module. Bitte in Notion anlegen.")
            ok = False
    else:
        ok = False

    print("\nAlles bereit." if ok else "\nBitte die Punkte mit FEHLT beheben und erneut prüfen.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
