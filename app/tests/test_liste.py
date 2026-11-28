"""Prüfungen für die Listenansicht (A11).

Die UI-Szenarien T1–T9 spielt der ``tester`` mit dem Moli-Browser durch; hier
werden ``liste.js`` und seine Verdrahtung ohne Browser geprüft. Die reine
Filter-/Sortier-/Formatier-Logik läuft über Node (keine neue Abhängigkeit).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
LISTE_JS = STATIC_DIR / "js" / "liste.js"
APP_JS = STATIC_DIR / "js" / "app.js"
API_JS = STATIC_DIR / "js" / "api.js"
NODE = shutil.which("node")

ohne_node = pytest.mark.skipif(NODE is None, reason="node nicht verfügbar")

FILTER_IDS = [
    "tabelle",
    "tabelle-wellen",
    "tabelle-aufgaben",
    "filter-status",
    "filter-owner",
    "filter-zuruecksetzen",
    "filter-wellen-status",
    "filter-wellen-owner",
    "filter-wellen-zuruecksetzen",
    "filter-aufgaben-status",
    "filter-aufgaben-owner",
    "filter-aufgaben-zuruecksetzen",
    "uebersicht-zuletzt",
    "uebersicht-klarung",
]


def lies(pfad: Path) -> str:
    assert pfad.is_file(), f"{pfad} fehlt"
    return pfad.read_text(encoding="utf-8")


def js(ausdruck: str, daten=None):
    """Wertet einen Ausdruck im Kontext von ``liste.js`` über Node aus."""
    assert NODE is not None
    skript = (
        f"import * as liste from {json.dumps(LISTE_JS.as_uri())};\n"
        f"const daten = {json.dumps(daten, ensure_ascii=False)};\n"
        f"console.log(JSON.stringify({ausdruck}));"
    )
    ergebnis = subprocess.run(
        [NODE, "--input-type=module", "-e", skript],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    return json.loads(ergebnis.stdout)


# --- Statische Prüfungen ---------------------------------------------------


def test_liste_js_vorhanden():
    assert LISTE_JS.is_file()


def test_app_js_importiert_liste():
    assert re.search(r'from\s+"\./liste\.js"', lies(APP_JS))


@pytest.mark.parametrize("basis", ["uebersicht", "wellen", "aufgaben"])
def test_app_js_verdrahtet_ansicht(basis):
    assert f'registriereAnsicht("{basis}"' in lies(APP_JS)


@pytest.mark.parametrize("endpunkt", ["/api/overview", "/api/aufgaben", "/api/wellen"])
def test_liste_js_nutzt_endpunkt(endpunkt):
    assert endpunkt in lies(LISTE_JS)


@pytest.mark.parametrize("element_id", FILTER_IDS)
def test_liste_js_verwendet_ids(element_id):
    assert f'"{element_id}"' in lies(LISTE_JS)


def test_liste_js_zeigt_leerzustand():
    assert "Keine Einträge" in lies(LISTE_JS)


def test_liste_js_hebt_klarung_hervor():
    js_quelle = lies(LISTE_JS)
    assert '"klarung"' in js_quelle
    assert '"Klarung"' in js_quelle


def test_liste_js_rendert_ohne_innerhtml():
    js_quelle = lies(LISTE_JS)
    assert "textContent" in js_quelle
    assert "innerHTML" not in js_quelle


@pytest.mark.parametrize(
    "senke",
    ["outerHTML", "insertAdjacentHTML", "document.write(", "eval("],
)
def test_liste_js_vermeidet_weitere_html_senken(senke):
    assert senke not in lies(LISTE_JS)


def test_liste_js_hebt_klarung_per_klassenliste_hervor():
    js_quelle = lies(LISTE_JS)
    assert 'classList.add("klarung")' in js_quelle
    assert 'className = "klarung"' not in js_quelle


def test_liste_js_setzt_klassen_nur_per_klassenliste():
    # A11-1: Einheitlichkeit — auch Initialklassen laufen über `classList.add`.
    js_quelle = lies(LISTE_JS)
    assert "classList.add(" in js_quelle
    assert "className =" not in js_quelle
    assert "className=" not in js_quelle


def test_liste_js_ohne_submit_handler():
    # Formulare filtern über `change`/`click`; ein Submit-Pfad existiert nicht.
    assert 'addEventListener("submit"' not in lies(LISTE_JS)


def test_liste_js_formatiert_zeitstempel_lokal():
    assert "Intl.DateTimeFormat" in lies(LISTE_JS)


def test_liste_js_nutzt_api_helper():
    assert re.search(r"import\s*\{[^}]*\bgetJson\b[^}]*\}\s*from\s*\"\./api\.js\"", lies(LISTE_JS))


def test_liste_js_fragt_ohne_cache_ab():
    # ``cache: "no-store"`` kommt zentral aus api.js und gilt damit auch hier.
    assert 'cache: "no-store"' in lies(API_JS)


# --- Reine Logik über Node -------------------------------------------------

EINTRAEGE = [
    {
        "path": "aufgaben/a1.md",
        "titel": "A1",
        "status": "Klarung",
        "owner": "mensch",
        "zuletzt_geaendert": "2026-11-14T10:00:00",
    },
    {
        "path": "aufgaben/a2.md",
        "titel": "A2",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T12:00:00",
    },
    {
        "path": "wellen/w1.md",
        "titel": "W1",
        "status": "Klarung",
        "owner": None,
        "zuletzt_geaendert": "2026-11-13T09:00:00",
    },
    {
        "path": "wellen/w2.md",
        "titel": "W2",
        "status": "Geschlossen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-12T09:00:00",
    },
]


@ohne_node
def test_filter_status():
    pfade = js("liste.filtereEintraege(daten, { status: 'Klarung' }).map((e) => e.path)", EINTRAEGE)
    assert pfade == ["aufgaben/a1.md", "wellen/w1.md"]


@ohne_node
def test_filter_owner():
    pfade = js("liste.filtereEintraege(daten, { owner: 'mensch' }).map((e) => e.path)", EINTRAEGE)
    assert pfade == ["aufgaben/a1.md"]


@ohne_node
def test_filter_owner_ohne():
    pfade = js("liste.filtereEintraege(daten, { owner: 'ohne' }).map((e) => e.path)", EINTRAEGE)
    assert pfade == ["wellen/w1.md"]


@ohne_node
def test_filter_kombiniert():
    pfade = js(
        "liste.filtereEintraege(daten, { status: 'Klarung', owner: 'mensch' }).map((e) => e.path)",
        EINTRAEGE,
    )
    assert pfade == ["aufgaben/a1.md"]


@ohne_node
def test_filter_ohne_auswahl_liefert_vollbestand():
    anzahl = js(
        "liste.filtereEintraege(daten, { status: '', owner: '' }).length",
        EINTRAEGE,
    )
    assert anzahl == len(EINTRAEGE)


@ohne_node
def test_filter_behaelt_geschlossene_eintraege():
    pfade = js("liste.filtereEintraege(daten, {}).map((e) => e.path)", EINTRAEGE)
    assert "wellen/w2.md" in pfade


@ohne_node
def test_filter_vertraegt_fehlende_liste():
    assert js("liste.filtereEintraege(null, {})", None) == []
    assert js("liste.filtereEintraege(undefined, {})", None) == []


@ohne_node
def test_anzeige_bei_antwort_array():
    anzeige = js("liste.waehleAnzeige(daten)", EINTRAEGE)
    assert anzeige["art"] == "tabelle"
    assert len(anzeige["eintraege"]) == len(EINTRAEGE)
    assert not anzeige["text"]


@ohne_node
def test_anzeige_bei_leerer_liste_ist_leerzustand():
    anzeige = js("liste.waehleAnzeige([])", None)
    assert anzeige["art"] == "leer"
    assert "Keine Einträge" in anzeige["text"]


@ohne_node
def test_anzeige_bei_ladefehler_bleibt_bei_filterwechsel_fehler():
    ladefehler = js("liste.waehleAnzeige(null).text", None)
    anzeige = js("liste.waehleAnzeige(null, { status: 'Klarung', owner: 'mensch' })", None)
    assert anzeige["art"] == "fehler"
    assert anzeige["text"] == ladefehler
    assert anzeige["text"]


@pytest.mark.parametrize("antwort", ["{}", '{"error": "kaputt"}', '"text"', "42", "undefined"])
@ohne_node
def test_anzeige_bei_nicht_array_meldet_formatfehler(antwort):
    anzeige = js(f"liste.waehleAnzeige({antwort})", None)
    assert anzeige["art"] == "fehler"
    assert anzeige["text"]
    assert "Keine Einträge" not in anzeige["text"]


@ohne_node
def test_filter_veraendert_eingabe_nicht():
    unveraendert = js(
        "(() => { const vorher = daten.map((e) => e.path).join(',');"
        " liste.filtereEintraege(daten, { status: 'Klarung' });"
        " return daten.map((e) => e.path).join(',') === vorher; })()",
        EINTRAEGE,
    )
    assert unveraendert is True


@ohne_node
def test_sortierung_nach_zuletzt_geaendert():
    pfade = js("liste.sortiereNachAenderung(daten).map((e) => e.path)", EINTRAEGE)
    assert pfade == ["aufgaben/a2.md", "aufgaben/a1.md", "wellen/w1.md", "wellen/w2.md"]


@ohne_node
def test_sortierung_vertraegt_ungueltige_zeit():
    daten = [
        {"path": "b.md", "zuletzt_geaendert": None},
        {"path": "a.md", "zuletzt_geaendert": "2026-11-14T10:00:00"},
        {"path": "c.md", "zuletzt_geaendert": "keine-zeit"},
    ]
    assert js("liste.sortiereNachAenderung(daten).map((e) => e.path)", daten) == [
        "a.md",
        "b.md",
        "c.md",
    ]


@ohne_node
def test_zeitstempel_lokal_formatiert():
    formatiert = js("liste.formatiereZeitstempel('2026-11-14T10:00:00')", None)
    assert formatiert != "—"
    assert re.search(r"\d{2}\.\d{2}\.\d{2}", formatiert)


@ohne_node
def test_zeitstempel_fehlend_oder_ungueltig():
    assert js("liste.formatiereZeitstempel(null)", None) == "—"
    assert js("liste.formatiereZeitstempel('keine-zeit')", None) == "—"
