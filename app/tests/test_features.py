"""Prüfungen für die Feature-List-Ansicht (A23).

Die UI-Szenarien S1–S4 spielt der ``tester`` mit dem Moli-Browser durch; hier
werden ``features.js`` und seine Verdrahtung ohne Browser geprüft. Der Parser
läuft über Node (keine neue Abhängigkeit), die Ansichten im Node-DOM-Harness —
einmal mit Antworten aus dem Fetch-Stab und einmal per HTTP gegen ein
Test-Bundle unter ``tmp_path`` (nie gegen das echte Projekt-Bundle). Genutzt
werden ausschließlich ``GET /api/file`` und ``GET /api/aufgaben``.
Der Mini-DOM-Harness liegt in ``dom_helfer.py``; hier bleiben Seiten- und
Fetch-Gerüst.
"""

import json
import re
import sys
import threading
from pathlib import Path
from urllib.parse import unquote

import pytest
from werkzeug.serving import make_server

from dom_helfer import MINI_DOM, lies, node_ausfuehren, ohne_node

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
INDEX_HTML = STATIC_DIR / "index.html"
FEATURES_JS = STATIC_DIR / "js" / "features.js"
APP_JS = STATIC_DIR / "js" / "app.js"
SERVER_PY = Path(__file__).resolve().parents[1] / "server.py"

FEATURES_PFAD = "features.md"
AUFGABEN_ENDPUNKT = "/api/aufgaben"
FEATURES_ROUTE = "#/features"
DETAIL_VORSCHLAG = "#/detail/"

NAVIGATION_PUNKTE = ["Übersicht", "Wellen", "Aufgaben", "Entscheidungen", "Projekt"]
NAVIGATION_ROUTEN = ["uebersicht", "wellen", "aufgaben", "entscheidungen", "projekt"]
UNTERPUNKT_ROUTEN = ["konzept", "technische-spec", "user-stories", "phasen", "log"]
ANSICHT_IDS = [
    "ansicht-uebersicht",
    "ansicht-wellen",
    "ansicht-aufgaben",
    "ansicht-entscheidungen",
    "ansicht-projekt",
    "ansicht-detail",
]

# Fixture, das die reale Struktur von `wissen/features.md` nachbildet:
# Frontmatter, Statuswerte, Regeln (mit /aufgaben/-Link), Feature-Abschnitt,
# Offene Punkte (mit A22-Link) und Umgesetzte Features.
FEATURES_MD = """---
type: Feature Overview
title: Features-Überblick
description: Testfixture.
tags: [features, steuerung]
---

# Statuswerte

`offen` · `in Umsetzung` · `umgesetzt` · `pausiert`

# Regeln

* Jeder Eintrag verlinkt auf seine Feature-Datei unter `/features/` und auf die zugehörigen Aufgaben unter `/aufgaben/`.
* Zu jedem offenen Punkt müssen die Aufgaben dokumentiert sein (siehe [Phasenmodell](/projekt/phasen.md)).

# Offene Features

* [OKF Projekt-Manager (SPA)](features/okf-projekt-manager-spa.md) — Tracker auf das OKF-Bundle · **umgesetzt — MVP abnahmefähig (Abnahme durch Projektleitung ausstehend)** · Priorität **hoch**
  * **Umgesetzt (Review/Test/Doku):** [A1](aufgaben/a1-okf-bundle.md) Fundament, [A2](aufgaben/a2-status-mapping.md) Mapping, [A1 erneut](aufgaben/a1-okf-bundle.md) doppelt
  * **Offen:** nur noch **MVP-Abnahme** durch die Projektleitung
  * **Vorgemerkt:** **A21 „Desktop-Modus"** — ohne Dateilink

# Offene Punkte

## Erledigt — Kleinbefunde

* **Batch A:** echte Fixes.
* [A22](aufgaben/a22-e2e-regression.md) E2E-Regression.

# Umgesetzte Features

*Noch keine.*
"""

FEATURES_ERWARTET = [
    {
        "titel": "OKF Projekt-Manager (SPA)",
        "pfad": "features/okf-projekt-manager-spa.md",
        "slug": "okf-projekt-manager-spa",
        "status": "umgesetzt",
        "hinweis": "MVP abnahmefähig (Abnahme durch Projektleitung ausstehend)",
        "prioritaet": "hoch",
        "aufgaben": ["aufgaben/a1-okf-bundle.md", "aufgaben/a2-status-mapping.md"],
    }
]

LEERER_ABSCHNITT_MD = "# Offene Features\n\n# Umgesetzte Features\n\n*Noch keine.*\n"


def js(ausdruck: str, daten=None):
    """Wertet einen Ausdruck im Kontext von ``features.js`` über Node aus."""
    skript = (
        f"import * as features from {json.dumps(FEATURES_JS.as_uri())};\n"
        f"const daten = {json.dumps(daten, ensure_ascii=False)};\n"
        f"console.log(JSON.stringify({ausdruck}));"
    )
    return node_ausfuehren(skript)


def js_ablauf(ablauf: str, daten=None):
    """Führt ein mehrzeiliges Node-Skript im Kontext von ``features.js`` aus."""
    skript = (
        f"import * as features from {json.dumps(FEATURES_JS.as_uri())};\n"
        f"const daten = {json.dumps(daten, ensure_ascii=False)};\n"
        "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        "console.log(JSON.stringify(ergebnis));"
    )
    return node_ausfuehren(skript)


# --- Statische Prüfungen (T1–T5) ------------------------------------------


def test_features_js_vorhanden():
    assert FEATURES_JS.is_file()


def navigation(html: str) -> str:
    treffer = re.search(r"<nav\b.*?</nav>", html, re.DOTALL)
    assert treffer, "index.html enthält kein <nav>-Element"
    return treffer.group(0)


def test_t1_ein_menuepunkt_feature_list():
    nav = navigation(lies(INDEX_HTML))
    assert len(re.findall(r'href="#/features"', nav)) == 1
    assert ">Feature List</a>" in nav


def test_t1_menuepunkt_nach_aufgaben():
    html = lies(INDEX_HTML)
    assert html.index('href="#/features"') > html.index('href="#/aufgaben"')
    assert html.index('href="#/features"') < html.index('href="#/entscheidungen"')


def test_t1_bestehende_navigation_bleibt_vollstaendig():
    nav = navigation(lies(INDEX_HTML))
    for label in NAVIGATION_PUNKTE:
        assert f">{label}</a>" in nav
    for route in NAVIGATION_ROUTEN:
        assert f'href="#/{route}"' in nav
    for unterpunkt in UNTERPUNKT_ROUTEN:
        assert f'href="#/projekt/{unterpunkt}"' in nav
    # Teilmengenprüfung: mindestens die elf erwarteten Links (fünf Hauptpunkte,
    # fünf Projekt-Unterpunkte, Feature List) müssen vorhanden sein; weitere
    # Menüpunkte anderer Aufgaben brechen diesen Test nicht.
    assert nav.count('class="navigation-link"') >= 11


def test_t1_view_container_feature_list():
    html = lies(INDEX_HTML)
    treffer = re.search(r'<section id="ansicht-features"[^>]*>', html)
    assert treffer, "Sektion #ansicht-features fehlt"
    assert 'data-ansicht="features"' in treffer.group(0)
    assert 'id="liste-features"' in html


@pytest.mark.parametrize("ansicht_id", ANSICHT_IDS)
def test_t1_bestehende_ansichten_bleiben(ansicht_id):
    assert f'id="{ansicht_id}"' in lies(INDEX_HTML)


def test_t2_app_js_kennt_features_ansicht():
    js_quelle = lies(APP_JS)
    assert 'features: "ansicht-features"' in js_quelle


def test_t2_app_js_importiert_und_registriert_features():
    js_quelle = lies(APP_JS)
    assert re.search(r'from\s+"\./features\.js"', js_quelle)
    assert 'registriereAnsicht("features", ladeFeaturesAnsicht)' in js_quelle


def test_t4_features_js_nutzt_nur_bestehende_endpunkte():
    js_quelle = lies(FEATURES_JS)
    assert set(re.findall(r"/api/[a-z_-]+", js_quelle)) == {"/api/file", AUFGABEN_ENDPUNKT}
    assert "postJson" not in js_quelle


@pytest.mark.parametrize(
    "senke",
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write(", "eval("],
)
def test_t4_features_js_vermeidet_html_senken(senke):
    assert senke not in lies(FEATURES_JS)


def test_t4_features_js_nutzt_textcontent_und_classlist():
    js_quelle = lies(FEATURES_JS)
    assert "textContent" in js_quelle
    assert "classList" in js_quelle
    assert "className" not in js_quelle


def test_t4_server_ohne_neuen_endpunkt():
    quelle = lies(SERVER_PY)
    assert "/api/features" not in quelle
    # Teilmengenprüfung: die bestehenden GET-Endpunkte bleiben vorhanden;
    # zusätzliche Endpunkte anderer Aufgaben (z. B. A27) brechen den Test nicht.
    assert len(re.findall(r"@app\.get\(", quelle)) >= 5


def test_t5_menuepunkt_ueber_http_erreichbar(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    antwort = server.create_app(bundle).test_client().get("/")
    assert antwort.status_code == 200
    html = antwort.get_data(as_text=True)
    assert 'href="#/features"' in html
    assert 'id="liste-features"' in html


# --- Parser `parseFeatures` (T6–T11) --------------------------------------


@ohne_node
def test_t6_reale_struktur_wird_gelesen():
    assert js("features.parseFeatures(daten)", FEATURES_MD) == FEATURES_ERWARTET


@ohne_node
def test_t6_titel_mit_klammern_und_slug():
    ergebnis = js("features.parseFeatures(daten)", FEATURES_MD)[0]
    assert ergebnis["titel"] == "OKF Projekt-Manager (SPA)"
    assert ergebnis["slug"] == "okf-projekt-manager-spa"


@ohne_node
def test_t6_aufgaben_in_dateireihenfolge_dedupliziert():
    assert js("features.parseFeatures(daten)", FEATURES_MD)[0]["aufgaben"] == [
        "aufgaben/a1-okf-bundle.md",
        "aufgaben/a2-status-mapping.md",
    ]


@ohne_node
def test_t7_regeln_und_offene_punkte_erzeugen_kein_feature():
    # `# Regeln` und `# Offene Punkte` enthalten `/features/`- und
    # `/aufgaben/`-Links (u. a. A22); nur die Feature-Abschnitte zählen.
    ergebnis = js("features.parseFeatures(daten)", FEATURES_MD)
    assert len(ergebnis) == 1
    assert "aufgaben/a22-e2e-regression.md" not in ergebnis[0]["aufgaben"]


@ohne_node
def test_t7_nur_feature_abschnitte_liefern_eintraege():
    markdown = (
        "# Regeln\n"
        "\n"
        "* [Falsch](features/falsch.md) — **offen** · Priorität **hoch**\n"
        "\n"
        "# Offene Features\n"
        "\n"
        "* [Richtig](features/richtig.md) — **offen** · Priorität **mittel**\n"
        "\n"
        "# Offene Punkte\n"
        "\n"
        "* [Auch falsch](features/auch-falsch.md) — **umgesetzt**\n"
    )
    titel = [eintrag["titel"] for eintrag in js("features.parseFeatures(daten)", markdown)]
    assert titel == ["Richtig"]


@ohne_node
def test_t7_unterabschnitte_beenden_feature_abschnitt_nicht():
    # `## …` innerhalb von `# Offene Features` beendet den Abschnitt nicht.
    markdown = (
        "# Offene Features\n"
        "\n"
        "## Unterpunkt\n"
        "\n"
        "* [Titel](features/titel.md) — **offen** · Priorität **niedrig**\n"
    )
    assert js("features.parseFeatures(daten)", markdown)[0]["titel"] == "Titel"


@ohne_node
@pytest.mark.parametrize(
    "segment,status,hinweis",
    [
        ("**offen**", "offen", None),
        ("**in Umsetzung**", "in Umsetzung", None),
        ("**umgesetzt — Text**", "umgesetzt", "Text"),
        ("**umgesetzt – Text**", "umgesetzt", "Text"),
        ("**umgesetzt - Text**", "umgesetzt", "Text"),
        ("**pausiert**", "pausiert", None),
        ("**pausiert — Warten auf Freigabe**", "pausiert", "Warten auf Freigabe"),
    ],
)
def test_t8_statusvarianten(segment, status, hinweis):
    markdown = (
        "# Offene Features\n"
        "\n"
        f"* [Titel](features/titel.md) — Text · {segment} · Priorität **hoch**\n"
    )
    ergebnis = js("features.parseFeatures(daten)", markdown)[0]
    assert ergebnis["status"] == status
    assert ergebnis["hinweis"] == hinweis
    assert ergebnis["prioritaet"] == "hoch"


@ohne_node
@pytest.mark.parametrize("prioritaet", ["hoch", "mittel", "niedrig"])
def test_t8_prioritaet_wird_nicht_als_status_gelesen(prioritaet):
    markdown = (
        "# Offene Features\n"
        "\n"
        f"* [Titel](features/titel.md) — Text · **offen** · Priorität **{prioritaet}**\n"
    )
    ergebnis = js("features.parseFeatures(daten)", markdown)[0]
    assert ergebnis["status"] == "offen"
    assert ergebnis["prioritaet"] == prioritaet


@ohne_node
def test_t8_prioritaet_ist_kein_status():
    markdown = (
        "# Offene Features\n"
        "\n"
        "* [Titel](features/titel.md) — Text · Priorität **hoch**\n"
    )
    ergebnis = js("features.parseFeatures(daten)", markdown)[0]
    assert ergebnis["status"] == "offen"
    assert ergebnis["hinweis"] == "ohne Status"
    assert ergebnis["prioritaet"] == "hoch"


@ohne_node
def test_t9_fehlender_status_ist_offen_ohne_status():
    markdown = "# Offene Features\n\n* [Titel](features/titel.md) — nur Text\n"
    ergebnis = js("features.parseFeatures(daten)", markdown)[0]
    assert ergebnis["status"] == "offen"
    assert ergebnis["hinweis"] == "ohne Status"
    assert ergebnis["prioritaet"] is None


@ohne_node
def test_t9_unbekannter_status_wird_gespiegelt():
    markdown = (
        "# Offene Features\n"
        "\n"
        "* [Titel](features/titel.md) — Text · **in Arbeit** · Priorität **hoch**\n"
    )
    ergebnis = js("features.parseFeatures(daten)", markdown)[0]
    assert ergebnis["status"] == "offen"
    assert ergebnis["hinweis"] == "in Arbeit"


@ohne_node
def test_t10_mehrere_features_und_getrennte_aufgaben():
    markdown = (
        "# Offene Features\n"
        "\n"
        "* [Erstes](features/erstes.md) — Text · **offen** · Priorität **hoch**\n"
        "  * [A1](aufgaben/a1-okf-bundle.md) Fundament\n"
        "* [Zweites](features/zweites.md) — Text · **pausiert** · Priorität **niedrig**\n"
        "* [Drittes](features/drittes.md) — Text · **in Umsetzung** · Priorität **mittel**\n"
        "  * [A2](aufgaben/a2-status-mapping.md) Mapping\n"
    )
    ergebnis = js("features.parseFeatures(daten)", markdown)
    assert [eintrag["titel"] for eintrag in ergebnis] == ["Erstes", "Zweites", "Drittes"]
    assert ergebnis[0]["aufgaben"] == ["aufgaben/a1-okf-bundle.md"]
    assert ergebnis[1]["aufgaben"] == []
    assert ergebnis[2]["aufgaben"] == ["aufgaben/a2-status-mapping.md"]


@ohne_node
def test_t10_top_level_aufgabenlink_erzeugt_kein_feature():
    markdown = (
        "# Offene Features\n"
        "\n"
        "* [Titel](features/titel.md) — **offen** · Priorität **hoch**\n"
        "* [A9](aufgaben/a9-api-schreiben.md) nur eine Aufgabe\n"
    )
    ergebnis = js("features.parseFeatures(daten)", markdown)
    assert len(ergebnis) == 1
    assert ergebnis[0]["aufgaben"] == []


@ohne_node
def test_t11_leere_und_falsche_eingaben():
    for eingabe in ("", "   ", "\n \n", None, 42):
        assert js("features.parseFeatures(daten)", eingabe) == []


@ohne_node
def test_t11_crlf_und_kodierte_ziele():
    markdown = (
        "# Offene Features\r\n"
        "\r\n"
        "* [Titel](features/titel%20mit%20leerzeichen.md) — **offen**\r\n"
    )
    ergebnis = js("features.parseFeatures(daten)", markdown)[0]
    assert ergebnis["pfad"] == "features/titel mit leerzeichen.md"
    assert ergebnis["slug"] == "titel mit leerzeichen"


@ohne_node
def test_t11_absolute_linkziele_werden_normalisiert():
    # `wissen/features.md` verlinkt relativ, absolute Ziele (`/aufgaben/…`)
    # dürfen aber nicht still herausfallen.
    markdown = (
        "# Offene Features\n"
        "\n"
        "* [Titel](/features/titel.md) — **offen** · Priorität **hoch**\n"
        "  * [A1](/aufgaben/a1-okf-bundle.md) Fundament\n"
    )
    ergebnis = js("features.parseFeatures(daten)", markdown)[0]
    assert ergebnis["pfad"] == "features/titel.md"
    assert ergebnis["slug"] == "titel"
    assert ergebnis["aufgaben"] == ["aufgaben/a1-okf-bundle.md"]


@ohne_node
def test_t11_bullet_ohne_link_und_ziel_ohne_md():
    markdown = (
        "# Offene Features\n"
        "\n"
        "* **fett** Text ohne Link\n"
        "* [Kein Markdown](features/kein-markdown.txt) — **offen**\n"
    )
    assert js("features.parseFeatures(daten)", markdown) == []


@ohne_node
def test_t11_abschnitte_ohne_eintraege_sind_leer():
    assert js("features.parseFeatures(daten)", LEERER_ABSCHNITT_MD) == []


@ohne_node
def test_t11_zeile_mit_link_nicht_am_anfang_ist_formatfehler():
    # Ein Top-Level-Bullet mit `.md`-Link, dessen Link nicht am Zeilenanfang
    # steht, ist eine kaputte Feature-Zeile — kein stilles Verwerfen.
    markdown = (
        "# Offene Features\n"
        "\n"
        "* [Gut](features/gut.md) — **offen**\n"
        "* Siehe [Kaputt](features/kaputt.md) — **offen**\n"
    )
    ergebnis = js_ablauf(
        "try {\n"
        "  features.parseFeatures(daten);\n"
        "  return { wirft: false };\n"
        "} catch (fehler) {\n"
        "  return { wirft: true, text: String(fehler.message) };\n"
        "}",
        markdown,
    )
    assert ergebnis["wirft"] is True
    assert "Format" in ergebnis["text"]
    assert "Zeile" in ergebnis["text"]


@ohne_node
def test_t11_fehlender_feature_abschnitt_ist_formatfehler():
    markdown = "# Statuswerte\n\n`offen` · `umgesetzt`\n\n# Regeln\n\n* Text.\n"
    skript = (
        f"import * as features from {json.dumps(FEATURES_JS.as_uri())};\n"
        f"const daten = {json.dumps(markdown)};\n"
        "try {\n"
        "  features.parseFeatures(daten);\n"
        "  console.log(JSON.stringify({ wirft: false }));\n"
        "} catch (fehler) {\n"
        "  console.log(JSON.stringify({ wirft: true, text: String(fehler.message) }));\n"
        "}\n"
    )
    ergebnis = node_ausfuehren(skript)
    assert ergebnis["wirft"] is True
    assert ergebnis["text"]


# --- Gruppierung und Join (T12–T15) ---------------------------------------

API_AUFGABEN = [
    {
        "path": "aufgaben/a1-okf-bundle.md",
        "titel": "A1 OKF-Bundle",
        "status": "Geschlossen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T10:00:00+00:00",
    },
    {
        "path": "aufgaben/a2-status-mapping.md",
        "titel": "A2 Status-Mapping",
        "status": "In Arbeit",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T11:00:00+00:00",
    },
    {
        "path": "aufgaben/a3-nachtrag.md",
        "titel": "A3 Nachtrag",
        "status": "Klarung",
        "owner": "mensch",
        "zuletzt_geaendert": "2026-11-14T12:00:00+00:00",
    },
    {
        "path": "aufgaben/a4-neu-aufgabe.md",
        "titel": "A4 Neu-Aufgabe",
        "status": "Offen",
        "hinweis": "pausiert",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T13:00:00+00:00",
    },
    {
        "path": "aufgaben/a5-neu-welle.md",
        "titel": "A5 Neu-Welle",
        "status": "Testing",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T14:00:00+00:00",
    },
    {
        "path": "aufgaben/a6-meta.md",
        "titel": "A6 Meta",
        "status": "Dokumentation",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T15:00:00+00:00",
    },
]

GRUPPEN_SZENARIO = """
const gruppen = features.gruppeAufgaben(daten);
return {
  offen: gruppen.offen.map((aufgabe) => aufgabe.path),
  inBearbeitung: gruppen.inBearbeitung.map((aufgabe) => aufgabe.path),
  erledigt: gruppen.erledigt.map((aufgabe) => aufgabe.path),
  zaehler: features.zaehleGruppen(gruppen),
};
"""


@ohne_node
@pytest.mark.parametrize(
    "status,gruppe",
    [
        ("Klarung", "offen"),
        ("Offen", "offen"),
        ("In Arbeit", "inBearbeitung"),
        ("Testing", "inBearbeitung"),
        ("Dokumentation", "inBearbeitung"),
        ("Geschlossen", "erledigt"),
    ],
)
def test_t12_status_wird_der_anzeigegruppe_zugeordnet(status, gruppe):
    ergebnis = js_ablauf(GRUPPEN_SZENARIO, [{"path": "aufgaben/a1.md", "titel": "A1", "status": status}])
    assert ergebnis[gruppe] == ["aufgaben/a1.md"]
    assert ergebnis["zaehler"][gruppe] == 1
    assert sum(ergebnis["zaehler"].values()) == 1


@ohne_node
def test_t12_reihenfolge_und_vollstaendigkeit():
    ergebnis = js_ablauf(GRUPPEN_SZENARIO, API_AUFGABEN)
    assert ergebnis["offen"] == ["aufgaben/a3-nachtrag.md", "aufgaben/a4-neu-aufgabe.md"]
    assert ergebnis["inBearbeitung"] == [
        "aufgaben/a2-status-mapping.md",
        "aufgaben/a5-neu-welle.md",
        "aufgaben/a6-meta.md",
    ]
    assert ergebnis["erledigt"] == ["aufgaben/a1-okf-bundle.md"]
    assert sum(ergebnis["zaehler"].values()) == len(API_AUFGABEN)


@ohne_node
def test_t12_leere_eingabe_liefert_drei_leere_gruppen():
    for eingabe in ([], None):
        ergebnis = js_ablauf(GRUPPEN_SZENARIO, eingabe)
        assert ergebnis["offen"] == []
        assert ergebnis["inBearbeitung"] == []
        assert ergebnis["erledigt"] == []
        assert ergebnis["zaehler"] == {"offen": 0, "inBearbeitung": 0, "erledigt": 0}


@ohne_node
def test_t12_unbekannter_status_landet_sichtbar_in_offen():
    ergebnis = js_ablauf(GRUPPEN_SZENARIO, [{"path": "aufgaben/a1.md", "titel": "A1", "status": "Unbekannt"}])
    assert ergebnis["offen"] == ["aufgaben/a1.md"]
    hinweis = js("features.gruppeAufgaben(daten).offen[0].hinweis", [
        {"path": "aufgaben/a1.md", "titel": "A1", "status": "Unbekannt"}
    ])
    assert hinweis == "Unbekannt"


@ohne_node
def test_t12_bekannter_hinweis_bleibt_erhalten():
    hinweis = js("features.gruppeAufgaben(daten).offen[0].hinweis", [
        {"path": "aufgaben/a4.md", "titel": "A4", "status": "Offen", "hinweis": "pausiert"}
    ])
    assert hinweis == "pausiert"


FEATURE_MIT_AUFGABEN = {
    "titel": "OKF Projekt-Manager (SPA)",
    "pfad": "features/okf-projekt-manager-spa.md",
    "slug": "okf-projekt-manager-spa",
    "status": "umgesetzt",
    "hinweis": None,
    "prioritaet": "hoch",
    "aufgaben": ["aufgaben/a1-okf-bundle.md", "aufgaben/a2-status-mapping.md"],
}

JOIN_SZENARIO = """
const ergebnis = features.verbindeAufgaben(daten.feature, daten.aufgaben);
return {
  aufgaben: ergebnis.aufgaben,
  warnungen: ergebnis.warnungen,
};
"""


@ohne_node
def test_t13_join_nimmt_titel_und_ui_status_aus_der_api():
    ergebnis = js_ablauf(
        JOIN_SZENARIO,
        {"feature": FEATURE_MIT_AUFGABEN, "aufgaben": API_AUFGABEN},
    )
    assert ergebnis["warnungen"] == []
    assert ergebnis["aufgaben"] == [
        {
            "path": "aufgaben/a1-okf-bundle.md",
            "titel": "A1 OKF-Bundle",
            "status": "Geschlossen",
            "hinweis": None,
        },
        {
            "path": "aufgaben/a2-status-mapping.md",
            "titel": "A2 Status-Mapping",
            "status": "In Arbeit",
            "hinweis": None,
        },
    ]


@ohne_node
def test_t13_join_uebernimmt_hinweis_der_api():
    feature = dict(FEATURE_MIT_AUFGABEN, aufgaben=["aufgaben/a4-neu-aufgabe.md"])
    ergebnis = js_ablauf(JOIN_SZENARIO, {"feature": feature, "aufgaben": API_AUFGABEN})
    assert ergebnis["aufgaben"] == [
        {
            "path": "aufgaben/a4-neu-aufgabe.md",
            "titel": "A4 Neu-Aufgabe",
            "status": "Offen",
            "hinweis": "pausiert",
        }
    ]


@ohne_node
def test_t14_fehlender_api_eintrag_wird_gewarnt_statt_verworfen():
    feature = dict(
        FEATURE_MIT_AUFGABEN,
        aufgaben=["aufgaben/a1-okf-bundle.md", "aufgaben/a99-xy.md"],
    )
    ergebnis = js_ablauf(JOIN_SZENARIO, {"feature": feature, "aufgaben": API_AUFGABEN})
    assert [aufgabe["path"] for aufgabe in ergebnis["aufgaben"]] == ["aufgaben/a1-okf-bundle.md"]
    assert ergebnis["warnungen"] == [{"pfad": "aufgaben/a99-xy.md", "grund": "nicht gefunden"}]


@ohne_node
def test_t15_aufgaben_ohne_feature_zuordnung():
    features = [
        dict(FEATURE_MIT_AUFGABEN, aufgaben=["aufgaben/a1-okf-bundle.md"]),
        {
            "titel": "Zweites",
            "pfad": "features/zweites.md",
            "slug": "zweites",
            "status": "offen",
            "hinweis": None,
            "prioritaet": None,
            "aufgaben": ["aufgaben/a2-status-mapping.md"],
        },
    ]
    ergebnis = js(
        "features.ohneZuordnung(daten.features, daten.aufgaben).map((aufgabe) => aufgabe.path)",
        {"features": features, "aufgaben": API_AUFGABEN},
    )
    assert ergebnis == [
        "aufgaben/a3-nachtrag.md",
        "aufgaben/a4-neu-aufgabe.md",
        "aufgaben/a5-neu-welle.md",
        "aufgaben/a6-meta.md",
    ]


@ohne_node
def test_t15_ohne_luecken_ist_die_liste_leer():
    features = [dict(FEATURE_MIT_AUFGABEN, aufgaben=[aufgabe["path"] for aufgabe in API_AUFGABEN])]
    assert js(
        "features.ohneZuordnung(daten.features, daten.aufgaben)",
        {"features": features, "aufgaben": API_AUFGABEN},
    ) == []


# --- DOM-Harness (T16–T21) -------------------------------------------------

SEITEN_DOM = r"""
// Fehler-/Erfolgsbereich und der Feature-Container (wie index.html).
for (const id of ["fehler", "meldung", "liste-features"]) {
  const bereich = document.createElement("div");
  bereich.id = id;
  if (id === "fehler" || id === "meldung") bereich.hidden = true;
  bereich._imDokument = true;
}
"""

FETCH_STAB = r"""
// Fetch-Stab: protokolliert jeden Aufruf und liefert Antworten je Anfrage.
const aufrufe = [];
const antworten = __ANTWORTEN__;
globalThis.fetch = async (pfad, optionen = {}) => {
  const ziel = new URL(String(pfad), __BASIS__);
  const datei = ziel.searchParams.get("path") ?? ziel.pathname;
  aufrufe.push({ endpunkt: ziel.pathname, datei, methode: optionen.method ?? "GET" });
  const vorgabe = antworten[datei] ?? { status: 404, koerper: { error: "Nicht gefunden." } };
  return {
    ok: vorgabe.status < 400,
    status: vorgabe.status,
    headers: { get: () => "application/json" },
    text: async () => JSON.stringify(vorgabe.koerper ?? null),
  };
};
"""

FETCH_PROXY = r"""
// Proxy an den echten Server: macht Pfade absolut und protokolliert die Aufrufe.
const echtesFetch = globalThis.fetch;
const aufrufe = [];
globalThis.fetch = async (pfad, optionen = {}) => {
  const ziel = new URL(String(pfad), __BASIS__);
  const datei = ziel.searchParams.get("path") ?? ziel.pathname;
  aufrufe.push({ endpunkt: ziel.pathname, datei, methode: optionen.method ?? "GET" });
  return echtesFetch(ziel, optionen);
};
"""


def _harness(ablauf: str, fetch_skript: str) -> dict:
    skript = (
        MINI_DOM
        + SEITEN_DOM
        + fetch_skript
        + f"\nimport * as features from {json.dumps(FEATURES_JS.as_uri())};\n"
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


def dom(ablauf: str, antworten: dict | None = None) -> dict:
    """Führt einen Ablauf im DOM-Stab aus; Antworten kommen aus dem Fetch-Stab."""
    fetch_skript = (
        FETCH_STAB.replace("__ANTWORTEN__", json.dumps(antworten or {}, ensure_ascii=False))
        .replace("__BASIS__", json.dumps("http://lokal"))
    )
    return _harness(ablauf, fetch_skript)


def ui_lauf(basis: str, ablauf: str) -> dict:
    """Führt einen Ablauf im DOM-Harness gegen den echten Server unter ``basis`` aus."""
    return _harness(ablauf, FETCH_PROXY.replace("__BASIS__", json.dumps(basis)))


def antwort_features(markdown: str, status: int = 200) -> dict:
    return {"status": status, "koerper": {"frontmatter": {}, "markdown": markdown}}


def antwort_aufgaben(aufgaben: list) -> dict:
    return {"status": 200, "koerper": aufgaben}


def standard_antworten() -> dict:
    return {
        FEATURES_PFAD: antwort_features(FEATURES_MD),
        AUFGABEN_ENDPUNKT: antwort_aufgaben(API_AUFGABEN),
    }


SZENARIO_LISTE = r"""
await features.ladeFeaturesAnsicht({ unterpunkt: "" });
const alle = bei("liste-features").alleKnoten();
return {
  links: links("liste-features"),
  marken: knotenMitKlasse("liste-features", "status").map((knoten) => knoten.textContent),
  punkte: alle.filter((knoten) => knoten.marke === "li").map((knoten) => knoten.textContent),
  ueberschriften: alle.filter((knoten) => knoten.marke === "h3").map((knoten) => knoten.textContent),
  text: bei("liste-features").textContent,
  fehler: { sichtbar: sichtbar("fehler"), text: bei("fehler").textContent },
  abgerufen: aufrufe.map((a) => a.endpunkt + " " + a.datei),
};
"""

SZENARIO_DETAIL = r"""
await features.ladeFeaturesAnsicht({ unterpunkt: "okf-projekt-manager-spa" });
const alle = bei("liste-features").alleKnoten();
return {
  text: bei("liste-features").textContent,
  ueberschriften: alle
    .filter((knoten) => /^h[1-6]$/.test(knoten.marke))
    .map((knoten) => ({ tag: knoten.marke, text: knoten.textContent })),
  marken: knotenMitKlasse("liste-features", "status").map((knoten) => knoten.textContent),
  gruppen: knotenMitKlasse("liste-features", "feature-gruppe").map((knoten) => ({
    name: knoten.dataset.gruppe,
    text: knoten.textContent,
    links: links(knoten.id),
  })),
  links: links("liste-features"),
  fehler: { sichtbar: sichtbar("fehler"), text: bei("fehler").textContent },
  abgerufen: aufrufe.map((a) => a.endpunkt + " " + a.datei),
};
"""


def szenario_fehler(aufruf: str) -> str:
    return (
        aufruf
        + "\nconst alle = bei(\"liste-features\").alleKnoten();\n"
        + "return {\n"
        + "  text: bei(\"liste-features\").textContent,\n"
        + "  kinder: bei(\"liste-features\").kinder.length,\n"
        + "  links: links(\"liste-features\").length,\n"
        + "  fehler: { sichtbar: sichtbar(\"fehler\"), text: bei(\"fehler\").textContent },\n"
        + "  abgerufen: aufrufe.map((a) => a.endpunkt + \" \" + a.datei),\n"
        + "};"
    )


@ohne_node
def test_t16_liste_zeigt_features_mit_status_prioritaet_und_zaehlern():
    ergebnis = dom(SZENARIO_LISTE, standard_antworten())
    assert ergebnis["links"] == [
        {"text": "OKF Projekt-Manager (SPA)", "href": "#/features/okf-projekt-manager-spa"}
    ]
    assert ergebnis["marken"] == [
        "umgesetzt — MVP abnahmefähig (Abnahme durch Projektleitung ausstehend)"
    ]
    punkt = ergebnis["punkte"][0]
    assert "Priorität hoch" in punkt
    assert "0 offen · 1 in Bearbeitung · 1 erledigt" in punkt
    assert ergebnis["fehler"]["sichtbar"] is False


@ohne_node
def test_t16_liste_ruft_genau_die_zwei_endpunkte_ab():
    ergebnis = dom(SZENARIO_LISTE, standard_antworten())
    assert ergebnis["abgerufen"] == [
        f"/api/file {FEATURES_PFAD}",
        "/api/aufgaben /api/aufgaben",
    ]


@ohne_node
def test_t16_liste_zeigt_sammelhinweis_fuer_nicht_zugeordnete_aufgaben():
    ergebnis = dom(SZENARIO_LISTE, standard_antworten())
    assert "4 Aufgaben ohne Feature-Zuordnung" in ergebnis["text"]


@ohne_node
@pytest.mark.parametrize(
    "anzahl,erwartet",
    [(1, "1 Aufgabe ohne Feature-Zuordnung"), (2, "2 Aufgaben ohne Feature-Zuordnung")],
)
def test_t16_sammelhinweis_ist_im_singular_und_plural(anzahl, erwartet):
    zugeordnet = {"aufgaben/a1-okf-bundle.md", "aufgaben/a2-status-mapping.md"}
    rest = [aufgabe for aufgabe in API_AUFGABEN if aufgabe["path"] not in zugeordnet]
    antworten = standard_antworten()
    antworten[AUFGABEN_ENDPUNKT] = antwort_aufgaben(
        [aufgabe for aufgabe in API_AUFGABEN if aufgabe["path"] in zugeordnet] + rest[:anzahl]
    )
    ergebnis = dom(SZENARIO_LISTE, antworten)
    assert erwartet in ergebnis["text"]
    if anzahl == 1:
        assert "1 Aufgaben" not in ergebnis["text"]


@ohne_node
def test_t15_ohne_luecken_kein_sammelhinweis():
    antworten = standard_antworten()
    antworten[AUFGABEN_ENDPUNKT] = antwort_aufgaben(
        [aufgabe for aufgabe in API_AUFGABEN if aufgabe["path"].startswith("aufgaben/a1-") or aufgabe["path"].startswith("aufgaben/a2-")]
    )
    ergebnis = dom(SZENARIO_LISTE, antworten)
    assert "ohne Feature-Zuordnung" not in ergebnis["text"]


@ohne_node
def test_t17_detail_zeigt_status_gruppen_und_aufgabenlinks():
    ergebnis = dom(SZENARIO_DETAIL, standard_antworten())
    assert ergebnis["ueberschriften"][0] == {"tag": "h3", "text": "OKF Projekt-Manager (SPA)"}
    assert [eintrag["text"] for eintrag in ergebnis["ueberschriften"][1:]] == [
        "Offen (0)",
        "In Bearbeitung (1)",
        "Erledigt (1)",
    ]
    assert ergebnis["marken"][0] == (
        "umgesetzt — MVP abnahmefähig (Abnahme durch Projektleitung ausstehend)"
    )
    assert {eintrag["name"] for eintrag in ergebnis["gruppen"]} == {
        "offen",
        "inBearbeitung",
        "erledigt",
    }
    ziele = [unquote(link["href"][len(DETAIL_VORSCHLAG):]) for link in ergebnis["links"]]
    assert "aufgaben/a1-okf-bundle.md" in ziele
    assert "aufgaben/a2-status-mapping.md" in ziele
    assert "#/features" == ergebnis["links"][-1]["href"]
    assert ergebnis["fehler"]["sichtbar"] is False


@ohne_node
def test_t17_detail_gruppiert_nach_offen_bearbeitung_erledigt():
    ergebnis = dom(SZENARIO_DETAIL, standard_antworten())
    gruppen = {eintrag["name"]: eintrag["text"] for eintrag in ergebnis["gruppen"]}
    assert "A2 Status-Mapping" in gruppen["inBearbeitung"]
    assert "A1 OKF-Bundle" in gruppen["erledigt"]
    assert "A1 OKF-Bundle" not in gruppen["inBearbeitung"]
    assert "Keine Aufgaben." in gruppen["offen"]
    assert "Offen (0)" in gruppen["offen"]


@ohne_node
def test_t17_detailmarke_zeigt_aufgabenstatus():
    ergebnis = dom(SZENARIO_DETAIL, standard_antworten())
    assert "Geschlossen" in ergebnis["marken"]
    assert "In Arbeit" in ergebnis["marken"]


@ohne_node
def test_t17_detail_linkziel_ist_dekodiert_der_api_pfad():
    ergebnis = dom(SZENARIO_DETAIL, standard_antworten())
    for link in ergebnis["links"][:-1]:
        assert link["href"].startswith(DETAIL_VORSCHLAG)
        assert unquote(link["href"][len(DETAIL_VORSCHLAG):]).startswith("aufgaben/")


XSS_TITEL = "<img src=x onerror=alert(1)>"
XSS_FEATURES_MD = (
    "# Offene Features\n"
    "\n"
    f"* [{XSS_TITEL}](features/xss.md) — **offen** · Priorität **hoch**\n"
    "  * [A1](aufgaben/a1-okf-bundle.md) Fundament\n"
)
XSS_AUFGABEN = [
    {
        "path": "aufgaben/a1-okf-bundle.md",
        "titel": XSS_TITEL,
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T10:00:00+00:00",
    }
]

SZENARIO_XSS_LISTE = r"""
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await features.ladeFeaturesAnsicht({ unterpunkt: "" });
const alle = bei("liste-features").alleKnoten();
return {
  texte: links("liste-features").map((eintrag) => eintrag.text),
  marken: alle.map((knoten) => knoten.marke),
  ausfuehrungen,
};
"""

SZENARIO_XSS_DETAIL = r"""
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await features.ladeFeaturesAnsicht({ unterpunkt: "xss" });
const alle = bei("liste-features").alleKnoten();
return {
  texte: links("liste-features").map((eintrag) => eintrag.text),
  marken: alle.map((knoten) => knoten.marke),
  text: bei("liste-features").textContent,
  ausfuehrungen,
};
"""


@ohne_node
def test_t18_html_im_featuretitel_bleibt_text():
    ergebnis = dom(
        SZENARIO_XSS_LISTE,
        {FEATURES_PFAD: antwort_features(XSS_FEATURES_MD), AUFGABEN_ENDPUNKT: antwort_aufgaben(XSS_AUFGABEN)},
    )
    assert ergebnis["texte"] == [XSS_TITEL]
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []


@ohne_node
def test_t18_html_im_aufgabentitel_bleibt_text():
    ergebnis = dom(
        SZENARIO_XSS_DETAIL,
        {FEATURES_PFAD: antwort_features(XSS_FEATURES_MD), AUFGABEN_ENDPUNKT: antwort_aufgaben(XSS_AUFGABEN)},
    )
    assert XSS_TITEL in ergebnis["text"]
    aufgabenlink = [text for text in ergebnis["texte"] if text.startswith("<img")][0]
    assert aufgabenlink == XSS_TITEL
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []


@ohne_node
def test_t19a_fehlende_datei_ist_fail_loud():
    ergebnis = dom(
        szenario_fehler('await features.ladeFeaturesAnsicht({ unterpunkt: "" });'),
        {AUFGABEN_ENDPUNKT: antwort_aufgaben(API_AUFGABEN)},
    )
    assert ergebnis["text"]
    assert ergebnis["kinder"] > 0
    assert ergebnis["links"] == 0
    assert ergebnis["fehler"]["sichtbar"] is True
    assert ergebnis["fehler"]["text"]


@ohne_node
def test_t19b_unlesbare_datei_zeigt_servermeldung():
    ergebnis = dom(
        szenario_fehler('await features.ladeFeaturesAnsicht({ unterpunkt: "" });'),
        {
            FEATURES_PFAD: {"status": 500, "koerper": {"error": "Datei ist nicht lesbar."}},
            AUFGABEN_ENDPUNKT: antwort_aufgaben(API_AUFGABEN),
        },
    )
    assert ergebnis["text"]
    assert ergebnis["links"] == 0
    assert ergebnis["fehler"]["sichtbar"] is True
    assert "nicht lesbar" in ergebnis["fehler"]["text"]


@ohne_node
def test_t19c_unerwartetes_dateiformat_ist_fail_loud():
    ergebnis = dom(
        szenario_fehler('await features.ladeFeaturesAnsicht({ unterpunkt: "" });'),
        {
            FEATURES_PFAD: {"status": 200, "koerper": {"markdown": 42}},
            AUFGABEN_ENDPUNKT: antwort_aufgaben(API_AUFGABEN),
        },
    )
    assert "Format" in ergebnis["text"]
    assert ergebnis["fehler"]["sichtbar"] is True
    assert "Format" in ergebnis["fehler"]["text"]


@ohne_node
def test_t19d_dokument_ohne_feature_abschnitt_ist_formatfehler():
    ergebnis = dom(
        szenario_fehler('await features.ladeFeaturesAnsicht({ unterpunkt: "" });'),
        {
            FEATURES_PFAD: antwort_features("# Regeln\n\n* Nur Regeln.\n"),
            AUFGABEN_ENDPUNKT: antwort_aufgaben(API_AUFGABEN),
        },
    )
    assert "Format" in ergebnis["text"]
    assert "Keine Features." not in ergebnis["text"]
    assert ergebnis["fehler"]["sichtbar"] is True


@ohne_node
def test_t19d_zeile_mit_link_nicht_am_anfang_zeigt_formatfehler():
    markdown = (
        "# Offene Features\n"
        "\n"
        "* [Gut](features/gut.md) — **offen**\n"
        "* Siehe [Kaputt](features/kaputt.md) — **offen**\n"
    )
    ergebnis = dom(
        szenario_fehler('await features.ladeFeaturesAnsicht({ unterpunkt: "" });'),
        {
            FEATURES_PFAD: antwort_features(markdown),
            AUFGABEN_ENDPUNKT: antwort_aufgaben(API_AUFGABEN),
        },
    )
    assert "Format" in ergebnis["text"]
    assert "Zeile" in ergebnis["text"]
    assert "Keine Features." not in ergebnis["text"]
    assert ergebnis["links"] == 0
    assert ergebnis["fehler"]["sichtbar"] is True


@ohne_node
def test_t19e_aufgabenfehler_zeigt_keine_teilliste():
    ergebnis = dom(
        szenario_fehler('await features.ladeFeaturesAnsicht({ unterpunkt: "" });'),
        {
            FEATURES_PFAD: antwort_features(FEATURES_MD),
            AUFGABEN_ENDPUNKT: {"status": 500, "koerper": {"error": "Interner Serverfehler."}},
        },
    )
    assert ergebnis["text"]
    assert ergebnis["links"] == 0
    assert ergebnis["fehler"]["sichtbar"] is True


@ohne_node
def test_t19f_aufgaben_objekt_statt_array_ist_formatfehler():
    ergebnis = dom(
        szenario_fehler('await features.ladeFeaturesAnsicht({ unterpunkt: "" });'),
        {
            FEATURES_PFAD: antwort_features(FEATURES_MD),
            AUFGABEN_ENDPUNKT: {"status": 200, "koerper": {"aufgaben": []}},
        },
    )
    assert "Format" in ergebnis["text"]
    assert ergebnis["links"] == 0
    assert ergebnis["fehler"]["sichtbar"] is True


OHNE_AUFGABEN_MD = (
    "# Offene Features\n"
    "\n"
    "* [Leeres Feature](features/leer.md) — **offen** · Priorität **mittel**\n"
)


@ohne_node
def test_t20_feature_ohne_aufgaben_zeigt_hinweis_statt_gruppen():
    ergebnis = dom(
        SZENARIO_DETAIL.replace("okf-projekt-manager-spa", "leer"),
        {FEATURES_PFAD: antwort_features(OHNE_AUFGABEN_MD), AUFGABEN_ENDPUNKT: antwort_aufgaben([])},
    )
    assert "Keine Aufgaben zugeordnet." in ergebnis["text"]
    assert ergebnis["gruppen"] == []
    assert not any("(" in eintrag["text"] for eintrag in ergebnis["ueberschriften"][1:])


@ohne_node
def test_t20_liste_zeigt_nullzaehler():
    ergebnis = dom(
        SZENARIO_LISTE,
        {FEATURES_PFAD: antwort_features(OHNE_AUFGABEN_MD), AUFGABEN_ENDPUNKT: antwort_aufgaben([])},
    )
    assert "0 offen · 0 in Bearbeitung · 0 erledigt" in ergebnis["punkte"][0]
    assert "ohne Feature-Zuordnung" not in ergebnis["text"]


@ohne_node
def test_t21_unbekannter_slug_ist_fail_loud():
    ergebnis = dom(
        szenario_fehler('await features.ladeFeaturesAnsicht({ unterpunkt: "gibtsnicht" });'),
        standard_antworten(),
    )
    assert "Unbekanntes Feature: gibtsnicht" in ergebnis["text"]
    assert ergebnis["fehler"]["sichtbar"] is True
    assert "Unbekanntes Feature: gibtsnicht" in ergebnis["fehler"]["text"]
    assert ergebnis["links"] == 0
    # Ohne bekanntes Feature werden die Aufgaben gar nicht erst geladen.
    assert ergebnis["abgerufen"] == [f"/api/file {FEATURES_PFAD}"]


@ohne_node
def test_t21_fehlender_container_ist_fail_loud():
    ablauf = (
        'REGISTRIERT.delete("liste-features");\n'
        "await features.ladeFeaturesAnsicht({ unterpunkt: \"\" });\n"
        "return {\n"
        "  fehler: { sichtbar: sichtbar(\"fehler\"), text: bei(\"fehler\").textContent },\n"
        "  abgerufen: aufrufe.map((a) => a.endpunkt),\n"
        "};"
    )
    ergebnis = dom(ablauf, standard_antworten())
    assert ergebnis["fehler"]["sichtbar"] is True
    assert "liste-features" in ergebnis["fehler"]["text"]
    assert ergebnis["abgerufen"] == []


@ohne_node
def test_t21_ohne_container_und_ohne_fehlerbereich_ist_robust():
    ablauf = (
        'for (const id of ["fehler", "liste-features"]) REGISTRIERT.delete(id);\n'
        "await features.ladeFeaturesAnsicht({ unterpunkt: \"\" });\n"
        "return { ok: true };"
    )
    assert dom(ablauf, standard_antworten()) == {"ok": True}


# --- Router-Läufe (T2/T3) --------------------------------------------------

APP_UMGEBUNG = (
    MINI_DOM
    + SEITEN_DOM
    + r"""
const basisListe = ["uebersicht", "wellen", "aufgaben", "features", "entscheidungen", "projekt", "detail"];
const sicht = {};
for (const basis of basisListe) {
  const sektion = document.createElement("section");
  sektion.id = `ansicht-${basis}`;
  sektion.dataset.ansicht = basis;
  sektion.classList.add("ansicht-bereich");
  sektion.hidden = true;
  sicht[basis] = sektion;
}

const navigation = {};
const navigationBereich = document.createElement("nav");
for (const basis of ["uebersicht", "wellen", "aufgaben", "features", "entscheidungen", "projekt"]) {
  const link = document.createElement("a");
  link.classList.add("navigation-link");
  link.dataset.ansicht = basis;
  link.textContent = basis === "features" ? "Feature List" : basis;
  navigationBereich.append(link);
  navigation[basis] = link;
}
// Zwei Projekt-Unterpunkte wie in index.html (`data-unterpunkt`), damit die
// Aktivmarkierung Unterpunkt-Routen gegen die Hauptpunkte abgrenzt.
for (const unterpunkt of ["konzept", "phasen"]) {
  const link = document.createElement("a");
  link.classList.add("navigation-link");
  link.dataset.ansicht = "projekt";
  link.dataset.unterpunkt = unterpunkt;
  link.textContent = unterpunkt;
  navigationBereich.append(link);
  navigation[`projekt/${unterpunkt}`] = link;
}
sicht.features.append(bei("liste-features"));

const detailBereich = document.createElement("div");
detailBereich.id = "detail";
sicht.detail.append(detailBereich);

document.readyState = "loading";
const dokumentHoerer = {};
document.addEventListener = (art, hoerer) => {
  if (!dokumentHoerer[art]) dokumentHoerer[art] = [];
  dokumentHoerer[art].push(hoerer);
};

const fensterHoerer = {};
globalThis.window = {
  location: { hash: "" },
  addEventListener: (art, hoerer) => {
    if (!fensterHoerer[art]) fensterHoerer[art] = [];
    fensterHoerer[art].push(hoerer);
  },
};

const warte = () => new Promise((fertig) => setTimeout(fertig, 5));
const warteAuf = async (bedingung) => {
  for (let versuch = 0; versuch < 100; versuch += 1) {
    if (bedingung()) return true;
    await warte();
  }
  return false;
};
"""
)

def app_lauf(ablauf: str, antworten: dict | None = None) -> dict:
    """Führt einen Ablauf über den echten Router (``app.js``) im DOM-Stab aus."""
    fetch_skript = (
        FETCH_STAB.replace("__ANTWORTEN__", json.dumps(antworten or {}, ensure_ascii=False))
        .replace("__BASIS__", json.dumps("http://lokal"))
    )
    skript = (
        APP_UMGEBUNG
        + fetch_skript
        + "\nconst ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


SZENARIO_ROUTER = r"""
window.location.hash = __HASH__;
await import(__APP__);
for (const hoerer of dokumentHoerer.DOMContentLoaded || []) await hoerer();
await warteAuf(() => aufrufe.length >= 2 && bei("liste-features").kinder.length > 0);

return {
  sichtbar: basisListe.filter((basis) => sicht[basis].hidden === false),
  fehler: { sichtbar: sichtbar("fehler"), text: bei("fehler").textContent },
  aktiv: Object.entries(navigation)
    .filter(([, link]) => link.classList.contains("aktiv"))
    .map(([basis]) => basis),
  aria: Object.entries(navigation)
    .filter(([, link]) => link.getAttribute("aria-current") === "page")
    .map(([basis]) => basis),
  text: bei("liste-features").textContent,
  abgerufen: aufrufe.map((a) => a.endpunkt + " " + a.datei),
};
"""


def router_lauf(hash_wert: str, antworten: dict | None = None) -> dict:
    ablauf = SZENARIO_ROUTER.replace("__HASH__", json.dumps(hash_wert)).replace(
        "__APP__", json.dumps(APP_JS.as_uri())
    )
    return app_lauf(ablauf, antworten or standard_antworten())


@ohne_node
def test_t2_router_zeigt_nur_die_features_ansicht():
    ergebnis = router_lauf("#/features")
    assert ergebnis["sichtbar"] == ["features"]
    assert ergebnis["fehler"]["sichtbar"] is False
    assert "OKF Projekt-Manager (SPA)" in ergebnis["text"]


@ohne_node
def test_t3_feature_list_ist_bei_detailroute_aktiv():
    ergebnis = router_lauf("#/features/okf-projekt-manager-spa")
    assert ergebnis["sichtbar"] == ["features"]
    # Genau ein aktiver Link, auch mit den Projekt-Unterpunkten im Menü.
    assert ergebnis["aktiv"] == ["features"]
    assert ergebnis["aria"] == ["features"]
    assert "Erledigt (1)" in ergebnis["text"]


SZENARIO_ROUTER_KURZ = r"""
window.location.hash = __HASH__;
await import(__APP__);
for (const hoerer of dokumentHoerer.DOMContentLoaded || []) await hoerer();
await warte();
const aktive = (pruefung) => Object.entries(navigation)
  .filter(([, link]) => pruefung(link))
  .map(([basis]) => basis);
return {
  aktiv: aktive((link) => link.classList.contains("aktiv")),
  aria: aktive((link) => link.getAttribute("aria-current") === "page"),
};
"""


@ohne_node
def test_t3_projektroute_markiert_genau_den_unterpunkt():
    ablauf = SZENARIO_ROUTER_KURZ.replace("__HASH__", json.dumps("#/projekt/konzept")).replace(
        "__APP__", json.dumps(APP_JS.as_uri())
    )
    ergebnis = app_lauf(ablauf, standard_antworten())
    assert ergebnis["aktiv"] == ["projekt/konzept"]
    assert ergebnis["aria"] == ["projekt/konzept"]


SZENARIO_ROUTER_WECHSEL = r"""
// Zwei-Routen-Lauf: der aktive Menüpunkt wandert per `hashchange` weiter.
// `markiereNavigation` muss den alten Link per `removeAttribute` freiräumen.
const projektZiel = document.createElement("div");
projektZiel.id = "liste-projekt";
sicht.projekt.append(projektZiel);

window.location.hash = "#/features";
await import(__APP__);
for (const hoerer of dokumentHoerer.DOMContentLoaded || []) await hoerer();
await warteAuf(() => bei("liste-features").kinder.length > 0);

const aktive = (pruefung) => Object.entries(navigation)
  .filter(([, link]) => pruefung(link))
  .map(([basis]) => basis);
const stand = () => ({
  aktiv: aktive((link) => link.classList.contains("aktiv")),
  aria: aktive((link) => link.getAttribute("aria-current") === "page"),
});

const vorher = stand();
window.location.hash = "#/projekt/konzept";
for (const hoerer of fensterHoerer.hashchange || []) await hoerer();
await warte();
const nachher = stand();
return { vorher, nachher };
"""


@ohne_node
def test_t3_routenwechsel_raeumt_aria_current_beim_altlink_ab():
    """A37/M10: `removeAttribute` im Harness wirkt — sonst bliebe der alte Link
    zusätzlich als `aria-current="page"` markiert (zwei aktive Menüpunkte)."""
    antworten = standard_antworten()
    antworten["projekt/konzept.md"] = {
        "status": 200,
        "koerper": {"frontmatter": {}, "markdown": "# Konzept\n\nFixture.\n"},
    }
    ablauf = SZENARIO_ROUTER_WECHSEL.replace("__APP__", json.dumps(APP_JS.as_uri()))
    ergebnis = app_lauf(ablauf, antworten)
    assert ergebnis["vorher"] == {"aktiv": ["features"], "aria": ["features"]}
    assert ergebnis["nachher"] == {
        "aktiv": ["projekt/konzept"],
        "aria": ["projekt/konzept"],
    }


# --- HTTP-Läufe gegen ein Test-Bundle unter tmp_path (T22) ----------------

BUNDLE_FEATURES = (
    "# Statuswerte\n"
    "\n"
    "`offen` · `in Umsetzung` · `umgesetzt` · `pausiert`\n"
    "\n"
    "# Regeln\n"
    "\n"
    "* Regel mit [A22](aufgaben/a3-nachtrag.md)-Link.\n"
    "\n"
    "# Offene Features\n"
    "\n"
    "* [Feature Eins](features/eins.md) — Erstes Feature · **offen** · Priorität **hoch**\n"
    "  * [A1](aufgaben/a1-okf-bundle.md) Fundament\n"
    "  * [A2](aufgaben/a2-status-mapping.md) Mapping\n"
    "\n"
    "* [Feature Zwei](features/zwei.md) — Zweites Feature · **umgesetzt — fertig** · Priorität **niedrig**\n"
    "\n"
    "# Umgesetzte Features\n"
    "\n"
    "*Noch keine.*\n"
)

BUNDLE_AUFGABEN = {
    "aufgaben/a1-okf-bundle.md": (
        "---\ntype: Task\ntitle: A1 OKF-Bundle\ntask_status: abgeschlossen\n---\n\n# A1\n"
    ),
    "aufgaben/a2-status-mapping.md": (
        "---\ntype: Task\ntitle: A2 Status-Mapping\ntask_status: in Umsetzung\n---\n\n# A2\n"
    ),
    "aufgaben/a3-nachtrag.md": (
        "---\ntype: Task\ntitle: A3 Nachtrag\ntask_status: offen\n---\n\n# A3\n"
    ),
}


@pytest.fixture()
def szenario_bundle(tmp_path):
    wurzel = tmp_path / "bundle"
    (wurzel / "features").mkdir(parents=True)
    (wurzel / "aufgaben").mkdir(parents=True)
    (wurzel / FEATURES_PFAD).write_text(BUNDLE_FEATURES, encoding="utf-8")
    for pfad, inhalt in BUNDLE_AUFGABEN.items():
        (wurzel / pfad).write_text(inhalt, encoding="utf-8")
    return wurzel


@pytest.fixture()
def luecken_bundle(tmp_path):
    """Bundle ohne `features.md` (S4)."""
    wurzel = tmp_path / "luecke"
    (wurzel / "aufgaben").mkdir(parents=True)
    for pfad, inhalt in BUNDLE_AUFGABEN.items():
        (wurzel / pfad).write_text(inhalt, encoding="utf-8")
    return wurzel


@pytest.fixture()
def format_bundle(tmp_path):
    """Bundle mit `features.md`, aber ohne Feature-Abschnitt."""
    wurzel = tmp_path / "format"
    (wurzel / "aufgaben").mkdir(parents=True)
    (wurzel / FEATURES_PFAD).write_text("# Regeln\n\n* Nur Regeln.\n", encoding="utf-8")
    for pfad, inhalt in BUNDLE_AUFGABEN.items():
        (wurzel / pfad).write_text(inhalt, encoding="utf-8")
    return wurzel


def _server(wurzel: Path):
    httpd = make_server("127.0.0.1", 0, server.create_app(wurzel), threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def app_server(szenario_bundle):
    yield from _server(szenario_bundle)


@pytest.fixture()
def luecken_server(luecken_bundle):
    yield from _server(luecken_bundle)


@pytest.fixture()
def format_server(format_bundle):
    yield from _server(format_bundle)


@ohne_node
def test_http_t22_liste_aus_test_bundle(app_server):
    ergebnis = ui_lauf(app_server, SZENARIO_LISTE)
    assert [link["text"] for link in ergebnis["links"]] == ["Feature Eins", "Feature Zwei"]
    assert "offen" in ergebnis["marken"][0]
    assert "umgesetzt — fertig" in ergebnis["marken"][1]
    assert "0 offen · 1 in Bearbeitung · 1 erledigt" in ergebnis["punkte"][0]
    assert "0 offen · 0 in Bearbeitung · 0 erledigt" in ergebnis["punkte"][1]
    assert "1 Aufgabe ohne Feature-Zuordnung" in ergebnis["text"]
    assert "1 Aufgaben ohne Feature-Zuordnung" not in ergebnis["text"]
    assert ergebnis["abgerufen"] == [
        f"/api/file {FEATURES_PFAD}",
        "/api/aufgaben /api/aufgaben",
    ]


@ohne_node
def test_http_t22_detail_aus_test_bundle(app_server):
    ergebnis = ui_lauf(
        app_server, SZENARIO_DETAIL.replace("okf-projekt-manager-spa", "eins")
    )
    assert ergebnis["ueberschriften"][0]["text"] == "Feature Eins"
    assert [eintrag["text"] for eintrag in ergebnis["ueberschriften"][1:]] == [
        "Offen (0)",
        "In Bearbeitung (1)",
        "Erledigt (1)",
    ]
    assert "A1 OKF-Bundle" in ergebnis["text"]
    assert "A2 Status-Mapping" in ergebnis["text"]
    assert ergebnis["links"][-1] == {"text": "← Zurück zur Feature-Liste", "href": "#/features"}


@ohne_node
def test_http_t22_fehlendes_features_md(luecken_server):
    ergebnis = ui_lauf(
        luecken_server, szenario_fehler('await features.ladeFeaturesAnsicht({ unterpunkt: "" });')
    )
    assert ergebnis["text"]
    assert ergebnis["links"] == 0
    assert ergebnis["fehler"]["sichtbar"] is True


@ohne_node
def test_http_t22_formatfehler_bundle(format_server):
    ergebnis = ui_lauf(
        format_server, szenario_fehler('await features.ladeFeaturesAnsicht({ unterpunkt: "" });')
    )
    assert "Format" in ergebnis["text"]
    assert "Keine Features." not in ergebnis["text"]
    assert ergebnis["fehler"]["sichtbar"] is True


SZENARIO_AUFGABE_OEFFNEN = r"""
window.location.hash = "#/features/okf-projekt-manager-spa";
await import(__APP__);
for (const hoerer of dokumentHoerer.DOMContentLoaded || []) await hoerer();
await warteAuf(() => links("liste-features").some((link) => link.href.startsWith("#/detail/")));

const aufgabenlink = links("liste-features").find((link) => link.href.startsWith("#/detail/"));
window.location.hash = aufgabenlink.href;
for (const hoerer of fensterHoerer.hashchange || []) await hoerer();
await warteAuf(() => bei("detail").textContent.includes("A2 Status-Mapping"));

return {
  href: aufgabenlink.href,
  detailText: bei("detail").textContent,
  sichtbar: basisListe.filter((basis) => sicht[basis].hidden === false),
  fehler: { sichtbar: sichtbar("fehler"), text: bei("fehler").textContent },
};
"""


@ohne_node
def test_t17_klick_auf_aufgabe_oeffnet_die_detailansicht():
    ablauf = SZENARIO_AUFGABE_OEFFNEN.replace("__APP__", json.dumps(APP_JS.as_uri()))
    antworten = standard_antworten()
    # Die Detailansicht lädt bei Aufgaben zusätzlich die Wellen-Auswahl (A26/A27);
    # hier genügt eine leere, gültige Liste.
    antworten["/api/wellen"] = antwort_aufgaben([])
    antworten["aufgaben/a2-status-mapping.md"] = {
        "status": 200,
        "koerper": {
            "frontmatter": {
                "type": "Task",
                "title": "A2 Status-Mapping",
                "task_status": "in Umsetzung",
                "owner": "ai",
            },
            "markdown": "# A2 Status-Mapping\n\nMapping-Beschreibung.\n",
            # A35: Der UI-Status kommt aus der Server-Ableitung, nicht mehr aus
            # einem JS-Spiegel des task_status.
            "ui_status": "In Arbeit",
        },
    }
    ergebnis = app_lauf(ablauf, antworten)
    assert ergebnis["href"] == f"{DETAIL_VORSCHLAG}aufgaben%2Fa2-status-mapping.md"
    assert ergebnis["sichtbar"] == ["detail"]
    assert "A2 Status-Mapping" in ergebnis["detailText"]
    assert "In Arbeit" in ergebnis["detailText"]
    assert ergebnis["fehler"]["sichtbar"] is False


LUECKEN_FEATURE_MD = (
    "# Offene Features\n"
    "\n"
    "* [Mit Lücke](features/mit-luecke.md) — **offen** · Priorität **hoch**\n"
    "  * [A1](aufgaben/a1-okf-bundle.md) Fundament\n"
    "  * [A99](aufgaben/a99-xy.md) fehlt in der API\n"
)


@ohne_node
def test_t14_warnung_ist_in_der_ansicht_sichtbar():
    ergebnis = dom(
        SZENARIO_DETAIL.replace("okf-projekt-manager-spa", "mit-luecke"),
        {
            FEATURES_PFAD: antwort_features(LUECKEN_FEATURE_MD),
            AUFGABEN_ENDPUNKT: antwort_aufgaben(API_AUFGABEN),
        },
    )
    assert "In features.md verlinkt, aber nicht gefunden: aufgaben/a99-xy.md" in ergebnis["text"]
    assert "Erledigt (1)" in ergebnis["text"]
    assert "A99" not in "".join(link["text"] for link in ergebnis["links"])
    assert ergebnis["fehler"]["sichtbar"] is False
