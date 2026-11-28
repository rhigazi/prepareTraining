"""Nachträge der Projektleitung als Blockquote an das Dateiende anfügen.

Nachtrag-Format laut Technischer Spec::

    # Nachträge

    > **Nachtrag (Mensch, YYYY-MM-DD):** <Text>

Es wird ausschließlich angefügt; bestehende Bytes bleiben unverändert.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

import okf_bundle
from okf_bundle import EingabeFehler

_ABSCHNITT = re.compile(r"(?m)^#\s+Nachträge\s*$")
_UEBERSCHRIFT = re.compile(r"(?m)^#\s")
_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def anfuegen(bundle_rel_pfad: str, text: str | None, datum: str | date | None = None) -> str:
    """Fügt ``text`` als Nachtrag an das Ende des Abschnitts ``# Nachträge`` an.

    Der Abschnitt wird am Dateiende angelegt, falls er fehlt. ``datum`` ist
    injizierbar (``YYYY-MM-DD``); ohne Angabe gilt das heutige Datum in UTC.
    Liefert den neuen Dateiinhalt.
    """
    eintrag = _eintrag(text)
    datum_text = _datum_text(datum)
    ziel = okf_bundle.pruefe_zieldatei(bundle_rel_pfad)
    bestand = _lies(ziel)
    ende = "\r\n" if "\r\n" in bestand else "\n"

    ergebnis = _anhaengen(bestand, ende, _marker_zeilen(eintrag, datum_text))
    okf_bundle.schreiben(bundle_rel_pfad, ergebnis)
    return ergebnis


def _eintrag(text: str | None) -> str:
    if not isinstance(text, str) or not text.strip():
        raise EingabeFehler("Nachtragstext darf nicht leer sein")
    return text.strip()


def _datum_text(datum: str | date | None) -> str:
    if datum is None:
        return datetime.now(timezone.utc).date().isoformat()
    if isinstance(datum, datetime):
        return datum.date().isoformat()
    if isinstance(datum, date):
        return datum.isoformat()

    text = str(datum).strip()
    if not _DATUM.fullmatch(text):
        raise EingabeFehler(f"Datum muss dem Format YYYY-MM-DD entsprechen: {datum!r}")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as fehler:
        raise EingabeFehler(f"Ungültiges Datum: {datum!r}") from fehler


def _marker_zeilen(eintrag: str, datum: str) -> list[str]:
    zeilen = eintrag.splitlines()
    block = [f"> **Nachtrag (Mensch, {datum}):** {zeilen[0]}"]
    block.extend(f"> {zeile}".rstrip() for zeile in zeilen[1:])
    return block


def _anhaengen(bestand: str, ende: str, marker: list[str]) -> str:
    """Hängt ``marker`` an das Ende des Nachtrags-Abschnitts bzw. der Datei an."""
    block = ende.join(marker) + ende
    abschnitt = _ABSCHNITT.search(bestand)
    if abschnitt is None:
        return bestand + _abstand(bestand, ende) + "# Nachträge" + ende + ende + block

    naechste = _UEBERSCHRIFT.search(bestand, abschnitt.end())
    einfuegen = naechste.start() if naechste is not None else len(bestand)
    kopf, rest = bestand[:einfuegen], bestand[einfuegen:]

    anhang = _abstand(kopf, ende) + block
    if rest:
        anhang += "" if rest.startswith(ende) else ende
    return kopf + anhang + rest


def _abstand(teil: str, ende: str) -> str:
    """Trennzeilen vor dem Anhang, ohne bestehende Bytes zu verändern."""
    if not teil:
        return ""
    if teil.endswith(ende * 2):
        return ""
    if teil.endswith(ende):
        return ende
    return ende + ende


def _lies(ziel: Path) -> str:
    """Liest die Datei; OS-Meldungen werden neutral übersetzt (nie Pfade/Details)."""
    try:
        with open(ziel, encoding="utf-8", newline="") as datei:
            return datei.read()
    except FileNotFoundError:
        raise FileNotFoundError(okf_bundle.MELDUNG_NICHT_GEFUNDEN) from None
    except (OSError, UnicodeDecodeError):
        raise PermissionError(okf_bundle.MELDUNG_NICHT_LESBAR) from None
