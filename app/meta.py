"""``owner``, die erlaubten UI-Status und die Wellen-Zuordnung setzen.

Die App darf ``owner`` umschalten, den Status ausschließlich auf ``Klarung``
und ``Geschlossen`` setzen (Entscheidung R1) und eine Aufgabe einer Welle
zuordnen (``welle``, Konvention aus A13). Pipeline-Status bleiben der KI
vorbehalten. Geschrieben wird immer in einem einzigen, atomaren Vorgang über
:func:`okf_bundle.set_meta`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

import okf_bundle

OWNER_WERTE = ("mensch", "ai")
STATUS_WERTE = ("Klarung", "Geschlossen")

# Erlaubter UI-Status -> zu schreibender ``task_status`` (Technische Spec, R1).
TASK_STATUS_ZIELE = {"Klarung": "in Klärung", "Geschlossen": "abgeschlossen"}

# Wellen liegen flach unter ``wellen/`` (A5/A13).
WELLEN_ORDNER = "wellen"

# ``freigabe`` ist ein Menschen-Recht (A28): hier nie setzbar, auch nicht ``False``.
MELDUNG_FREIGABE = "freigabe ist ein Menschen-Recht und kann hier nicht gesetzt werden."
WELLE_MELDUNG = "welle muss eine vorhandene Wellen-Datei unter wellen/ sein"

# Sentinel: „welle nicht übergeben" ist von „Zuordnung entfernen" (None) zu trennen.
_NICHT_GESETZT = object()


class RechteFehler(PermissionError):
    """Die App darf diesen Zielwert bzw. diese Datei nicht schreiben (HTTP 403)."""


def setzen(
    pfad: str,
    owner: str | None = None,
    status: str | None = None,
    welle: Any = _NICHT_GESETZT,
    freigabe: Any = _NICHT_GESETZT,
) -> dict:
    """Setzt ``owner``, ``status`` und/oder ``welle`` und liefert das neue Frontmatter.

    Ohne Zielwerte wird nichts geschrieben. Reservierte Dateien, unbekannte
    Zielwerte und Dateien ohne Frontmatter werden abgewiesen, bevor geschrieben
    wird; der Body bleibt unverändert. Die Prüfreihenfolge ist fail-closed:
    reservierte Zieldatei, ``owner``-, ``status``-Whitelist, ``welle``,
    Zielpfad/Datei. ``welle=None`` (oder leer) entfernt die Zuordnung.
    ``freigabe`` ist ein Menschen-Recht: jedes Mitgeben ist ein Rechtefehler.
    """
    if freigabe is not _NICHT_GESETZT:
        raise RechteFehler(MELDUNG_FREIGABE)

    ziel = okf_bundle.resolve_path(pfad)
    if okf_bundle.ist_reserviert(pfad) or okf_bundle.ist_reserviert(ziel):
        raise RechteFehler(f"Reservierte Datei ist schreibgeschützt: {ziel.name}")

    if owner is not None:
        owner = _pruefe_owner(owner)
    if status is not None:
        status = _pruefe_status(status)

    welle_aenderung: tuple[str, str | None] | None = None
    if welle is not _NICHT_GESETZT:
        welle_aenderung = _pruefe_welle(welle)

    # Validierung vollständig vor dem Lesen: nur bestehende .md-Dateien.
    okf_bundle.pruefe_zieldatei(pfad)
    frontmatter, _ = okf_bundle.lesen(pfad)

    updates: dict[str, Any] = {}
    if owner is not None:
        updates["owner"] = owner
    if status is not None:
        if _hat_task_status(frontmatter):
            updates["task_status"] = TASK_STATUS_ZIELE[status]
        else:
            updates["status"] = status

    entfernen: list[str] = []
    if welle_aenderung is not None:
        art, wellen_pfad = welle_aenderung
        if art == "setzen" and wellen_pfad is not None:
            if _text(frontmatter.get("welle")) != wellen_pfad:
                updates["welle"] = wellen_pfad
        elif "welle" in frontmatter:
            entfernen.append("welle")

    if not updates and not entfernen:
        return frontmatter
    return okf_bundle.set_meta(pfad, updates, entfernen=tuple(entfernen))


def _pruefe_owner(owner: Any) -> str:
    if owner not in OWNER_WERTE:
        raise RechteFehler(f"owner darf nur 'mensch' oder 'ai' sein, nicht {owner!r}")
    return owner


def _pruefe_status(status: Any) -> str:
    if status not in STATUS_WERTE:
        raise RechteFehler(
            "Status darf die App nur auf 'Klarung' oder 'Geschlossen' setzen, "
            f"nicht {status!r} — Pipeline-Status bleibt der KI vorbehalten"
        )
    return status


def _pruefe_welle(wert: Any) -> tuple[str, str | None]:
    """Prüft den ``welle``-Wert: ``("setzen", pfad)`` oder ``("entfernen", None)``.

    Ungültige Werte sind ein :class:`okf_bundle.EingabeFehler` (HTTP 400), nie
    ein Rechtefehler: ``welle`` ist ein Eingabefeld, kein Rechtepfad.
    """
    if wert is None:
        return ("entfernen", None)
    if not isinstance(wert, str):
        raise okf_bundle.EingabeFehler(WELLE_MELDUNG)
    text = wert.strip()
    if not text:
        return ("entfernen", None)
    return ("setzen", _wellen_pfad(text))


def _wellen_pfad(text: str) -> str:
    """Akzeptiert genau ``wellen/<name>.md`` als existierende, nicht reservierte Datei.

    Prozent-kodierte Pfade werden strikt abgewiesen (A27-K1): sonst würde die
    Zuordnung unter der kodierten Schreibweise gespeichert, während
    :func:`okf_bundle.resolve_path` die Datei über die dekodierte Form findet.
    """
    if unquote(text) != text:
        raise okf_bundle.EingabeFehler(WELLE_MELDUNG)

    teile = text.split("/")
    if len(teile) != 2 or teile[0] != WELLEN_ORDNER:
        raise okf_bundle.EingabeFehler(WELLE_MELDUNG)

    name = teile[1]
    if not name.lower().endswith(".md") or name.lower() == ".md":
        raise okf_bundle.EingabeFehler(WELLE_MELDUNG)
    if okf_bundle.ist_reserviert(text):
        raise okf_bundle.EingabeFehler(WELLE_MELDUNG)

    try:
        ziel = okf_bundle.resolve_path(text)
    except okf_bundle.BundlePfadFehler:
        raise okf_bundle.EingabeFehler(WELLE_MELDUNG) from None
    if not ziel.is_file():
        raise okf_bundle.EingabeFehler(WELLE_MELDUNG)
    return text


def _hat_task_status(frontmatter: dict) -> bool:
    """Punkte mit ``task_status`` (Aufgaben) werden darüber gesteuert, sonst ``status``."""
    wert = frontmatter.get("task_status")
    return wert is not None and str(wert).strip() != ""


def _text(wert: object) -> str | None:
    if wert is None:
        return None
    text = str(wert).strip()
    return text or None
