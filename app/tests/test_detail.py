"""Prüfungen für die Detailansicht (A12).

Die UI-Szenarien T1–T10 spielt der ``tester`` mit dem Moli-Browser durch; hier
werden ``detail.js`` und seine Verdrahtung ohne Browser geprüft. Die reine
Markdown-/Metadaten-Logik läuft über Node (keine neue Abhängigkeit). T10
(403-Pfad) ist zusätzlich hier direkt belegt: Mini-DOM in Node, der
``fetch``-Proxy erzwingt die 403 am echten Server. Der Mini-DOM-Harness liegt
in ``dom_helfer.py``; hier bleiben Seiten-/Fetch-Gerüst und Prüfungen.
"""

import hashlib
import json
import re
import sys
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from dom_helfer import MINI_DOM, js_detail as js, lies, node_ausfuehren, ohne_node

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
DETAIL_JS = STATIC_DIR / "js" / "detail.js"
APP_JS = STATIC_DIR / "js" / "app.js"
API_JS = STATIC_DIR / "js" / "api.js"

# Nur diese beiden UI-Status darf die App setzen (R1); Pipeline-Status fehlen.
ERLAUBTE_STATUS_KNOEPFE = ["Klarung", "Geschlossen"]

# T10: Die UI zeigt "In Arbeit" an, darf ihn aber nie setzen (R1).
T10_DATEI = "aufgaben/a1.md"
T10_VERBOTENER_STATUS = "In Arbeit"


# --- Statische Prüfungen ---------------------------------------------------


def test_detail_js_vorhanden():
    assert DETAIL_JS.is_file()


def test_app_js_importiert_detail():
    assert re.search(r'from\s+"\./detail\.js"', lies(APP_JS))


def test_app_js_verdrahtet_detail():
    assert 'registriereAnsicht("detail"' in lies(APP_JS)


def test_app_js_oeffnet_detail_bei_zeilenklick():
    js_quelle = lies(APP_JS)
    assert "data-path" in js_quelle
    assert "closest" in js_quelle
    assert "#/detail/" in js_quelle


@pytest.mark.parametrize("endpunkt", ["/api/file", "/api/nachtrag", "/api/meta"])
def test_detail_js_nutzt_endpunkt(endpunkt):
    assert endpunkt in lies(DETAIL_JS)


def test_detail_js_nutzt_api_helper():
    js_quelle = lies(DETAIL_JS)
    assert re.search(r"import\s*\{[^}]*\bgetJson\b[^}]*\}\s*from\s*\"\./api\.js\"", js_quelle)
    assert re.search(r"import\s*\{[^}]*\bpostJson\b[^}]*\}\s*from\s*\"\./api\.js\"", js_quelle)
    assert "zeigeMeldung" in js_quelle
    assert "zeigeFehler" in js_quelle


def test_detail_js_verwendet_container_id():
    assert '"detail"' in lies(DETAIL_JS)


def test_detail_js_rendert_ohne_innerhtml():
    js_quelle = lies(DETAIL_JS)
    assert "textContent" in js_quelle
    assert "innerHTML" not in js_quelle


@pytest.mark.parametrize(
    "senke",
    ["outerHTML", "insertAdjacentHTML", "document.write(", "eval("],
)
def test_detail_js_vermeidet_weitere_html_senken(senke):
    assert senke not in lies(DETAIL_JS)


def test_detail_js_hat_nachtrag_formular():
    js_quelle = lies(DETAIL_JS)
    assert '"nachtrag-formular"' in js_quelle
    assert '"nachtrag-text"' in js_quelle
    assert '"nachtrag-fehler"' in js_quelle
    assert "addEventListener(\"submit\"" in js_quelle


def test_detail_js_hat_owner_umschalter():
    js_quelle = lies(DETAIL_JS)
    assert '"detail-owner"' in js_quelle
    assert "OWNER_WERTE" in js_quelle


def test_detail_js_zeigt_status_als_marke():
    js_quelle = lies(DETAIL_JS)
    assert '"status"' in js_quelle
    assert "status--klarung" in js_quelle
    assert "status--geschlossen" in js_quelle


def test_detail_js_laedt_nach_schreiben_neu():
    # Nach POST wird der gespeicherte Stand erneut geladen (Sofortanzeige/Persistenz).
    js_quelle = lies(DETAIL_JS)
    treffer = re.search(r'postJson\("/api/nachtrag"[\s\S]{0,600}?ladeDetail\(', js_quelle)
    assert treffer, "Nachtrag-Handler lädt die Datei nach dem Speichern nicht neu"


def test_detail_js_meldet_erfolg():
    js_quelle = lies(DETAIL_JS)
    assert "zeigeMeldung(NACHRAG_ERFOLG)" in js_quelle
    assert "zeigeMeldung(erfolgsmeldung)" in js_quelle
    assert re.search(r"speichereMeta\([^)]*OWNER_ERFOLG\)", js_quelle)
    assert re.search(r"speichereMeta\([^)]*STATUS_ERFOLG\)", js_quelle)


def test_detail_js_hat_zurueck_link():
    js_quelle = lies(DETAIL_JS)
    assert '"#/uebersicht"' in js_quelle


def test_detail_js_fragt_ohne_cache_ab():
    # ``cache: "no-store"`` kommt zentral aus api.js und gilt damit auch hier.
    assert 'cache: "no-store"' in lies(API_JS)


# --- Reine Logik über Node -------------------------------------------------


@ohne_node
def test_status_knoepfe_sind_genau_klarung_und_geschlossen():
    assert js("detail.STATUS_KNOEPFE") == ERLAUBTE_STATUS_KNOEPFE


@ohne_node
@pytest.mark.parametrize("verboten", ["Offen", "In Arbeit", "Testing", "Dokumentation"])
def test_status_knoepfe_ohne_pipeline_status(verboten):
    assert verboten not in js("detail.STATUS_KNOEPFE")


@ohne_node
def test_parse_ueberschrift_und_absatz():
    bloecke = js("detail.parseMarkdown('# Ziel\\n\\nEin Absatz.')")
    assert bloecke == [
        {"art": "ueberschrift", "ebene": 1, "text": "Ziel"},
        {"art": "absatz", "text": "Ein Absatz."},
    ]


@ohne_node
def test_parse_absatz_ueber_mehrere_zeilen():
    bloecke = js("detail.parseMarkdown('Erste Zeile\\nzweite Zeile')")
    assert bloecke == [{"art": "absatz", "text": "Erste Zeile zweite Zeile"}]


@ohne_node
def test_parse_ungeordnete_liste():
    bloecke = js("detail.parseMarkdown('- eins\\n- zwei')")
    assert bloecke == [{"art": "liste", "geordnet": False, "eintraege": ["eins", "zwei"]}]


@ohne_node
def test_parse_geordnete_liste():
    bloecke = js("detail.parseMarkdown('1. eins\\n2. zwei')")
    assert bloecke == [{"art": "liste", "geordnet": True, "eintraege": ["eins", "zwei"]}]


@ohne_node
def test_parse_getrennte_listen():
    bloecke = js("detail.parseMarkdown('- eins\\n\\n1. zwei')")
    assert [block["geordnet"] for block in bloecke] == [False, True]


@ohne_node
def test_parse_codeblock():
    bloecke = js("detail.parseMarkdown('```python\\nprint(1)\\n```')")
    assert bloecke == [{"art": "code", "text": "print(1)"}]


@ohne_node
def test_parse_blockquote():
    bloecke = js("detail.parseMarkdown('> Zeile eins\\n> Zeile zwei')")
    assert bloecke == [{"art": "zitat", "text": "Zeile eins\nZeile zwei"}]


@ohne_node
def test_parse_nachtrag_marker_als_zitat():
    bloecke = js(
        "detail.parseMarkdown('> **Nachtrag (Mensch, 2026-11-14):** Bitte prüfen')",
    )
    assert bloecke == [
        {
            "art": "zitat",
            "text": "**Nachtrag (Mensch, 2026-11-14):** Bitte prüfen",
        }
    ]


@ohne_node
def test_parse_html_bleibt_text():
    bloecke = js(
        "detail.parseMarkdown('<script>alert(1)</script>')",
    )
    assert bloecke == [{"art": "absatz", "text": "<script>alert(1)</script>"}]


@ohne_node
def test_parse_leer_und_crlf():
    assert js("detail.parseMarkdown('')") == []
    assert js("detail.parseMarkdown(null)") == []
    assert js("detail.parseMarkdown('# A\\r\\n\\r\\ntext')") == [
        {"art": "ueberschrift", "ebene": 1, "text": "A"},
        {"art": "absatz", "text": "text"},
    ]


@ohne_node
def test_meta_payload_nur_pfad():
    assert js("detail.erstelleMetaPayload('aufgaben/a1.md', {})") == {"path": "aufgaben/a1.md"}


@ohne_node
def test_meta_payload_laesst_leere_felder_weg():
    assert js("detail.erstelleMetaPayload('a.md', { owner: '', status: '   ' })") == {
        "path": "a.md"
    }


@ohne_node
def test_meta_payload_nimmt_einzelwerte():
    assert js("detail.erstelleMetaPayload('a.md', { owner: 'ai' })") == {
        "path": "a.md",
        "owner": "ai",
    }
    assert js("detail.erstelleMetaPayload('a.md', { status: 'Klarung' })") == {
        "path": "a.md",
        "status": "Klarung",
    }


@ohne_node
def test_meta_payload_trimmt_werte():
    assert js("detail.erstelleMetaPayload('a.md', { owner: '  mensch  ' })") == {
        "path": "a.md",
        "owner": "mensch",
    }


@ohne_node
def test_nachtrag_payload_leer_ist_null():
    assert js("detail.erstelleNachtragPayload('a.md', '   ')") is None
    assert js("detail.erstelleNachtragPayload('a.md', '')") is None


@ohne_node
def test_nachtrag_payload_trimmt():
    assert js("detail.erstelleNachtragPayload('a.md', '  Text  ')") == {
        "path": "a.md",
        "text": "Text",
    }


@ohne_node
def test_status_kommt_aus_ui_status():
    # A35: Der JS-Spiegel ist entfernt; der Server liefert den UI-Status.
    assert js("detail.ermittleStatus({ ui_status: 'In Arbeit', hinweis: null })") == {
        "status": "In Arbeit",
        "hinweis": None,
    }
    assert js("detail.ermittleStatus({ ui_status: 'Klarung' })")["status"] == "Klarung"
    assert js("detail.ermittleStatus({ ui_status: 'Geschlossen' })")["status"] == "Geschlossen"


@ohne_node
def test_status_ohne_server_feld_ist_offen():
    assert js("detail.ermittleStatus({})") == {"status": "Offen", "hinweis": None}
    # ``task_status`` wird ohne Server-Ableitung nicht mehr interpretiert.
    assert js("detail.ermittleStatus({ task_status: 'in Umsetzung' })") == {
        "status": "Offen",
        "hinweis": None,
    }


@ohne_node
def test_status_nimmt_ui_status_feld():
    assert js("detail.ermittleStatus({ ui_status: 'Geschlossen' })") == {
        "status": "Geschlossen",
        "hinweis": None,
    }


@ohne_node
def test_status_unbekannt_bleibt_offen_mit_hinweis():
    assert js("detail.ermittleStatus({ ui_status: 'Offen', hinweis: 'kaputt' })") == {
        "status": "Offen",
        "hinweis": "kaputt",
    }


@ohne_node
def test_owner_default_vor_rohem_frontmatter():
    """Der Server löst `owner` bereits in `owner_default` auf (R3).

    Die Werte müssen sich unterscheiden, sonst pinnt der Test keinen Vorrang:
    bei Gleichstand liefert jede Reihenfolge dasselbe Ergebnis. Das rohe
    `frontmatter.owner` ist nur der Altantwort-Fallback.
    """
    assert (
        js(
            "detail.ermittleOwner({ owner_default: 'ai',"
            " frontmatter: { owner: 'mensch', task_status: 'in Umsetzung' } })"
        )
        == "ai"
    )
    assert (
        js(
            "detail.ermittleOwner({ owner_default: 'mensch',"
            " frontmatter: { owner: 'ai', task_status: 'in Umsetzung' } })"
        )
        == "mensch"
    )


@ohne_node
def test_owner_default_aus_server():
    assert js("detail.ermittleOwner({ owner_default: 'mensch' })") == "mensch"
    assert js("detail.ermittleOwner({ owner_default: 'ai' })") == "ai"
    assert js("detail.ermittleOwner({ owner_default: null })") is None


@ohne_node
def test_owner_ohne_angabe_ist_null():
    assert js("detail.ermittleOwner({})") is None


# --- UI-Läufe in Node (Mini-DOM + fetch-Proxy) ----------------------------

UI_UMGEBUNG = r"""
// Fehler-/Erfolgsbereich und Detail-Container wie in index.html.
const fehler = document.createElement("div");
fehler.id = "fehler";
fehler.hidden = true;
const meldung = document.createElement("div");
meldung.id = "meldung";
meldung.hidden = true;
const ziel = document.createElement("div");
ziel.id = "detail";

// Sperrzustand der Bedienelemente (A12-2): sichtbar während laufender Requests.
function gesperrtZustand() {
  const alle = ziel.alleKnoten();
  const absenden = alle.find((knoten) => knoten.type === "submit");
  return {
    absenden: Boolean(absenden && absenden.disabled),
    status: alle
      .filter((knoten) => knoten.dataset.status)
      .map((knoten) => Boolean(knoten.disabled)),
  };
}

function zustand() {
  const alle = ziel.alleKnoten();
  const marke = alle.find((knoten) => knoten.classList.contains("status"));
  return {
    statusMarke: marke ? marke.textContent : null,
    aktiv: alle
      .filter((knoten) => knoten.dataset.status && knoten.classList.contains("knopf--primaer"))
      .map((knoten) => knoten.dataset.status),
    gesperrt: gesperrtZustand(),
  };
}

// fetch-Proxy an den echten Server; mit VERBOTENER_STATUS wird der Status im
// POST /api/meta ersetzt und so die 403 erzwungen (T10).
const echtesFetch = globalThis.fetch;
const anfragen = [];

globalThis.fetch = async (pfad, optionen = {}) => {
  const anfrageZiel = new URL(String(pfad), BASIS);
  const methode = optionen.method || "GET";
  const aufzeichnung = {
    methode,
    pfad: anfrageZiel.pathname,
    status: null,
    payload: null,
    gesperrt: methode === "GET" ? null : gesperrtZustand(),
  };
  let koerper = optionen.body;
  if (methode !== "GET" && koerper !== undefined) {
    aufzeichnung.payload = JSON.parse(koerper);
    if (VERBOTENER_STATUS && anfrageZiel.pathname === "/api/meta") {
      aufzeichnung.payload.status = VERBOTENER_STATUS;
      koerper = JSON.stringify(aufzeichnung.payload);
    }
  }
  const antwort = await echtesFetch(anfrageZiel, { ...optionen, body: koerper });
  aufzeichnung.status = antwort.status;
  anfragen.push(aufzeichnung);
  return antwort;
};
"""

SZENARIO_403 = r"""
await detail.ladeDetail({ unterpunkt: DATEI });
const klarung = ziel.alleKnoten().find((knoten) => knoten.dataset.status === "Klarung");
const vorher = zustand();

await klarung.ausloesen("click");

console.log(JSON.stringify({
  anfragen,
  fehler: { sichtbar: !fehler.hidden, text: fehler.textContent },
  meldung: { sichtbar: !meldung.hidden, text: meldung.textContent },
  vorher,
  nachher: zustand(),
  dateiLadungen: anfragen.filter((a) => a.methode === "GET" && a.pfad === "/api/file").length,
}));
"""

SZENARIO_DOPPELT_ABSENDEN = r"""
await detail.ladeDetail({ unterpunkt: DATEI });
document.getElementById("nachtrag-text").value = "Bitte prüfen.";
const formular = document.getElementById("nachtrag-formular");

// Zweimal schnell hintereinander — wie ein Doppelklick, nur ohne die
// browserseitige Klick-Unterdrückung (strengerer Fall).
const erstes = formular.ausloesen("submit");
const zweites = formular.ausloesen("submit");
await Promise.all([erstes, zweites]);

console.log(JSON.stringify({
  anfragen,
  nachher: zustand(),
}));
"""

SZENARIO_DOPPELKLICK_STATUS = r"""
await detail.ladeDetail({ unterpunkt: DATEI });
const klarung = ziel.alleKnoten().find((knoten) => knoten.dataset.status === "Klarung");

const erstes = klarung.ausloesen("click");
const zweites = klarung.ausloesen("click");
await Promise.all([erstes, zweites]);

console.log(JSON.stringify({
  anfragen,
  nachher: zustand(),
}));
"""

SZENARIO_LEERER_NACHTRAG = r"""
await detail.ladeDetail({ unterpunkt: DATEI });
const eingabe = document.getElementById("nachtrag-text");
eingabe.value = "   ";
const formular = document.getElementById("nachtrag-formular");

await formular.ausloesen("submit");

const fehlerFeld = document.getElementById("nachtrag-fehler");
console.log(JSON.stringify({
  anfragen,
  feld: { sichtbar: !fehlerFeld.hidden, text: fehlerFeld.textContent },
  eingabe: eingabe.value,
}));
"""


def ui_lauf(basis: str, szenario: str, verbotener_status: str | None = None) -> dict:
    """Spielt ein UI-Szenario in Node gegen den echten Server unter ``basis`` aus."""
    skript = (
        f"import * as detail from {json.dumps(DETAIL_JS.as_uri())};\n"
        + MINI_DOM
        + f"const BASIS = {json.dumps(basis)};\n"
        + f"const DATEI = {json.dumps(T10_DATEI)};\n"
        + f"const VERBOTENER_STATUS = {json.dumps(verbotener_status)};\n"
        + UI_UMGEBUNG
        + szenario
    )
    return node_ausfuehren(skript)


# --- A12-3: unbekannter owner --------------------------------------------

# Feste Dateiantwort ohne Server: hier zählt nur, was die Detailansicht zeigt.
UI_STAB_OHNE_SERVER = r"""
// Fehler-/Erfolgsbereich und Detail-Container wie in index.html.
const fehler = document.createElement("div");
fehler.id = "fehler";
fehler.hidden = true;
const meldung = document.createElement("div");
meldung.id = "meldung";
meldung.hidden = true;
const ziel = document.createElement("div");
ziel.id = "detail";

const anfragen = [];
globalThis.fetch = async (pfad, optionen = {}) => {
  anfragen.push({
    methode: optionen.method || "GET",
    pfad: String(pfad),
    payload: typeof optionen.body === "string" ? JSON.parse(optionen.body) : null,
  });
  return {
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    text: async () => JSON.stringify(ANTWORT),
  };
};
"""

UNBEKANNTER_OWNER_DATEI = {
    "markdown": "# Datei\n",
    "frontmatter": {"title": "A1", "type": "aufgabe", "owner": "bot"},
}


def ui_lauf_ohne_server(datei: dict, ablauf: str) -> dict:
    """Spielt einen Ablauf im Mini-DOM mit fester Dateiantwort aus (kein Server)."""
    skript = (
        f"import * as detail from {json.dumps(DETAIL_JS.as_uri())};\n"
        + MINI_DOM
        + f"const ANTWORT = {json.dumps(datei, ensure_ascii=False)};\n"
        + UI_STAB_OHNE_SERVER
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


@ohne_node
def test_a12_3_unbekannter_owner_wird_als_unbekannt_angezeigt_und_gemeldet():
    ergebnis = ui_lauf_ohne_server(
        UNBEKANNTER_OWNER_DATEI,
        "await detail.ladeDetail({ unterpunkt: 'aufgaben/a1.md' });\n"
        "const auswahl = document.getElementById('detail-owner');\n"
        "const hinweis = document.getElementById('detail-owner-hinweis');\n"
        "return {\n"
        "  wert: auswahl.value,\n"
        "  optionen: auswahl.kinder.map((o) => ({ wert: o.value, text: o.textContent })),\n"
        "  hinweis: hinweis ? hinweis.textContent : null,\n"
        "};",
    )
    # Fail-loud: der unbekannte Wert wird benannt statt still auf „—" zu fallen.
    assert ergebnis["wert"] == "bot"
    assert {"wert": "bot", "text": "bot (unbekannt)"} in ergebnis["optionen"]
    assert any(option["text"] == "—" for option in ergebnis["optionen"])
    assert ergebnis["hinweis"] is not None
    assert "bot" in ergebnis["hinweis"]
    assert "unbekannt" in ergebnis["hinweis"]


@ohne_node
def test_a12_3_unbekannter_owner_loest_keinen_schreibzugriff_aus():
    ergebnis = ui_lauf_ohne_server(
        UNBEKANNTER_OWNER_DATEI,
        "await detail.ladeDetail({ unterpunkt: 'aufgaben/a1.md' });\n"
        "const auswahl = document.getElementById('detail-owner');\n"
        "auswahl.value = 'kaputt';\n"
        "await auswahl.ausloesen('change');\n"
        "return {\n"
        "  posts: anfragen.filter((a) => a.methode === 'POST').length,\n"
        "  wert: auswahl.value,\n"
        "};",
    )
    assert ergebnis["posts"] == 0
    assert ergebnis["wert"] == "bot"  # Rückfall auf den Anzeigewert


@ohne_node
def test_a12_3_bekannter_owner_ohne_unbekannt_hinweis():
    datei = {"markdown": "# Datei\n", "frontmatter": {"title": "A1", "owner": "mensch"}}
    ergebnis = ui_lauf_ohne_server(
        datei,
        "await detail.ladeDetail({ unterpunkt: 'aufgaben/a1.md' });\n"
        "const auswahl = document.getElementById('detail-owner');\n"
        "return {\n"
        "  wert: auswahl.value,\n"
        "  optionen: auswahl.kinder.map((o) => o.value),\n"
        "  hinweis: document.getElementById('detail-owner-hinweis') !== null,\n"
        "};",
    )
    assert ergebnis["wert"] == "mensch"
    assert ergebnis["optionen"] == ["", "mensch", "ai"]
    assert ergebnis["hinweis"] is False


@pytest.fixture()
def app_server(bundle):
    """Echter HTTP-Server auf einem freien Port für die UI-Läufe."""
    httpd = make_server("127.0.0.1", 0, server.create_app(bundle), threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


# --- A28-K3-Rest: Trenner zwischen Zustand und Knopf sind Textknoten -----


@ohne_node
def test_a28_k3_trenner_aufgaben_freigabe_ist_textknoten():
    ergebnis = ui_lauf_ohne_server(
        {
            "markdown": "# Ziel\n",
            "frontmatter": {"title": "A1", "type": "Task"},
            "freigabe": False,
        },
        "await detail.ladeDetail({ unterpunkt: 'aufgaben/a1.md' });\n"
        "const dd = document.getElementById('detail-freigabe').parentElement;\n"
        "return {\n"
        "  kinder: dd.kinder.map((k) => ({ marke: k.marke, text: k.textContent })),\n"
        "  gesamt: dd.textContent,\n"
        "};",
    )
    # Der Abstand ist ein echter Textknoten — kein leeres span-Element mehr.
    assert ergebnis["kinder"] == [
        {"marke": "span", "text": "Nicht freigegeben"},
        {"marke": "#text", "text": " "},
        {"marke": "button", "text": "Freigeben"},
    ]
    assert ergebnis["gesamt"] == "Nicht freigegeben Freigeben"


@ohne_node
def test_a28_k3_trenner_wellen_freigabe_sind_textknoten():
    ergebnis = ui_lauf_ohne_server(
        {
            "markdown": "# Ziel\n",
            "frontmatter": {"title": "Welle 1", "type": "Welle"},
            "freigabe": False,
        },
        "await detail.ladeDetail({ unterpunkt: 'wellen/w1.md' });\n"
        "const dd = document.getElementById('detail-welle-freigabe').parentElement;\n"
        "return {\n"
        "  kinder: dd.kinder.map((k) => ({ marke: k.marke, text: k.textContent })),\n"
        "  gesamt: dd.textContent,\n"
        "};",
    )
    assert ergebnis["kinder"] == [
        {"marke": "#text", "text": " "},
        {"marke": "span", "text": "nicht freigegeben (Standard)"},
        {"marke": "#text", "text": " "},
        {"marke": "button", "text": "Welle freigeben"},
    ]
    assert ergebnis["gesamt"] == " nicht freigegeben (Standard) Welle freigeben"


# --- T10: 403-Pfad (verbotener Status) -----------------------------------


def _sha256(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def _bestand(wurzel: Path) -> list[str]:
    return sorted(pfad.relative_to(wurzel).as_posix() for pfad in wurzel.rglob("*"))


@ohne_node
def test_t10_verbotener_status_403_zeigt_fehler_ohne_zustandswechsel(bundle, app_server):
    datei = bundle / T10_DATEI
    inhalt_vorher = _sha256(datei)
    bestand_vorher = _bestand(bundle)

    ergebnis = ui_lauf(app_server, SZENARIO_403, T10_VERBOTENER_STATUS)

    # Der Proxy hat den verbotenen Status wirklich geschickt und 403 erzwungen.
    meta = [
        eintrag
        for eintrag in ergebnis["anfragen"]
        if eintrag["methode"] == "POST" and eintrag["pfad"] == "/api/meta"
    ]
    assert meta, "UI hat /api/meta nicht aufgerufen"
    assert meta[0]["payload"]["status"] == T10_VERBOTENER_STATUS
    assert meta[0]["status"] == 403

    # Fail-loud wie im Fehlerzustand-Design (A11/A12): sichtbar und verständlich.
    assert ergebnis["fehler"]["sichtbar"] is True
    assert "Status" in ergebnis["fehler"]["text"]

    # Kein falscher Zustand: kein Erfolg, Ansicht ohne Zustandswechsel, Datei unverändert.
    assert ergebnis["meldung"] == {"sichtbar": False, "text": ""}
    assert ergebnis["nachher"] == ergebnis["vorher"]
    assert ergebnis["nachher"]["statusMarke"] == "Offen"
    assert ergebnis["nachher"]["aktiv"] == []
    assert ergebnis["dateiLadungen"] == 1
    assert _sha256(datei) == inhalt_vorher
    assert _bestand(bundle) == bestand_vorher


# --- A12-2: Sperren bei laufenden Requests -------------------------------


@ohne_node
def test_a12_2_doppeltes_absenden_erzeugt_genau_einen_eintrag(bundle, app_server):
    datei = bundle / T10_DATEI

    ergebnis = ui_lauf(app_server, SZENARIO_DOPPELT_ABSENDEN)

    schreibungen = [
        eintrag
        for eintrag in ergebnis["anfragen"]
        if eintrag["methode"] == "POST" and eintrag["pfad"] == "/api/nachtrag"
    ]
    assert len(schreibungen) == 1
    assert schreibungen[0]["gesperrt"]["absenden"] is True
    assert ergebnis["nachher"]["gesperrt"]["absenden"] is False
    assert datei.read_text(encoding="utf-8").count("**Nachtrag (") == 1


@ohne_node
def test_a12_2_doppelklick_status_schreibt_nur_einmal(bundle, app_server):
    ergebnis = ui_lauf(app_server, SZENARIO_DOPPELKLICK_STATUS)

    schreibungen = [
        eintrag
        for eintrag in ergebnis["anfragen"]
        if eintrag["methode"] == "POST" and eintrag["pfad"] == "/api/meta"
    ]
    assert len(schreibungen) == 1
    assert schreibungen[0]["gesperrt"]["status"] == [True, True]
    assert ergebnis["nachher"]["gesperrt"]["status"] == [False, False]


# --- A12-T4-Hardening: Fehlertext bei leerem Nachtrag --------------------


@ohne_node
def test_a12_t4_leerer_nachtrag_zeigt_fehlertext_ohne_schreibzugriff(bundle, app_server):
    datei = bundle / T10_DATEI
    vorher = _sha256(datei)

    ergebnis = ui_lauf(app_server, SZENARIO_LEERER_NACHTRAG)

    # DOM-Regression: der sichtbare Fehlertext hängt am Feld, nicht nur die Payload-Logik.
    assert ergebnis["feld"] == {"sichtbar": True, "text": "Bitte einen Nachtrag eingeben."}
    assert ergebnis["eingabe"] == "   "  # Eingabe bleibt für die Korrektur stehen

    schreibungen = [
        eintrag
        for eintrag in ergebnis["anfragen"]
        if eintrag["methode"] == "POST" and eintrag["pfad"] == "/api/nachtrag"
    ]
    assert schreibungen == []
    assert _sha256(datei) == vorher


# --- A38-K2: Ankersuche bleibt im Detailbereich ---------------------------

# Seiten-Gerüst wie in index.html; die festen IDs stehen im Baum vor dem
# Detailbereich. `getElementById` liefert damit bei einer Kollision das
# Seitenelement — genau der Fall, den die bereichsgebundene Suche abfängt.
ANKER_UMGEBUNG = r"""
const seite = document.createElement("div");
const seitenFehler = document.createElement("div");
seitenFehler.id = "fehler";
seitenFehler._imDokument = true;
const meldung = document.createElement("div");
meldung.id = "meldung";
meldung._imDokument = true;
const ziel = document.createElement("div");
ziel.id = "detail";
ziel._imDokument = true;
seite.append(seitenFehler, meldung, ziel);
seite._imDokument = true;

// Browser-Semantik bei doppelten IDs: das erste Element im Baum gewinnt.
document.getElementById = (id) => {
  const treffer = sammle(seite).filter((knoten) => knoten !== seite && knoten.id === id);
  return treffer[0] ?? null;
};

// Mini-DOM kennt nur Klassen-Selektoren; hier kommt der Attribut-Selektor
// hinzu, den `springeZuAnker` für die Suche im Detailbereich nutzt.
Knoten.prototype.querySelectorAll = function (auswahl) {
  const treffer = /^\[id="([^"]+)"\]$/.exec(auswahl);
  if (!treffer) return [];
  return sammle(this).filter((knoten) => knoten !== this && knoten.id === treffer[1]);
};

globalThis.gescrollt = [];
Knoten.prototype.scrollIntoView = function () {
  gescrollt.push(this.id);
};

globalThis.fetch = async () => ({
  ok: true,
  status: 200,
  headers: { get: () => "application/json" },
  text: async () => JSON.stringify({ frontmatter: {}, markdown: `# ${SLUG}\n\nText.\n` }),
});
"""


def anker_lauf(slug: str) -> dict:
    """Lädt ``log.md#<slug>``; die Überschrift trägt exakt diesen Slug als ID."""
    skript = (
        MINI_DOM
        + f"const SLUG = {json.dumps(slug)};\n"
        + ANKER_UMGEBUNG
        + f'import * as detail from {json.dumps(DETAIL_JS.as_uri())};\n'
        + "await detail.ladeDetail({ unterpunkt: `log.md#${SLUG}` });\n"
        + "const kopf = sammle(ziel).find((knoten) => knoten.marke === 'h1') ?? null;\n"
        + "console.log(JSON.stringify({\n"
        + "  gescrollt,\n"
        + "  kopf: kopf ? kopf.id : null,\n"
        + "  kopfKlasse: Boolean(kopf && kopf.classList.contains('anker-ziel')),\n"
        + "  kopfTabindex: kopf ? kopf.getAttribute('tabindex') : null,\n"
        + "  fokusIstKopf: document.activeElement === kopf,\n"
        + "  seitenKlasse: seitenFehler.classList.contains('anker-ziel'),\n"
        + "  seitenTabindex: seitenFehler.getAttribute('tabindex'),\n"
        + "  zielKlasse: ziel.classList.contains('anker-ziel'),\n"
        + "}));\n"
    )
    return node_ausfuehren(skript)


@ohne_node
@pytest.mark.parametrize("slug", ["fehler", "detail"])
def test_a38_k2_anker_slug_kollidiert_nicht_mit_seiten_ids(slug):
    ergebnis = anker_lauf(slug)

    # Der Sprung trifft die Überschrift — nicht das Seitengerüst.
    assert ergebnis["kopf"] == slug
    assert ergebnis["kopfKlasse"] is True
    assert ergebnis["kopfTabindex"] == "-1"
    assert ergebnis["fokusIstKopf"] is True
    assert ergebnis["gescrollt"] == [slug]
    # Feste Seiten-IDs bleiben unangetastet.
    assert ergebnis["seitenKlasse"] is False
    assert ergebnis["seitenTabindex"] is None
    assert ergebnis["zielKlasse"] is False


@ohne_node
def test_a38_k2_anker_ohne_kollision_springt_wie_bisher():
    ergebnis = anker_lauf("log")

    assert ergebnis["kopf"] == "log"
    assert ergebnis["kopfKlasse"] is True
    assert ergebnis["gescrollt"] == ["log"]
    assert ergebnis["seitenKlasse"] is False
