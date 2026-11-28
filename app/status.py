"""Abbildung von ``task_status``/``status`` auf die sechs UI-Status und den owner-Default.

Reine Logik ohne Dateizugriffe; Grundlage ist die Mapping-Tabelle der Technischen Spec.
"""

OFFEN = "Offen"
OHNE_STATUS_HINWEIS = "ohne Status"

# task_status -> (UI-Status, Hinweis, owner-Default)
TASK_STATUS_MAPPING = {
    "offen": ("Offen", None, "ai"),
    "in Klärung": ("Klarung", None, "mensch"),
    "in Planung": ("Offen", None, "ai"),
    "geplant": ("Offen", None, "ai"),
    "in Umsetzung": ("In Arbeit", None, "ai"),
    "im Review": ("Testing", None, "ai"),
    "im Test": ("Testing", None, "ai"),
    "in Doku": ("Dokumentation", None, "ai"),
    "zur Abnahme": ("Klarung", None, "mensch"),
    "abgeschlossen": ("Geschlossen", None, None),
    "pausiert": ("Offen", "pausiert", None),
}

# Wellen/Punkte ohne task_status: status -> owner-Default
STATUS_OWNER_DEFAULTS = {
    "Klarung": "mensch",
    "Offen": "ai",
    "In Arbeit": "ai",
    "Testing": "ai",
    "Dokumentation": "ai",
    "Geschlossen": None,
}

UI_STATUS_WERTE = ("Klarung", "Offen", "In Arbeit", "Testing", "Dokumentation", "Geschlossen")


def ui_status(frontmatter):
    """Liefert ``(UI-Status, Hinweis oder None)`` für ein Frontmatter-Dict.

    Führend ist ``task_status``; fehlt es, wird ``status`` direkt übernommen.
    Unbekannte Werte führen zu ``("Offen", <wert>)`` statt zu einer Exception.
    """
    task_status, eintrag = _task_status_eintrag(frontmatter)
    if task_status is not None:
        if eintrag is None:
            return OFFEN, task_status
        return eintrag[0], eintrag[1]

    status_wert = _wert(frontmatter, "status")
    if status_wert is None:
        return OFFEN, OHNE_STATUS_HINWEIS
    if status_wert in UI_STATUS_WERTE:
        return status_wert, None
    return OFFEN, status_wert


def owner_default(frontmatter):
    """Liefert die Zuständigkeit: explizites ``owner``-Feld, sonst Default aus dem Status.

    Ohne ``owner``-Feld gilt der Default aus ``task_status`` bzw. ``status``.
    Ein unbekannter oder nicht auswertbarer ``task_status`` ergibt ``None``; ebenso
    ``None`` ohne ``owner`` und ohne auswertbaren Status (Anzeige „—“).
    """
    owner = _wert(frontmatter, "owner")
    if owner is not None:
        return owner

    task_status, eintrag = _task_status_eintrag(frontmatter)
    if task_status is not None:
        return eintrag[2] if eintrag is not None else None

    return STATUS_OWNER_DEFAULTS.get(_wert(frontmatter, "status"))


def _task_status_eintrag(frontmatter):
    """Liefert ``(task_status, Mapping-Eintrag oder None)``; ``(None, None)`` ohne Feld."""
    task_status = _wert(frontmatter, "task_status")
    if task_status is None:
        return None, None
    return task_status, TASK_STATUS_MAPPING.get(task_status)


def _wert(frontmatter, feld):
    """Liest ein Frontmatter-Feld als getrimmten Text; ``None`` bei fehlend oder leer."""
    if not isinstance(frontmatter, dict):
        return None

    wert = frontmatter.get(feld)
    if wert is None:
        return None
    if not isinstance(wert, str):
        wert = str(wert)

    wert = wert.strip()
    return wert or None
