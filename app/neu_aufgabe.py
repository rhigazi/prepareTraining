"""Neue Aufgaben-Datei im Phasen-Format anlegen.

Erzeugt ``aufgaben/<slug>.md`` aus den Formulardaten der App: Frontmatter nach
dem Phasenmodell (ergänzt um ``owner: ai``), Body mit allen sechs Abschnitten
und ein freier, lesbarer ASCII-Slug (Entscheidung R2). Vorhandene Dateien
werden nie überschrieben — Kollisionen bekommen ein Suffix (``-2``, ``-3``, …).
"""

from __future__ import annotations

import re

import yaml

import kennung
import okf_bundle
import slug
from okf_bundle import EingabeFehler

AUFGABEN_ORDNER = "aufgaben"
MAX_KURZBESCHREIBUNG = 160
MAX_KANDIDATEN = 1000

PRIORITAETEN = ("hoch", "mittel", "niedrig")

# Ein mitgegebenes Kennungspräfix wird entfernt (die App vergibt die Kennung).
_KENNUNG_PRAEFIX = re.compile(r"^A[0-9]+(?:\.[0-9]{3})?\s*:\s*")

ERGEBNIS_PLATZHALTER = (
    "Noch keine Einträge. Der `documenter` pflegt hier je Übergabe Datum, "
    "Rolle (coder/reviewer/tester), Ergebnis, Befunde, offene Punkte und Belege."
)


# --- Öffentliche Schnittstelle --------------------------------------------


def anlegen(daten: dict) -> str:
    """Legt eine neue Aufgaben-Datei an und liefert ihren bundle-relativen Pfad.

    Erwartet ``{titel, ziel, akzeptanz[], prioritaet, welle?, user_story?, parent?}``.
    Mit ``parent`` entsteht eine Unter-Aufgabe: die App vergibt ``A{xxx}.{uuu}``,
    erbt die ``welle`` der Eltern-Aufgabe und schreibt ``parent``. Unzulässige
    Daten führen zu :class:`EingabeFehler`, ohne dass eine Datei entsteht.
    """
    felder = _pruefe(daten)
    pfad = _freier_pfad(felder["basis"])
    okf_bundle.schreiben(pfad, _inhalt(felder))
    return pfad


# --- Eingabeprüfung -------------------------------------------------------


def _pruefe(daten: dict) -> dict:
    """Validiert und normalisiert die Formulardaten; wirft sonst ``EingabeFehler``."""
    if not isinstance(daten, dict):
        raise EingabeFehler("Formulardaten fehlen")

    titel = _text(daten.get("titel"), "Titel", einzeilig=True)
    ziel = _text(daten.get("ziel"), "Ziel")
    akzeptanz = _akzeptanzliste(daten.get("akzeptanz"))

    prioritaet = daten.get("prioritaet")
    if not isinstance(prioritaet, str) or not prioritaet.strip():
        raise EingabeFehler("Priorität fehlt")
    prioritaet = prioritaet.strip()
    if prioritaet not in PRIORITAETEN:
        raise EingabeFehler(
            f"Unzulässige Priorität {prioritaet!r} "
            f"(erlaubt: {', '.join(PRIORITAETEN)})"
        )

    parent = _eltern(daten.get("parent"))
    welle = _verweis(daten.get("welle"), "welle")
    if parent is not None and welle is not None:
        raise EingabeFehler(
            "welle darf nicht zusammen mit parent gesetzt werden — "
            "die Welle wird von der Eltern-Aufgabe geerbt"
        )

    if parent is None:
        basis = slug.slug_aus_titel(titel)
        if not basis:
            raise EingabeFehler("Titel enthält keine verwendbaren Zeichen für ein Kürzel")
    else:
        titel = _ohne_kennung(titel)
        basis = slug.slug_aus_titel(titel)
        if not basis:
            raise EingabeFehler("Titel enthält keine verwendbaren Zeichen für ein Kürzel")
        unterkennung = kennung.naechste_unterkennung(parent["pfad"])
        welle = parent["welle"]
        titel = f"{unterkennung}: {titel}"
        basis = f"{unterkennung.lower()}-{basis}"

    return {
        "titel": titel,
        "ziel": ziel,
        "akzeptanz": akzeptanz,
        "prioritaet": prioritaet,
        "basis": basis,
        "user_story": _verweis(daten.get("user_story"), "user_story"),
        "welle": welle,
        "parent": parent["pfad"] if parent is not None else None,
    }


def _text(wert: object, feldname: str, einzeilig: bool = False) -> str:
    if not isinstance(wert, str) or not wert.strip():
        raise EingabeFehler(f"{feldname} fehlt")
    return " ".join(wert.split()) if einzeilig else wert.strip()


def _akzeptanzliste(wert: object) -> list[str]:
    if not isinstance(wert, (list, tuple)):
        raise EingabeFehler("Akzeptanzkriterien müssen als Liste übergeben werden")

    eintraege: list[str] = []
    for eintrag in wert:
        if not isinstance(eintrag, str):
            raise EingabeFehler("Akzeptanzkriterien müssen Text sein")
        if eintrag.strip():
            eintraege.append(" ".join(eintrag.split()))
    if not eintraege:
        raise EingabeFehler("Mindestens ein Akzeptanzkriterium ist nötig")
    return eintraege


def _verweis(wert: object, feldname: str) -> str | None:
    """Optionaler Bundle-Verweis; leer oder fehlend ergibt ``None``."""
    if wert is None:
        return None
    if not isinstance(wert, str):
        raise EingabeFehler(f"{feldname} muss ein Pfad sein")
    text = " ".join(wert.split())
    return text or None


def _eltern(wert: object) -> dict | None:
    """Validiert ``parent`` und liefert ``{pfad, kennung, welle}`` oder ``None``.

    Gültig ist nur eine vorhandene, lesbare Aufgabe unter ``aufgaben/`` ohne
    eigenes ``parent`` (Tiefe 1), die nicht ``abgeschlossen`` ist und eine
    konsistente Top-Level-Kennung trägt. Verstöße sind Eingabefehler (400).
    """
    if wert is None:
        return None
    if not isinstance(wert, str):
        raise EingabeFehler("parent muss ein Pfad sein")
    pfad = " ".join(wert.split())
    if not pfad:
        return None
    if not pfad.startswith(f"{AUFGABEN_ORDNER}/"):
        raise EingabeFehler("parent muss auf eine Aufgabe unter aufgaben/ zeigen")
    if okf_bundle.ist_reserviert(pfad):
        raise EingabeFehler("parent darf keine reservierte Datei sein")
    try:
        ziel = okf_bundle.resolve_path(pfad)
        aufgaben = okf_bundle.resolve_path(AUFGABEN_ORDNER)
    except okf_bundle.BundlePfadFehler:
        raise EingabeFehler("parent ist kein gültiger Pfad") from None
    if ziel.suffix.lower() != ".md" or not ziel.is_relative_to(aufgaben):
        raise EingabeFehler("parent muss auf eine Aufgabe unter aufgaben/ zeigen")

    try:
        frontmatter, _ = okf_bundle.lesen(pfad)
    except FileNotFoundError:
        raise EingabeFehler("Eltern-Aufgabe wurde nicht gefunden") from None
    except (okf_bundle.FrontmatterFehler, OSError, UnicodeDecodeError):
        raise EingabeFehler("Eltern-Aufgabe ist nicht lesbar") from None

    if _wert(frontmatter.get("type")) != "Task":
        raise EingabeFehler("parent muss auf eine Aufgabe zeigen")
    if _wert(frontmatter.get("parent")):
        raise EingabeFehler("Unter-Aufgaben sind nur eine Ebene tief")
    if _wert(frontmatter.get("task_status")) == "abgeschlossen":
        raise EingabeFehler(
            "Unter einer abgeschlossenen Aufgabe können keine Unter-Aufgaben entstehen"
        )

    eltern = kennung.eltern_kennung(pfad, frontmatter)
    if eltern is None:
        raise EingabeFehler("Eltern-Aufgabe hat keine gültige Kennung")
    return {
        "pfad": pfad,
        "kennung": eltern,
        "welle": _wert(frontmatter.get("welle")),
    }


def _ohne_kennung(titel: str) -> str:
    """Entfernt ein führendes ``A<N>``/``A<N>.<uuu>``-Präfix samt Doppelpunkt."""
    return _KENNUNG_PRAEFIX.sub("", titel).strip()


def _wert(wert: object) -> str | None:
    """Getrimmter String oder ``None`` (für optionale Frontmatter-Werte)."""
    if not isinstance(wert, str):
        return None
    text = " ".join(wert.split())
    return text or None


# --- Dateiname ------------------------------------------------------------


def _freier_pfad(slug: str) -> str:
    """Erster freier Dateiname im Aufgaben-Ordner; reservierte Dateien bleiben frei."""
    for nummer in range(1, MAX_KANDIDATEN + 1):
        name = f"{slug}.md" if nummer == 1 else f"{slug}-{nummer}.md"
        if okf_bundle.ist_reserviert(name):
            continue
        pfad = f"{AUFGABEN_ORDNER}/{name}"
        if not okf_bundle.resolve_path(pfad).exists():
            return pfad
    raise EingabeFehler(f"Kein freier Dateiname für {slug!r} gefunden")


# --- Dateiinhalt ----------------------------------------------------------


def _inhalt(felder: dict) -> str:
    frontmatter = {
        "type": "Task",
        "title": felder["titel"],
        "description": _kurzbeschreibung(felder["ziel"]),
        "task_status": "offen",
        "phase": "2 Planung",
        "priority": felder["prioritaet"],
        "assigned_to": "coder",
    }
    for feld in ("user_story", "welle", "parent"):
        if felder[feld]:
            frontmatter[feld] = felder[feld]
    frontmatter["owner"] = "ai"
    # Neue Aufgaben sind nicht freigegeben (Menschen-Recht, A28).
    frontmatter["freigabe"] = False

    kopf = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip("\n")
    return f"---\n{kopf}\n---\n{_body(felder)}"


def _body(felder: dict) -> str:
    akzeptanz = "".join(f"- {eintrag}\n" for eintrag in felder["akzeptanz"])
    return (
        "\n# Ziel\n\n"
        f"{felder['ziel']}\n\n"
        "# Akzeptanzkriterien\n\n"
        f"{akzeptanz}\n"
        "# Testfälle (TDD)\n\n"
        "Noch keine Einträge — der `planner` ergänzt die Testfälle.\n\n"
        "# Kontext\n\n"
        f"{_kontext(felder)}\n\n"
        "# Betroffene Dateien\n\n"
        "Noch keine Einträge — die Planung ergänzt die betroffenen Dateien.\n\n"
        "# Ergebnisse\n\n"
        f"{ERGEBNIS_PLATZHALTER}\n"
    )


def _kontext(felder: dict) -> str:
    zeilen = []
    if felder["user_story"]:
        zeilen.append(f"- User Story: {_verweis_zeile(felder['user_story'])}")
    if felder["welle"]:
        zeilen.append(f"- Welle: [{_wellen_titel(felder['welle'])}]({felder['welle']})")
    return "\n".join(zeilen) or "Kein zusätzlicher Kontext angegeben."


def _wellen_titel(pfad: str) -> str:
    """Titel der Wellen-Datei als Linktext; sonst der Dateistamm (fail-safe).

    Ein fehlender, unlesbarer oder titelloser Verweis darf das Anlegen der
    Aufgabe nie verhindern — dann bleibt der bisherige Dateistamm stehen.
    """
    stamm = pfad.rstrip("/").rsplit("/", 1)[-1].removesuffix(".md")
    try:
        frontmatter, _ = okf_bundle.lesen(pfad)
    except (okf_bundle.BundlePfadFehler, okf_bundle.FrontmatterFehler, OSError):
        return stamm
    return _wert(frontmatter.get("title")) or stamm


def _verweis_zeile(pfad: str) -> str:
    name = pfad.rstrip("/").rsplit("/", 1)[-1].removesuffix(".md")
    return f"[{name}]({pfad})"


def _kurzbeschreibung(ziel: str) -> str:
    """Erste Zeile des Ziels als OKF-``description`` (max. 160 Zeichen)."""
    erste = ziel.splitlines()[0].strip() or ziel.strip()
    if len(erste) <= MAX_KURZBESCHREIBUNG:
        return erste
    return erste[: MAX_KURZBESCHREIBUNG - 1].rstrip() + "…"
