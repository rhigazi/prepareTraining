"""Arbeitsstatus aus dem Frontmatter-Feld ``aktuell`` ableiten (framework-frei).

Das Feld ``aktuell: "<Rolle>: <Was passiert gerade>"`` ist die einzige Quelle
(PM-Regel „Live-Arbeitsstand pflegen"). Es wird beim Lesen in eine normalisierte
Rolle, deren deutsche Bezeichnung und den freien Text zerlegt — es wird nie
etwas geschrieben und kein zweites Feld gepflegt.
"""

from __future__ import annotations

from typing import Any

import status

# Abgeschlossene Aufgaben zeigen keinen Arbeitsstatus (Feld wird geleert).
GESCHLOSSEN = "Geschlossen"
TYP_AUFGABE = "Task"

# Rolle/Alias (case-insensitiv) -> (arbeitsrolle, arbeitsrolle_label).
ROLLEN = {
    "planner": ("planner", "Planer"),
    "planer": ("planner", "Planer"),
    "coder": ("coder", "Coder"),
    "tester": ("tester", "Tester"),
    "reviewer": ("reviewer", "Review"),
    "review": ("reviewer", "Review"),
    "documenter": ("documenter", "Documenter"),
    "doku": ("documenter", "Documenter"),
    "pm": ("pm", "PM"),
    "projektmanager": ("pm", "PM"),
    "projektleitung": ("pm", "PM"),
}


def ermittle(frontmatter: Any) -> dict:
    """Liefert die ableitbaren Arbeitsstatus-Felder eines Frontmatter-Dicts.

    Nur ``arbeitsrolle`` (bei bekannter Rolle), ``arbeitsrolle_label`` und
    ``arbeitsstatus`` (Text nach dem ersten Doppelpunkt) erscheinen — jeweils
    nur, wenn sie belegt sind. Unbekannte Rollen bleiben als Originaltext
    erhalten (fail-loud, kein Raten). Nicht-Aufgaben (``type != "Task"``),
    fehlendes/leeres/nicht-textliches ``aktuell`` und abgeschlossene Aufgaben
    ergeben ``{}``.
    """
    if not isinstance(frontmatter, dict):
        return {}
    if _text(frontmatter.get("type")) != TYP_AUFGABE:
        return {}
    if status.ui_status(frontmatter)[0] == GESCHLOSSEN:
        return {}

    text = _text(frontmatter.get("aktuell"))
    if text is None:
        return {}

    # Nur der erste Doppelpunkt trennt; ohne Doppelpunkt ist alles Text (T3).
    if ":" in text:
        roh_rolle, _, rest = text.partition(":")
    else:
        roh_rolle, rest = "", text

    ergebnis: dict[str, str] = {}
    rolle = roh_rolle.strip()
    if rolle:
        bekannt = ROLLEN.get(rolle.lower())
        if bekannt is None:
            ergebnis["arbeitsrolle_label"] = rolle
        else:
            ergebnis["arbeitsrolle"] = bekannt[0]
            ergebnis["arbeitsrolle_label"] = bekannt[1]

    inhalt = rest.strip()
    if inhalt:
        ergebnis["arbeitsstatus"] = inhalt
    return ergebnis


def _text(wert: object) -> str | None:
    """Getrimmter Text mit zusammengefasstem Leerraum; ``None`` bei Nicht-String."""
    if not isinstance(wert, str):
        return None
    return " ".join(wert.split()) or None
