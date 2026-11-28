"""Menschen-Recht ``freigabe``: fail-closed lesen, nur mit Herkunft ``MENSCH`` setzen.

Die Projektleitung gibt Aufgaben und Wellen über die App frei. Die KI darf das
Feld nie setzen (``herkunft=KI`` → :class:`meta.RechteFehler`). Geschrieben wird
ausschließlich ``true``/``false`` über :func:`okf_bundle.set_meta` — ein
atomarer Vorgang; gelesen gilt nur ein echtes ``True`` als freigegeben.
"""

from __future__ import annotations

from typing import Any

import meta
import okf_bundle

MENSCH = "MENSCH"
KI = "KI"
FELD = "freigabe"

MELDUNG_NUR_MENSCH = "freigabe ist ein Menschen-Recht und kann hier nicht gesetzt werden."
MELDUNG_WERT = "freigabe muss true oder false sein."
MELDUNG_ZIEL = "freigabe ist nur für Aufgaben und Wellen zulässig."
MELDUNG_UNERWARTET = "freigabe hat einen unerwarteten Wert — gilt als nicht freigegeben."

TYP_AUFGABE = "Task"
TYP_WELLE = "Welle"
ORDNER = ("aufgaben/", "wellen/")


def ist_freigegeben(frontmatter: Any) -> bool:
    """Fail-closed: nur ein echtes ``true`` gilt als freigegeben."""
    return isinstance(frontmatter, dict) and frontmatter.get(FELD) is True


def hinweis(frontmatter: Any) -> str | None:
    """Deutsche Meldung für einen vorhandenen, aber ungültigen Rohwert (sonst ``None``)."""
    if not isinstance(frontmatter, dict) or FELD not in frontmatter:
        return None
    if isinstance(frontmatter[FELD], bool):
        return None
    return MELDUNG_UNERWARTET


def setzen(pfad: Any, wert: Any, *, herkunft: Any) -> dict:
    """Setzt ``freigabe`` und liefert das Frontmatter.

    Nur ``herkunft == MENSCH`` darf schreiben; jede andere/fehlende Herkunft ist
    ein :class:`meta.RechteFehler` (403) ohne Schreibvorgang — auch für ``False``.
    ``wert`` muss ein echtes ``bool`` sein (sonst :class:`okf_bundle.EingabeFehler`).
    """
    if herkunft != MENSCH:
        raise meta.RechteFehler(MELDUNG_NUR_MENSCH)
    if not isinstance(wert, bool):
        raise okf_bundle.EingabeFehler(MELDUNG_WERT)

    frontmatter = pruefe_ziel(pfad)
    if frontmatter.get(FELD) is wert:
        return frontmatter
    return okf_bundle.set_meta(pfad, {FELD: wert})


def pruefe_ziel(pfad: Any) -> dict:
    """Prüft das Ziel (bestehende Aufgabe/Welle) und liefert sein Frontmatter.

    Reihenfolge fail-closed: Eingabe → Pfadschutz → reserviert (403) →
    existierende Datei (404) → Frontmatter/Typ (400).
    """
    if not isinstance(pfad, str) or not pfad.strip():
        raise okf_bundle.EingabeFehler(MELDUNG_ZIEL)
    pfad = pfad.strip()

    ziel = okf_bundle.resolve_path(pfad)
    if okf_bundle.ist_reserviert(pfad) or okf_bundle.ist_reserviert(ziel):
        raise meta.RechteFehler(f"Reservierte Datei ist schreibgeschützt: {ziel.name}")
    if not ziel.is_file():
        raise FileNotFoundError(okf_bundle.MELDUNG_NICHT_GEFUNDEN)

    frontmatter, _ = okf_bundle.lesen(pfad)
    if not _ist_freigabefaehig(pfad, frontmatter):
        raise okf_bundle.EingabeFehler(MELDUNG_ZIEL)
    return frontmatter


def _ist_freigabefaehig(pfad: str, frontmatter: dict) -> bool:
    """Aufgaben/Wellen sind über den Ordner oder ``type`` erkennbar."""
    if pfad.startswith(ORDNER[0]) or pfad.startswith(ORDNER[1]):
        return True
    typ = frontmatter.get("type")
    return isinstance(typ, str) and typ.strip() in (TYP_AUFGABE, TYP_WELLE)
