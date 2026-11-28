"""Prüfungen für die Formulare „Aufgabe" und „Welle" (A13).

Die UI-Szenarien T1–T8 spielt der ``tester`` mit dem Moli-Browser durch; hier
werden ``formulare.js`` und seine Verdrahtung ohne Browser geprüft. Die reine
Validierungs-/Payload-Logik läuft über Node, das Formularverhalten (Inline-
Fehler, Doppelklickschutz, Erfolgsanzeige) über einen minimalen DOM-Stab und
das Anlegen über die HTTP-API mit den Formular-Payloads — jeweils ohne neue
Abhängigkeiten und ausschließlich gegen ``tmp_path``-Bundles.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
FORMULARE_JS = STATIC_DIR / "js" / "formulare.js"
APP_JS = STATIC_DIR / "js" / "app.js"
API_JS = STATIC_DIR / "js" / "api.js"
STYLE = STATIC_DIR / "style.css"
NODE = shutil.which("node")

ohne_node = pytest.mark.skipif(NODE is None, reason="node nicht verfügbar")

# Werte-Whitelists der Anlege-API (A4/A5/A9); Spiegel der Formular-Auswahlen.
PRIORITAETEN = ["hoch", "mittel", "niedrig"]
WELLEN_STATUS_WERTE = ["Klarung", "Offen", "In Arbeit", "Testing", "Dokumentation", "Geschlossen"]
OWNER_WERTE = ["mensch", "ai"]


def lies(pfad: Path) -> str:
    assert pfad.is_file(), f"{pfad} fehlt"
    return pfad.read_text(encoding="utf-8")


def js(ausdruck: str, daten=None):
    """Wertet einen Ausdruck im Kontext von ``formulare.js`` über Node aus."""
    assert NODE is not None
    skript = (
        f"import * as formulare from {json.dumps(FORMULARE_JS.as_uri())};\n"
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


# Minimaler DOM-Stab: deckt genau die API ab, die ``formulare.js`` und
# ``api.js`` nutzen (createElement, getElementById, textContent, classList,
# append/replaceChildren, addEventListener/dispatch, focus, attribute).
DOM_STAB = r"""
const registry = new Map();
function element(tag) {
  const el = {
    tagName: String(tag).toUpperCase(),
    childNodes: [],
    attributes: {},
    listeners: {},
    dataset: {},
    _klassen: new Set(),
    _text: "",
    hidden: false,
    disabled: false,
    value: "",
  };
  Object.defineProperty(el, "id", {
    get: () => el._id ?? "",
    set: (wert) => { el._id = String(wert); registry.set(el._id, el); },
  });
  Object.defineProperty(el, "textContent", {
    get: () => (el.childNodes.length === 0
      ? el._text
      : el.childNodes.map((kind) => kind.textContent ?? String(kind)).join("")),
    set: (wert) => { el._text = String(wert); el.childNodes = []; },
  });
  Object.defineProperty(el, "className", {
    get: () => [...el._klassen].join(" "),
    set: (wert) => { el._klassen = new Set(String(wert).split(/\s+/).filter(Boolean)); },
  });
  el.classList = {
    add: (...k) => k.forEach((n) => el._klassen.add(n)),
    remove: (...k) => k.forEach((n) => el._klassen.delete(n)),
    toggle: (n) => (el._klassen.has(n) ? el._klassen.delete(n) : el._klassen.add(n)),
    contains: (n) => el._klassen.has(n),
  };
  el.append = (...knoten) => { el.childNodes.push(...knoten); };
  el.replaceChildren = (...knoten) => { el.childNodes = [...knoten]; el._text = ""; };
  el.setAttribute = (name, wert) => { el.attributes[name] = String(wert); };
  el.getAttribute = (name) => (name in el.attributes ? el.attributes[name] : null);
  el.addEventListener = (typ, handler) => { (el.listeners[typ] ??= []).push(handler); };
  el.focus = () => { dokument.fokus = el; };
  el.dispatch = (typ, ereignis = {}) => {
    const geschehen = { type: typ, target: el, preventDefault() {}, ...ereignis };
    return (el.listeners[typ] ?? []).map((handler) => handler(geschehen));
  };
  return el;
}
const dokument = {
  createElement: element,
  getElementById: (id) => registry.get(String(id)) ?? null,
  addEventListener() {},
  readyState: "complete",
};
globalThis.document = dokument;
for (const id of ["fehler", "meldung"]) {
  const banner = element("div");
  banner.id = id;
  banner.hidden = true;
}
// Container aus index.html (A10); ohne sie prüfen wir die Robustheit.
if (__CONTAINER__) {
  for (const id of ["formular-aufgabe", "formular-welle"]) {
    const bereich = element("div");
    bereich.id = id;
  }
}

// Fetch-Stab: protokolliert jeden Aufruf und liefert canned JSON-Antworten.
const aufrufe = [];
const antworten = __ANTWORTEN__;
globalThis.fetch = async (pfad, optionen = {}) => {
  const eintrag = { pfad: String(pfad), methode: optionen.method ?? "GET", koerper: null };
  if (typeof optionen.body === "string") eintrag.koerper = JSON.parse(optionen.body);
  aufrufe.push(eintrag);
  const vorgabe = antworten[String(pfad)] ?? antworten["*"] ?? { status: 200, koerper: null };
  return {
    ok: vorgabe.status < 400,
    status: vorgabe.status,
    headers: { get: () => "application/json" },
    text: async () => JSON.stringify(vorgabe.koerper ?? null),
  };
};
if (typeof AbortSignal.timeout !== "function") {
  AbortSignal.timeout = () => new AbortController().signal;
}

const bei = (id) => document.getElementById(id);
const sichtbar = (id) => document.getElementById(id)?.hidden === false;
const sammle = (el) => [el, ...(el.childNodes ?? []).flatMap(sammle)];
"""


def dom(ablauf: str, antworten: dict | None = None, container: bool = True):
    """Führt einen Ablauf im DOM-Stab aus und liefert dessen JSON-Ergebnis."""
    assert NODE is not None
    skript = (
        DOM_STAB.replace("__ANTWORTEN__", json.dumps(antworten or {}, ensure_ascii=False))
        .replace("__CONTAINER__", "true" if container else "false")
        + f"\nimport * as formulare from {json.dumps(FORMULARE_JS.as_uri())};\n"
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
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


def test_formulare_js_vorhanden():
    assert FORMULARE_JS.is_file()


def test_app_js_importiert_formulare():
    assert re.search(r'from\s+"\./formulare\.js"', lies(APP_JS))


def test_app_js_verdrahtet_formulare():
    js_quelle = lies(APP_JS)
    assert "initialisiereFormulare(" in js_quelle
    assert "ladeAufgabenAnsicht" in js_quelle
    assert "ladeWellenAnsicht" in js_quelle


@pytest.mark.parametrize("endpunkt", ["/api/task", "/api/welle", "/api/wellen"])
def test_formulare_js_nutzt_endpunkt(endpunkt):
    assert endpunkt in lies(FORMULARE_JS)


def test_formulare_js_nutzt_api_helper():
    js_quelle = lies(FORMULARE_JS)
    assert re.search(r"import\s*\{[^}]*\bpostJson\b[^}]*\}\s*from\s*\"\./api\.js\"", js_quelle)
    assert re.search(r"import\s*\{[^}]*\bgetJson\b[^}]*\}\s*from\s*\"\./api\.js\"", js_quelle)


def test_formulare_js_rendert_ohne_innerhtml():
    js_quelle = lies(FORMULARE_JS)
    assert "textContent" in js_quelle
    assert "innerHTML" not in js_quelle


@pytest.mark.parametrize(
    "senke",
    ["outerHTML", "insertAdjacentHTML", "document.write(", "eval("],
)
def test_formulare_js_vermeidet_weitere_html_senken(senke):
    assert senke not in lies(FORMULARE_JS)


def test_formulare_js_hat_submit_handler():
    assert 'addEventListener("submit"' in lies(FORMULARE_JS)


def test_formulare_js_doppelklickschutz_deaktiviert_knopf():
    js_quelle = lies(FORMULARE_JS)
    assert ".disabled = true" in js_quelle
    assert ".disabled = false" in js_quelle


@pytest.mark.parametrize("container_id", ["formular-aufgabe", "formular-welle"])
def test_formulare_js_verwendet_container_id(container_id):
    assert f'"{container_id}"' in lies(FORMULARE_JS)


def test_style_css_formular_klassen():
    css = lies(STYLE)
    assert ".formular-ueberschrift" in css
    assert ".formular-erfolg" in css


# --- Reine Logik über Node -------------------------------------------------


@ohne_node
def test_teile_akzeptanz_drei_zeilen():
    assert js("formulare.teileAkzeptanz(daten)", "eins\nzwei\ndrei") == ["eins", "zwei", "drei"]


@ohne_node
def test_teile_akzeptanz_trimmt_und_laesst_leerzeilen_weg():
    assert js("formulare.teileAkzeptanz(daten)", "  a  \n\n \n b ") == ["a", "b"]


@ohne_node
def test_teile_akzeptanz_crlf_und_leer():
    assert js("formulare.teileAkzeptanz(daten)", "a\r\nb") == ["a", "b"]
    assert js("formulare.teileAkzeptanz(daten)", "") == []
    assert js("formulare.teileAkzeptanz(daten)", "\n  \n") == []
    assert js("formulare.teileAkzeptanz(daten)", None) == []
    assert js("formulare.teileAkzeptanz(daten)", 42) == []


@ohne_node
def test_aufgabe_payload_felder():
    payload = js(
        "formulare.erstelleAufgabePayload(daten)",
        {
            "titel": "A99: Neue Aufgabe",
            "ziel": "Ziel der neuen Aufgabe.",
            "akzeptanz": "Erstes Kriterium.\nZweites Kriterium.",
            "prioritaet": "hoch",
        },
    )
    assert payload == {
        "titel": "A99: Neue Aufgabe",
        "ziel": "Ziel der neuen Aufgabe.",
        "akzeptanz": ["Erstes Kriterium.", "Zweites Kriterium."],
        "prioritaet": "hoch",
    }


@ohne_node
def test_aufgabe_payload_ohne_pfadfeld():
    # R2: Slug/Kollision entstehen serverseitig; das Formular sendet kein `path`.
    payload = js(
        "formulare.erstelleAufgabePayload(daten)",
        {"titel": "T", "ziel": "Z", "akzeptanz": "a", "prioritaet": "hoch"},
    )
    assert js("Object.hasOwn(daten, 'path')", payload) is False
    assert "path" not in payload


@ohne_node
def test_aufgabe_payload_optionale_felder_nur_wenn_gesetzt():
    payload = js(
        "formulare.erstelleAufgabePayload(daten)",
        {
            "titel": "T",
            "ziel": "Z",
            "akzeptanz": "a",
            "prioritaet": "hoch",
            "welle": "wellen/w1.md",
            "user_story": "/projekt/user-stories/us-3.md",
        },
    )
    assert payload["welle"] == "wellen/w1.md"
    assert payload["user_story"] == "/projekt/user-stories/us-3.md"

    ohne = js(
        "formulare.erstelleAufgabePayload(daten)",
        {"titel": "T", "ziel": "Z", "akzeptanz": "a", "prioritaet": "hoch", "welle": "", "user_story": "  "},
    )
    assert set(ohne) == {"titel", "ziel", "akzeptanz", "prioritaet"}


@ohne_node
def test_aufgabe_payload_trimmt():
    payload = js(
        "formulare.erstelleAufgabePayload(daten)",
        {"titel": "  T  ", "ziel": "  Z  ", "akzeptanz": "  a  ", "prioritaet": "  hoch  "},
    )
    assert payload == {"titel": "T", "ziel": "Z", "akzeptanz": ["a"], "prioritaet": "hoch"}


@pytest.mark.parametrize("feld", ["titel", "ziel", "akzeptanz", "prioritaet"])
@ohne_node
def test_validiere_aufgabe_pflichtfeld_fehlt(feld):
    eingaben = {"titel": "T", "ziel": "Z", "akzeptanz": "a", "prioritaet": "hoch"}
    eingaben[feld] = ""
    pruefung = js("formulare.validiereAufgabe(daten)", eingaben)
    assert pruefung["ok"] is False
    assert feld in pruefung["fehler"]
    assert pruefung["fehler"][feld]


@ohne_node
def test_validiere_aufgabe_gueltig():
    pruefung = js(
        "formulare.validiereAufgabe(daten)",
        {"titel": "T", "ziel": "Z", "akzeptanz": "a\nb", "prioritaet": "mittel"},
    )
    assert pruefung == {"ok": True, "fehler": {}}


@ohne_node
@pytest.mark.parametrize("prioritaet", ["dringend", "Hoch", ""])
def test_validiere_aufgabe_prioritaet_ungueltig(prioritaet):
    pruefung = js(
        "formulare.validiereAufgabe(daten)",
        {"titel": "T", "ziel": "Z", "akzeptanz": "a", "prioritaet": prioritaet},
    )
    assert pruefung["ok"] is False
    assert "prioritaet" in pruefung["fehler"]


@pytest.mark.parametrize("feld", ["titel", "ziel", "status", "owner"])
@ohne_node
def test_validiere_welle_pflichtfeld_fehlt(feld):
    eingaben = {"titel": "T", "ziel": "Z", "status": "Offen", "owner": "ai"}
    eingaben[feld] = ""
    pruefung = js("formulare.validiereWelle(daten)", eingaben)
    assert pruefung["ok"] is False
    assert feld in pruefung["fehler"]
    assert pruefung["fehler"][feld]


@ohne_node
@pytest.mark.parametrize("status_wert", WELLEN_STATUS_WERTE)
def test_validiere_welle_status_gueltig(status_wert):
    pruefung = js(
        "formulare.validiereWelle(daten)",
        {"titel": "T", "ziel": "Z", "status": status_wert, "owner": "ai"},
    )
    assert pruefung == {"ok": True, "fehler": {}}


@ohne_node
@pytest.mark.parametrize("status_wert", ["In Umsetzung", "offen", "kaputt"])
def test_validiere_welle_status_ungueltig(status_wert):
    pruefung = js(
        "formulare.validiereWelle(daten)",
        {"titel": "T", "ziel": "Z", "status": status_wert, "owner": "ai"},
    )
    assert pruefung["ok"] is False
    assert "status" in pruefung["fehler"]


@ohne_node
@pytest.mark.parametrize("owner_wert", ["bot", "Mensch", ""])
def test_validiere_welle_owner_ungueltig(owner_wert):
    pruefung = js(
        "formulare.validiereWelle(daten)",
        {"titel": "T", "ziel": "Z", "status": "Offen", "owner": owner_wert},
    )
    assert pruefung["ok"] is False
    assert "owner" in pruefung["fehler"]


@ohne_node
def test_welle_payload_felder_und_kein_pfadfeld():
    payload = js(
        "formulare.erstelleWellePayload(daten)",
        {"titel": "  Welle 2: Neu  ", "ziel": "  Ziel.  ", "status": " Offen ", "owner": "ai"},
    )
    assert payload == {"titel": "Welle 2: Neu", "ziel": "Ziel.", "status": "Offen", "owner": "ai"}
    assert "path" not in payload


@ohne_node
def test_kurzkontext_enthaelt_titel_pfad_ziel():
    kontext = js(
        "formulare.erstelleKurzkontext(daten)",
        {"titel": "A99: Neue Aufgabe", "pfad": "aufgaben/a99.md", "ziel": "Ziel der Aufgabe."},
    )
    assert "Titel: A99: Neue Aufgabe" in kontext
    assert "Pfad: aufgaben/a99.md" in kontext
    assert "Ziel: Ziel der Aufgabe." in kontext


@ohne_node
def test_lese_angelegten_pfad_gueltig():
    assert js("formulare.leseAngelegtenPfad(daten)", {"path": "aufgaben/a99.md"}) == "aufgaben/a99.md"
    assert js("formulare.leseAngelegtenPfad(daten)", {"path": " wellen/w2.md "}) == "wellen/w2.md"


@ohne_node
@pytest.mark.parametrize("antwort", ["{}", "null", "[]", '{"path": 42}', '{"path": ""}', '{"pfad": "a.md"}'])
def test_lese_angelegten_pfad_unerwartet_ist_null(antwort):
    # fail-loud: unerwartete Antworten liefern keinen Pfad und werden gemeldet.
    assert js(f"formulare.leseAngelegtenPfad({antwort})") is None


@ohne_node
def test_werte_whitelists():
    assert js("formulare.PRIORITAETEN") == PRIORITAETEN
    assert js("formulare.WELLEN_STATUS_WERTE") == WELLEN_STATUS_WERTE
    assert js("formulare.OWNER_WERTE") == OWNER_WERTE


# --- Formularverhalten im DOM-Stab ----------------------------------------


def _aufgabe_ausfuellen(ergaenzung: str = "") -> str:
    return (
        'bei("aufgabe-titel").value = "A99: Neue Aufgabe";\n'
        'bei("aufgabe-ziel").value = "Ziel der neuen Aufgabe.";\n'
        'bei("aufgabe-akzeptanz").value = "Erstes Kriterium.\\nZweites Kriterium.";\n'
        'bei("aufgabe-prioritaet").value = "hoch";\n'
        + ergaenzung
        + 'const formular = bei("aufgabe-formular");\n'
    )


@ohne_node
def test_t1_aufgabe_anlegen_sendet_payload_und_laedt_liste():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        + _aufgabe_ausfuellen(
            'bei("aufgabe-welle").value = "wellen/w1.md";\n'
            'bei("aufgabe-user-story").value = "/projekt/user-stories/us-3.md";\n'
        )
        + "await Promise.all(formular.dispatch(\"submit\"));\n"
        + "return {\n"
        + "  aufrufe: aufrufe.map((a) => a.methode + \" \" + a.pfad),\n"
        + "  post: aufrufe.find((a) => a.methode === \"POST\")?.koerper ?? null,\n"
        + "  erfolg: sichtbar(\"aufgabe-erfolg\"),\n"
        + "  meldung: sichtbar(\"meldung\"),\n"
        + "  knopf: bei(\"aufgabe-anlegen\").disabled,\n"
        + "};",
        antworten={"/api/task": {"status": 200, "koerper": {"path": "aufgaben/a99-neue-aufgabe.md"}}},
    )
    assert ergebnis["post"] == {
        "titel": "A99: Neue Aufgabe",
        "ziel": "Ziel der neuen Aufgabe.",
        "akzeptanz": ["Erstes Kriterium.", "Zweites Kriterium."],
        "prioritaet": "hoch",
        "welle": "wellen/w1.md",
        "user_story": "/projekt/user-stories/us-3.md",
    }
    assert "POST /api/task" in ergebnis["aufrufe"]
    assert "GET /api/aufgaben" in ergebnis["aufrufe"]
    assert ergebnis["erfolg"] is True
    assert ergebnis["meldung"] is True
    assert ergebnis["knopf"] is False


@ohne_node
def test_t2_pflichtfeld_leer_feldfehler_ohne_eintrag():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        + _aufgabe_ausfuellen('bei("aufgabe-titel").value = "";\n')
        + "await Promise.all(formular.dispatch(\"submit\"));\n"
        + "return {\n"
        + "  fehlerText: bei(\"aufgabe-fehler-titel\").textContent,\n"
        + "  fehlerSichtbar: sichtbar(\"aufgabe-fehler-titel\"),\n"
        + "  aufrufe: aufrufe.length,\n"
        + "  erfolg: sichtbar(\"aufgabe-erfolg\"),\n"
        + "};",
        antworten={"/api/task": {"status": 200, "koerper": {"path": "aufgaben/x.md"}}},
    )
    assert ergebnis["fehlerText"]
    assert ergebnis["fehlerSichtbar"] is True
    assert ergebnis["aufrufe"] == 0
    assert ergebnis["erfolg"] is False


@ohne_node
def test_t3_akzeptanz_wird_mehrzeilig_uebergeben():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        'bei("aufgabe-titel").value = "T";\n'
        'bei("aufgabe-ziel").value = "Z";\n'
        'bei("aufgabe-akzeptanz").value = "eins\\nzwei\\ndrei";\n'
        'bei("aufgabe-prioritaet").value = "niedrig";\n'
        'const formular = bei("aufgabe-formular");\n'
        "await Promise.all(formular.dispatch(\"submit\"));\n"
        "return aufrufe.find((a) => a.methode === \"POST\")?.koerper ?? null;",
        antworten={"/api/task": {"status": 200, "koerper": {"path": "aufgaben/t.md"}}},
    )
    assert ergebnis["akzeptanz"] == ["eins", "zwei", "drei"]


@ohne_node
def test_t4_kurzkontext_ist_kopierbar_und_vollstaendig():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        + _aufgabe_ausfuellen()
        + "await Promise.all(formular.dispatch(\"submit\"));\n"
        + "const kontext = bei(\"aufgabe-kurzkontext\");\n"
        + "const links = sammle(bei(\"aufgabe-erfolg\"))\n"
        + "  .filter((k) => k.tagName === \"A\")\n"
        + "  .map((k) => ({ text: k.textContent, href: k.href }));\n"
        + "return {\n"
        + "  wert: kontext.value,\n"
        + "  readOnly: kontext.readOnly,\n"
        + "  sichtbar: sichtbar(\"aufgabe-erfolg\"),\n"
        + "  links,\n"
        + "};",
        antworten={"/api/task": {"status": 200, "koerper": {"path": "aufgaben/a99-neue-aufgabe.md"}}},
    )
    assert ergebnis["sichtbar"] is True
    assert ergebnis["readOnly"] is True
    assert "Titel: A99: Neue Aufgabe" in ergebnis["wert"]
    assert "Pfad: aufgaben/a99-neue-aufgabe.md" in ergebnis["wert"]
    assert "Ziel: Ziel der neuen Aufgabe." in ergebnis["wert"]
    assert any(link["text"] == "aufgaben/a99-neue-aufgabe.md" for link in ergebnis["links"])


@ohne_node
def test_t5_welle_anlegen_sendet_payload_und_laedt_liste():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        'bei("welle-titel").value = "Welle 2: Neu";\n'
        'bei("welle-ziel").value = "Ziel der neuen Welle.";\n'
        'bei("welle-status").value = "Offen";\n'
        'bei("welle-owner").value = "ai";\n'
        'const formular = bei("welle-formular");\n'
        "await Promise.all(formular.dispatch(\"submit\"));\n"
        "return {\n"
        "  aufrufe: aufrufe.map((a) => a.methode + \" \" + a.pfad),\n"
        "  post: aufrufe.find((a) => a.methode === \"POST\")?.koerper ?? null,\n"
        "  erfolg: sichtbar(\"welle-erfolg\"),\n"
        "};",
        antworten={"/api/welle": {"status": 200, "koerper": {"path": "wellen/welle-2-neu.md"}}},
    )
    assert ergebnis["post"] == {
        "titel": "Welle 2: Neu",
        "ziel": "Ziel der neuen Welle.",
        "status": "Offen",
        "owner": "ai",
    }
    assert "POST /api/welle" in ergebnis["aufrufe"]
    assert "GET /api/wellen" in ergebnis["aufrufe"]
    assert ergebnis["erfolg"] is True


@ohne_node
def test_t6_welle_ungueltig_feldfehler_ohne_eintrag():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        'bei("welle-titel").value = "Welle 2: Neu";\n'
        'bei("welle-ziel").value = "Ziel.";\n'
        'const formular = bei("welle-formular");\n'
        'bei("welle-status").value = "";\n'
        'bei("welle-owner").value = "";\n'
        "await Promise.all(formular.dispatch(\"submit\"));\n"
        'bei("welle-status").value = "In Umsetzung";\n'
        'bei("welle-owner").value = "bot";\n'
        "await Promise.all(formular.dispatch(\"submit\"));\n"
        "return {\n"
        "  statusFehler: bei(\"welle-fehler-status\").textContent,\n"
        "  statusSichtbar: sichtbar(\"welle-fehler-status\"),\n"
        "  ownerFehler: bei(\"welle-fehler-owner\").textContent,\n"
        "  ownerSichtbar: sichtbar(\"welle-fehler-owner\"),\n"
        "  aufrufe: aufrufe.length,\n"
        "};",
        antworten={"/api/welle": {"status": 200, "koerper": {"path": "wellen/x.md"}}},
    )
    assert ergebnis["statusFehler"]
    assert ergebnis["statusSichtbar"] is True
    assert ergebnis["ownerFehler"]
    assert ergebnis["ownerSichtbar"] is True
    assert ergebnis["aufrufe"] == 0


@ohne_node
def test_t7_doppelklick_genau_ein_request():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        + _aufgabe_ausfuellen()
        + "const erste = formular.dispatch(\"submit\");\n"
        + "const waehrend = bei(\"aufgabe-anlegen\").disabled;\n"
        + "const zweite = formular.dispatch(\"submit\");\n"
        + "await Promise.all([...erste, ...zweite]);\n"
        + "return {\n"
        + "  posts: aufrufe.filter((a) => a.methode === \"POST\").length,\n"
        + "  waehrend,\n"
        + "  nachher: bei(\"aufgabe-anlegen\").disabled,\n"
        + "};",
        antworten={"/api/task": {"status": 200, "koerper": {"path": "aufgaben/a99.md"}}},
    )
    assert ergebnis["posts"] == 1
    assert ergebnis["waehrend"] is True
    assert ergebnis["nachher"] is False


@ohne_node
@pytest.mark.parametrize("koerper", [{}, {"path": 42}, [], {"pfad": "aufgaben/a.md"}])
def test_unerwartete_antwort_ist_fail_loud(koerper):
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        + _aufgabe_ausfuellen()
        + "await Promise.all(formular.dispatch(\"submit\"));\n"
        + "return {\n"
        + "  fehler: bei(\"fehler\").textContent,\n"
        + "  fehlerSichtbar: sichtbar(\"fehler\"),\n"
        + "  erfolg: sichtbar(\"aufgabe-erfolg\"),\n"
        + "};",
        antworten={"/api/task": {"status": 200, "koerper": koerper}},
    )
    assert ergebnis["fehler"]
    assert ergebnis["fehlerSichtbar"] is True
    assert ergebnis["erfolg"] is False


@ohne_node
def test_t8_wellen_zuordnung_in_der_anzeige():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        + _aufgabe_ausfuellen('bei("aufgabe-welle").value = "wellen/w1.md";\n')
        + "await Promise.all(formular.dispatch(\"submit\"));\n"
        + "const links = sammle(bei(\"aufgabe-erfolg\"))\n"
        + "  .filter((k) => k.tagName === \"A\")\n"
        + "  .map((k) => ({ text: k.textContent, href: k.href }));\n"
        + "return {\n"
        + "  post: aufrufe.find((a) => a.methode === \"POST\")?.koerper ?? null,\n"
        + "  welleLink: links.find((k) => k.text === \"wellen/w1.md\") ?? null,\n"
        + "};",
        antworten={"/api/task": {"status": 200, "koerper": {"path": "aufgaben/a99.md"}}},
    )
    assert ergebnis["post"]["welle"] == "wellen/w1.md"
    assert ergebnis["welleLink"] is not None
    assert ergebnis["welleLink"]["href"].startswith("#/detail/")


@ohne_node
def test_wellen_auswahl_wird_aus_api_befuellt():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        "await formulare.ladeAufgabenAnsicht();\n"
        "const auswahl = bei(\"aufgabe-welle\");\n"
        "return {\n"
        "  optionen: auswahl.childNodes.map((o) => ({ wert: o.value, text: o.textContent })),\n"
        "  auswahl: auswahl.value,\n"
        "};",
        antworten={
            "/api/wellen": {
                "status": 200,
                "koerper": [
                    {"path": "wellen/w1.md", "titel": "Welle 1: Fixture"},
                    {"path": "wellen/w2.md", "titel": "Welle 2"},
                ],
            }
        },
    )
    assert ergebnis["optionen"][0] == {"wert": "", "text": "—"}
    # A13-Klein 1: Label ist „Titel (Pfad)", damit Titel-Duplikate trennbar sind.
    assert ergebnis["optionen"][1:] == [
        {"wert": "wellen/w1.md", "text": "Welle 1: Fixture (wellen/w1.md)"},
        {"wert": "wellen/w2.md", "text": "Welle 2 (wellen/w2.md)"},
    ]
    assert ergebnis["auswahl"] == ""


@ohne_node
def test_wellen_auswahl_bleibt_nach_neuladen_erhalten():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        "await formulare.ladeAufgabenAnsicht();\n"
        'bei("aufgabe-welle").value = "wellen/w2.md";\n'
        "await formulare.ladeAufgabenAnsicht();\n"
        "return {\n"
        '  auswahl: bei("aufgabe-welle").value,\n'
        '  optionen: bei("aufgabe-welle").childNodes.length,\n'
        "};",
        antworten={
            "/api/wellen": {
                "status": 200,
                "koerper": [
                    {"path": "wellen/w1.md", "titel": "Welle 1: Fixture"},
                    {"path": "wellen/w2.md", "titel": "Welle 2"},
                ],
            }
        },
    )
    assert ergebnis["auswahl"] == "wellen/w2.md"
    assert ergebnis["optionen"] == 3


@ohne_node
def test_wellen_auswahl_reset_wenn_welle_verschwindet():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        "await formulare.ladeAufgabenAnsicht();\n"
        'bei("aufgabe-welle").value = "wellen/w2.md";\n'
        'antworten["/api/wellen"] = {\n'
        "  status: 200,\n"
        '  koerper: [{ path: "wellen/w1.md", titel: "Welle 1: Fixture" }],\n'
        "};\n"
        "await formulare.ladeAufgabenAnsicht();\n"
        "return {\n"
        '  auswahl: bei("aufgabe-welle").value,\n'
        '  optionen: bei("aufgabe-welle").childNodes.map((o) => o.value),\n'
        "};",
        antworten={
            "/api/wellen": {
                "status": 200,
                "koerper": [
                    {"path": "wellen/w1.md", "titel": "Welle 1: Fixture"},
                    {"path": "wellen/w2.md", "titel": "Welle 2"},
                ],
            }
        },
    )
    assert ergebnis["auswahl"] == ""
    assert ergebnis["optionen"] == ["", "wellen/w1.md"]


@ohne_node
def test_wellen_auswahl_unerwartetes_format_ist_fail_loud():
    ergebnis = dom(
        "formulare.initialisiereFormulare();\n"
        "await formulare.ladeAufgabenAnsicht();\n"
        "return {\n"
        "  fehler: bei(\"fehler\").textContent,\n"
        "  fehlerSichtbar: sichtbar(\"fehler\"),\n"
        "  optionen: bei(\"aufgabe-welle\").childNodes.length,\n"
        "};",
        antworten={"/api/wellen": {"status": 200, "koerper": {"fehler": "kaputt"}}},
    )
    assert ergebnis["fehler"]
    assert ergebnis["fehlerSichtbar"] is True
    assert ergebnis["optionen"] == 1


@ohne_node
def test_initialisiere_ohne_container_ist_robust():
    ergebnis = dom("formulare.initialisiereFormulare();\nreturn { ok: true };", container=False)
    assert ergebnis == {"ok": True}


# --- Anlegen über die HTTP-API (Formular-Payloads) -------------------------


@pytest.fixture()
def client(bundle):
    return server.create_app(bundle).test_client()


def _dateien(bundle: Path) -> list[str]:
    return sorted(p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file())


def _aufgabe_payload(**abweichungen) -> dict:
    # Wie im Formular: Akzeptanz ist ein mehrzeiliger String, kein Array.
    daten = {
        "titel": "A99: Neue Aufgabe",
        "ziel": "Ziel der neuen Aufgabe.",
        "akzeptanz": "Erstes Kriterium.\nZweites Kriterium.",
        "prioritaet": "hoch",
    }
    daten.update(abweichungen)
    return js("formulare.erstelleAufgabePayload(daten)", daten)


def _welle_payload(**abweichungen) -> dict:
    daten = {
        "titel": "Welle 2: Neu",
        "ziel": "Ziel der neuen Welle.",
        "status": "Offen",
        "owner": "ai",
    }
    daten.update(abweichungen)
    return js("formulare.erstelleWellePayload(daten)", daten)


@ohne_node
def test_t1_aufgabe_erscheint_in_liste_mit_offen_und_ai(client, bundle):
    antwort = client.post("/api/task", json=_aufgabe_payload())

    assert antwort.status_code == 200
    pfad = antwort.get_json()["path"]
    eintraege = {eintrag["path"]: eintrag for eintrag in client.get("/api/aufgaben").get_json()}
    assert eintraege[pfad]["titel"] == "A99: Neue Aufgabe"
    assert eintraege[pfad]["status"] == "Offen"
    assert eintraege[pfad]["owner"] == "ai"


@ohne_node
def test_t2_unvollstaendiger_payload_kein_eintrag(client, bundle):
    vorher = _dateien(bundle)
    payload = _aufgabe_payload(titel="")

    antwort = client.post("/api/task", json=payload)

    assert antwort.status_code == 400
    assert _dateien(bundle) == vorher


@ohne_node
def test_t3_akzeptanz_als_bindestrich_zeilen(client, bundle):
    payload = _aufgabe_payload(akzeptanz="eins\nzwei\ndrei")

    antwort = client.post("/api/task", json=payload)

    assert antwort.status_code == 200
    inhalt = (bundle / antwort.get_json()["path"]).read_text(encoding="utf-8")
    zeilen = [zeile for zeile in inhalt.splitlines() if zeile.startswith("- ")]
    assert zeilen == ["- eins", "- zwei", "- drei"]


@ohne_node
def test_t5_welle_erscheint_in_wellenliste_mit_spalten(client, bundle):
    antwort = client.post("/api/welle", json=_welle_payload())

    assert antwort.status_code == 200
    pfad = antwort.get_json()["path"]
    eintraege = {eintrag["path"]: eintrag for eintrag in client.get("/api/wellen").get_json()}
    eintrag = eintraege[pfad]
    assert eintrag["titel"] == "Welle 2: Neu"
    assert eintrag["status"] == "Offen"
    assert eintrag["owner"] == "ai"
    assert eintrag["zuletzt_geaendert"]


@ohne_node
@pytest.mark.parametrize("abweichung", [{"status": "In Umsetzung"}, {"owner": "bot"}])
def test_t6_ungueltige_welle_kein_eintrag(client, bundle, abweichung):
    vorher = _dateien(bundle)
    payload = _welle_payload(**abweichung)
    pruefung = js("formulare.validiereWelle(daten)", payload)
    assert pruefung["ok"] is False

    antwort = client.post("/api/welle", json=payload)

    assert antwort.status_code == 400
    assert _dateien(bundle) == vorher


@ohne_node
def test_t7_anlegen_erzeugt_genau_eine_datei(client, bundle):
    vorher = _dateien(bundle)

    antwort = client.post("/api/task", json=_aufgabe_payload())

    assert antwort.status_code == 200
    assert len(_dateien(bundle)) == len(vorher) + 1


@ohne_node
def test_t8_wellen_zuordnung_in_beiden_ansichten(client, bundle):
    payload = _aufgabe_payload(welle="wellen/w1.md")

    antwort = client.post("/api/task", json=payload)
    assert antwort.status_code == 200
    pfad = antwort.get_json()["path"]

    # Listenansicht: der Eintrag trägt die Wellen-Zuordnung.
    eintraege = {eintrag["path"]: eintrag for eintrag in client.get("/api/aufgaben").get_json()}
    assert eintraege[pfad]["welle"] == "wellen/w1.md"

    # Detailansicht: Frontmatter und Kontext-Verweis zeigen auf die Welle.
    datei = (bundle / pfad).read_text(encoding="utf-8")
    assert "welle: wellen/w1.md" in datei
    # A33-T10 (A13-3): Linktext ist der Wellen-Titel, nicht der Dateistamm.
    assert "- Welle: [Welle 1: Fixture](wellen/w1.md)" in datei
    detail = client.get(f"/api/file?path={pfad}").get_json()
    assert detail["frontmatter"]["welle"] == "wellen/w1.md"
    assert "wellen/w1.md" in detail["markdown"]
