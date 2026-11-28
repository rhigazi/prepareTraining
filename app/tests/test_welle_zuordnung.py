"""Prüfungen für die Wellen-Zuordnung in der UI (A27, Paket 2).

Die UI-Szenarien S1–S7 spielt der ``tester`` mit dem Moli-Browser durch; hier
werden ``detail.js``/``liste.js`` ohne Browser geprüft. Die reine Filter-/
Payload-Logik läuft über Node (keine neue Abhängigkeit), Montage und Verdrahtung
über einen Mini-DOM-Harness mit Fetch-Stab.

Der Harness (Mini-DOM, Node-Runner und Auswerte-Helfer) liegt in
``dom_helfer.py``; diese Datei bringt nur das Seiten-/Fetch-Gerüst und die
Prüfungen. Alle Läufe arbeiten gegen Fetch-Antworten aus dem Stab — nie gegen
``wissen/``.
"""

import hashlib
import json
import re
import sys
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from dom_helfer import MINI_DOM, js_detail, js_liste, lies, node_ausfuehren, ohne_node

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import okf_bundle
import server

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
DETAIL_JS = STATIC_DIR / "js" / "detail.js"
LISTE_JS = STATIC_DIR / "js" / "liste.js"
INDEX_HTML = STATIC_DIR / "index.html"
STYLE_CSS = STATIC_DIR / "style.css"
APP_JS = STATIC_DIR / "js" / "app.js"
API_JS = STATIC_DIR / "js" / "api.js"
FORMULARE_JS = STATIC_DIR / "js" / "formulare.js"
SERVER_PY = Path(__file__).resolve().parents[1] / "server.py"

AUFGABE = "aufgaben/a1.md"
WELLE_1 = "wellen/w1.md"
WELLE_2 = "wellen/w2.md"

WELLE_ERFOLG = "Welle gespeichert."
WELLE_ENTFERNT = "Welle entfernt."
WELLEN_LADE_FEHLER = "Wellen konnten nicht geladen werden."
WELLEN_FORMAT_FEHLER = "Wellen haben ein unerwartetes Format."
AUFGABEN_LADE_FEHLER = "Aufgaben konnten nicht geladen werden."
AUFGABEN_FORMAT_FEHLER = "Aufgaben haben ein unerwartetes Format."
KEINE_AUFGABEN = "Keine Aufgaben dieser Welle."
KEINE_EINTRAEGE = "Keine Einträge."
KEINE_TREFFER = "Keine Treffer."

HTML_PAYLOAD = "<img src=x onerror=alert(1)>"
SCRIPT_PAYLOAD = "<script>alert(1)</script>"


# --- Fixtures -------------------------------------------------------------

AUFGABE_DATEI = {
    "frontmatter": {
        "type": "Task",
        "title": "A1: Mini-Aufgabe",
        "task_status": "offen",
        "owner": "ai",
    },
    "markdown": "# Ziel\n\nFixture-Ziel.\n",
    "nachtraege": [],
}

WELLEN_LISTE = [
    {
        "path": WELLE_1,
        "typ": "Welle",
        "titel": "Welle 1: Fixture",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T10:00:00",
    },
    {
        "path": WELLE_2,
        "typ": "Welle",
        "titel": "",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-13T10:00:00",
    },
]

AUFGABEN_LISTE = [
    {
        "path": "aufgaben/a1.md",
        "typ": "Task",
        "titel": "A1: Mini-Aufgabe",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T10:00:00",
        "welle": WELLE_1,
    },
    {
        "path": "aufgaben/a2.md",
        "typ": "Task",
        "titel": "A2: Zweite Aufgabe",
        "status": "Klarung",
        "owner": "mensch",
        "zuletzt_geaendert": "2026-11-13T10:00:00",
        "welle": WELLE_1,
    },
    {
        "path": "aufgaben/a3.md",
        "typ": "Task",
        "titel": "A3: Andere Welle",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-12T10:00:00",
        "welle": WELLE_2,
    },
    {
        "path": "aufgaben/a4.md",
        "typ": "Task",
        "titel": "A4: Ohne Welle",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-11T10:00:00",
    },
]

LISTEN_EINTRAEGE = [
    {
        "path": "aufgaben/a1.md",
        "titel": "A1: Mini-Aufgabe",
        "typ": "Task",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T10:00:00",
        "welle": WELLE_1,
    },
    {
        "path": "aufgaben/a2.md",
        "titel": "A2: Zweite Aufgabe",
        "typ": "Task",
        "status": "Klarung",
        "owner": "mensch",
        "zuletzt_geaendert": "2026-11-13T10:00:00",
        "welle": WELLE_1,
    },
    {
        "path": "aufgaben/a3.md",
        "titel": "A3: Andere Welle",
        "typ": "Task",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-12T10:00:00",
        "welle": WELLE_2,
    },
    {
        "path": "aufgaben/a4.md",
        "titel": "A4: Ohne Welle",
        "typ": "Task",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-11T10:00:00",
    },
    WELLEN_LISTE[0],
    WELLEN_LISTE[1],
]


# --- Detail-Umgebung: Stab mit veränderlicher Datei -----------------------

DETAIL_UMGEBUNG = r"""
const fehler = document.createElement("div");
fehler.id = "fehler";
fehler.hidden = true;
fehler._imDokument = true;
const meldung = document.createElement("div");
meldung.id = "meldung";
meldung.hidden = true;
meldung._imDokument = true;
const ziel = document.createElement("div");
ziel.id = "detail";
ziel._imDokument = true;

const aufrufe = [];
let freigeben = null;
const abrufe = (endpunkt) => aufrufe.filter((eintrag) => eintrag.endpunkt === endpunkt).length;
const datei = { ...DATEI, frontmatter: { ...(DATEI.frontmatter || {}) } };
const antworte = (status, koerper) => ({
  ok: status < 400,
  status,
  headers: { get: () => "application/json" },
  text: async () => JSON.stringify(koerper ?? null),
});

globalThis.fetch = async (pfad, optionen = {}) => {
  const adresse = String(pfad);
  const methode = optionen.method || "GET";
  const nutzlast = typeof optionen.body === "string" ? JSON.parse(optionen.body) : null;
  aufrufe.push({ methode, endpunkt: adresse, pfad: adresse, nutzlast });

  if (methode === "GET" && adresse.startsWith("/api/file")) return antworte(200, datei);
  if (methode === "GET" && adresse === "/api/wellen") return antworte(WELLEN_STATUS, WELLEN);
  if (methode === "GET" && adresse === "/api/aufgaben") return antworte(AUFGABEN_STATUS, AUFGABEN);

  if (methode === "POST" && adresse === "/api/meta") {
    if (GATE) await new Promise((fertig) => { freigeben = fertig; });
    if (META_STATUS >= 400) return antworte(META_STATUS, { error: META_FEHLER });
    if (nutzlast && "welle" in nutzlast) {
      if (nutzlast.welle === null) delete datei.frontmatter.welle;
      else datei.frontmatter.welle = nutzlast.welle;
    }
    return antworte(200, { path: nutzlast?.path, frontmatter: datei.frontmatter });
  }

  return antworte(404, { error: "Nicht gefunden." });
};
"""


def detail_lauf(
    datei: dict,
    ablauf: str,
    *,
    wellen=None,
    wellen_status: int = 200,
    aufgaben=None,
    aufgaben_status: int = 200,
    meta_status: int = 200,
    meta_fehler: str = "welle muss eine vorhandene Wellen-Datei unter wellen/ sein",
    gate: bool = False,
) -> dict:
    """Spielt einen Ablauf in der Detailansicht mit Fetch-Stab aus."""
    skript = (
        f"import * as detail from {json.dumps(DETAIL_JS.as_uri())};\n"
        + MINI_DOM
        + f"const DATEI = {json.dumps(datei, ensure_ascii=False)};\n"
        + f"const WELLEN = {json.dumps(wellen, ensure_ascii=False)};\n"
        + f"const AUFGABEN = {json.dumps(aufgaben, ensure_ascii=False)};\n"
        + f"const WELLEN_STATUS = {wellen_status};\n"
        + f"const AUFGABEN_STATUS = {aufgaben_status};\n"
        + f"const META_STATUS = {meta_status};\n"
        + f"const META_FEHLER = {json.dumps(meta_fehler, ensure_ascii=False)};\n"
        + f"const GATE = {'true' if gate else 'false'};\n"
        + DETAIL_UMGEBUNG
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


LISTEN_UMGEBUNG = r"""
// Ansichtsgerüst wie in index.html (A10/A11): Formular, Tabellencontainer,
// Zusatzblöcke der Übersicht.
const ANSICHTEN_DOM = [
  {
    ansicht: "ansicht-uebersicht",
    titel: "Übersicht",
    formular: "filter",
    status: "filter-status",
    owner: "filter-owner",
    zuruecksetzen: "filter-zuruecksetzen",
    tabelle: "tabelle",
    zusatz: true,
  },
  {
    ansicht: "ansicht-wellen",
    titel: "Wellen",
    formular: "filter-wellen",
    status: "filter-wellen-status",
    owner: "filter-wellen-owner",
    zuruecksetzen: "filter-wellen-zuruecksetzen",
    tabelle: "tabelle-wellen",
  },
  {
    ansicht: "ansicht-aufgaben",
    titel: "Aufgaben",
    formular: "filter-aufgaben",
    status: "filter-aufgaben-status",
    owner: "filter-aufgaben-owner",
    zuruecksetzen: "filter-aufgaben-zuruecksetzen",
    tabelle: "tabelle-aufgaben",
  },
];

for (const eintrag of ANSICHTEN_DOM) {
  const bereich = document.createElement("section");
  bereich.id = eintrag.ansicht;
  bereich._imDokument = true;
  const titel = document.createElement("h2");
  titel.textContent = eintrag.titel;
  const formular = document.createElement("form");
  formular.id = eintrag.formular;
  const status = document.createElement("select");
  status.id = eintrag.status;
  const owner = document.createElement("select");
  owner.id = eintrag.owner;
  const knopf = document.createElement("button");
  knopf.id = eintrag.zuruecksetzen;
  knopf.textContent = "Filter zurücksetzen";
  formular.append(status, owner, knopf);
  const tabelle = document.createElement("div");
  tabelle.id = eintrag.tabelle;
  tabelle.classList.add("tabelle-bereich");
  bereich.append(titel, formular, tabelle);
  if (eintrag.zusatz) {
    for (const id of ["uebersicht-zuletzt", "uebersicht-klarung"]) {
      const block = document.createElement("div");
      block.id = id;
      bereich.append(block);
    }
  }
}

for (const id of ["fehler", "meldung"]) {
  const bereich = document.createElement("div");
  bereich.id = id;
  bereich.hidden = true;
  bereich._imDokument = true;
}
"""

LISTEN_STAB = r"""
const ANTWORTEN = __ANTWORTEN__;
const aufrufe = [];
globalThis.fetch = async (pfad, optionen = {}) => {
  const ziel = String(pfad);
  const methode = optionen.method || "GET";
  aufrufe.push({ endpunkt: ziel, methode });
  const vorgabe = ANTWORTEN[methode + " " + ziel] ?? ANTWORTEN[ziel] ?? {
    status: 404,
    koerper: { error: "Nicht gefunden." },
  };
  return {
    ok: vorgabe.status < 400,
    status: vorgabe.status,
    headers: { get: () => "application/json" },
    text: async () => JSON.stringify(vorgabe.koerper ?? null),
  };
};
const abrufe = (endpunkt) => aufrufe.filter((eintrag) => eintrag.endpunkt === endpunkt).length;
"""


def listen_lauf(ablauf: str, antworten: dict | None = None) -> dict:
    """Führt einen Ablauf im Listen-DOM-Harness aus."""
    skript = (
        MINI_DOM
        + LISTEN_UMGEBUNG
        + LISTEN_STAB.replace("__ANTWORTEN__", json.dumps(antworten or {}, ensure_ascii=False))
        + f"\nimport * as liste from {json.dumps(LISTE_JS.as_uri())};\n"
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


def listen_antwort(daten, endpunkt: str = "/api/overview") -> dict:
    return {endpunkt: {"status": 200, "koerper": daten}}


# --- A. Detailansicht: Dropdown, Speichern, Fehler ------------------------


@ohne_node
def test_t19_detail_welle_dropdown_mit_optionen():
    ergebnis = detail_lauf(
        AUFGABE_DATEI,
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
const auswahl = bei("detail-welle");
const kopf = sammle(bei("detail")).find((knoten) => knoten.classList.contains("detail-kopf"));
const bezeichnungen = kopf
  ? sammle(kopf).filter((knoten) => knoten.marke === "dt").map((knoten) => knoten.textContent)
  : [];
const feld = kopf ? sammle(kopf).find((knoten) => knoten === auswahl) : null;
return {
  vorhanden: auswahl !== null,
  marke: auswahl?.marke ?? null,
  imKopf: Boolean(feld),
  bezeichnungen,
  werte: optionenwerte(auswahl),
  texte: optionstexte(auswahl),
  wert: auswahl?.value ?? null,
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt.split("?")[0]),
};
""",
        wellen=WELLEN_LISTE,
    )
    assert ergebnis["vorhanden"] is True
    assert ergebnis["marke"] == "select"
    assert ergebnis["imKopf"] is True
    assert "Welle" in ergebnis["bezeichnungen"]
    assert ergebnis["werte"] == ["", WELLE_1, WELLE_2]
    assert ergebnis["texte"] == ["keine", "Welle 1: Fixture (wellen/w1.md)", WELLE_2]
    assert ergebnis["wert"] == ""
    # A34/T43: Aufgaben-Details laden zusätzlich ``/api/aufgaben`` (Unter-Aufgaben).
    assert ergebnis["aufrufe"] == ["/api/file", "/api/wellen", "/api/aufgaben"]


@ohne_node
@pytest.mark.parametrize(
    "pfad,datei,endpunkte",
    [
        (
            WELLE_1,
            {"frontmatter": {"type": "Welle", "title": "W1"}, "markdown": "# Ziel\n"},
            ["/api/file", "/api/aufgaben"],
        ),
        (
            "projekt/phasen.md",
            {"frontmatter": {"type": "Projekt", "title": "Phasen"}, "markdown": "# Phasen\n"},
            ["/api/file"],
        ),
    ],
)
def test_t20_kein_dropdown_ausserhalb_von_aufgaben(pfad, datei, endpunkte):
    ergebnis = detail_lauf(
        datei,
        f"""
await detail.ladeDetail({{ unterpunkt: {json.dumps(pfad)} }});
return {{
  feld: bei("detail-welle") !== null,
  wellen: abrufe("/api/wellen"),
  titel: sammle(bei("detail")).find((knoten) => knoten.marke === "h2")?.textContent ?? null,
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt.split("?")[0]),
}};
""",
        wellen=WELLEN_LISTE,
    )
    assert ergebnis["feld"] is False
    assert ergebnis["wellen"] == 0
    assert ergebnis["titel"]
    assert ergebnis["aufrufe"] == endpunkte


@ohne_node
def test_t21_speichern_beim_wechsel():
    ergebnis = detail_lauf(
        AUFGABE_DATEI,
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
const auswahl = bei("detail-welle");
auswahl.value = "wellen/w1.md";
await ausloesen(auswahl, "change");
const nachher = bei("detail-welle");
return {
  posts: aufrufe
    .filter((eintrag) => eintrag.methode === "POST")
    .map((eintrag) => ({ pfad: eintrag.pfad, nutzlast: eintrag.nutzlast })),
  meldung: { sichtbar: !bei("meldung").hidden, text: bei("meldung").textContent },
  wert: nachher?.value ?? null,
  texte: optionstexte(nachher),
};
""",
        wellen=WELLEN_LISTE,
    )
    assert ergebnis["posts"] == [
        {"pfad": "/api/meta", "nutzlast": {"path": AUFGABE, "welle": WELLE_1}}
    ]
    assert ergebnis["meldung"] == {"sichtbar": True, "text": WELLE_ERFOLG}
    assert ergebnis["wert"] == WELLE_1
    assert "keine" in ergebnis["texte"]


@ohne_node
def test_t22_entfernen_im_ui():
    datei = {
        **AUFGABE_DATEI,
        "frontmatter": {**AUFGABE_DATEI["frontmatter"], "welle": WELLE_1},
    }
    ergebnis = detail_lauf(
        datei,
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
const auswahl = bei("detail-welle");
const vorher = auswahl.value;
auswahl.value = "";
await ausloesen(auswahl, "change");
const nachher = bei("detail-welle");
return {
  vorher,
  posts: aufrufe
    .filter((eintrag) => eintrag.methode === "POST")
    .map((eintrag) => ({ pfad: eintrag.pfad, nutzlast: eintrag.nutzlast })),
  meldung: { sichtbar: !bei("meldung").hidden, text: bei("meldung").textContent },
  wert: nachher?.value ?? null,
};
""",
        wellen=WELLEN_LISTE,
    )
    assert ergebnis["vorher"] == WELLE_1
    assert ergebnis["posts"] == [
        {"pfad": "/api/meta", "nutzlast": {"path": AUFGABE, "welle": None}}
    ]
    assert ergebnis["meldung"] == {"sichtbar": True, "text": WELLE_ENTFERNT}
    assert ergebnis["wert"] == ""


@ohne_node
def test_t23_fehlerpfad_rollt_die_auswahl_zurueck():
    ergebnis = detail_lauf(
        AUFGABE_DATEI,
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
const auswahl = bei("detail-welle");
auswahl.value = "wellen/w1.md";
await ausloesen(auswahl, "change");
return {
  posts: aufrufe.filter((eintrag) => eintrag.methode === "POST").length,
  dateiLadungen: aufrufe.filter((eintrag) => eintrag.endpunkt.startsWith("/api/file")).length,
  wert: auswahl.value,
  fehler: { sichtbar: !bei("fehler").hidden, text: bei("fehler").textContent },
  meldung: { sichtbar: !bei("meldung").hidden, text: bei("meldung").textContent },
};
""",
        wellen=WELLEN_LISTE,
        meta_status=400,
    )
    assert ergebnis["posts"] == 1
    assert ergebnis["dateiLadungen"] == 1
    assert ergebnis["wert"] == ""
    assert ergebnis["fehler"]["sichtbar"] is True
    assert "wellen/" in ergebnis["fehler"]["text"]
    assert ergebnis["meldung"] == {"sichtbar": False, "text": ""}


@ohne_node
def test_t24_unbekannte_welle_ist_fail_loud():
    datei = {
        **AUFGABE_DATEI,
        "frontmatter": {**AUFGABE_DATEI["frontmatter"], "welle": "wellen/geloescht.md"},
    }
    ergebnis = detail_lauf(
        datei,
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
const auswahl = bei("detail-welle");
const hinweis = bei("detail-welle-hinweis");
return {
  wert: auswahl?.value ?? null,
  optionen: optionen(auswahl).map((option) => ({ wert: option.value, text: option.textContent })),
  hinweis: hinweis?.textContent ?? null,
  posts: aufrufe.filter((eintrag) => eintrag.methode === "POST").length,
};
""",
        wellen=WELLEN_LISTE,
    )
    assert ergebnis["wert"] == "wellen/geloescht.md"
    assert {
        "wert": "wellen/geloescht.md",
        "text": "wellen/geloescht.md (unbekannt)",
    } in ergebnis["optionen"]
    assert ergebnis["hinweis"] == (
        "Welle „wellen/geloescht.md\" ist unbekannt; bitte eine Welle wählen oder „keine\" setzen."
    )
    assert ergebnis["posts"] == 0


@ohne_node
def test_t25_xss_in_wellen_titel_und_welle_wert():
    wellen = [
        {
            "path": WELLE_1,
            "typ": "Welle",
            "titel": HTML_PAYLOAD,
            "status": "Offen",
            "owner": "ai",
        }
    ]
    datei = {
        **AUFGABE_DATEI,
        "frontmatter": {**AUFGABE_DATEI["frontmatter"], "welle": SCRIPT_PAYLOAD},
    }
    ergebnis = detail_lauf(
        datei,
        f"""
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await detail.ladeDetail({{ unterpunkt: "aufgaben/a1.md" }});
return {{
  texte: optionstexte(bei("detail-welle")),
  hinweis: bei("detail-welle-hinweis")?.textContent ?? null,
  marken: marken(bei("detail")),
  ausfuehrungen,
}};
""",
        wellen=wellen,
    )
    assert f"{HTML_PAYLOAD} (wellen/w1.md)" in ergebnis["texte"]
    assert SCRIPT_PAYLOAD in ergebnis["hinweis"]
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []


@ohne_node
@pytest.mark.parametrize(
    "wellen,erwartet",
    [(None, WELLEN_LADE_FEHLER), ({}, WELLEN_FORMAT_FEHLER), (42, WELLEN_FORMAT_FEHLER)],
)
def test_t26_wellenliste_fail_loud(wellen, erwartet):
    ergebnis = detail_lauf(
        AUFGABE_DATEI,
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
return {
  fehler: { sichtbar: !bei("fehler").hidden, text: bei("fehler").textContent },
  hinweis: bei("detail-welle-hinweis")?.textContent ?? null,
  wert: bei("detail-welle")?.value ?? null,
  gesperrt: bei("detail-welle")?.disabled ?? null,
  texte: optionstexte(bei("detail-welle")),
  titel: sammle(bei("detail")).find((knoten) => knoten.marke === "h2")?.textContent ?? null,
  markdown: sammle(bei("detail")).some((knoten) => knoten.marke === "p"),
  nachtrag: bei("nachtrag-formular") !== null,
};
""",
        wellen=wellen,
    )
    assert ergebnis["fehler"] == {"sichtbar": True, "text": erwartet}
    assert ergebnis["hinweis"] == erwartet
    assert ergebnis["gesperrt"] is True
    assert ergebnis["texte"] == ["keine"]
    assert ergebnis["wert"] == ""
    assert ergebnis["titel"] == "A1: Mini-Aufgabe"
    assert ergebnis["markdown"] is True
    assert ergebnis["nachtrag"] is True


@ohne_node
@pytest.mark.parametrize("meta_status", [200, 400])
def test_t27_parallelwechsel_schreibt_genau_einmal(meta_status):
    ergebnis = detail_lauf(
        AUFGABE_DATEI,
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
const auswahl = bei("detail-welle");
auswahl.value = "wellen/w1.md";
const erstes = ausloesen(auswahl, "change");
const gesperrtWaehrend = auswahl.disabled;
const zweites = ausloesen(auswahl, "change");
if (freigeben) freigeben();
await Promise.all([erstes, zweites]);
const nachher = bei("detail-welle");
return {
  gesperrtWaehrend,
  posts: aufrufe.filter((eintrag) => eintrag.methode === "POST").length,
  danachBedienbar: nachher ? nachher.disabled === false : null,
};
""",
        wellen=WELLEN_LISTE,
        meta_status=meta_status,
        gate=True,
    )
    assert ergebnis["gesperrtWaehrend"] is True
    assert ergebnis["posts"] == 1
    assert ergebnis["danachBedienbar"] is True


# --- B. Listenfilter ------------------------------------------------------


@ohne_node
def test_t28_wellen_filter_wird_dynamisch_und_idempotent_montiert():
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
const feld = bei("filter-welle");
const gruppe = feld?.parentElement;
const formular = bei("filter");
const zuruecksetzen = bei("filter-zuruecksetzen");
const label = gruppe ? sammle(gruppe).find((knoten) => knoten.marke === "label") : null;

feld.value = "wellen/w1.md";
await ausloesen(feld, "change");
const nachWahl = pfade("tabelle");

await liste.ladeUebersicht();
const zweites = bei("filter-welle");

await liste.ladeAufgaben();
const aufgabenFeld = bei("filter-welle-aufgaben");
const aufgabenLabel = aufgabenFeld
  ? sammle(aufgabenFeld.parentElement).find((knoten) => knoten.marke === "label")
  : null;
const aufgabenFormular = bei("filter-aufgaben");

await liste.ladeWellen();
return {
  imFormular: Boolean(formular && feld && feld.parentElement.parentElement === formular),
  vorReset:
    Boolean(formular && zuruecksetzen)
    && formular.kinder.indexOf(feld.parentElement) < formular.kinder.indexOf(zuruecksetzen),
  labelText: label?.textContent ?? null,
  labelFor: label?.htmlFor || null,
  gruppeKlassen: gruppe?.klassen() ?? [],
  werte: optionenwerte(feld),
  texte: optionstexte(feld),
  nachWahl,
  anzahl: anzahl("ansicht-uebersicht", "filter-welle"),
  gleichesObjekt: zweites === feld,
  wertNachNeuladen: zweites?.value ?? null,
  aufgabenFeld: aufgabenFeld !== null,
  aufgabenLabel: aufgabenLabel?.textContent ?? null,
  imAufgabenFormular: Boolean(
    aufgabenFormular && aufgabenFeld && aufgabenFeld.parentElement.parentElement === aufgabenFormular
  ),
  wellenFeldInWellenansicht: bei("filter-wellen-welle") !== null,
  wellenFeldAnzahl: anzahl("ansicht-wellen", "filter-welle"),
  wellenAbrufe: abrufe("/api/wellen"),
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt),
  html: null,
};
""",
        listen_antwort(LISTEN_EINTRAEGE),
    )
    assert ergebnis["imFormular"] is True
    assert ergebnis["vorReset"] is True
    assert ergebnis["labelText"] == "Welle"
    assert ergebnis["labelFor"] == "filter-welle"
    assert ergebnis["gruppeKlassen"] == ["filter-feld"]
    assert ergebnis["werte"] == ["", "ohne", WELLE_1, WELLE_2]
    assert ergebnis["texte"] == [
        "Alle",
        "ohne Welle",
        "Welle 1: Fixture (wellen/w1.md)",
        WELLE_2,
    ]
    assert ergebnis["nachWahl"] == ["aufgaben/a1.md", "aufgaben/a2.md"]
    assert ergebnis["anzahl"] == 1
    assert ergebnis["gleichesObjekt"] is True
    assert ergebnis["wertNachNeuladen"] == WELLE_1
    assert ergebnis["aufgabenFeld"] is True
    assert ergebnis["aufgabenLabel"] == "Welle"
    assert ergebnis["imAufgabenFormular"] is True
    assert ergebnis["wellenFeldInWellenansicht"] is False
    assert ergebnis["wellenFeldAnzahl"] == 0
    # Kein zusätzlicher Request: die Wellen stammen aus dem geladenen Bestand.
    assert ergebnis["aufrufe"] == ["/api/overview", "/api/overview", "/api/aufgaben", "/api/wellen"]
    html = lies(INDEX_HTML)
    assert 'id="filter-welle"' not in html
    assert 'id="filter-welle-aufgaben"' not in html


@ohne_node
def test_t28_aufgabenliste_ohne_uebersicht_kennt_die_referenzierten_wellen():
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
const feld = bei("filter-welle-aufgaben");
return {
  werte: optionenwerte(feld),
  texte: optionstexte(feld),
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt),
};
""",
        listen_antwort(AUFGABEN_LISTE, "/api/aufgaben"),
    )
    assert ergebnis["werte"] == ["", "ohne", WELLE_1, WELLE_2]
    assert ergebnis["texte"] == ["Alle", "ohne Welle", WELLE_1, WELLE_2]
    assert ergebnis["aufrufe"] == ["/api/aufgaben"]


@ohne_node
def test_t29_filterlogik_nach_welle():
    voll = [eintrag["path"] for eintrag in LISTEN_EINTRAEGE]
    treffer = js_liste(
        f"liste.filtereEintraege(daten, {{ welle: {json.dumps(WELLE_1)} }}).map((e) => e.path)",
        LISTEN_EINTRAEGE,
    )
    assert treffer == ["aufgaben/a1.md", "aufgaben/a2.md"]

    for leer in ["", None]:
        pfade = js_liste(
            f"liste.filtereEintraege(daten, {{ welle: {json.dumps(leer)} }}).map((e) => e.path)",
            LISTEN_EINTRAEGE,
        )
        assert pfade == voll

    assert js_liste("liste.filtereEintraege(daten, {}).map((e) => e.path)", LISTEN_EINTRAEGE) == voll

    ohne = js_liste(
        'liste.filtereEintraege(daten, { welle: "ohne" }).map((e) => e.path)',
        LISTEN_EINTRAEGE,
    )
    assert ohne == ["aufgaben/a4.md"] + [eintrag["path"] for eintrag in WELLEN_LISTE]

    unveraendert = js_liste(
        "(() => { const vorher = daten.map((e) => e.path).join(',');"
        f" liste.filtereEintraege(daten, {{ welle: {json.dumps(WELLE_1)} }});"
        " return daten.map((e) => e.path).join(',') === vorher; })()",
        LISTEN_EINTRAEGE,
    )
    assert unveraendert is True


@ohne_node
def test_t30_kombination_mit_status_owner_und_suche():
    kombination = js_liste(
        "liste.filtereEintraege(daten, { status: 'Offen', owner: 'ai', suche: 'a1',"
        f" welle: {json.dumps(WELLE_1)} }}).map((e) => e.path)",
        LISTEN_EINTRAEGE,
    )
    assert kombination == ["aufgaben/a1.md"]

    ohne_suche = js_liste(
        "liste.filtereEintraege(daten, { status: 'Offen', owner: 'ai', suche: '',"
        f" welle: {json.dumps(WELLE_1)} }}).map((e) => e.path)",
        LISTEN_EINTRAEGE,
    )
    assert ohne_suche == kombination

    leer = js_liste(
        "liste.filtereEintraege(daten, { status: 'Klarung', owner: 'ai', suche: '',"
        f" welle: {json.dumps(WELLE_1)} }}).map((e) => e.path)",
        LISTEN_EINTRAEGE,
    )
    assert leer == []


@ohne_node
def test_t31_dom_filter_und_reset():
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
const feld = bei("filter-welle");
const kopfVorher = kopfzeilen("tabelle");
feld.value = "wellen/w1.md";
await ausloesen(feld, "change");
const gefiltert = pfade("tabelle");
const kopfNachher = kopfzeilen("tabelle");

feld.value = "wellen/gibtsnicht.md";
await ausloesen(feld, "change");
const ohneTreffer = bei("tabelle").textContent;

feld.value = "wellen/w1.md";
await ausloesen(feld, "change");
bei("filter-status").value = "Klarung";
await ausloesen(bei("filter-status"), "change");
const kombination = pfade("tabelle");

bei("suche-uebersicht").value = "gibtsnicht";
await ausloesen(bei("suche-uebersicht"), "input");
const ohneTrefferMitSuche = bei("tabelle").textContent;

await ausloesen(bei("filter-zuruecksetzen"), "click");
return {
  kopfVorher,
  kopfNachher,
  gefiltert,
  ohneTreffer,
  kombination,
  ohneTrefferMitSuche,
  nachReset: pfade("tabelle"),
  welleNachReset: feld.value,
  statusNachReset: bei("filter-status").value,
  sucheNachReset: bei("suche-uebersicht").value,
  aufrufe: aufrufe.length,
};
""",
        listen_antwort(LISTEN_EINTRAEGE),
    )
    assert ergebnis["kopfVorher"] == ["Titel", "Welle", "Status", "owner", "zuletzt geändert"]
    assert ergebnis["kopfNachher"] == ergebnis["kopfVorher"]
    assert ergebnis["gefiltert"] == ["aufgaben/a1.md", "aufgaben/a2.md"]
    assert ergebnis["ohneTreffer"] == KEINE_EINTRAEGE
    assert ergebnis["kombination"] == ["aufgaben/a2.md"]
    assert ergebnis["ohneTrefferMitSuche"] == KEINE_TREFFER
    assert ergebnis["nachReset"] == [eintrag["path"] for eintrag in LISTEN_EINTRAEGE]
    assert ergebnis["welleNachReset"] == ""
    assert ergebnis["statusNachReset"] == ""
    assert ergebnis["sucheNachReset"] == ""
    assert ergebnis["aufrufe"] == 1


@ohne_node
@pytest.mark.parametrize("daten", [None, {}, 42])
def test_t32_fehlerhafte_liste_deaktiviert_den_wellen_filter(daten):
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
const feld = bei("filter-welle");
return {
  gesperrt: feld?.disabled ?? null,
  werte: optionenwerte(feld),
  inhalt: bei("tabelle").textContent,
  fehler: sammle(bei("tabelle")).filter((knoten) => knoten.marke === "p").length,
};
""",
        listen_antwort(daten),
    )
    assert ergebnis["gesperrt"] is True
    assert ergebnis["werte"] == [""]
    assert ergebnis["inhalt"] in (
        KEINE_EINTRAEGE,
        "Einträge konnten nicht geladen werden.",
        "Einträge haben ein unerwartetes Format.",
    )


@ohne_node
def test_t33_xss_im_wellen_filter():
    daten = [
        {
            "path": "aufgaben/a1.md",
            "titel": "A1",
            "typ": "Task",
            "status": "Offen",
            "owner": "ai",
            "zuletzt_geaendert": "2026-11-14T10:00:00",
            "welle": WELLE_1,
        },
        {
            "path": WELLE_1,
            "titel": HTML_PAYLOAD,
            "typ": "Welle",
            "status": "Offen",
            "owner": "ai",
            "zuletzt_geaendert": "2026-11-13T10:00:00",
        },
    ]
    ergebnis = listen_lauf(
        f"""
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await liste.ladeUebersicht();
return {{
  texte: optionstexte(bei("filter-welle")),
  marken: marken(bei("ansicht-uebersicht")),
  ausfuehrungen,
}};
""",
        listen_antwort(daten),
    )
    assert f"{HTML_PAYLOAD} (wellen/w1.md)" in ergebnis["texte"]
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []


# --- C. Wellen-Sicht -----------------------------------------------------


@ohne_node
def test_t34_wellen_detail_zeigt_die_aufgaben_der_welle():
    ergebnis = detail_lauf(
        {"frontmatter": {"type": "Welle", "title": "Welle 1: Fixture"}, "markdown": "# Ziel\n"},
        r"""
await detail.ladeDetail({ unterpunkt: "wellen/w1.md" });
const bereich = sammle(bei("detail")).find(
  (knoten) => knoten.marke === "section" && knoten.classList.contains("detail-abschnitt")
);
const ueberschrift = bereich
  ? sammle(bereich).filter((knoten) => /^h[1-6]$/.test(knoten.marke)).map((knoten) => knoten.textContent)
  : [];
return {
  ueberschrift,
  pfade: bereich
    ? sammle(bereich)
        .filter((knoten) => knoten.marke === "tr" && knoten.dataset.path)
        .map((knoten) => knoten.dataset.path)
    : [],
  spalten: bereich
    ? sammle(bereich).filter((knoten) => knoten.marke === "th").map((knoten) => knoten.textContent)
    : [],
  zeilen: bereich ? sammle(bereich).filter((knoten) => knoten.marke === "tr").length : 0,
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt.split("?")[0]),
};
""",
        aufgaben=AUFGABEN_LISTE,
    )
    assert ergebnis["ueberschrift"] == ["Aufgaben dieser Welle (2)"]
    assert ergebnis["pfade"] == ["aufgaben/a1.md", "aufgaben/a2.md"]
    assert ergebnis["spalten"] == ["Titel", "Status", "owner", "zuletzt geändert"]
    assert ergebnis["zeilen"] == 3  # Kopfzeile plus zwei Treffer
    assert ergebnis["aufrufe"] == ["/api/file", "/api/aufgaben"]


@ohne_node
@pytest.mark.parametrize(
    "aufgaben,aufgaben_status,erwartet",
    [
        ([], 200, ("leer", KEINE_AUFGABEN)),
        (None, 200, ("fehler", AUFGABEN_LADE_FEHLER)),
        ({}, 200, ("fehler", AUFGABEN_FORMAT_FEHLER)),
    ],
)
def test_t35_wellen_sicht_leer_und_fail_loud(aufgaben, aufgaben_status, erwartet):
    art, text = erwartet
    ergebnis = detail_lauf(
        {"frontmatter": {"type": "Welle", "title": "Welle 1: Fixture"}, "markdown": "# Ziel\n"},
        r"""
await detail.ladeDetail({ unterpunkt: "wellen/w1.md" });
const bereich = sammle(bei("detail")).find(
  (knoten) => knoten.marke === "section" && knoten.classList.contains("detail-abschnitt")
);
return {
  ueberschrift: bereich
    ? sammle(bereich)
        .filter((knoten) => /^h[1-6]$/.test(knoten.marke))
        .map((knoten) => knoten.textContent)
    : [],
  text: bereich?.textContent ?? null,
  tabellen: bereich ? sammle(bereich).filter((knoten) => knoten.marke === "table").length : 0,
  koerperzeilen: bereich
    ? sammle(bereich)
        .filter((knoten) => knoten.marke === "tbody")
        .flatMap((knoten) => knoten.kinder).length
    : 0,
  titel: sammle(bei("detail")).find((knoten) => knoten.marke === "h2")?.textContent ?? null,
  markdown: sammle(bei("detail")).some((knoten) => knoten.marke === "p"),
};
""",
        aufgaben=aufgaben,
        aufgaben_status=aufgaben_status,
    )
    assert ergebnis["ueberschrift"] == ["Aufgaben dieser Welle (0)"]
    assert text in ergebnis["text"]
    assert ergebnis["titel"] == "Welle 1: Fixture"
    assert ergebnis["markdown"] is True
    if art == "leer":
        assert ergebnis["tabellen"] == 0
        assert ergebnis["koerperzeilen"] == 0
    else:
        assert ergebnis["tabellen"] == 0


@ohne_node
def test_t37_xss_in_der_wellen_sicht():
    aufgaben = [
        {
            "path": "aufgaben/xss.md",
            "titel": HTML_PAYLOAD,
            "status": "Offen",
            "owner": "ai",
            "zuletzt_geaendert": "2026-11-14T10:00:00",
            "welle": WELLE_1,
        }
    ]
    ergebnis = detail_lauf(
        {"frontmatter": {"type": "Welle", "title": "Welle 1"}, "markdown": "# Ziel\n"},
        f"""
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await detail.ladeDetail({{ unterpunkt: "wellen/w1.md" }});
const bereich = sammle(bei("detail")).find(
  (knoten) => knoten.marke === "section" && knoten.classList.contains("detail-abschnitt")
);
return {{
  text: bereich?.textContent ?? null,
  marken: marken(bereich),
  ausfuehrungen,
}};
""",
        aufgaben=aufgaben,
    )
    assert HTML_PAYLOAD in ergebnis["text"]
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []


@ohne_node
@pytest.mark.parametrize(
    "pfad,datei,endpunkte,abschnitt",
    [
        (
            AUFGABE,
            AUFGABE_DATEI,
            ["/api/file", "/api/wellen", "/api/aufgaben"],
            False,
        ),
        (
            WELLE_1,
            {"frontmatter": {"type": "Welle", "title": "W1"}, "markdown": "# Ziel\n"},
            ["/api/file", "/api/aufgaben"],
            True,
        ),
        (
            "projekt/phasen.md",
            {"frontmatter": {"type": "Projekt", "title": "Phasen"}, "markdown": "# Phasen\n"},
            ["/api/file"],
            False,
        ),
    ],
)
def test_t38_request_budget_und_abgrenzung(pfad, datei, endpunkte, abschnitt):
    ergebnis = detail_lauf(
        datei,
        f"""
await detail.ladeDetail({{ unterpunkt: {json.dumps(pfad)} }});
return {{
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt.split("?")[0]),
  abschnitt: sammle(bei("detail")).some(
    (knoten) => knoten.marke === "section" && knoten.classList.contains("detail-abschnitt")
  ),
}};
""",
        wellen=WELLEN_LISTE,
        aufgaben=AUFGABEN_LISTE,
    )
    assert ergebnis["aufrufe"] == endpunkte
    assert ergebnis["abschnitt"] is abschnitt


# --- D. Server-Belege (Join, keine Doppelpflege, A13) ---------------------


@pytest.fixture()
def client(bundle):
    return server.create_app(bundle).test_client()


@pytest.fixture()
def app_server(bundle):
    httpd = make_server("127.0.0.1", 0, server.create_app(bundle), threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


WELLE_2_INHALT = (
    "---\n"
    "type: Welle\n"
    'title: "Welle 2: Zweite Fixture"\n'
    "status: Offen\n"
    "owner: ai\n"
    "---\n\n"
    "# Ziel\n\nZweite Fixture-Welle.\n\n"
    "# Aufgaben\n"
)


def test_t21_join_beleg_ueber_die_lese_api(client):
    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": WELLE_1})
    assert antwort.status_code == 200

    aufgaben = {eintrag["path"]: eintrag for eintrag in client.get("/api/aufgaben").get_json()}
    assert aufgaben[AUFGABE]["welle"] == WELLE_1


def test_t36_wellen_datei_wird_nie_geschrieben(client, bundle):
    (bundle / WELLE_2).write_text(WELLE_2_INHALT, encoding="utf-8")
    hash_1 = hashlib.sha256((bundle / WELLE_1).read_bytes()).hexdigest()
    hash_2 = hashlib.sha256((bundle / WELLE_2).read_bytes()).hexdigest()

    client.post("/api/meta", json={"path": AUFGABE, "welle": WELLE_1})
    client.post("/api/meta", json={"path": AUFGABE, "welle": WELLE_2})

    assert hashlib.sha256((bundle / WELLE_1).read_bytes()).hexdigest() == hash_1
    assert hashlib.sha256((bundle / WELLE_2).read_bytes()).hexdigest() == hash_2
    # `# Aufgaben` bleibt der A5-Initialstand und wird nicht synchronisiert.
    assert (bundle / WELLE_2).read_text(encoding="utf-8").endswith("# Aufgaben\n")

    aufgaben = {eintrag["path"]: eintrag for eintrag in client.get("/api/aufgaben").get_json()}
    assert aufgaben[AUFGABE]["welle"] == WELLE_2


def test_t36_wellen_sicht_folgt_der_neuen_zuordnung(client, app_server, bundle):
    (bundle / WELLE_2).write_text(WELLE_2_INHALT, encoding="utf-8")
    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": WELLE_2})
    assert antwort.status_code == 200

    skript = (
        f"import * as detail from {json.dumps(DETAIL_JS.as_uri())};\n"
        + MINI_DOM
        + f"const BASIS = {json.dumps(app_server)};\n"
        + DETAIL_ECHTER_SERVER
        + r"""
const ergebnis = {};
for (const pfad of ["wellen/w1.md", "wellen/w2.md"]) {
  await detail.ladeDetail({ unterpunkt: pfad });
  const bereich = sammle(bei("detail")).find(
    (knoten) => knoten.marke === "section" && knoten.classList.contains("detail-abschnitt")
  );
  ergebnis[pfad] = {
    ueberschrift: sammle(bereich)
      .filter((knoten) => /^h[1-6]$/.test(knoten.marke))
      .map((knoten) => knoten.textContent),
    pfade: sammle(bereich)
      .filter((knoten) => knoten.marke === "tr" && knoten.dataset.path)
      .map((knoten) => knoten.dataset.path),
  };
}
console.log(JSON.stringify(ergebnis));
"""
    )
    ergebnis = node_ausfuehren(skript)

    assert ergebnis[WELLE_1]["ueberschrift"] == ["Aufgaben dieser Welle (0)"]
    assert ergebnis[WELLE_1]["pfade"] == []
    assert ergebnis[WELLE_2]["ueberschrift"] == ["Aufgaben dieser Welle (1)"]
    assert ergebnis[WELLE_2]["pfade"] == [AUFGABE]


DETAIL_ECHTER_SERVER = r"""
const fehler = document.createElement("div");
fehler.id = "fehler";
fehler.hidden = true;
fehler._imDokument = true;
const meldung = document.createElement("div");
meldung.id = "meldung";
meldung.hidden = true;
meldung._imDokument = true;
const ziel = document.createElement("div");
ziel.id = "detail";
ziel._imDokument = true;

const echtesFetch = globalThis.fetch;
globalThis.fetch = (pfad, optionen = {}) =>
  echtesFetch(new URL(String(pfad), BASIS), optionen);
"""


def test_t40_a13_anlegen_mit_welle_bleibt_unveraendert(client, bundle):
    daten = {
        "titel": "A98: Neue Aufgabe mit Welle",
        "ziel": "Ziel der neuen Aufgabe.",
        "akzeptanz": ["Erstes Kriterium."],
        "prioritaet": "hoch",
        "welle": WELLE_1,
    }

    antwort = client.post("/api/task", json=daten)

    assert antwort.status_code == 200
    pfad = antwort.get_json()["path"]
    inhalt = (bundle / pfad).read_text(encoding="utf-8")
    assert f"welle: {WELLE_1}" in inhalt
    assert okf_bundle.lesen(pfad)[0]["welle"] == WELLE_1


@pytest.mark.parametrize("datei", [INDEX_HTML, STYLE_CSS, APP_JS, API_JS, FORMULARE_JS])
def test_t40_a13_und_rahmen_dateien_ohne_a27_markup(datei):
    quelle = lies(datei)
    assert 'id="filter-welle"' not in quelle
    assert 'id="filter-welle-aufgaben"' not in quelle
    assert "detail-welle" not in quelle


def test_t40_server_ohne_neuen_endpunkt():
    quelle = lies(SERVER_PY)
    assert "/api/welle" in quelle
    assert "/api/meta" in quelle
    assert not re.search(r'"/api/(welle|wellen)-[a-z]+"', quelle)


# --- E. Regression: A11/A25-Verträge und die zwei A25-Kleinbefunde --------


@ohne_node
def test_t39_a11_und_a25_vertraege_bleiben():
    voll = js_liste("liste.waehleAnzeige(daten)", LISTEN_EINTRAEGE)
    assert voll["art"] == "tabelle"
    assert [eintrag["path"] for eintrag in voll["eintraege"]] == [
        eintrag["path"] for eintrag in LISTEN_EINTRAEGE
    ]

    ohne_welle = js_liste("liste.waehleAnzeige(daten, { status: 'Klarung' })", LISTEN_EINTRAEGE)
    assert [eintrag["path"] for eintrag in ohne_welle["eintraege"]] == ["aufgaben/a2.md"]

    assert js_liste("liste.waehleAnzeige(null).text", None) == "Einträge konnten nicht geladen werden."
    assert js_liste("liste.waehleAnzeige([]).text", None) == KEINE_EINTRAEGE


@ohne_node
def test_a25_befund_1_verwaistes_suchfeld_wird_neu_montiert():
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
const erstes = bei("suche-uebersicht");
const gruppe = erstes.parentElement;
gruppe.remove();
const verwaist = erstes.isConnected === false;
await liste.ladeUebersicht();
const zweites = bei("suche-uebersicht");
return {
  verwaist,
  neu: zweites !== erstes,
  verbunden: zweites.isConnected === true,
  imBaum: sammle(bei("ansicht-uebersicht")).includes(zweites),
  anzahl: anzahl("ansicht-uebersicht", "suche-uebersicht"),
};
""",
        listen_antwort(LISTEN_EINTRAEGE),
    )
    assert ergebnis["verwaist"] is True
    assert ergebnis["neu"] is True
    assert ergebnis["verbunden"] is True
    assert ergebnis["imBaum"] is True
    assert ergebnis["anzahl"] == 1


@ohne_node
def test_a25_befund_2_leerzustand_erscheint_nur_einmal():
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
return {
  tabelle: bei("tabelle").textContent,
  zuletzt: bei("uebersicht-zuletzt").textContent,
  klarung: bei("uebersicht-klarung").textContent,
  leerEintraege: sammle(bei("ansicht-uebersicht")).filter(
    (knoten) => knoten.marke === "p" && knoten.textContent === "Keine Einträge."
  ).length,
};
""",
        listen_antwort([]),
    )
    assert ergebnis["tabelle"] == KEINE_EINTRAEGE
    assert ergebnis["zuletzt"] == ""
    assert ergebnis["klarung"] == "Keine offenen Rückfragen."
    assert ergebnis["leerEintraege"] == 1
