"""Prüfungen für die Entscheidungen- und Projekt-Ansicht (A14).

Die UI-Szenarien T1–T5 spielt der ``tester`` mit dem Moli-Browser durch; hier
werden ``projekt.js`` und seine Verdrahtung ohne Browser geprüft. Der Parser
der Log-Einträge läuft über Node (keine neue Abhängigkeit); die Ansichten
laufen im Node-DOM-Harness — einmal mit Antworten aus dem Fetch-Stab und
einmal per HTTP gegen ein Test-Bundle unter ``tmp_path`` (nie gegen das echte
Projekt-Bundle). Genutzt wird ausschließlich ``GET /api/file``.
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
PROJEKT_JS = STATIC_DIR / "js" / "projekt.js"
APP_JS = STATIC_DIR / "js" / "app.js"
API_JS = STATIC_DIR / "js" / "api.js"
DETAIL_JS = STATIC_DIR / "js" / "detail.js"

ENTSCHEIDUNGEN_PFAD = "entscheidungen/log.md"
DETAIL_VORSCHLAG = "#/detail/"
PROJEKT_VORSCHLAG = "#/projekt/"

# Die fünf Projekt-Unterpunkte laut Navigation (index.html, A10).
PROJEKT_ERWARTET = [
    {"unterpunkt": "konzept", "titel": "Konzept", "pfad": "projekt/konzept.md"},
    {"unterpunkt": "technische-spec", "titel": "Technische Spec", "pfad": "projekt/technische-spec.md"},
    {"unterpunkt": "user-stories", "titel": "User Stories", "pfad": "projekt/user-stories/index.md"},
    {"unterpunkt": "phasen", "titel": "Phasen", "pfad": "projekt/phasen.md"},
    {"unterpunkt": "log", "titel": "Log", "pfad": "log.md"},
]

# Log-Fixture für die Stub-Läufe (Format `## YYYY-MM-DD: Titel`).
LOG_MD = (
    "# Entscheidungslog\n"
    "\n"
    "## 2026-11-14: Moli-Frage — Standardentscheidung Harness\n"
    "\n"
    "**Entscheidung:** Harness bleibt.\n"
    "\n"
    "## 2026-11-13: Navigation mit fünf Hauptpunkten\n"
    "\n"
    "**Entscheidung:** Fünf Punkte.\n"
)

# A38: Jeder Eintrag trägt seinen Anker (ID im gerenderten Markdown).
LOG_ERWARTET = [
    {
        "datum": "2026-11-14",
        "titel": "Moli-Frage — Standardentscheidung Harness",
        "anker": "2026-11-14-moli-frage-standardentscheidung-harness",
    },
    {
        "datum": "2026-11-13",
        "titel": "Navigation mit fünf Hauptpunkten",
        "anker": "2026-11-13-navigation-mit-fuenf-hauptpunkten",
    },
]

# A14-Befund 3: HTML im Titel muss Literal bleiben (kein Knoten, keine Ausführung).
HTML_TITEL = '<img src=x onerror=alert(1)>'
LOG_HTML = f"# Entscheidungslog\n\n## 2026-11-14: {HTML_TITEL}\n"

SPEC_MD = "# Technische Spec\n\nSpec-Absatz zur Prüfung.\n\n- Erster Punkt\n"

# Test-Bundle für die HTTP-Läufe (relativ zum Bundle-Root, wie in A14 vorgegeben).
BUNDLE_DATEIEN = {
    "projekt/konzept.md": "# Konzept\n\nKonzept-Absatz.\n",
    "projekt/technische-spec.md": "# Technische Spec\n\nSpec-Absatz.\n",
    "projekt/user-stories/index.md": "# User Stories\n\nStories-Absatz.\n",
    "projekt/phasen.md": "# Phasen\n\nPhasen-Absatz.\n",
    "log.md": "---\ntype: Log\ntitle: Projekt-Log (Test)\n---\n\n# Projekt-Log\n\nLog-Absatz.\n",
}

BUNDLE_LOG = (
    "# Entscheidungslog\n"
    "\n"
    "## 2026-11-14: Erste Entscheidung\n"
    "\n"
    "**Entscheidung:** Text eins.\n"
    "\n"
    "## 2026-11-13: Zweite Entscheidung\n"
    "\n"
    "**Entscheidung:** Text zwei.\n"
)


def js(ausdruck: str, daten=None):
    """Wertet einen Ausdruck im Kontext von ``projekt.js`` über Node aus."""
    skript = (
        f"import * as projekt from {json.dumps(PROJEKT_JS.as_uri())};\n"
        f"const daten = {json.dumps(daten, ensure_ascii=False)};\n"
        f"console.log(JSON.stringify({ausdruck}));"
    )
    return node_ausfuehren(skript)


# --- Statische Prüfungen ---------------------------------------------------


def test_projekt_js_vorhanden():
    assert PROJEKT_JS.is_file()


def test_app_js_importiert_projekt():
    assert re.search(r'from\s+"\./projekt\.js"', lies(APP_JS))


def test_app_js_verdrahtet_projekt():
    js_quelle = lies(APP_JS)
    assert 'registriereAnsicht("entscheidungen"' in js_quelle
    assert 'registriereAnsicht("projekt"' in js_quelle


def test_projekt_js_nutzt_nur_den_file_endpunkt():
    # A14: kein neuer Server-Endpunkt, ausschließlich GET /api/file.
    js_quelle = lies(PROJEKT_JS)
    assert set(re.findall(r"/api/[a-z_-]+", js_quelle)) == {"/api/file"}
    assert "postJson" not in js_quelle


def test_projekt_js_nutzt_api_helper():
    js_quelle = lies(PROJEKT_JS)
    assert re.search(r"import\s*\{[^}]*\bgetJson\b[^}]*\}\s*from\s*\"\./api\.js\"", js_quelle)


def test_projekt_js_nutzt_detail_renderer():
    # R6: der Minimal-Renderer aus detail.js wird wiederverwendet.
    js_quelle = lies(PROJEKT_JS)
    assert re.search(r"import\s*\{[^}]*\brendereMarkdown\b[^}]*\}\s*from\s*\"\./detail\.js\"", js_quelle)


def test_projekt_js_rendert_ohne_innerhtml():
    js_quelle = lies(PROJEKT_JS)
    assert "textContent" in js_quelle
    assert "innerHTML" not in js_quelle


@pytest.mark.parametrize(
    "senke",
    ["outerHTML", "insertAdjacentHTML", "document.write(", "eval("],
)
def test_projekt_js_vermeidet_weitere_html_senken(senke):
    assert senke not in lies(PROJEKT_JS)


def test_projekt_js_nutzt_classlist_statt_classname():
    js_quelle = lies(PROJEKT_JS)
    assert "classList" in js_quelle
    assert "className" not in js_quelle


@pytest.mark.parametrize("container_id", ["liste-entscheidungen", "liste-projekt"])
def test_projekt_js_verwendet_container_id(container_id):
    assert f'"{container_id}"' in lies(PROJEKT_JS)


@pytest.mark.parametrize("container_id", ["liste-entscheidungen", "liste-projekt"])
def test_index_html_hat_container(container_id):
    # A14-Befund 2: der Vertrag aus A10 muss im Markup stehen (nur lesen).
    assert re.search(rf'id="{container_id}"', lies(INDEX_HTML))


@pytest.mark.parametrize(
    "pfad",
    [
        "entscheidungen/log.md",
        "projekt/konzept.md",
        "projekt/technische-spec.md",
        "projekt/user-stories/index.md",
        "projekt/phasen.md",
    ],
)
def test_projekt_js_pfade_relativ_zum_bundle(pfad):
    assert pfad in lies(PROJEKT_JS)


# --- Reine Logik über Node -------------------------------------------------


@ohne_node
def test_parse_entscheidungen_datum_und_titel():
    assert js("projekt.parseEntscheidungen(daten)", LOG_MD) == LOG_ERWARTET


@ohne_node
@pytest.mark.parametrize("trennzeichen", ["", ": ", ":", " - ", "-", " – ", "–", " — ", "—"])
def test_parse_entscheidungen_trennzeichen_tolerant(trennzeichen):
    markdown = f"## 2026-11-14{trennzeichen}Titel der Entscheidung"
    # Ohne Trennzeichen klebt der Titel im Anker an der Jahreszahl (A38).
    erwarteter_anker = {
        "": "2026-11-14titel-der-entscheidung",
        ": ": "2026-11-14-titel-der-entscheidung",
        ":": "2026-11-14-titel-der-entscheidung",
        " - ": "2026-11-14-titel-der-entscheidung",
        "-": "2026-11-14-titel-der-entscheidung",
        " – ": "2026-11-14-titel-der-entscheidung",
        "–": "2026-11-14-titel-der-entscheidung",
        " — ": "2026-11-14-titel-der-entscheidung",
        "—": "2026-11-14-titel-der-entscheidung",
    }
    assert js("projekt.parseEntscheidungen(daten)", markdown) == [
        {
            "datum": "2026-11-14",
            "titel": "Titel der Entscheidung",
            "anker": erwarteter_anker[trennzeichen],
        }
    ]


@ohne_node
def test_parse_entscheidungen_titel_mit_sonderzeichen():
    markdown = "## 2026-11-14: Titel — mit Bindestrich: und Doppelpunkt"
    assert js("projekt.parseEntscheidungen(daten)", markdown) == [
        {
            "datum": "2026-11-14",
            "titel": "Titel — mit Bindestrich: und Doppelpunkt",
            "anker": "2026-11-14-titel-mit-bindestrich-und-doppelpunkt",
        }
    ]


@ohne_node
def test_parse_entscheidungen_ignoriert_unpassende_zeilen():
    markdown = (
        "# Entscheidungslog\n"
        "\n"
        "## Übersicht\n"
        "\n"
        "### 2026-01-01: Zu tief\n"
        "\n"
        "2026-01-02: Ohne Raute\n"
        "\n"
        "## 2026-01-03\n"
        "\n"
        "## 2026-01-05: Gültig\n"
    )
    assert js("projekt.parseEntscheidungen(daten)", markdown) == [
        {
            "datum": "2026-01-05",
            "titel": "Gültig",
            "anker": "2026-01-05-gueltig",
        }
    ]


@ohne_node
def test_parse_entscheidungen_leer_und_crlf():
    assert js("projekt.parseEntscheidungen(daten)", "") == []
    assert js("projekt.parseEntscheidungen(daten)", "\n  \n") == []
    assert js("projekt.parseEntscheidungen(daten)", None) == []
    assert js("projekt.parseEntscheidungen(daten)", 42) == []
    assert js("projekt.parseEntscheidungen(daten)", "# Titel\r\n\r\n## 2026-11-14: Eins\r\n") == [
        {"datum": "2026-11-14", "titel": "Eins", "anker": "2026-11-14-eins"}
    ]


@ohne_node
def test_projekt_punkte_genau_fuenf():
    assert js("projekt.PROJEKT_PUNKTE") == PROJEKT_ERWARTET


@ohne_node
def test_projekt_punkt_findet_unterpunkt():
    assert js("projekt.projektPunkt('log')") == {
        "unterpunkt": "log",
        "titel": "Log",
        "pfad": "log.md",
    }
    assert js("projekt.projektPunkt('technische-spec')")["pfad"] == "projekt/technische-spec.md"


@ohne_node
def test_projekt_punkt_unbekannt_ist_null():
    assert js("projekt.projektPunkt('gibtsnicht')") is None
    assert js("projekt.projektPunkt('')") is None


# --- UI-Läufe im DOM-Stab (Fetch-Antworten simuliert) ----------------------

SEITEN_DOM = r"""
// Fehler-/Erfolgsbereich und Ansichtscontainer wie in index.html (A10).
for (const id of ["fehler", "meldung", "liste-entscheidungen", "liste-projekt"]) {
  const bereich = document.createElement("div");
  bereich.id = id;
  if (id === "fehler" || id === "meldung") bereich.hidden = true;
  bereich._imDokument = true;
}
"""

FETCH_STAB = r"""
// Fetch-Stab: protokolliert jeden Aufruf und liefert Antworten je Bundle-Pfad.
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
        + f"\nimport * as projekt from {json.dumps(PROJEKT_JS.as_uri())};\n"
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


APP_UMGEBUNG = (
    MINI_DOM
    + SEITEN_DOM
    + r"""
// Router-Umgebung (A14-Befund 4): Fenster-Hash, DOM-Ereignisse, Detail-Bereich.
const dokumentHoerer = {};
document.querySelectorAll = () => [];
document.addEventListener = (art, hoerer) => {
  if (!dokumentHoerer[art]) dokumentHoerer[art] = [];
  dokumentHoerer[art].push(hoerer);
};
document.readyState = "loading";

const fensterHoerer = {};
globalThis.window = {
  location: { hash: "" },
  addEventListener: (art, hoerer) => {
    if (!fensterHoerer[art]) fensterHoerer[art] = [];
    fensterHoerer[art].push(hoerer);
  },
};

const detailBereich = document.createElement("div");
detailBereich.id = "detail";

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
    """Führt einen Ablauf über den echten Router (``app.js``) im DOM-Stab aus.

    Der Klick auf einen Link wird wie im Browser nachgestellt: der Hash wird
    gesetzt und ``hashchange`` ausgelöst — danach entscheidet ``app.js``, welche
    Ansicht lädt.
    """
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


SZENARIO_T1 = r"""
await projekt.ladeEntscheidungenAnsicht();
return {
  eintraege: links("liste-entscheidungen"),
  abgerufen: aufrufe.map((a) => a.endpunkt + " " + a.datei),
};
"""

SZENARIO_T3 = r"""
await projekt.ladeProjektAnsicht({ unterpunkt: "" });
return {
  punkte: links("liste-projekt"),
  abgerufen: aufrufe.map((a) => a.endpunkt + " " + a.datei),
};
"""

SZENARIO_T4 = r"""
await projekt.ladeProjektAnsicht({ unterpunkt: "technische-spec" });
const alle = bei("liste-projekt").alleKnoten();
return {
  ueberschriften: alle.filter((k) => k.marke === "h1").map((k) => k.textContent),
  absaetze: alle.filter((k) => k.marke === "p").map((k) => k.textContent),
  listenpunkte: alle.filter((k) => k.marke === "li").map((k) => k.textContent),
  links: links("liste-projekt"),
  abgerufen: aufrufe.map((a) => a.endpunkt + " " + a.datei),
};
"""

SZENARIO_FEHLER = r"""
__AUFRUF__
return {
  text: bei("__CONTAINER__").textContent,
  kinder: bei("__CONTAINER__").kinder.length,
  links: links("__CONTAINER__").length,
  fehler: { sichtbar: sichtbar("fehler"), text: bei("fehler").textContent },
  abgerufen: aufrufe.map((a) => a.endpunkt + " " + a.datei),
};
"""


def szenario_fehler(aufruf: str, container: str) -> str:
    return SZENARIO_FEHLER.replace("__AUFRUF__", aufruf).replace("__CONTAINER__", container)


SZENARIO_HTML_TITEL = r"""
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await projekt.ladeEntscheidungenAnsicht();
const alle = bei("liste-entscheidungen").alleKnoten();
return {
  texte: links("liste-entscheidungen").map((eintrag) => eintrag.text),
  marken: alle.map((knoten) => knoten.marke),
  ausfuehrungen,
  abgerufen: aufrufe.map((a) => a.endpunkt + " " + a.datei),
};
"""

SZENARIO_LEERER_UNTERPUNKT = r"""
await projekt.ladeProjektAnsicht({ unterpunkt: "phasen" });
const alle = bei("liste-projekt").alleKnoten();
return {
  hinweise: alle.filter((knoten) => knoten.classList.contains("leer")).map((knoten) => knoten.textContent),
  absaetze: alle.filter((knoten) => knoten.marke === "p").map((knoten) => knoten.textContent),
  ueberschriften: alle.filter((knoten) => knoten.marke === "h3").map((knoten) => knoten.textContent),
  links: links("liste-projekt"),
  abgerufen: aufrufe.map((a) => a.endpunkt + " " + a.datei),
};
"""

SZENARIO_T2_KLICK = r"""
window.location.hash = __START__;
await import(__APP__);
for (const hoerer of dokumentHoerer.DOMContentLoaded || []) await hoerer();
await warteAuf(() => links("liste-entscheidungen").length > 0);

const eintrag = links("liste-entscheidungen")[0];
// Klick wie im Browser: Hash setzen, dann meldet sich der Router per hashchange.
window.location.hash = eintrag.href;
for (const hoerer of fensterHoerer.hashchange || []) await hoerer();
await warteAuf(() => bei("detail").textContent.includes(__TITEL__));

return {
  href: eintrag.href,
  abgerufen: aufrufe.map((a) => a.endpunkt + " " + a.datei),
  detailText: bei("detail").textContent,
  fehler: { sichtbar: sichtbar("fehler"), text: bei("fehler").textContent },
};
"""


def szenario_klick(start: str, titel: str) -> str:
    return (
        SZENARIO_T2_KLICK.replace("__START__", json.dumps(start))
        .replace("__APP__", json.dumps(APP_JS.as_uri()))
        .replace("__TITEL__", json.dumps(titel))
    )


@ohne_node
def test_t1_entscheidungen_zeigen_datum_und_titel():
    ergebnis = dom(
        SZENARIO_T1,
        antworten={ENTSCHEIDUNGEN_PFAD: {"status": 200, "koerper": {"frontmatter": {}, "markdown": LOG_MD}}},
    )
    assert ergebnis["eintraege"] == [
        {
            "text": f"{eintrag['datum']}: {eintrag['titel']}",
            "href": f"{DETAIL_VORSCHLAG}entscheidungen%2Flog.md#{eintrag['anker']}",
        }
        for eintrag in LOG_ERWARTET
    ]
    assert ergebnis["abgerufen"] == [f"/api/file {ENTSCHEIDUNGEN_PFAD}"]


@ohne_node
def test_t2_eintrag_oeffnet_detail_der_log_datei():
    # Jeder Klick öffnet das Detail der Log-Datei (die Einträge sind keine Dateien).
    ergebnis = dom(
        SZENARIO_T1,
        antworten={ENTSCHEIDUNGEN_PFAD: {"status": 200, "koerper": {"frontmatter": {}, "markdown": LOG_MD}}},
    )
    assert len(ergebnis["eintraege"]) == len(LOG_ERWARTET)
    for erwartet, eintrag in zip(LOG_ERWARTET, ergebnis["eintraege"]):
        assert eintrag["href"].startswith(DETAIL_VORSCHLAG)
        ziel, _, anker = eintrag["href"][len(DETAIL_VORSCHLAG):].partition("#")
        assert unquote(ziel) == ENTSCHEIDUNGEN_PFAD
        # A38: jeder Eintrag zielt auf seinen eigenen Anker, nicht auf den Anfang.
        assert anker == erwartet["anker"]

    # A14-Befund 4: der Klick lädt die Datei wirklich über die A12-Ansicht —
    # nicht nur ein gesetztes `href`. Geprüft wird der dekodierte Zielpfad.
    klick = app_lauf(
        szenario_klick("#/entscheidungen", LOG_ERWARTET[0]["titel"]),
        antworten={ENTSCHEIDUNGEN_PFAD: {"status": 200, "koerper": {"frontmatter": {}, "markdown": LOG_MD}}},
    )
    ziel, _, anker = klick["href"][len(DETAIL_VORSCHLAG):].partition("#")
    assert unquote(ziel) == ENTSCHEIDUNGEN_PFAD
    assert anker == LOG_ERWARTET[0]["anker"]
    assert klick["abgerufen"] == [
        f"/api/file {ENTSCHEIDUNGEN_PFAD}",
        f"/api/file {ENTSCHEIDUNGEN_PFAD}",
    ]
    assert LOG_ERWARTET[0]["titel"] in klick["detailText"]
    assert klick["fehler"]["sichtbar"] is False


@ohne_node
def test_t1_html_im_titel_bleibt_text():
    # A14-Befund 3: HTML-Payload im Log-Titel wird Literal gerendert.
    ergebnis = dom(
        SZENARIO_HTML_TITEL,
        antworten={ENTSCHEIDUNGEN_PFAD: {"status": 200, "koerper": {"frontmatter": {}, "markdown": LOG_HTML}}},
    )
    assert ergebnis["texte"] == [f"2026-11-14: {HTML_TITEL}"]
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []
    assert ergebnis["abgerufen"] == [f"/api/file {ENTSCHEIDUNGEN_PFAD}"]


@ohne_node
def test_t3_projekt_zeigt_fuenf_unterpunkte():
    ergebnis = dom(SZENARIO_T3)
    assert ergebnis["punkte"] == [
        {"text": punkt["titel"], "href": f"{PROJEKT_VORSCHLAG}{punkt['unterpunkt']}"}
        for punkt in PROJEKT_ERWARTET
    ]
    # Die Liste ist statisch: kein Request nötig.
    assert ergebnis["abgerufen"] == []


@ohne_node
def test_t4_spec_oeffnet_detail_mit_gerendertem_inhalt():
    ergebnis = dom(
        SZENARIO_T4,
        antworten={
            "projekt/technische-spec.md": {
                "status": 200,
                "koerper": {"frontmatter": {}, "markdown": SPEC_MD},
            }
        },
    )
    # Gerendert und nicht als Rohtext: Überschrift, Absatz und Liste sind Knoten.
    assert ergebnis["ueberschriften"] == ["Technische Spec"]
    assert ergebnis["absaetze"] == ["Spec-Absatz zur Prüfung."]
    assert ergebnis["listenpunkte"] == ["Erster Punkt"]
    assert ergebnis["links"] == [{"text": "← Zurück zum Projekt", "href": "#/projekt"}]
    assert ergebnis["abgerufen"] == ["/api/file projekt/technische-spec.md"]


@ohne_node
def test_t5_fehlende_datei_entscheidungen_zeigt_fehlermeldung():
    ergebnis = dom(
        szenario_fehler("await projekt.ladeEntscheidungenAnsicht();", "liste-entscheidungen"),
        antworten={ENTSCHEIDUNGEN_PFAD: {"status": 404, "koerper": {"error": "Nicht gefunden."}}},
    )
    # Fehlermeldung statt leerem Screen (fail-loud wie A11/A12).
    assert ergebnis["text"]
    assert ergebnis["kinder"] > 0
    assert ergebnis["links"] == 0
    assert ergebnis["fehler"]["sichtbar"] is True
    assert ergebnis["fehler"]["text"]


@ohne_node
def test_t5_fehlende_datei_projekt_zeigt_fehlermeldung():
    ergebnis = dom(
        szenario_fehler('await projekt.ladeProjektAnsicht({ unterpunkt: "phasen" });', "liste-projekt"),
        antworten={"projekt/phasen.md": {"status": 404, "koerper": {"error": "Nicht gefunden."}}},
    )
    assert ergebnis["text"]
    assert ergebnis["kinder"] > 0
    assert ergebnis["links"] == 0
    assert ergebnis["fehler"]["sichtbar"] is True
    assert ergebnis["fehler"]["text"]


@ohne_node
def test_unerwartetes_format_ist_fail_loud():
    ergebnis = dom(
        szenario_fehler("await projekt.ladeEntscheidungenAnsicht();", "liste-entscheidungen"),
        antworten={ENTSCHEIDUNGEN_PFAD: {"status": 200, "koerper": {"markdown": 42}}},
    )
    assert "Format" in ergebnis["text"]
    assert ergebnis["fehler"]["sichtbar"] is True
    assert "Format" in ergebnis["fehler"]["text"]


@ohne_node
def test_unbekannter_unterpunkt_ist_fail_loud():
    ergebnis = dom(
        szenario_fehler('await projekt.ladeProjektAnsicht({ unterpunkt: "gibtsnicht" });', "liste-projekt"),
    )
    assert ergebnis["text"]
    assert ergebnis["fehler"]["sichtbar"] is True
    assert ergebnis["abgerufen"] == []


@ohne_node
@pytest.mark.parametrize(
    "container,aufruf",
    [
        ("liste-entscheidungen", "await projekt.ladeEntscheidungenAnsicht();"),
        ("liste-projekt", 'await projekt.ladeProjektAnsicht({ unterpunkt: "konzept" });'),
    ],
)
def test_ohne_container_zeigt_fehlermeldung(container, aufruf):
    # A14-Befund 2: fehlt der Container, wird das gemeldet statt still beendet.
    ablauf = (
        f'REGISTRIERT.delete("{container}");\n'
        + aufruf
        + "\nreturn {"
        + ' fehler: { sichtbar: sichtbar("fehler"), text: bei("fehler").textContent },'
        + " abgerufen: aufrufe.map((a) => a.endpunkt),"
        + " };"
    )
    ergebnis = dom(
        ablauf,
        antworten={"projekt/konzept.md": {"status": 200, "koerper": {"markdown": "# Konzept"}}},
    )
    assert ergebnis["fehler"]["sichtbar"] is True
    assert container in ergebnis["fehler"]["text"]
    # Ohne Ziel Container wird auch nichts geladen.
    assert ergebnis["abgerufen"] == []


@ohne_node
def test_ohne_container_und_ohne_fehlerbereich_ist_robust():
    # Doppelter Ausfall (Container und Fehlerbereich fehlen) darf nicht crashen.
    ergebnis = dom(
        'for (const id of ["fehler", "liste-entscheidungen", "liste-projekt"]) REGISTRIERT.delete(id);\n'
        "await projekt.ladeEntscheidungenAnsicht();\n"
        'await projekt.ladeProjektAnsicht({ unterpunkt: "konzept" });\n'
        "return { ok: true };",
        antworten={"projekt/konzept.md": {"status": 200, "koerper": {"markdown": "# Konzept"}}},
    )
    assert ergebnis == {"ok": True}


@ohne_node
@pytest.mark.parametrize("markdown", ["", "   ", "\n \n"])
def test_leerer_unterpunkt_zeigt_hinweis(markdown):
    # A14-Befund 8: leere Datei zeigt einen Hinweis statt leerer Fläche.
    ergebnis = dom(
        SZENARIO_LEERER_UNTERPUNKT,
        antworten={"projekt/phasen.md": {"status": 200, "koerper": {"frontmatter": {}, "markdown": markdown}}},
    )
    assert ergebnis["hinweise"] == ["Keine Inhalte."]
    assert ergebnis["absaetze"] == ["Keine Inhalte."]
    assert ergebnis["ueberschriften"] == ["Phasen"]
    assert ergebnis["links"] == [{"text": "← Zurück zum Projekt", "href": "#/projekt"}]
    assert ergebnis["abgerufen"] == ["/api/file projekt/phasen.md"]


# --- HTTP-Läufe gegen ein Test-Bundle unter tmp_path -----------------------


@pytest.fixture()
def szenario_bundle(tmp_path):
    wurzel = tmp_path / "bundle"
    (wurzel / "entscheidungen").mkdir(parents=True)
    (wurzel / "projekt" / "user-stories").mkdir(parents=True)
    (wurzel / ENTSCHEIDUNGEN_PFAD).write_text(BUNDLE_LOG, encoding="utf-8")
    for pfad, inhalt in BUNDLE_DATEIEN.items():
        (wurzel / pfad).write_text(inhalt, encoding="utf-8")
    return wurzel


@pytest.fixture()
def luecken_bundle(tmp_path):
    """Bundle ohne `entscheidungen/log.md` und ohne `projekt/phasen.md` (T5)."""
    wurzel = tmp_path / "luecke"
    (wurzel / "projekt" / "user-stories").mkdir(parents=True)
    for pfad, inhalt in BUNDLE_DATEIEN.items():
        if pfad == "projekt/phasen.md":
            continue
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


@ohne_node
def test_http_t1_entscheidungen_aus_test_bundle(app_server):
    ergebnis = ui_lauf(app_server, SZENARIO_T1)
    assert ergebnis["eintraege"] == [
        {
            "text": "2026-11-14: Erste Entscheidung",
            "href": f"{DETAIL_VORSCHLAG}entscheidungen%2Flog.md#2026-11-14-erste-entscheidung",
        },
        {
            "text": "2026-11-13: Zweite Entscheidung",
            "href": f"{DETAIL_VORSCHLAG}entscheidungen%2Flog.md#2026-11-13-zweite-entscheidung",
        },
    ]
    assert ergebnis["abgerufen"] == [f"/api/file {ENTSCHEIDUNGEN_PFAD}"]


@ohne_node
def test_http_t2_eintrag_link_zur_log_datei(app_server):
    ergebnis = ui_lauf(app_server, SZENARIO_T1)
    anker = []
    for eintrag in ergebnis["eintraege"]:
        ziel, _, anker_teil = eintrag["href"][len(DETAIL_VORSCHLAG):].partition("#")
        assert unquote(ziel) == ENTSCHEIDUNGEN_PFAD
        anker.append(anker_teil)
    assert anker == ["2026-11-14-erste-entscheidung", "2026-11-13-zweite-entscheidung"]


@ohne_node
def test_http_t3_projekt_unterpunkte(app_server):
    ergebnis = ui_lauf(app_server, SZENARIO_T3)
    assert [punkt["text"] for punkt in ergebnis["punkte"]] == [
        "Konzept",
        "Technische Spec",
        "User Stories",
        "Phasen",
        "Log",
    ]
    assert ergebnis["abgerufen"] == []


@ohne_node
def test_http_t4_spec_gerendert(app_server):
    ergebnis = ui_lauf(app_server, SZENARIO_T4)
    assert ergebnis["ueberschriften"] == ["Technische Spec"]
    assert ergebnis["absaetze"] == ["Spec-Absatz."]
    assert ergebnis["links"] == [{"text": "← Zurück zum Projekt", "href": "#/projekt"}]
    assert ergebnis["abgerufen"] == ["/api/file projekt/technische-spec.md"]


@ohne_node
@pytest.mark.parametrize("punkt", PROJEKT_ERWARTET)
def test_http_unterpunkt_laedt_passende_datei(app_server, punkt):
    ablauf = (
        f'await projekt.ladeProjektAnsicht({{ unterpunkt: "{punkt["unterpunkt"]}" }});\n'
        "const alle = bei(\"liste-projekt\").alleKnoten();\n"
        "return {\n"
        "  ueberschriften: alle.filter((k) => k.marke === \"h1\").map((k) => k.textContent),\n"
        "  abgerufen: aufrufe.map((a) => a.endpunkt + \" \" + a.datei),\n"
        "};"
    )
    ergebnis = ui_lauf(app_server, ablauf)
    assert ergebnis["abgerufen"] == [f"/api/file {punkt['pfad']}"]
    assert ergebnis["ueberschriften"], f"{punkt['titel']} rendert keinen Inhalt"


@ohne_node
def test_http_t5_fehlende_datei_entscheidungen_zeigt_fehlermeldung(luecken_server):
    ergebnis = ui_lauf(
        luecken_server,
        szenario_fehler("await projekt.ladeEntscheidungenAnsicht();", "liste-entscheidungen"),
    )
    assert ergebnis["text"]
    assert ergebnis["kinder"] > 0
    assert ergebnis["fehler"]["sichtbar"] is True
    assert ergebnis["fehler"]["text"]


@ohne_node
def test_http_t5_fehlende_datei_projekt_zeigt_fehlermeldung(luecken_server):
    ergebnis = ui_lauf(
        luecken_server,
        szenario_fehler('await projekt.ladeProjektAnsicht({ unterpunkt: "phasen" });', "liste-projekt"),
    )
    assert ergebnis["text"]
    assert ergebnis["kinder"] > 0
    assert ergebnis["fehler"]["sichtbar"] is True
    assert ergebnis["fehler"]["text"]
