"""Statische Prüfungen für das Frontend-Gerüst (A10).

Die UI-Szenarien (Moli-Browser) prüft der ``tester`` gegen die laufende App;
hier werden ausschließlich die Dateien unter ``static/`` geprüft.
"""

import json
import re
from pathlib import Path

import pytest

from dom_helfer import node_ausfuehren, ohne_node

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
INDEX = STATIC_DIR / "index.html"
STYLE = STATIC_DIR / "style.css"
API_JS = STATIC_DIR / "js" / "api.js"
APP_JS = STATIC_DIR / "js" / "app.js"

NAVIGATIONS_PUNKTE = ["Übersicht", "Wellen", "Aufgaben", "Entscheidungen", "Projekt"]
PROJEKT_UNTERPUNKTE = ["Konzept", "Technische Spec", "User Stories", "Phasen", "Log"]
PROJEKT_UNTERPUNKT_ROUTEN = [
    "konzept",
    "technische-spec",
    "user-stories",
    "phasen",
    "log",
]

ANSICHT_IDS = [
    "ansicht-uebersicht",
    "ansicht-wellen",
    "ansicht-aufgaben",
    "ansicht-entscheidungen",
    "ansicht-projekt",
    "ansicht-detail",
]

CONTAINER_IDS = [
    "ansicht",
    "fehler",
    "meldung",
    "tabelle",
    "tabelle-wellen",
    "tabelle-aufgaben",
    "filter-status",
    "filter-owner",
    "filter-zuruecksetzen",
    "uebersicht-zuletzt",
    "uebersicht-klarung",
    "filter-wellen",
    "filter-wellen-status",
    "filter-wellen-owner",
    "filter-wellen-zuruecksetzen",
    "filter-aufgaben",
    "filter-aufgaben-status",
    "filter-aufgaben-owner",
    "filter-aufgaben-zuruecksetzen",
    "liste-entscheidungen",
    "liste-projekt",
    "detail",
    "formular-aufgabe",
    "formular-welle",
]

STATUS_FILTERWERTE = [
    "Klarung",
    "Offen",
    "In Arbeit",
    "Testing",
    "Dokumentation",
    "Geschlossen",
]

OWNER_FILTERWERTE = ["mensch", "ai", "ohne"]


def lies(pfad: Path) -> str:
    assert pfad.is_file(), f"{pfad} fehlt"
    return pfad.read_text(encoding="utf-8")


def navigation(html: str) -> str:
    treffer = re.search(r"<nav\b.*?</nav>", html, re.DOTALL)
    assert treffer, "index.html enthält kein <nav>-Element"
    return treffer.group(0)


def test_dateien_vorhanden():
    for pfad in (INDEX, STYLE, API_JS, APP_JS):
        assert pfad.is_file(), f"{pfad} fehlt"


@pytest.mark.parametrize("label", NAVIGATIONS_PUNKTE)
def test_t1_navigationspunkt_vorhanden(label):
    assert f">{label}</a>" in navigation(lies(INDEX))


@pytest.mark.parametrize("label", PROJEKT_UNTERPUNKTE)
def test_t1_projekt_unterpunkt_vorhanden(label):
    assert f">{label}</a>" in navigation(lies(INDEX))


def test_t1_navigation_verweist_auf_hash_routen():
    html = lies(INDEX)
    for route in ("uebersicht", "wellen", "aufgaben", "entscheidungen", "projekt"):
        assert f'href="#/{route}"' in navigation(html)


@pytest.mark.parametrize("unterpunkt", PROJEKT_UNTERPUNKT_ROUTEN)
def test_t1_projekt_unterpunkt_hash_route(unterpunkt):
    assert f'href="#/projekt/{unterpunkt}"' in navigation(lies(INDEX))


@pytest.mark.parametrize("container_id", CONTAINER_IDS)
def test_t2_container_id_vorhanden(container_id):
    assert f'id="{container_id}"' in lies(INDEX)


@pytest.mark.parametrize("ansicht_id", ANSICHT_IDS)
def test_t2_ansichts_sektion_vorhanden(ansicht_id):
    html = lies(INDEX)
    assert f'id="{ansicht_id}"' in html
    assert f'data-ansicht="{ansicht_id.removeprefix("ansicht-")}"' in html


def test_t2_filter_optionen():
    html = lies(INDEX)
    for wert in STATUS_FILTERWERTE:
        assert f">{wert}</option>" in html
    for wert in OWNER_FILTERWERTE:
        assert f">{wert}</option>" in html


@pytest.mark.parametrize("basis", ["wellen", "aufgaben"])
def test_t2_filter_je_ansicht(basis):
    html = lies(INDEX)
    treffer = re.search(rf'<form id="filter-{basis}".*?</form>', html, re.DOTALL)
    assert treffer, f"Filterformular für {basis} fehlt"
    block = treffer.group(0)
    assert f'id="filter-{basis}-status"' in block
    assert f'id="filter-{basis}-owner"' in block
    assert f'id="filter-{basis}-zuruecksetzen"' in block


def test_t2_uebersicht_zusatzbereiche():
    html = lies(INDEX)
    assert 'id="uebersicht-zuletzt"' in html
    assert 'id="uebersicht-klarung"' in html
    assert "Zuletzt geändert" in html
    assert "Klarung" in html


def test_t3_app_als_es_modul_eingebunden():
    html = lies(INDEX)
    assert 'type="module"' in html
    assert 'src="/static/js/app.js"' in html
    assert '<link rel="stylesheet" href="/static/style.css">' in html


def test_t3_meta_viewport_und_sprache():
    html = lies(INDEX)
    assert '<meta name="viewport"' in html
    assert '<html lang="de">' in html


def test_keine_externen_ressourcen():
    html = lies(INDEX)
    assert not re.search(r'(?:src|href)="https?://', html), "kein CDN/externe Ressource erlaubt"


def test_t4_api_js_exportiert_wrapper():
    js = lies(API_JS)
    assert re.search(r"export\s+async\s+function\s+getJson\b", js)
    assert re.search(r"export\s+async\s+function\s+postJson\b", js)


def test_t4_api_js_behandelt_netzwerk_und_serverfehler():
    js = lies(API_JS)
    assert "fetch(" in js
    assert "Netzwerkfehler" in js
    assert ".error" in js
    assert 'id="fehler"' in lies(INDEX)


def test_t4_api_js_exportiert_meldungshelfer():
    js = lies(API_JS)
    assert re.search(r"export\s+function\s+zeigeMeldung\b", js)
    assert re.search(r"export\s+function\s+loescheMeldung\b", js)
    assert 'id="meldung"' in lies(INDEX)


def test_t4_api_js_get_ohne_cache():
    assert 'cache: "no-store"' in lies(API_JS)


def test_t4_api_js_mit_zeitueberschreitung():
    js = lies(API_JS)
    assert "AbortSignal.timeout" in js
    assert "Zeitüberschreitung" in js


def test_t4_api_js_leerer_body_ist_kein_fehler():
    js = lies(API_JS)
    assert "204" in js


def test_api_js_loescht_fehler_nicht_im_erfolgsfall():
    js = lies(API_JS)
    treffer = re.search(r"async function anfrage\([\s\S]*?\n}\n", js)
    assert treffer, "anfrage() nicht gefunden"
    assert "loescheFehler" not in treffer.group(0)


def test_app_js_ist_hash_router():
    js = lies(APP_JS)
    assert "hashchange" in js
    assert "location.hash" in js
    assert "aria-current" in js


def test_app_js_exportiert_registriere_ansicht():
    assert re.search(r"export\s+function\s+registriereAnsicht\b", lies(APP_JS))


def test_app_js_unbekannte_route_laedt_trotzdem():
    js = lies(APP_JS)
    treffer = re.search(r"if \(rohBasis && basis !== rohBasis\) \{\n(.*?)\n  \}", js, re.DOTALL)
    assert treffer, "Prüfung auf unbekannte Route fehlt"
    block = treffer.group(1)
    assert "zeigeFehler" in block
    assert "return" not in block


def test_app_js_registriere_ansicht_bleibt_funktionsdeklaration():
    js = lies(APP_JS)
    treffer = re.search(r"(/\*\*[\s\S]*?\*/)\s*export function registriereAnsicht", js)
    assert treffer, "Kommentar zu registriereAnsicht fehlt"
    assert "zyklisch" in treffer.group(1).lower()


def test_app_js_registriere_ansicht_prueft_basis():
    js = lies(APP_JS)
    treffer = re.search(r"export function registriereAnsicht\([\s\S]*?\n}\n", js)
    assert treffer, "registriereAnsicht() nicht gefunden"
    assert "istAnsicht(basis)" in treffer.group(0)


# --- A33-T16 (A14-5): genau ein `istDatei`-Prädikat ----------------------

DETAIL_JS = STATIC_DIR / "js" / "detail.js"
FEATURES_JS = STATIC_DIR / "js" / "features.js"
PROJEKT_JS = STATIC_DIR / "js" / "projekt.js"


@ohne_node
def test_a33_t16_ist_datei_antwort_semantik():
    """Zentrales Prädikat: Objekt, kein Array, ``markdown`` ist ein String."""
    skript = (
        f"import * as api from {json.dumps(API_JS.as_uri())};\n"
        "const faelle = [\n"
        "  [{ markdown: '' }, true],\n"
        "  [{ markdown: '# x', frontmatter: {} }, true],\n"
        "  [null, false],\n"
        "  [undefined, false],\n"
        "  [[], false],\n"
        "  [['x'], false],\n"
        "  [{}, false],\n"
        "  [{ markdown: 42 }, false],\n"
        "  [{ markdown: null }, false],\n"
        "  ['# x', false],\n"
        "  [42, false],\n"
        "];\n"
        "console.log(JSON.stringify(faelle.map(([wert, erwartet]) => ({\n"
        "  erwartet,\n"
        "  tatsaechlich: api.istDateiAntwort(wert),\n"
        "}))));"
    )
    ergebnis = node_ausfuehren(skript)

    assert len(ergebnis) == 11
    assert [fall for fall in ergebnis if fall["tatsaechlich"] != fall["erwartet"]] == []


def test_a33_t16_nur_ein_praedikat_und_importe():
    """Die drei Ansichten importieren das Prädikat statt eigener Kopien."""
    assert re.search(r"export\s+function\s+istDateiAntwort\b", lies(API_JS))

    for datei in (DETAIL_JS, FEATURES_JS, PROJEKT_JS):
        quelle = lies(datei)
        assert "function istDatei(" not in quelle, datei
        assert re.search(
            r'import\s*\{[^}]*\bistDateiAntwort\b[^}]*\}\s*from\s*"\./api\.js"', quelle
        ), f"{datei} importiert istDateiAntwort nicht aus api.js"

    for datei in sorted((STATIC_DIR / "js").glob("*.js")):
        if datei.name == "api.js":
            continue
        assert 'typeof daten.markdown === "string"' not in lies(datei), datei


@pytest.mark.parametrize(
    ("datei", "meldung"),
    [
        (DETAIL_JS, "Datei hat ein unerwartetes Format."),
        (PROJEKT_JS, "Datei hat ein unerwartetes Format."),
        (FEATURES_JS, "Feature-Liste hat ein unerwartetes Format"),
    ],
)
def test_a33_t16_meldungen_bleiben_kontextspezifisch(datei, meldung):
    """Nur das Prädikat ist geteilt; die Meldungen bleiben je Ansicht eigen."""
    quelle = lies(datei)
    assert meldung in quelle
    assert "Format" not in lies(API_JS)
    assert "konnte nicht geladen werden" not in lies(API_JS)
