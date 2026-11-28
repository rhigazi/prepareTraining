"""Prüfungen für Log-Anker (A38, aus A14-9).

Jeder Log-Eintrag bekommt im Markdown-Renderer eine stabile ``id``; Verweise
aus der Entscheidungen-Liste öffnen ``#/detail/entscheidungen/log.md#<anker>``
und springen zum konkreten Eintrag. Die UI-Läufe nutzen den gemeinsamen
Mini-DOM-Harness (``dom_helfer.py``); Seiten- und Fetch-Gerüst bleiben hier.
"""

import json
import re
import sys
from pathlib import Path

import pytest

from dom_helfer import MINI_DOM, js_detail as js, lies, node_ausfuehren, ohne_node

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
DETAIL_JS = STATIC_DIR / "js" / "detail.js"
PROJEKT_JS = STATIC_DIR / "js" / "projekt.js"
APP_JS = STATIC_DIR / "js" / "app.js"

ENTSCHEIDUNGEN_PFAD = "entscheidungen/log.md"
DETAIL_VORSCHLAG = "#/detail/"

LOG_MD = (
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

ANKER_ERSTE = "2026-11-14-erste-entscheidung"
ANKER_ZWEITE = "2026-11-13-zweite-entscheidung"

PROJEKT_LOG_MD = (
    "# Projekt-Log\n"
    "\n"
    "## 2026-11-16\n"
    "\n"
    "Eintrag eins.\n"
    "\n"
    "## 2026-11-15\n"
    "\n"
    "Eintrag zwei.\n"
)


# --- Statische Prüfungen ---------------------------------------------------


def test_detail_js_exportiert_anker_funktionen():
    quelle = lies(DETAIL_JS)
    assert "export function erstelleAnker" in quelle
    assert "export function erstelleAnkerVergabe" in quelle


def test_detail_js_rendert_ohne_innerhtml():
    assert "innerHTML" not in lies(DETAIL_JS)


def test_projekt_js_rendert_ohne_innerhtml():
    assert "innerHTML" not in lies(PROJEKT_JS)


@pytest.mark.parametrize("senke", ["outerHTML", "insertAdjacentHTML", "document.write(", "eval("])
def test_keine_weiteren_html_senken(senke):
    assert senke not in lies(DETAIL_JS)
    assert senke not in lies(PROJEKT_JS)


# --- Reine Logik: Anker ----------------------------------------------------


@ohne_node
def test_anker_aus_log_ueberschrift():
    assert js("detail.erstelleAnker('2026-11-14: Erste Entscheidung')") == ANKER_ERSTE


@ohne_node
def test_anker_normalisiert_umlaute_und_sonderzeichen():
    assert js("detail.erstelleAnker('Übersicht: Änderung & Größe („frei“)')") == (
        "uebersicht-aenderung-groesse-frei"
    )
    assert js("detail.erstelleAnker('Straße / Maßnahme')") == "strasse-massnahme"
    assert js("detail.erstelleAnker('  Doppel   Leerzeichen  ')") == "doppel-leerzeichen"


@ohne_node
@pytest.mark.parametrize(
    "text",
    [
        '2026-11-14: <img src=x onerror=alert(1)>',
        'Titel mit "Anführungszeichen" und / Slash',
        "Emoji 🚀 und Ümläüte",
        "\t\n",
        # Nicht-ASCII-Kleinbuchstaben dürfen nicht durchrutschen (W1: `islower()`
        # akzeptiert z. B. `ø`; ein Sanitizer, der es durchlässt, bliebe unentdeckt).
        "Café crème",
        "Falsch: ø und İ und ẞ",
        "Gemischte Umlaute: äöü ÄÖÜ ß",
        "Türkisch: İstanbul, ı und ıi",
    ],
)
def test_anker_nur_ascii_kleinbuchstaben_ziffern_bindestrich(text):
    anker = js("detail.erstelleAnker(daten)", text)
    assert anker
    assert re.fullmatch(r"[a-z0-9-]+", anker), anker
    assert anker.strip("-") == anker


@ohne_node
def test_anker_fallback_und_laengenbegrenzung():
    assert js("detail.erstelleAnker('')") == "abschnitt"
    assert js("detail.erstelleAnker('###')") == "abschnitt"
    assert js("detail.erstelleAnker(null)") == "abschnitt"
    lang = js("detail.erstelleAnker(daten)", "wort " * 60)
    assert len(lang) <= 80
    assert not lang.endswith("-")


@ohne_node
def test_trenne_anker_trennt_am_ersten_rautezeichen():
    # Belegt das dokumentierte Verhalten: `#` im Dateinamen ist nicht
    # vorgesehen — getrennt wird am *ersten* `#`, der Rest gehört zum Anker
    # (A38-K1: Verhalten gepinnt, nicht geändert).
    ergebnis = js(
        "['ordner/datei#mit#raute.md#anker', ' log.md#2026-11-15 ',"
        " 'log.md', '  #nur-anker '].map((text) => detail.trenneAnker(text))"
    )
    assert ergebnis == [
        {"pfad": "ordner/datei", "anker": "mit#raute.md#anker"},
        {"pfad": "log.md", "anker": "2026-11-15"},
        {"pfad": "log.md", "anker": ""},
        {"pfad": "", "anker": "nur-anker"},
    ]


@ohne_node
def test_anker_vergabe_haengt_suffix_bei_doppelten_titeln_an():
    ergebnis = js(
        "(() => { const vergabe = detail.erstelleAnkerVergabe();"
        " return [vergabe('2026-11-16: Gleicher Titel'), vergabe('2026-11-16: Gleicher Titel'),"
        " vergabe('2026-11-16: Gleicher Titel')]; })()"
    )
    assert ergebnis == [
        "2026-11-16-gleicher-titel",
        "2026-11-16-gleicher-titel-2",
        "2026-11-16-gleicher-titel-3",
    ]


# --- Renderer --------------------------------------------------------------

RENDER_UMGEBUNG = r"""
Knoten.prototype.scrollIntoView = function () {
  globalThis.gescrollt.push(this.id);
};
function ueberschriften(knoten) {
  return sammle(knoten)
    .filter((kind) => /^h[1-6]$/.test(kind.marke))
    .map((kind) => ({ id: kind.id, marke: kind.marke, text: kind.textContent }));
}
"""


def render_lauf(ablauf: str, markdown: str) -> dict:
    skript = (
        f'import * as detail from {json.dumps(DETAIL_JS.as_uri())};\n'
        + MINI_DOM
        + "globalThis.gescrollt = [];\n"
        + RENDER_UMGEBUNG
        + f"const MARKDOWN = {json.dumps(markdown, ensure_ascii=False)};\n"
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


@ohne_node
def test_renderer_vergibt_ids_aus_ueberschriften():
    ergebnis = render_lauf(
        "const frag = detail.rendereMarkdown(MARKDOWN);\n"
        "return { ueberschriften: ueberschriften(frag), marken: marken(frag) };",
        LOG_MD,
    )
    assert ergebnis["ueberschriften"] == [
        {"id": "entscheidungslog", "marke": "h1", "text": "Entscheidungslog"},
        {"id": ANKER_ERSTE, "marke": "h2", "text": "2026-11-14: Erste Entscheidung"},
        {"id": ANKER_ZWEITE, "marke": "h2", "text": "2026-11-13: Zweite Entscheidung"},
    ]


@ohne_node
def test_renderer_ids_sind_bei_doppelten_titeln_eindeutig():
    markdown = "# Log\n\n## 2026-11-16: Gleicher Titel\n\n## 2026-11-16: Gleicher Titel\n"
    ergebnis = render_lauf(
        "const frag = detail.rendereMarkdown(MARKDOWN);\n"
        "return ueberschriften(frag).map((k) => k.id);",
        markdown,
    )
    assert ergebnis == [
        "log",
        "2026-11-16-gleicher-titel",
        "2026-11-16-gleicher-titel-2",
    ]


@ohne_node
def test_renderer_bleibt_bei_html_im_titel_literal_und_sicher():
    markdown = '# Log\n\n## 2026-11-14: <img src=x onerror=alert(1)>\n'
    ergebnis = render_lauf(
        "const ausfuehrungen = [];\n"
        "globalThis.alert = (wert) => ausfuehrungen.push(String(wert));\n"
        "const frag = detail.rendereMarkdown(MARKDOWN);\n"
        "return {\n"
        "  ueberschriften: ueberschriften(frag),\n"
        "  marken: marken(frag),\n"
        "  ausfuehrungen,\n"
        "};",
        markdown,
    )
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []
    assert ergebnis["ueberschriften"][1]["text"] == "2026-11-14: <img src=x onerror=alert(1)>"
    assert ergebnis["ueberschriften"][1]["id"] == "2026-11-14-img-src-x-onerror-alert-1"


# --- Detailansicht: Sprung zum Anker --------------------------------------

SEITEN_DOM = r"""
const fehler = document.createElement("div");
fehler.id = "fehler";
fehler.hidden = true;
const meldung = document.createElement("div");
meldung.id = "meldung";
meldung.hidden = true;
for (const id of ["detail", "liste-entscheidungen", "liste-projekt"]) {
  const bereich = document.createElement("div");
  bereich.id = id;
  bereich._imDokument = true;
}
Knoten.prototype.scrollIntoView = function () {
  globalThis.gescrollt.push(this.id);
};
function ueberschriften(knoten) {
  return sammle(knoten)
    .filter((kind) => /^h[1-6]$/.test(kind.marke))
    .map((kind) => ({ id: kind.id, marke: kind.marke, text: kind.textContent }));
}
"""

FETCH_STAB = r"""
globalThis.gescrollt = [];
const aufrufe = [];
globalThis.fetch = async (pfad) => {
  const ziel = new URL(String(pfad), "http://lokal");
  const datei = ziel.searchParams.get("path") ?? ziel.pathname;
  aufrufe.push({ endpunkt: ziel.pathname, datei, roh: String(pfad) });
  const inhalt = ANTWORTEN[datei];
  const vorgabe = inhalt ? { status: 200, koerper: inhalt } : { status: 404, koerper: { error: "Nicht gefunden." } };
  return {
    ok: vorgabe.status < 400,
    status: vorgabe.status,
    headers: { get: () => "application/json" },
    text: async () => JSON.stringify(vorgabe.koerper),
  };
};
"""


def seiten_lauf(ablauf: str, antworten: dict, markdown: str = LOG_MD) -> dict:
    skript = (
        MINI_DOM
        + SEITEN_DOM
        + f"const ANTWORTEN = {json.dumps(antworten, ensure_ascii=False)};\n"
        + f"const MARKDOWN = {json.dumps(markdown, ensure_ascii=False)};\n"
        + FETCH_STAB
        + f'import * as detail from {json.dumps(DETAIL_JS.as_uri())};\n'
        + f'import * as projekt from {json.dumps(PROJEKT_JS.as_uri())};\n'
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


def datei_antwort(markdown: str) -> dict:
    return {"frontmatter": {}, "markdown": markdown}


@ohne_node
def test_detail_springt_zum_anker_und_hebt_ihn_hervor():
    ergebnis = seiten_lauf(
        f'await detail.ladeDetail({{ unterpunkt: "{ENTSCHEIDUNGEN_PFAD}#{ANKER_ERSTE}" }});\n'
        "const kopf = document.getElementById({anker});\n"
        "return {\n"
        "  gescrollt,\n"
        "  aktiv: document.activeElement ? document.activeElement.id : null,\n"
        "  klassen: kopf ? kopf.klassen() : [],\n"
        "  tabindex: kopf ? kopf.getAttribute('tabindex') : null,\n"
        "  text: bei('detail').textContent,\n"
        "  aufrufe: aufrufe.map((a) => a.endpunkt + ' ' + a.datei),\n"
        "};".replace("{anker}", json.dumps(ANKER_ERSTE)),
        {ENTSCHEIDUNGEN_PFAD: datei_antwort(LOG_MD)},
    )
    assert ergebnis["aufrufe"] == [f"/api/file {ENTSCHEIDUNGEN_PFAD}"]
    assert ergebnis["gescrollt"] == [ANKER_ERSTE]
    assert ergebnis["aktiv"] == ANKER_ERSTE
    assert "anker-ziel" in ergebnis["klassen"]
    assert ergebnis["tabindex"] == "-1"
    assert "2026-11-14: Erste Entscheidung" in ergebnis["text"]


@ohne_node
def test_detail_ohne_anker_bleibt_am_seitenanfang():
    ergebnis = seiten_lauf(
        f'await detail.ladeDetail({{ unterpunkt: "{ENTSCHEIDUNGEN_PFAD}" }});\n'
        "return { gescrollt, aktiv: document.activeElement ? document.activeElement.id : null };",
        {ENTSCHEIDUNGEN_PFAD: datei_antwort(LOG_MD)},
    )
    assert ergebnis["gescrollt"] == []
    assert ergebnis["aktiv"] is None


@ohne_node
def test_detail_unbekannter_anker_ist_robust():
    ergebnis = seiten_lauf(
        f'await detail.ladeDetail({{ unterpunkt: "{ENTSCHEIDUNGEN_PFAD}#gibt-es-nicht" }});\n'
        "return {\n"
        "  gescrollt,\n"
        "  fehler: { sichtbar: !fehler.hidden, text: fehler.textContent },\n"
        "  text: bei('detail').textContent,\n"
        "};",
        {ENTSCHEIDUNGEN_PFAD: datei_antwort(LOG_MD)},
    )
    assert ergebnis["gescrollt"] == []
    assert ergebnis["fehler"]["sichtbar"] is False
    assert "2026-11-14: Erste Entscheidung" in ergebnis["text"]


@ohne_node
def test_detail_anker_wird_nicht_als_dateipfad_geladen():
    ergebnis = seiten_lauf(
        f'await detail.ladeDetail({{ unterpunkt: "{ENTSCHEIDUNGEN_PFAD}#{ANKER_ERSTE}" }});\n'
        "return aufrufe;",
        {ENTSCHEIDUNGEN_PFAD: datei_antwort(LOG_MD)},
    )
    assert [eintrag["datei"] for eintrag in ergebnis] == [ENTSCHEIDUNGEN_PFAD]
    assert all("#" not in eintrag["roh"] for eintrag in ergebnis)


# --- Entscheidungen-Liste: Verweise mit Anker ------------------------------

@ohne_node
def test_parse_entscheidungen_liefert_anker():
    ergebnis = seiten_lauf(
        "return projekt.parseEntscheidungen(MARKDOWN);",
        {},
    )
    assert ergebnis == [
        {"datum": "2026-11-14", "titel": "Erste Entscheidung", "anker": ANKER_ERSTE},
        {"datum": "2026-11-13", "titel": "Zweite Entscheidung", "anker": ANKER_ZWEITE},
    ]


@ohne_node
def test_liste_verlinkt_jeden_eintrag_mit_eigenem_anker():
    ergebnis = seiten_lauf(
        "await projekt.ladeEntscheidungenAnsicht();\n"
        "const eintraege = [];\n"
        "for (const knoten of sammle(bei('liste-entscheidungen'))) {\n"
        "  if (knoten.marke !== 'a') continue;\n"
        "  eintraege.push({ text: knoten.textContent, href: knoten.href });\n"
        "}\n"
        "return eintraege;",
        {ENTSCHEIDUNGEN_PFAD: datei_antwort(LOG_MD)},
    )
    assert ergebnis == [
        {
            "text": "2026-11-14: Erste Entscheidung",
            "href": f"{DETAIL_VORSCHLAG}entscheidungen%2Flog.md#{ANKER_ERSTE}",
        },
        {
            "text": "2026-11-13: Zweite Entscheidung",
            "href": f"{DETAIL_VORSCHLAG}entscheidungen%2Flog.md#{ANKER_ZWEITE}",
        },
    ]
    assert len({eintrag["href"] for eintrag in ergebnis}) == 2


@ohne_node
def test_liste_vergibt_suffixe_wie_der_renderer():
    markdown = (
        "# Entscheidungslog\n\n"
        "## 2026-11-16: Gleicher Titel\n\nText eins.\n\n"
        "## 2026-11-16: Gleicher Titel\n\nText zwei.\n"
    )
    ergebnis = seiten_lauf(
        "await projekt.ladeEntscheidungenAnsicht();\n"
        "const hrefs = sammle(bei('liste-entscheidungen'))\n"
        "  .filter((knoten) => knoten.marke === 'a')\n"
        "  .map((knoten) => knoten.href.split('#').slice(-1)[0]);\n"
        "const ids = ueberschriften(detail.rendereMarkdown(MARKDOWN))\n"
        "  .filter((k) => k.marke === 'h2')\n"
        "  .map((k) => k.id);\n"
        "return { hrefs, ids };",
        {ENTSCHEIDUNGEN_PFAD: datei_antwort(markdown)},
        markdown=markdown,
    )
    # Renderer und Liste müssen dieselben Anker vergeben (sonst springt nichts).
    assert ergebnis["hrefs"] == ergebnis["ids"] == [
        "2026-11-16-gleicher-titel",
        "2026-11-16-gleicher-titel-2",
    ]


# --- Projekt-Ansicht: Anker im Unterpunkt ---------------------------------

@ohne_node
def test_projekt_ansicht_springt_zum_anker_im_log():
    ergebnis = seiten_lauf(
        'await projekt.ladeProjektAnsicht({ unterpunkt: "log#2026-11-15" });\n'
        "return {\n"
        "  gescrollt,\n"
        "  aktiv: document.activeElement ? document.activeElement.id : null,\n"
        "  aufrufe: aufrufe.map((a) => a.endpunkt + ' ' + a.datei),\n"
        "  text: bei('liste-projekt').textContent,\n"
        "};",
        {"log.md": datei_antwort(PROJEKT_LOG_MD)},
    )
    assert ergebnis["aufrufe"] == ["/api/file log.md"]
    assert ergebnis["gescrollt"] == ["2026-11-15"]
    assert ergebnis["aktiv"] == "2026-11-15"
    assert "Eintrag zwei." in ergebnis["text"]


# --- Router: echter Hash-Weg ----------------------------------------------

APP_UMGEBUNG = r"""
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

const warte = () => new Promise((fertig) => setTimeout(fertig, 5));
const warteAuf = async (bedingung) => {
  for (let versuch = 0; versuch < 100; versuch += 1) {
    if (bedingung()) return true;
    await warte();
  }
  return false;
};
"""


def router_lauf(start: str, antworten: dict) -> dict:
    skript = (
        MINI_DOM
        + SEITEN_DOM
        + f"const ANTWORTEN = {json.dumps(antworten, ensure_ascii=False)};\n"
        + FETCH_STAB
        + APP_UMGEBUNG
        + f"window.location.hash = {json.dumps(start)};\n"
        + f"await import({json.dumps(APP_JS.as_uri())});\n"
        + "const ergebnis = await (async () => {\n"
        + "for (const hoerer of dokumentHoerer.DOMContentLoaded || []) await hoerer();\n"
        + "await warteAuf(() => bei('detail').textContent.includes('Erste Entscheidung'));\n"
        + "return {\n"
        "  gescrollt,\n"
        "  aktiv: document.activeElement ? document.activeElement.id : null,\n"
        "  text: bei('detail').textContent,\n"
        "  fehler: { sichtbar: !fehler.hidden, text: fehler.textContent },\n"
        "};\n"
        "})();\n"
        "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


@ohne_node
def test_router_oeffnet_konkreten_log_eintrag():
    hash = f"#/detail/entscheidungen%2Flog.md#{ANKER_ERSTE}"
    ergebnis = router_lauf(hash, {ENTSCHEIDUNGEN_PFAD: datei_antwort(LOG_MD)})
    assert ergebnis["fehler"]["sichtbar"] is False
    assert ergebnis["gescrollt"] == [ANKER_ERSTE]
    assert ergebnis["aktiv"] == ANKER_ERSTE
    assert "2026-11-14: Erste Entscheidung" in ergebnis["text"]
