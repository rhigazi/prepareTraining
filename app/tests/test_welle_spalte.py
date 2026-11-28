"""Prüfungen für die Wellen-Spalte in Übersicht und Aufgabenliste (A31).

Die UI-Szenarien S1–S4 spielt der ``tester`` mit dem Moli-Browser durch; hier
wird ``liste.js`` ohne Browser geprüft. Der Harness (Mini-DOM + Node-Runner)
liegt in ``dom_helfer.py``; diese Datei bringt ein eigenes, minimales Seiten-/
Fetch-Gerüst mit (kein Eingriff in die A30-Testlogik).

Bewusster Vertragswechsel (AK-8): Übersicht und Aufgabenliste haben fünf
Spalten, Wellenliste und Wellen-Detail bleiben bei vier.

Alle Läufe arbeiten gegen Fetch-Antworten aus dem Stab — nie gegen ``wissen/``.
"""

import json
import re
from pathlib import Path

import pytest

from dom_helfer import DETAIL_JS, LISTE_JS, MINI_DOM, js_detail, lies, node_ausfuehren, ohne_node

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
INDEX_HTML = STATIC_DIR / "index.html"
STYLE_CSS = STATIC_DIR / "style.css"
APP_JS = STATIC_DIR / "js" / "app.js"
API_JS = STATIC_DIR / "js" / "api.js"
DETAIL_JS_PFAD = STATIC_DIR / "js" / "detail.js"

# A31-K3: Im verteilten Projekt (installiertes Layout, ``<ziel>/app/tests/``)
# fehlt ``setup.sh`` im Projektwurzelverzeichnis. T19–T21 prüfen nur den
# Definitions-Arbeitsbaum (Baseline-Testdateien, Markup-Quellen) und liefern
# dort keinen Verhaltensnachweis — Muster wie ``test_setup_verteilung.py``.
NUR_DEFINITIONS_REPO = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "setup.sh").is_file(),
    reason="Setup-Skripte nur im Definitions-Repo vorhanden (setup.sh fehlt im "
    "installierten Zielprojekt; T19-T21 pruefen Definitions-Arbeitsbaum-Marker "
    "und liefern dort keinen Verhaltensnachweis, A31-K3)",
)

SPALTEN_FUENF = ["Titel", "Welle", "Status", "owner", "zuletzt geändert"]
SPALTEN_VIER = ["Titel", "Status", "owner", "zuletzt geändert"]
KEINE_ANGABE = "—"
KEINE_EINTRAEGE = "Keine Einträge."
LADE_FEHLER = "Einträge konnten nicht geladen werden."
FORMAT_FEHLER = "Einträge haben ein unerwartetes Format."

HTML_PAYLOAD = "<img src=x onerror=alert(1)>"

WELLE_1 = "wellen/w1.md"
WELLE_2 = "wellen/w2.md"
WELLE_3 = "wellen/w3.md"


def _aufgabe(pfad: str, titel: str, status: str = "In Arbeit", **felder) -> dict:
    eintrag = {
        "path": pfad,
        "titel": titel,
        "typ": "Task",
        "status": status,
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-15T10:00:00",
        # A28/A31-K1: Das Feld ``neu`` wird bewusst **weggelassen** (nicht auf
        # ``false`` gesetzt) — fehlendes ``neu`` gilt wie ``false``, also keine
        # Marke. Die Marke „standardmäßig an" decken A28-T23–T25 ab.
    }
    eintrag.update(felder)
    return eintrag


def _welle(pfad: str, titel: str | None, **felder) -> dict:
    eintrag = {
        "path": pfad,
        "titel": titel if titel is not None else "",
        "typ": "Welle",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T10:00:00",
    }
    eintrag.update(felder)
    return eintrag


MIT_WELLE = _aufgabe("aufgaben/a1.md", "A1: Mit Welle", welle=WELLE_2)
OHNE_WELLE = _aufgabe("aufgaben/a2.md", "A2: Ohne Welle", status="Offen")
WELLE_2_EINTRAG = _welle(WELLE_2, "W2")

# --- Seiten-/Fetch-Gerüst für die Listen ----------------------------------

LISTEN_SEITE = r"""
// Ansichtsgerüst wie in index.html (A10/A11): je Ansicht ein Filterformular
// mit Status/owner/Zurücksetzen, ein Tabellencontainer und die Zusatzblöcke
// der Übersicht.
const ANSICHTEN_DOM = [
  {
    ansicht: "ansicht-uebersicht",
    formular: "filter",
    status: "filter-status",
    owner: "filter-owner",
    zuruecksetzen: "filter-zuruecksetzen",
    tabelle: "tabelle",
    zusatz: true,
  },
  {
    ansicht: "ansicht-wellen",
    formular: "filter-wellen",
    status: "filter-wellen-status",
    owner: "filter-wellen-owner",
    zuruecksetzen: "filter-wellen-zuruecksetzen",
    tabelle: "tabelle-wellen",
  },
  {
    ansicht: "ansicht-aufgaben",
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
  titel.textContent = eintrag.ansicht;
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

// Zeilen einer Tabelle mit Zelltexten, Zell-Tooltips und data-path.
const zeilenDetails = (id) =>
  sammle(bei(id))
    .filter((knoten) => knoten.marke === "tr" && knoten.dataset.path)
    .map((zeile) => ({
      path: zeile.dataset.path,
      zellen: zeile.kinder.map((zelle) => ({ text: zelle.textContent, title: zelle.title || "" })),
    }));
const texte = (id) => zeilenDetails(id).map((zeile) => zeile.zellen.map((zelle) => zelle.text));
const tabellen = (id) => sammle(bei(id)).filter((knoten) => knoten.marke === "table").length;
"""


def listen_lauf(ablauf: str, antworten: dict) -> dict:
    """Führt einen Ablauf im Listen-Gerüst mit Fetch-Stab aus."""
    skript = (
        MINI_DOM
        + LISTEN_SEITE
        + LISTEN_STAB.replace("__ANTWORTEN__", json.dumps(antworten, ensure_ascii=False))
        + f"\nimport * as liste from {json.dumps(LISTE_JS.as_uri())};\n"
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


def listen_antwort(daten, endpunkt: str = "/api/overview") -> dict:
    return {endpunkt: {"status": 200, "koerper": daten}}


# --- Detail-Gerüst (nur für den Wellen-Abschnitt) ------------------------

DETAIL_SEITE = r"""
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
const antworte = (status, koerper) => ({
  ok: status < 400,
  status,
  headers: { get: () => "application/json" },
  text: async () => JSON.stringify(koerper ?? null),
});

globalThis.fetch = async (pfad, optionen = {}) => {
  const adresse = String(pfad);
  const methode = optionen.method || "GET";
  aufrufe.push({ methode, endpunkt: adresse.split("?")[0] });
  if (methode === "GET" && adresse.startsWith("/api/file")) return antworte(200, DATEI);
  if (methode === "GET" && adresse === "/api/wellen") return antworte(200, WELLEN);
  if (methode === "GET" && adresse === "/api/aufgaben") return antworte(200, AUFGABEN);
  return antworte(404, { error: "Nicht gefunden." });
};
"""


def detail_lauf(ablauf: str, datei: dict, wellen=None, aufgaben=None) -> dict:
    """Führt einen Ablauf in der Detailansicht mit Fetch-Stab aus."""
    skript = (
        MINI_DOM
        + f"const DATEI = {json.dumps(datei, ensure_ascii=False)};\n"
        + f"const WELLEN = {json.dumps(wellen or [], ensure_ascii=False)};\n"
        + f"const AUFGABEN = {json.dumps(aufgaben or [], ensure_ascii=False)};\n"
        + DETAIL_SEITE
        + f"\nimport * as detail from {json.dumps(DETAIL_JS.as_uri())};\n"
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


# --- A. Spalte und Grundanzeige (AK-1, AK-4) -----------------------------


@ohne_node
def test_t1_uebersicht_hat_fuenf_spalten():
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
const zeilen = zeilenDetails("tabelle");
return {
  kopf: kopfzeilen("tabelle"),
  zeilen: zeilen,
  texte: zeilen.map((zeile) => zeile.zellen.map((zelle) => zelle.text)),
  top5: kopfzeilen("uebersicht-zuletzt"),
};
""",
        listen_antwort([MIT_WELLE, OHNE_WELLE, WELLE_2_EINTRAG]),
    )

    assert ergebnis["kopf"] == SPALTEN_FUENF
    assert [zeile["path"] for zeile in ergebnis["zeilen"]] == [
        "aufgaben/a1.md",
        "aufgaben/a2.md",
        WELLE_2,
    ]
    for zellen in ergebnis["texte"]:
        assert len(zellen) == 5
    # Welle an Position 2 (Index 1); Titel bleibt Spalte 1, Status folgt danach.
    assert ergebnis["texte"][0][0] == "A1: Mit Welle"
    assert ergebnis["texte"][0][2] == "In Arbeit"
    assert ergebnis["texte"][0][3] == "ai"
    assert ergebnis["texte"][0][4]
    # Auch der Top-5-Block der Übersicht trägt die Wellen-Spalte.
    assert ergebnis["top5"] == SPALTEN_FUENF


@ohne_node
def test_t2_aufgabenliste_hat_fuenf_spalten():
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
return {
  kopf: kopfzeilen("tabelle-aufgaben"),
  zeilen: zeilenDetails("tabelle-aufgaben"),
};
""",
        listen_antwort([MIT_WELLE, OHNE_WELLE], "/api/aufgaben"),
    )

    assert ergebnis["kopf"] == SPALTEN_FUENF
    assert [zeile["path"] for zeile in ergebnis["zeilen"]] == ["aufgaben/a1.md", "aufgaben/a2.md"]
    mit, ohne = ergebnis["zeilen"]
    # Zuordnung vorhanden: die Wellen-Zelle zeigt den Titel (T6 vertieft das).
    assert mit["zellen"][1]["text"]
    assert mit["zellen"][1]["text"] != KEINE_ANGABE
    # Ohne Zuordnung: dezentes „—" in der Wellen-Spalte, Rest unverändert.
    assert ohne["zellen"][1]["text"] == KEINE_ANGABE
    assert ohne["zellen"][1]["title"] == ""
    assert ohne["zellen"][0]["text"] == "A2: Ohne Welle"
    assert ohne["zellen"][2]["text"] == "Offen"


@ohne_node
def test_t3_wellenliste_bleibt_bei_vier_spalten():
    ergebnis = listen_lauf(
        r"""
await liste.ladeWellen();
return {
  kopf: kopfzeilen("tabelle-wellen"),
  zeilen: zeilenDetails("tabelle-wellen"),
};
""",
        listen_antwort([_welle(WELLE_1, "W1"), WELLE_2_EINTRAG], "/api/wellen"),
    )

    assert ergebnis["kopf"] == SPALTEN_VIER
    assert [zeile["path"] for zeile in ergebnis["zeilen"]] == [
        "wellen/w1.md",
        "wellen/w2.md",
    ]
    for zeile in ergebnis["zeilen"]:
        assert len(zeile["zellen"]) == 4


@ohne_node
def test_t4_wellen_detail_bleibt_bei_vier_spalten():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "wellen/w1.md" });
const bereich = sammle(bei("detail")).find(
  (knoten) => knoten.marke === "section" && knoten.classList.contains("detail-abschnitt")
);
return {
  kopf: bereich
    ? sammle(bereich).filter((knoten) => knoten.marke === "th").map((knoten) => knoten.textContent)
    : [],
  pfade: bereich
    ? sammle(bereich)
        .filter((knoten) => knoten.marke === "tr" && knoten.dataset.path)
        .map((knoten) => knoten.dataset.path)
    : [],
};
""",
        {"frontmatter": {"type": "Welle", "title": "Welle 1"}, "markdown": "# Ziel\n"},
        wellen=[WELLE_2_EINTRAG],
        aufgaben=[
            _aufgabe("aufgaben/a1.md", "A1", welle=WELLE_1),
            _aufgabe("aufgaben/a2.md", "A2", welle=WELLE_1),
        ],
    )

    assert ergebnis["kopf"] == SPALTEN_VIER
    assert ergebnis["pfade"] == ["aufgaben/a1.md", "aufgaben/a2.md"]


@ohne_node
def test_t5_spaltenzahl_bleibt_konstant():
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
const nachLaden = kopfzeilen("tabelle");
bei("filter-status").value = "In Arbeit";
await ausloesen(bei("filter-status"), "change");
const nachFilter = kopfzeilen("tabelle");
bei("suche-uebersicht").value = "gibtsnicht";
await ausloesen(bei("suche-uebersicht"), "input");
const ohneTreffer = kopfzeilen("tabelle");
const ohneTrefferTabellen = sammle(bei("tabelle")).filter(
  (knoten) => knoten.marke === "table"
).length;
const leerText = bei("tabelle").textContent;
await ausloesen(bei("filter-zuruecksetzen"), "click");
const nachReset = kopfzeilen("tabelle");
await liste.ladeAufgaben();
const aufgaben = kopfzeilen("tabelle-aufgaben");
await liste.ladeWellen();
return {
  nachLaden,
  nachFilter,
  ohneTreffer,
  ohneTrefferTabellen,
  leerText,
  nachReset,
  aufgaben,
  wellen: kopfzeilen("tabelle-wellen"),
};
""",
        {
            "/api/overview": {"status": 200, "koerper": [MIT_WELLE, OHNE_WELLE, WELLE_2_EINTRAG]},
            "/api/aufgaben": {"status": 200, "koerper": [MIT_WELLE]},
            "/api/wellen": {"status": 200, "koerper": [WELLE_2_EINTRAG]},
        },
    )

    assert ergebnis["nachLaden"] == SPALTEN_FUENF
    assert ergebnis["nachFilter"] == SPALTEN_FUENF
    # Leerzustand: kein Tabellenkopf und keine halb aufgebaute Tabelle (A11/A25).
    assert ergebnis["ohneTreffer"] == []
    assert ergebnis["ohneTrefferTabellen"] == 0
    assert ergebnis["leerText"] == "Keine Treffer."
    assert ergebnis["nachReset"] == SPALTEN_FUENF
    assert ergebnis["aufgaben"] == SPALTEN_FUENF
    assert ergebnis["wellen"] == SPALTEN_VIER


@ohne_node
def test_t8_ohne_zuordnung_zeigt_strich():
    daten = [
        _aufgabe("aufgaben/a1.md", "A1: Ohne Feld"),
        _aufgabe("aufgaben/a2.md", "A2: Leer", welle=""),
        _aufgabe("aufgaben/a3.md", "A3: Null", welle=None),
    ]
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
return { zeilen: zeilenDetails("tabelle-aufgaben") };
""",
        listen_antwort(daten, "/api/aufgaben"),
    )

    for zeile in ergebnis["zeilen"]:
        assert zeile["zellen"][1]["text"] == KEINE_ANGABE
        assert zeile["zellen"][1]["title"] == ""
    assert [zeile["zellen"][0]["text"] for zeile in ergebnis["zeilen"]] == [
        "A1: Ohne Feld",
        "A2: Leer",
        "A3: Null",
    ]
    assert [zeile["zellen"][2]["text"] for zeile in ergebnis["zeilen"]] == [
        "In Arbeit",
        "In Arbeit",
        "In Arbeit",
    ]


# --- B. Auflösung und Fallbacks (AK-2, AK-3) -----------------------------


@ohne_node
def test_t6_zeigt_den_wellen_titel_mit_pfad_tooltip():
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
return {
  zeilen: zeilenDetails("tabelle"),
  titelZelle: zeilenDetails("tabelle")[0].zellen[0],
};
""",
        listen_antwort([MIT_WELLE, WELLE_2_EINTRAG]),
    )

    mit = ergebnis["zeilen"][0]
    assert mit["zellen"][1] == {"text": "W2", "title": WELLE_2}
    assert WELLE_2 not in mit["zellen"][1]["text"]
    # Kein Badge in der Titel-Zelle: dort steht nur der Aufgabentitel.
    assert mit["zellen"][0]["text"] == "A1: Mit Welle"


@ohne_node
def test_t7_mehrere_zuordnungen_bleiben_getrennt():
    daten = [
        _aufgabe("aufgaben/a1.md", "A1", welle=WELLE_1),
        _aufgabe("aufgaben/a2.md", "A2", welle=WELLE_2),
        _aufgabe("aufgaben/a3.md", "A3", welle=WELLE_3),
        _welle(WELLE_1, "W1"),
        _welle(WELLE_2, "W2"),
        _welle(WELLE_3, None),
    ]
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
return { zeilen: zeilenDetails("tabelle-aufgaben") };
""",
        listen_antwort(daten, "/api/aufgaben"),
    )

    aufgaben = [zeile for zeile in ergebnis["zeilen"] if zeile["path"].startswith("aufgaben/")]
    assert [(zeile["path"], zeile["zellen"][1]["text"]) for zeile in aufgaben] == [
        ("aufgaben/a1.md", "W1"),
        ("aufgaben/a2.md", "W2"),
        ("aufgaben/a3.md", WELLE_3),
    ]
    for zeile in aufgaben:
        assert zeile["zellen"][1]["title"] == zeile["zellen"][1]["title"].strip()
        assert zeile["zellen"][1]["text"] != ""


@ohne_node
def test_t9_falsche_typen_und_leerraum():
    daten = [
        _aufgabe("aufgaben/a1.md", "A1", welle=42),
        _aufgabe("aufgaben/a2.md", "A2", welle={}),
        _aufgabe("aufgaben/a3.md", "A3", welle=[]),
        _aufgabe("aufgaben/a4.md", "A4", welle="   "),
        _aufgabe("aufgaben/a5.md", "A5", welle=f" {WELLE_2} "),
        _welle(WELLE_2, "W2"),
    ]
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
return { zeilen: zeilenDetails("tabelle-aufgaben") };
""",
        listen_antwort(daten, "/api/aufgaben"),
    )

    aufgaben = [zeile for zeile in ergebnis["zeilen"] if zeile["path"].startswith("aufgaben/")]
    assert [zeile["zellen"][1]["text"] for zeile in aufgaben] == [
        KEINE_ANGABE,
        KEINE_ANGABE,
        KEINE_ANGABE,
        KEINE_ANGABE,
        "W2",
    ]
    # Getrimmter Pfad, keine Dublette: genau eine Wellen-Zeile mit Tooltip.
    assert aufgaben[4]["zellen"][1]["title"] == WELLE_2


@ohne_node
def test_t10_dangling_welle_zeigt_den_pfad():
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
return { zeilen: zeilenDetails("tabelle-aufgaben") };
""",
        listen_antwort(
            [_aufgabe("aufgaben/a1.md", "A1", welle="wellen/geloescht.md")],
            "/api/aufgaben",
        ),
    )

    zelle = ergebnis["zeilen"][0]["zellen"][1]
    assert zelle["text"] == "wellen/geloescht.md"
    assert zelle["title"] in ("", "wellen/geloescht.md")


@ohne_node
def test_t11_deep_link_zeigt_pfad_und_nutzt_danach_den_cache():
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
const ohneUebersicht = texte("tabelle-aufgaben")[0][1];
const aufrufeErste = aufrufe.map((eintrag) => eintrag.endpunkt);
await liste.ladeUebersicht();
await liste.ladeAufgaben();
return {
  ohneUebersicht,
  mitUebersicht: texte("tabelle-aufgaben")[0][1],
  aufrufeErste,
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt),
  wellenAbrufe: aufrufe.filter((eintrag) => eintrag.endpunkt === "/api/wellen").length,
};
""",
        {
            "/api/aufgaben": {"status": 200, "koerper": [MIT_WELLE]},
            "/api/overview": {"status": 200, "koerper": [MIT_WELLE, WELLE_2_EINTRAG]},
        },
    )

    assert ergebnis["ohneUebersicht"] == WELLE_2
    assert ergebnis["aufrufeErste"] == ["/api/aufgaben"]
    assert ergebnis["mitUebersicht"] == "W2"
    assert ergebnis["aufrufe"] == ["/api/aufgaben", "/api/overview", "/api/aufgaben"]
    assert ergebnis["wellenAbrufe"] == 0


@ohne_node
def test_t12_welle_ohne_titel_zeigt_den_pfad():
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
return { zeilen: zeilenDetails("tabelle-aufgaben") };
""",
        listen_antwort(
            [
                _aufgabe("aufgaben/a1.md", "A1", welle=WELLE_1),
                _aufgabe("aufgaben/a2.md", "A2", welle=WELLE_2),
                _welle(WELLE_1, None),
                _welle(WELLE_2, "W2"),
            ],
            "/api/aufgaben",
        ),
    )

    aufgaben = [zeile for zeile in ergebnis["zeilen"] if zeile["path"].startswith("aufgaben/")]
    ohne_titel, mit_titel = aufgaben
    assert ohne_titel["zellen"][1]["text"] == WELLE_1
    assert "(" not in ohne_titel["zellen"][1]["text"]
    assert mit_titel["zellen"][1]["text"] == "W2"
    assert "(" not in mit_titel["zellen"][1]["text"]


@ohne_node
def test_t13_lange_titel_werden_nicht_gekuerzt():
    langer_titel = "W" + "2" * 119
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
return { kopf: kopfzeilen("tabelle-aufgaben"), zeilen: zeilenDetails("tabelle-aufgaben") };
""",
        listen_antwort(
            [
                _aufgabe("aufgaben/a1.md", "A1", welle=WELLE_2),
                _welle(WELLE_2, langer_titel),
            ],
            "/api/aufgaben",
        ),
    )

    assert ergebnis["kopf"] == SPALTEN_FUENF
    assert ergebnis["zeilen"][0]["zellen"][1]["text"] == langer_titel
    assert len(ergebnis["zeilen"][0]["zellen"][1]["text"]) == 120


# --- C. Sicherheit (AK-5) ------------------------------------------------


@ohne_node
def test_t14_xss_bleibt_text():
    ausfuehrungen = []
    daten = [
        _aufgabe("aufgaben/a1.md", "A1", welle=WELLE_2),
        _aufgabe("aufgaben/a2.md", "A2", welle="<script>alert(1)</script>"),
        _welle(WELLE_2, HTML_PAYLOAD),
    ]
    ergebnis = listen_lauf(
        r"""
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await liste.ladeUebersicht();
return {
  zeilen: zeilenDetails("tabelle"),
  marken: marken(bei("ansicht-uebersicht")),
  ausfuehrungen,
};
""",
        listen_antwort(daten),
    )

    assert ergebnis["zeilen"][0]["zellen"][1]["text"] == HTML_PAYLOAD
    assert ergebnis["zeilen"][1]["zellen"][1]["text"] == "<script>alert(1)</script>"
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []
    assert "innerHTML" not in lies(LISTE_JS)
    assert "insertAdjacentHTML" not in lies(LISTE_JS)
    assert "eval(" not in lies(LISTE_JS)


# --- D. Fehlerzustand, Kombination und Regression (AK-4, AK-6) ----------


@ohne_node
@pytest.mark.parametrize(
    "daten,erwartet",
    [
        (None, LADE_FEHLER),
        ({}, FORMAT_FEHLER),
        (42, FORMAT_FEHLER),
        ([], KEINE_EINTRAEGE),
    ],
)
def test_t16_fehler_und_leerzustand_ohne_tabelle(daten, erwartet):
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
return {
  inhalt: bei("tabelle").textContent,
  tabellen: tabellen("tabelle"),
  kopf: kopfzeilen("tabelle"),
};
""",
        listen_antwort(daten),
    )

    assert ergebnis["inhalt"] == erwartet
    assert ergebnis["tabellen"] == 0
    assert ergebnis["kopf"] == []


@ohne_node
def test_t15_kombination_mit_dem_arbeitsstatus():
    daten = [
        _aufgabe(
            "aufgaben/a1.md",
            "A1: Kombination",
            welle=WELLE_2,
            arbeitsrolle="coder",
            arbeitsrolle_label="Coder",
            arbeitsstatus="Umsetzung Paket 2",
        ),
        WELLE_2_EINTRAG,
    ]
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
return { zeilen: zeilenDetails("tabelle") };
""",
        listen_antwort(daten),
    )

    zellen = ergebnis["zeilen"][0]["zellen"]
    status, welle = zellen[2]["text"], zellen[1]["text"]
    assert status.count("Coder: Umsetzung Paket 2") == 1
    assert welle == "W2"
    # Keine Doppelanzeige: Status-Zelle ohne Welle, Wellen-Zelle ohne Arbeitsstatus.
    assert "W2" not in status
    assert "Coder" not in welle
    assert "Umsetzung Paket 2" not in welle
    # Arbeitsstatus bleibt eine div-Zeile in der Status-Zelle (A30).
    assert ergebnis["zeilen"][0]["zellen"][2]["text"].startswith("In Arbeit")


@ohne_node
def test_t17_request_budget_bleibt_unveraendert():
    listen = listen_lauf(
        r"""
await liste.ladeUebersicht();
const uebersicht = aufrufe.map((eintrag) => eintrag.endpunkt);
await liste.ladeAufgaben();
const aufgaben = aufrufe.map((eintrag) => eintrag.endpunkt);
await liste.ladeWellen();
return { uebersicht, aufgaben, alle: aufrufe.map((eintrag) => eintrag.endpunkt) };
""",
        {
            "/api/overview": {"status": 200, "koerper": [MIT_WELLE, WELLE_2_EINTRAG]},
            "/api/aufgaben": {"status": 200, "koerper": [MIT_WELLE]},
            "/api/wellen": {"status": 200, "koerper": [WELLE_2_EINTRAG]},
        },
    )
    assert listen["uebersicht"] == ["/api/overview"]
    assert listen["aufgaben"] == ["/api/overview", "/api/aufgaben"]
    assert listen["alle"] == ["/api/overview", "/api/aufgaben", "/api/wellen"]

    detail = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
return { aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt) };
""",
        {
            "frontmatter": {"type": "Task", "title": "A1", "task_status": "in Umsetzung"},
            "markdown": "# Ziel\n",
            "nachtraege": [],
        },
        wellen=[WELLE_2_EINTRAG],
    )
    # A34/T43: Aufgaben-Details laden zusätzlich ``/api/aufgaben`` (Unter-Aufgaben).
    assert detail["aufrufe"] == ["/api/file", "/api/wellen", "/api/aufgaben"]


@ohne_node
def test_t18_filter_suche_und_reset_mit_wellen_spalte():
    daten = [
        _aufgabe("aufgaben/a1.md", "A1: Erste", welle=WELLE_2),
        _aufgabe("aufgaben/a2.md", "A2: Zweite", status="Klarung", owner="mensch", welle=WELLE_2),
        _aufgabe("aufgaben/a3.md", "A3: Dritte", welle=WELLE_1),
        _welle(WELLE_1, "W1"),
        _welle(WELLE_2, "Alpha"),
    ]
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
bei("filter-welle").value = "wellen/w2.md";
await ausloesen(bei("filter-welle"), "change");
const nurWelle = texte("tabelle");
bei("filter-status").value = "Klarung";
await ausloesen(bei("filter-status"), "change");
const mitStatus = texte("tabelle");
bei("filter-owner").value = "mensch";
await ausloesen(bei("filter-owner"), "change");
const mitOwner = texte("tabelle");
bei("suche-uebersicht").value = "a2";
await ausloesen(bei("suche-uebersicht"), "input");
const mitSuche = texte("tabelle");
bei("suche-uebersicht").value = "alpha";
await ausloesen(bei("suche-uebersicht"), "input");
const nurTitel = bei("tabelle").textContent;
const nurTitelTabellen = sammle(bei("tabelle")).filter((knoten) => knoten.marke === "table").length;
await ausloesen(bei("filter-zuruecksetzen"), "click");
return {
  nurWelle,
  mitStatus,
  mitOwner,
  mitSuche,
  nurTitel,
  nurTitelTabellen,
  nachReset: zeilenDetails("tabelle")
    .filter((zeile) => zeile.path.startsWith("aufgaben/"))
    .map((zeile) => [zeile.zellen[0].text, zeile.zellen[1].text]),
  kopfNachReset: kopfzeilen("tabelle"),
  wellenFilter: bei("filter-welle").value,
  statusFilter: bei("filter-status").value,
  ownerFilter: bei("filter-owner").value,
  suche: bei("suche-uebersicht").value,
};
""",
        listen_antwort(daten),
    )

    assert [(zeile[0], zeile[1]) for zeile in ergebnis["nurWelle"]] == [
        ("A1: Erste", "Alpha"),
        ("A2: Zweite", "Alpha"),
    ]
    assert [(zeile[0], zeile[1]) for zeile in ergebnis["mitStatus"]] == [("A2: Zweite", "Alpha")]
    assert [(zeile[0], zeile[1]) for zeile in ergebnis["mitOwner"]] == [("A2: Zweite", "Alpha")]
    assert [(zeile[0], zeile[1]) for zeile in ergebnis["mitSuche"]] == [("A2: Zweite", "Alpha")]
    # Der Wellen-Titel ist nicht durchsuchbar (nur der Pfad, A25 bleibt unberührt).
    assert ergebnis["nurTitel"] == "Keine Treffer."
    assert ergebnis["nurTitelTabellen"] == 0
    # Reset: Vollbestand, fünf Spalten, Titel weiterhin aufgelöst.
    assert ergebnis["kopfNachReset"] == SPALTEN_FUENF
    assert [(zeile[0], zeile[1]) for zeile in ergebnis["nachReset"]] == [
        ("A1: Erste", "Alpha"),
        ("A2: Zweite", "Alpha"),
        ("A3: Dritte", "W1"),
    ]
    assert ergebnis["wellenFilter"] == ""
    assert ergebnis["statusFilter"] == ""
    assert ergebnis["ownerFilter"] == ""
    assert ergebnis["suche"] == ""


# --- E. Grenzen und Vertragswechsel (AK-7, AK-8, AK-9) -----------------


@NUR_DEFINITIONS_REPO
def test_t20_grenzen_ohne_backend_und_markup_aenderung():
    for datei in (INDEX_HTML, STYLE_CSS, APP_JS, API_JS, DETAIL_JS_PFAD):
        quelle = lies(datei)
        assert "welleSpalte" not in quelle, datei
        assert "Wellen-Spalte" not in quelle, datei
    # Kein Spalten-Markup und kein neues Filterfeld (nur der Navigationslink „Wellen").
    assert ">Welle<" not in lies(INDEX_HTML)
    assert 'id="filter-welle"' not in lies(INDEX_HTML)

    liste = lies(LISTE_JS)
    assert "welleSpalte" in liste
    # Kein neuer Endpunkt, keine neue Abhängigkeit.
    assert set(re.findall(r"/api/[a-z_-]+", liste)) == {
        "/api/overview",
        "/api/aufgaben",
        "/api/wellen",
    }
    assert "import " not in liste.replace('import { getJson } from "./api.js";', "")


_KOPF_LITERAL = re.compile(r'\["Titel"(?:,\s*"[^"]*")*\]')
BASELINE_DATEIEN = ("test_suche.py", "test_welle_zuordnung.py", "test_arbeitsstand_ui.py")


def _kopf_erwartungen(datei: Path) -> set[tuple[str, ...]]:
    """Spalten-Erwartungen aus einem Testfile — nur echte ``assert``-Zeilen zählen.

    Reine Textsuche war zu locker (ein Literal im Kommentar hätte genügt, A31-H3).
    """
    erwartungen = set()
    for zeile in lies(datei).splitlines():
        if not zeile.strip().startswith("assert "):
            continue
        for treffer in _KOPF_LITERAL.findall(zeile):
            erwartungen.add(tuple(json.loads(treffer)))
    return erwartungen


@NUR_DEFINITIONS_REPO
def test_t21_a31_marker_lebt_nur_in_liste_js():
    """A31-H3: Die Wellen-Spalte lebt nur in ``liste.js``; die Wellenliste bleibt bei vier."""
    for datei in sorted((STATIC_DIR / "js").glob("*.js")):
        if datei.name == "liste.js":
            continue
        assert "welleSpalte" not in lies(datei), datei
    for datei in (INDEX_HTML, STYLE_CSS):
        quelle = lies(datei)
        assert "welleSpalte" not in quelle, datei
        assert "Wellen-Spalte" not in quelle, datei

    ergebnis = listen_lauf(
        r"""
await liste.ladeWellen();
return { kopf: kopfzeilen("tabelle-wellen"), texte: texte("tabelle-wellen") };
""",
        listen_antwort([_welle(WELLE_2, "W2")], "/api/wellen"),
    )
    assert ergebnis["kopf"] == SPALTEN_VIER
    assert len(ergebnis["texte"][0]) == len(SPALTEN_VIER)


# --- F. Vertragswechsel (AK-8) ------------------------------------------


@NUR_DEFINITIONS_REPO
@ohne_node
def test_t19_baselines_erwarten_die_fuenf_spalten():
    """A31-H3: Die fünf Spalten kommen aus der Implementierung UND aus den Baselines."""
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
return { kopf: kopfzeilen("tabelle") };
""",
        listen_antwort([_aufgabe("aufgaben/a1.md", "A1", welle=WELLE_2), WELLE_2_EINTRAG]),
    )
    assert ergebnis["kopf"] == SPALTEN_FUENF

    for datei in BASELINE_DATEIEN:
        erwartungen = _kopf_erwartungen(Path(__file__).parent / datei)
        assert tuple(SPALTEN_FUENF) in erwartungen, f"{datei} erwartet die fünf Spalten nicht"
        if datei != "test_welle_zuordnung.py":
            assert tuple(SPALTEN_VIER) not in erwartungen, f"{datei} erwartet noch vier Spalten"

    # Wellen-Detail (T34 in test_welle_zuordnung.py) bleibt bei vier Spalten.
    assert tuple(SPALTEN_VIER) in _kopf_erwartungen(
        Path(__file__).parent / "test_welle_zuordnung.py"
    )


# --- G. A33-Nachträge (A27-F1/K2, A31-H1) --------------------------------

WELLE_1_EINTRAG = _welle(WELLE_1, "W1")


@ohne_node
def test_a33_t22_k2_wellenliste_fuellt_den_options_cache():
    """A27-K2: `/api/wellen` liefert den vollständigen Bestand — Cache erneuern."""
    ergebnis = listen_lauf(
        r"""
await liste.ladeWellen();
await liste.ladeAufgaben();
return {
  optionen: optionenwerte(bei("filter-welle-aufgaben")),
  texte: texte("tabelle-aufgaben"),
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt),
};
""",
        {
            "/api/wellen": {"status": 200, "koerper": [WELLE_1_EINTRAG, WELLE_2_EINTRAG]},
            "/api/aufgaben": {"status": 200, "koerper": [MIT_WELLE]},
        },
    )

    assert ergebnis["optionen"] == ["", "ohne", WELLE_1, WELLE_2]
    assert ergebnis["texte"][0][1] == "W2"
    assert ergebnis["aufrufe"] == ["/api/wellen", "/api/aufgaben"]


@ohne_node
def test_a33_t23_h1_titel_cache_ohne_filterformular():
    """A31-H1: Ohne Wellen-Filterformular steht trotzdem der Titel in der Spalte."""
    ergebnis = listen_lauf(
        r"""
REGISTRIERT.delete("filter-aufgaben");
await liste.ladeAufgaben();
return { zeilen: texte("tabelle-aufgaben") };
""",
        listen_antwort([MIT_WELLE, WELLE_2_EINTRAG], "/api/aufgaben"),
    )

    assert ergebnis["zeilen"][0][1] == "W2"


@ohne_node
def test_a33_t24_f1_deep_link_laedt_wellen_bei_erster_filter_interaktion():
    """A27-F1: Der Deep-Link lädt den Wellen-Bestand erst bei der ersten Interaktion."""
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
const vorher = optionenwerte(bei("filter-welle-aufgaben"));
await ausloesen(bei("filter-welle-aufgaben"), "focus");
const nachher = optionenwerte(bei("filter-welle-aufgaben"));
const nachErstem = aufrufe.map((eintrag) => eintrag.endpunkt);
bei("filter-welle-aufgaben").value = "wellen/w1.md";
await ausloesen(bei("filter-welle-aufgaben"), "focus");
return {
  vorher,
  nachher,
  nachErstem,
  auswahl: bei("filter-welle-aufgaben").value,
  wellenAbrufe: aufrufe.filter((eintrag) => eintrag.endpunkt === "/api/wellen").length,
};
""",
        {
            "/api/aufgaben": {"status": 200, "koerper": [MIT_WELLE]},
            "/api/wellen": {"status": 200, "koerper": [WELLE_1_EINTRAG, WELLE_2_EINTRAG]},
        },
    )

    assert ergebnis["vorher"] == ["", "ohne", WELLE_2]
    assert ergebnis["nachher"] == ["", "ohne", WELLE_1, WELLE_2]
    assert ergebnis["nachErstem"] == ["/api/aufgaben", "/api/wellen"]
    assert ergebnis["auswahl"] == WELLE_1
    assert ergebnis["wellenAbrufe"] == 1
