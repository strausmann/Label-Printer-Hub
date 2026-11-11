#!/usr/bin/env python3
"""Write the configuration reference pages (English and German) from the backend settings.

Sources: ``backend/app/config.py`` (every ``LABELYARD_*`` variable, type and default),
``backend/app/settings_store/registry.py`` (which variables also appear in the web UI and lock
the field there) and ``website/src/config-descriptions.yml`` (the text, both languages).
A variable without an English and a German description fails the run.

    python website/scripts/gen-config-reference.py          # writes both pages
    python website/scripts/gen-config-reference.py --check  # exit 1 when a page is stale

Run it with the interpreter that has the backend installed (``pip install -e backend``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

SITE = Path(__file__).resolve().parent.parent
BACKEND = SITE.parent / "backend"
DESCRIPTIONS = SITE / "src" / "config-descriptions.yml"
TARGETS = {
    "en": SITE / "src" / "content" / "docs" / "reference" / "configuration.md",
    "de": SITE / "src" / "content" / "docs" / "de" / "reference" / "configuration.md",
}

TEXT = {
    "en": {
        "title": "Configuration",
        "description": "Every LABELYARD_ environment variable, its default and what it does.",
        "intro": (
            "Every setting is an environment variable with the `LABELYARD_` prefix. The "
            "names of earlier releases are still read until at least 2.0.0, and a "
            "`LABELYARD_` variable always wins; an empty value counts as not set on both "
            "prefixes. See [upgrades](/admin/upgrades/) for the details.\n\n"
            "Printers have no variables: you add them in the web UI under Settings > Printers."
        ),
        "generated": (
            "This page is generated from the backend settings by "
            "`website/scripts/gen-config-reference.py`; edit the descriptions in "
            "`website/src/config-descriptions.yml`, not here."
        ),
        "required": "Required",
        "default": "Default",
        "empty": "empty",
        "secret": "Secret: never logged or shown.",
        "ui": "Also set in the web UI; a value set here wins and locks the field there.",
        "locked": "Shown read-only in the web UI; it always comes from the environment.",
        "required_heading": "Required",
        "optional_heading": "Optional",
    },
    "de": {
        "title": "Konfiguration",
        "description": "Jede LABELYARD_-Umgebungsvariable, ihr Standardwert und was sie bewirkt.",
        "intro": (
            "Jede Einstellung ist eine Umgebungsvariable mit dem Präfix `LABELYARD_`. Die "
            "Namen früherer Versionen werden mindestens bis 2.0.0 weiter gelesen, "
            "und eine `LABELYARD_`-Variable gewinnt immer; ein leerer Wert gilt bei beiden "
            "Präfixen als nicht gesetzt. Details findest du unter "
            "[Aktualisieren](/de/admin/upgrades/).\n\n"
            "Drucker haben keine Variablen: Du legst sie in der Weboberfläche unter "
            "Einstellungen > Drucker an."
        ),
        "generated": (
            "Diese Seite wird von `website/scripts/gen-config-reference.py` aus den "
            "Backend-Einstellungen erzeugt; ändere die Beschreibungen in "
            "`website/src/config-descriptions.yml`, nicht hier."
        ),
        "required": "Pflicht",
        "default": "Standard",
        "empty": "leer",
        "secret": "Geheim: wird nie protokolliert oder angezeigt.",
        "ui": (
            "Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und "
            "sperrt das Feld dort."
        ),
        "locked": "In der Weboberfläche nur sichtbar; der Wert kommt immer aus der Umgebung.",
        "required_heading": "Pflichtangaben",
        "optional_heading": "Optional",
    },
}


def _load_backend() -> tuple[dict[str, object], set[str], set[str]]:
    sys.path.insert(0, str(BACKEND))
    from app.config import Settings
    from app.config_legacy import ENV_PREFIX
    from app.settings_store.registry import ALWAYS_LOCKED, SETTINGS
    from pydantic import SecretStr

    assert ENV_PREFIX == "LABELYARD_", ENV_PREFIX
    ui_fields = {
        d.env_field for d in SETTINGS.values() if d.env_field and d.key not in ALWAYS_LOCKED
    }
    locked = {SETTINGS[k].env_field for k in ALWAYS_LOCKED if SETTINGS[k].env_field}
    fields: dict[str, object] = {}
    for name, info in Settings.model_fields.items():
        secret = info.annotation is SecretStr
        default = None if info.is_required() else info.default
        if isinstance(default, SecretStr):
            default = default.get_secret_value()
        fields[name] = {"required": info.is_required(), "default": default, "secret": secret}
    return fields, ui_fields, {f for f in locked if f}


def _render(
    lang: str, fields: dict[str, object], ui: set[str], locked: set[str], texts: dict[str, dict]
) -> str:
    t = TEXT[lang]
    lines = [
        "---",
        f"title: {t['title']}",
        f"description: {t['description']}",
        "---",
        "",
        "<!-- " + t["generated"] + " -->",
        "",
        t["intro"],
        "",
    ]
    for heading, required in ((t["required_heading"], True), (t["optional_heading"], False)):
        lines += [f"## {heading}", ""]
        for name, meta in fields.items():
            if meta["required"] is not required:  # type: ignore[index]
                continue
            lines += [f"### `LABELYARD_{name.upper()}`", ""]
            if required:
                facts = [f"**{t['required']}**"]
            else:
                value = meta["default"]  # type: ignore[index]
                shown = f"`{value}`" if value not in ("", None) else t["empty"]
                facts = [f"{t['default']}: {shown}"]
            lines += [" · ".join(facts), "", texts[name][lang]]
            if meta["secret"]:  # type: ignore[index]
                lines += ["", t["secret"]]
            if name in ui:
                lines += ["", t["ui"]]
            if name in locked:
                lines += ["", t["locked"]]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="only compare, exit 1 when stale")
    args = parser.parse_args(argv)

    fields, ui, locked = _load_backend()
    texts = yaml.safe_load(DESCRIPTIONS.read_text(encoding="utf-8"))
    problems = []
    for name in fields:
        entry = texts.get(name) or {}
        for lang in ("en", "de"):
            if not str(entry.get(lang, "")).strip():
                problems.append(f"{name}: no {lang} description in {DESCRIPTIONS.name}")
    for name in sorted(set(texts) - set(fields)):
        problems.append(f"{name}: described in {DESCRIPTIONS.name} but not a setting")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1

    stale = []
    for lang, target in TARGETS.items():
        page = _render(lang, fields, ui, locked, texts)
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != page:
                stale.append(str(target.relative_to(SITE.parent)))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page, encoding="utf-8")
    if stale:
        print("stale, run website/scripts/gen-config-reference.py: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
