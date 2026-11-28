"""Lese-API-Logik: Übersichtsliste, Dateidetail und Nachträge (framework-frei).

Basis sind :mod:`okf_bundle` (Pfadschutz, Frontmatter-I/O, Scan) und
:mod:`status` (UI-Status, owner-Default). Die Übersicht listet alle
nicht-reservierten ``.md``-Dateien, absteigend nach ``zuletzt_geaendert``
(Datei-Mtime, ISO 8601) und bei Gleichstand aufsteigend nach ``path``.

Eine einzelne unlesbare Datei darf die Übersicht nicht scheitern lassen;
Fehlermeldungen nennen nie Dateipfade oder OS-Details.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import arbeitsstand
import freigabe
import kennung
import okf_bundle
import status

UNBEKANNTER_TYP = "unbekannt"
TYP_AUFGABE = "Task"
TYP_WELLE = "Welle"
AUFGABEN_ORDNER = "aufgaben/"
HINWEIS_NICHT_LESBAR = "nicht lesbar"
# Einzige Quelle der neutralen Meldungen ist okf_bundle (keine Pfade/OS-Details).
MELDUNG_NICHT_GEFUNDEN = okf_bundle.MELDUNG_NICHT_GEFUNDEN
MELDUNG_NICHT_LESBAR = okf_bundle.MELDUNG_NICHT_LESBAR

# Markerzeile laut Technischer Spec; Folgezeilen eines Nachtrags beginnen mit ``> ``.
_MARKER = re.compile(
    r"^>\s*\*\*Nachtrag\s*\((?P<autor>[^,)]+),\s*(?P<datum>\d{4}-\d{2}-\d{2})\):\*\*\s*"
    r"(?P<text>.*)$"
)
_FOLGEZEILE = re.compile(r"^>\s?(?P<text>.*)$")


def liste(praefix: str | None = None) -> list[dict]:
    """Übersichtseinträge aller Punkte; ``praefix`` grenzt auf einen Ordner ein.

    ``praefix="aufgaben"`` liefert nur ``aufgaben/*``, ``praefix="wellen"`` nur
    ``wellen/*``. Ohne Präfix erscheinen alle nicht-reservierten ``.md``-Dateien.
    """
    pfade = okf_bundle.scan()
    praefix = praefix.strip("/") if praefix else None
    if praefix:
        pfade = [pfad for pfad in pfade if pfad.startswith(f"{praefix}/")]

    eintraege = []
    for pfad in pfade:
        eintrag = _eintrag(pfad)
        if eintrag is not None:
            eintraege.append(eintrag)
    eintraege.sort(key=lambda eintrag: eintrag["path"])
    eintraege.sort(key=lambda eintrag: eintrag["zuletzt_geaendert"], reverse=True)
    return eintraege


def details(pfad: str) -> dict:
    """Dateiinhalt als ``{frontmatter, markdown, nachtraege}``.

    ``ui_status``, ``hinweis`` und ``owner_default`` werden für jede Datei
    top-level aus :mod:`status` abgeleitet (A35) — die einzige Mapping-Quelle;
    die Detailansicht spiegelt die Tabelle nicht mehr. ``owner_default`` ist die
    wirksame Anzeige-Zuständigkeit (explizites ``owner`` vor Status-Default).
    ``schreibgeschuetzt`` (A36) markiert reservierte KI-Dateien; die Liste der
    reservierten Namen lebt ausschließlich in :mod:`okf_bundle`. Listen führen
    kein Schreibschutz-Feld, weil sie keine Schreibaktionen haben; ein Symlink
    auf eine reservierte Datei kann dort als Kante erscheinen (``scan`` filtert
    namensbasiert), die Schreib-UI entfällt in Listen ohnehin. Aufgaben
    (``type: Task``) erhalten zusätzlich die abgeleiteten Arbeitsstatus-Felder;
    ``frontmatter`` bleibt roh.

    Wirft :class:`okf_bundle.BundlePfadFehler` bei Pfadausbruch oder nicht
    zulässiger Endung, :class:`FileNotFoundError`, wenn die Datei fehlt, und
    :class:`PermissionError`, wenn sie nicht lesbar ist. Die Meldungen sind
    neutral und nennen keinen Dateipfad.
    """
    ziel = okf_bundle.resolve_path(pfad)
    if ziel.suffix.lower() != ".md":
        raise okf_bundle.BundlePfadFehler("Nur .md-Dateien sind lesbar")
    if not ziel.is_file():
        raise FileNotFoundError(MELDUNG_NICHT_GEFUNDEN)

    frontmatter, markdown = _lesen(pfad)
    ui_status_wert, hinweis = status.ui_status(frontmatter)
    daten = {
        "frontmatter": frontmatter,
        "markdown": markdown,
        "nachtraege": nachtraege(markdown),
        "ui_status": ui_status_wert,
        "hinweis": hinweis,
        "owner_default": status.owner_default(frontmatter),
        # A36: Schreib-UI-Grenze; auch ein Symlink auf eine reservierte Datei.
        "schreibgeschuetzt": okf_bundle.ist_reserviert(pfad)
        or okf_bundle.ist_reserviert(ziel),
    }
    if _text(frontmatter.get("type")) == TYP_AUFGABE:
        titel = _text(frontmatter.get("title"))
        daten.update(arbeitsstand.ermittle(frontmatter))
        daten["neu"] = not kennung.ist_zugewiesen(titel, Path(pfad).name)
        kennungswert = kennung.kennung_aus_titel(titel)
        if kennungswert:
            daten["kennung"] = kennungswert
        daten["naechste_kennung"] = kennung.naechste_kennung()
        _ergaenze_gate(daten, frontmatter)
    _ergaenze_freigabe(daten, frontmatter)
    return daten


def nachtraege(markdown: str) -> list[dict]:
    """Parst die Markerzeilen ``> **Nachtrag (Autor, YYYY-MM-DD):** Text``.

    Folgezeilen mit ``> `` werden übernommen; eine leere ``>``-Zeile steht für
    einen Absatzumbruch und bleibt als Leerzeile im Text erhalten.
    """
    roh: list[dict] = []
    aktuell: dict | None = None

    for zeile in markdown.splitlines():
        marker = _MARKER.match(zeile)
        if marker:
            aktuell = {
                "autor": marker.group("autor").strip(),
                "datum": marker.group("datum"),
                "zeilen": [marker.group("text")],
            }
            roh.append(aktuell)
            continue

        folge = _FOLGEZEILE.match(zeile)
        if aktuell is not None and folge:
            aktuell["zeilen"].append(folge.group("text"))
            continue

        aktuell = None

    return [
        {
            "autor": eintrag["autor"],
            "datum": eintrag["datum"],
            "text": _nachtrag_text(eintrag["zeilen"]),
        }
        for eintrag in roh
    ]


def _nachtrag_text(zeilen: list[str]) -> str:
    """Zeilen eines Nachtrags als Text mit Leerzeilen als Absatzumbruch."""
    return "\n".join(zeile.strip() for zeile in zeilen).strip()


def _lesen(pfad: str) -> tuple[dict, str]:
    """Liest tolerant; OS- und Encoding-Fehler werden neutral übersetzt."""
    try:
        return okf_bundle.lesen_tolerant(pfad)
    except FileNotFoundError:
        raise FileNotFoundError(MELDUNG_NICHT_GEFUNDEN) from None
    except (OSError, UnicodeDecodeError):
        raise PermissionError(MELDUNG_NICHT_LESBAR) from None


def _eintrag(pfad: str) -> dict | None:
    """Übersichtseintrag einer Datei; ``None``, wenn sie inzwischen gelöscht ist."""
    try:
        frontmatter, _ = okf_bundle.lesen_tolerant(pfad)
        zeitstempel = _zeitstempel(pfad)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        return _nicht_lesbarer_eintrag(pfad)

    if not frontmatter and _hat_defektes_frontmatter(pfad):
        return _nicht_lesbarer_eintrag(pfad)

    ui_status, hinweis = status.ui_status(frontmatter)

    eintrag = {
        "path": pfad,
        "typ": _text(frontmatter.get("type")) or UNBEKANNTER_TYP,
        "titel": _text(frontmatter.get("title")) or "",
        "status": ui_status,
        "owner": status.owner_default(frontmatter),
        "zuletzt_geaendert": zeitstempel,
    }
    if hinweis:
        eintrag["hinweis"] = hinweis
    welle = _text(frontmatter.get("welle"))
    if welle:
        eintrag["welle"] = welle
    if eintrag["typ"] == TYP_AUFGABE:
        eintrag.update(arbeitsstand.ermittle(frontmatter))
        eintrag["neu"] = not kennung.ist_zugewiesen(
            eintrag["titel"], Path(pfad).name
        )
        kennungswert = kennung.kennung_aus_titel(eintrag["titel"])
        if kennungswert:
            eintrag["kennung"] = kennungswert
        parent = frontmatter.get("parent")
        if isinstance(parent, str) and parent.strip():
            eintrag["parent"] = parent.strip()
    _ergaenze_freigabe(eintrag, frontmatter)
    return eintrag


def _hat_defektes_frontmatter(pfad: str) -> bool:
    """Defektes YAML (Block vorhanden, nicht lesbar) statt Altbestand ohne Block."""
    try:
        okf_bundle.lesen(pfad)
    except okf_bundle.FrontmatterFehler:
        return _hat_frontmatter_block(pfad)
    except (OSError, UnicodeDecodeError):
        return False
    return False


def _hat_frontmatter_block(pfad: str) -> bool:
    """Beginnt die Datei mit ``---``?"""
    try:
        with open(okf_bundle.resolve_path(pfad), encoding="utf-8", newline="") as datei:
            return datei.readline().strip() == "---"
    except (OSError, UnicodeDecodeError):
        return False


def _ergaenze_gate(daten: dict, frontmatter: dict) -> None:
    """Wirksame Freigabe (A29): Aufgabe **und** – falls zugeordnet – ihre Welle.

    ``welle_freigabe`` ist ``None``, wenn keine Welle zugeordnet ist oder die
    Wellen-Datei fehlt/unbekannt/keine Welle ist (dann ist der Gate gesperrt).
    """
    wellen_freigabe, gate_offen = _wellen_gate(_text(frontmatter.get("welle")))
    daten["welle_freigabe"] = wellen_freigabe
    daten["wirksam_freigegeben"] = freigabe.ist_freigegeben(frontmatter) and gate_offen


def _wellen_gate(pfad: str | None) -> tuple[bool | None, bool]:
    """Liefert ``(welle_freigabe, gate_offen)``; ohne Welle ist der Gate offen."""
    if not pfad:
        return None, True

    wellen_freigabe = _wellen_freigabe(pfad)
    return wellen_freigabe, wellen_freigabe is True


def _wellen_freigabe(pfad: str) -> bool | None:
    """Freigabe der zugeordneten Welle; ``None`` bei fehlender/fremder Datei."""
    try:
        frontmatter, _ = okf_bundle.lesen_tolerant(pfad)
    except (OSError, UnicodeDecodeError, FileNotFoundError, okf_bundle.BundlePfadFehler):
        return None
    if _text(frontmatter.get("type")) != TYP_WELLE:
        return None
    return freigabe.ist_freigegeben(frontmatter)


def _ergaenze_freigabe(ziel: dict, frontmatter: dict) -> None:
    """``freigabe`` (fail-closed) für Aufgaben und Wellen, plus Hinweis bei ungültigem Wert.

    ``details`` führt keinen ``typ`` im Antwortobjekt — dort zählt der Frontmatter-Typ.
    """
    typ = ziel.get("typ") or _text(frontmatter.get("type"))
    if typ not in (TYP_AUFGABE, TYP_WELLE):
        return
    ziel["freigabe"] = freigabe.ist_freigegeben(frontmatter)
    meldung = freigabe.hinweis(frontmatter)
    if meldung:
        ziel["freigabe_hinweis"] = meldung


def _nicht_lesbarer_eintrag(pfad: str) -> dict | None:
    """Ersatzzeile für eine unlesbare Datei; ``None``, wenn auch ``stat`` scheitert."""
    try:
        zeitstempel = _zeitstempel(pfad)
    except OSError:
        return None

    eintrag = {
        "path": pfad,
        "typ": UNBEKANNTER_TYP,
        "titel": "",
        "status": status.OFFEN,
        "owner": None,
        "zuletzt_geaendert": zeitstempel,
        "hinweis": HINWEIS_NICHT_LESBAR,
    }
    if pfad.startswith(AUFGABEN_ORDNER):
        # Fail-loud: eine unlesbare Aufgabe ist immer „neu" (Kennung unprüfbar).
        eintrag["neu"] = True
    return eintrag



def _zeitstempel(pfad: str) -> str:
    """Mtime der Datei als ISO-8601-Zeitstempel in UTC."""
    mtime = okf_bundle.resolve_path(pfad).stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def _text(wert: object) -> str | None:
    if wert is None:
        return None
    text = str(wert).strip()
    return text or None
