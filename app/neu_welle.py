"""Neue Wellen-Dateien im OKF-Bundle anlegen (Aufgabe A5).

Kapselt Slug-Regel (R2), Eingabevalidierung und das Schreiben der Welle; das
Dateiformat folgt der Technischen Spec (``type: Welle`` mit ``status``/``owner``).
"""

from __future__ import annotations

import yaml

import okf_bundle
import slug
import status
from okf_bundle import EingabeFehler

WELLEN_ORDNER = "wellen"
MAX_KURZBESCHREIBUNG = 160
MAX_KANDIDATEN = 1000
FALLBACK_KUERZEL = "welle"
OWNER_WERTE = ("mensch", "ai")


def anlegen(eingaben: dict) -> str:
    """Legt ``wellen/<kuerzel>.md`` an und liefert den bundle-relativen Pfad.

    Validiert Titel, Ziel, ``status`` (nur die sechs UI-Werte) und ``owner``
    (``mensch``/``ai``) vollständig vor dem Schreiben; bei Verstoß wird keine
    Datei erzeugt. Bestehende Wellen werden nie überschrieben.
    Die OKF-``description`` ist optional und wird sonst aus der ersten
    Ziel-Zeile gebildet (siehe :func:`_beschreibung`).
    Den Ordner ``wellen/`` legt :func:`okf_bundle.schreiben` bei Erstanlage mit an.
    """
    if not isinstance(eingaben, dict):
        raise EingabeFehler("Eingaben fehlen")

    titel = _text(eingaben.get("titel"))
    if not titel:
        raise EingabeFehler("Titel darf nicht leer sein")

    ziel = _text(eingaben.get("ziel"))
    if not ziel:
        raise EingabeFehler("Ziel darf nicht leer sein")

    status_wert = _text(eingaben.get("status"))
    if status_wert not in status.UI_STATUS_WERTE:
        raise EingabeFehler(f"Ungültiger Status: {status_wert!r}")

    owner = _text(eingaben.get("owner"))
    if owner not in OWNER_WERTE:
        raise EingabeFehler(f"Ungültiger owner: {owner!r}")

    beschreibung = _beschreibung(eingaben.get("description"), ziel)

    pfad = _freier_pfad(titel)
    okf_bundle.schreiben(pfad, _inhalt(titel, beschreibung, ziel, status_wert, owner))
    return pfad


def kuerzel(titel: str) -> str:
    """ASCII-Slug aus dem Titel (gemeinsame Regel); leer → ``welle``."""
    return slug.slug_aus_titel(_text(titel) or "") or FALLBACK_KUERZEL


def _freier_pfad(titel: str) -> str:
    """Erster freier Pfad in ``wellen/``; reservierte Dateinamen werden übersprungen.

    Kollisionen erhalten ``-2``, ``-3``, …; die Kandidatensuche endet nach
    ``MAX_KANDIDATEN`` Versuchen (analog ``neu_aufgabe``).
    """
    basis = kuerzel(titel)
    for nummer in range(1, MAX_KANDIDATEN + 1):
        name = f"{basis}.md" if nummer == 1 else f"{basis}-{nummer}.md"
        if okf_bundle.ist_reserviert(name):
            continue
        pfad = f"{WELLEN_ORDNER}/{name}"
        if not okf_bundle.resolve_path(pfad).exists():
            return pfad
    raise EingabeFehler(f"Kein freier Dateiname für {basis!r} gefunden")


def _inhalt(titel: str, beschreibung: str, ziel: str, status_wert: str, owner: str) -> str:
    frontmatter = yaml.safe_dump(
        {
            "type": "Welle",
            "title": titel,
            "description": beschreibung,
            "status": status_wert,
            "owner": owner,
            "freigabe": False,
        },
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip("\n")
    return f"---\n{frontmatter}\n---\n\n# Ziel\n\n{ziel}\n\n# Aufgaben\n"


def _beschreibung(wert: object, ziel: str) -> str:
    """Kurzbeschreibung für das Frontmatter (OKF-``description``, max. 160 Zeichen).

    Ohne eigene Angabe dient die erste Ziel-Zeile als Beschreibung. Jede
    Beschreibung wird auf eine Zeile normalisiert und bei Bedarf mit ``…``
    gekürzt, damit das Frontmatter einzeilig und ohne Sonderfälle bleibt.
    """
    if wert is not None and not isinstance(wert, str):
        raise EingabeFehler("description muss ein Text sein")

    text = _einzeilig(wert or "") or _einzeilig(ziel.splitlines()[0])
    if len(text) <= MAX_KURZBESCHREIBUNG:
        return text
    return text[: MAX_KURZBESCHREIBUNG - 1].rstrip() + "…"


def _einzeilig(wert: str) -> str:
    """Fasst einen Text zu einer Zeile zusammen (Whitespace wird normalisiert)."""
    return " ".join(wert.split())


def _text(wert: object) -> str | None:
    """Liest einen Eingabewert als getrimmten Text; ``None`` bei fehlend/Nicht-Text."""
    if not isinstance(wert, str):
        return None
    return wert.strip() or None
