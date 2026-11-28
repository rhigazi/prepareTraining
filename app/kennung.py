"""Kennungsgrammatik der Aufgaben (A28/A34) — framework-frei und ohne I/O-Zwang.

Top-Level-Aufgaben tragen ``A12`` im Titel und ``a12-<slug>.md`` als Dateiname;
Unter-Aufgaben ``A34.001`` / ``a34.001-<slug>.md`` (``uuu`` = 001–999, genau
eine Unter-Ebene). Dieses Modul ist die **einzige** Quelle der Grammatik:
:mod:`overview` leitet daraus ``neu``/``kennung``/``naechste_kennung`` ab,
:mod:`neu_aufgabe` vergibt die Unter-Kennung beim Anlegen.

Ungültige Werte liefern ``Kennung()`` (alle Felder ``None``) statt zu werfen —
nur die Vergabe (:func:`naechste_unterkennung`) meldet Erschöpfung als
:class:`okf_bundle.EingabeFehler`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import okf_bundle

AUFGABEN_ORDNER = "aufgaben/"
MAX_UNTER = 999

# ``A34: …`` / ``A34.001: …`` — Doppelpunkt braucht Leerraum oder Zeilenende.
_TITEL = re.compile(r"^A([1-9][0-9]*)(?:\.([0-9]{3}))?:(?:\s|$)")
# ``a34-x.md`` / ``a34.001-x.md``; der Punkt trennt die Nummerierungsebenen.
_DATEI = re.compile(r"^a([1-9][0-9]*)(?:\.([0-9]{3}))?(?:-|$)")


class Kennung(NamedTuple):
    """Zerlegte Kennung; alle Felder ``None``, wenn das Format nicht passt."""

    nummer: int | None = None
    unter: int | None = None
    kennung: str | None = None


def zerlege_titel(text: object) -> Kennung:
    """Zerlegt einen Aufgabentitel in Nummer, Unter-Nummer und Kennung."""
    if not isinstance(text, str):
        return Kennung()
    treffer = _TITEL.match(text.strip())
    if treffer is None:
        return Kennung()
    return _baue(int(treffer.group(1)), treffer.group(2))


def zerlege_dateiname(name: object) -> Kennung:
    """Zerlegt einen Dateinamen (mit oder ohne ``.md``) in die Kennung."""
    if not isinstance(name, str):
        return Kennung()
    text = Path(name.strip()).name
    if text.lower().endswith(".md"):
        text = text[:-3]
    treffer = _DATEI.match(text)
    if treffer is None:
        return Kennung()
    return _baue(int(treffer.group(1)), treffer.group(2))


def kennung_aus_titel(text: object) -> str | None:
    """Kennung aus dem Titel (``A12``/``A34.001``); ``None`` ohne gültiges Format."""
    return zerlege_titel(text).kennung


def kennung_aus_dateiname(name: object) -> str | None:
    """Kennung aus dem Dateinamen (``a12-…``/``a34.001-…``)."""
    return zerlege_dateiname(name).kennung


def eltern_kennung(pfad: object, frontmatter: object) -> str | None:
    """Top-Level-Kennung einer Eltern-Aufgabe (Titel **und** Datei konsistent).

    ``None``, wenn die Datei eine Unter-Aufgabe ist, keine Kennung trägt oder
    Titel- und Datei-Kennung auseinanderlaufen.
    """
    if not isinstance(frontmatter, dict):
        return None
    titel = zerlege_titel(frontmatter.get("title"))
    datei = zerlege_dateiname(pfad if isinstance(pfad, str) else "")
    if titel.kennung is None or datei.kennung is None:
        return None
    if titel.unter is not None or datei.unter is not None:
        return None
    return titel.kennung if titel.kennung == datei.kennung else None


def ist_zugewiesen(titel: object, dateiname: object) -> bool:
    """Titel- und Datei-Kennung stimmen inklusive Unter-Nummer überein."""
    titel_kennung = kennung_aus_titel(titel)
    datei_kennung = kennung_aus_dateiname(dateiname)
    return titel_kennung is not None and titel_kennung == datei_kennung


def naechste_kennung() -> str:
    """Nächste freie **Top-Level**-Kennung (Maximum + 1, Unter-Nummern zählen nicht)."""
    hoechste = 0
    for pfad in okf_bundle.scan():
        if not pfad.startswith(AUFGABEN_ORDNER):
            continue
        datei = zerlege_dateiname(pfad)
        if datei.unter is None and datei.nummer is not None:
            hoechste = max(hoechste, datei.nummer)
        titel = zerlege_titel(_lesen(pfad).get("title"))
        if titel.unter is None and titel.nummer is not None:
            hoechste = max(hoechste, titel.nummer)
    return f"A{hoechste + 1}"


def naechste_unterkennung(eltern_pfad: str) -> str:
    """Kleinste freie Unter-Kennung ``A{xxx}.{001–999}`` unter ``eltern_pfad``.

    Belegt ist eine Nummer, wenn eine Aufgabe sie über ``parent`` **oder** über
    ihre Titel-/Datei-Kennung mit derselben Elternnummer trägt. Lücken werden
    gefüllt. Erschöpfung ist ein :class:`okf_bundle.EingabeFehler`.
    """
    eltern_frontmatter = _lesen(eltern_pfad)
    eltern = eltern_kennung(eltern_pfad, eltern_frontmatter)
    if eltern is None:
        raise okf_bundle.EingabeFehler("Eltern-Aufgabe hat keine gültige Kennung")
    nummer = int(eltern[1:])

    belegt = _belegte_unterkennungen(eltern_pfad.strip(), nummer)

    for unter in range(1, MAX_UNTER + 1):
        if unter not in belegt:
            return f"A{nummer}.{unter:03d}"
    raise okf_bundle.EingabeFehler(
        f"Der Nummernraum für Unter-Aufgaben von A{nummer} ist erschöpft"
    )


# --- intern ---------------------------------------------------------------


def _baue(nummer: int, unter: str | None) -> Kennung:
    if unter is None:
        return Kennung(nummer, None, f"A{nummer}")
    wert = int(unter)
    # ``000`` ist keine gültige Unter-Nummer (001–999).
    if not 1 <= wert <= MAX_UNTER:
        return Kennung()
    return Kennung(nummer, wert, f"A{nummer}.{unter}")


def _belegte_unterkennungen(eltern_pfad: str, nummer: int) -> set[int]:
    belegt: set[int] = set()
    for pfad in okf_bundle.scan():
        if not pfad.startswith(AUFGABEN_ORDNER):
            continue
        frontmatter = _lesen(pfad)
        datei = zerlege_dateiname(pfad)
        titel = zerlege_titel(frontmatter.get("title"))

        unter = _unter_der_familie(datei, nummer) or _unter_der_familie(titel, nummer)
        if unter is None and _text(frontmatter.get("parent")) == eltern_pfad:
            # ``parent`` zählt auch bei abweichender Familie im Titel/Dateinamen.
            unter = datei.unter or titel.unter
        if unter is not None and 1 <= unter <= MAX_UNTER:
            belegt.add(unter)
    return belegt


def _unter_der_familie(zerlegt: Kennung, nummer: int) -> int | None:
    if zerlegt.unter is None or zerlegt.nummer != nummer:
        return None
    return zerlegt.unter


def _lesen(pfad: str) -> dict:
    """Tolerant lesen; fehlende/kaputte Dateien zählen als „ohne Frontmatter"."""
    try:
        frontmatter, _ = okf_bundle.lesen_tolerant(pfad)
    except (OSError, UnicodeDecodeError, FileNotFoundError, okf_bundle.BundlePfadFehler):
        return {}
    return frontmatter


def _text(wert: object) -> str:
    if not isinstance(wert, str):
        return ""
    return " ".join(wert.split())


__all__ = [
    "Kennung",
    "eltern_kennung",
    "ist_zugewiesen",
    "kennung_aus_dateiname",
    "kennung_aus_titel",
    "naechste_kennung",
    "naechste_unterkennung",
    "zerlege_dateiname",
    "zerlege_titel",
]
