"""Prüfungen für die Arbeitsstatus-Anzeige (A30, Paket 2: UI).

Die UI-Szenarien S1–S4 spielt der ``tester`` mit dem Moli-Browser durch; hier
werden ``liste.js`` und ``detail.js`` ohne Browser geprüft. Der Harness
(Mini-DOM + Node-Runner) liegt in ``dom_helfer.py`` — der konsolidierten Quelle;
hier stehen nur das Seiten-/Fetch-Gerüst und die Prüfungen T14–T20.

Alle Läufe arbeiten gegen Fetch-Antworten aus dem Stab — nie gegen ``wissen/``.
"""

import json
import re
from pathlib import Path

import pytest

from dom_helfer import (
    DETAIL_JS,
    LISTE_JS,
    MINI_DOM,
    js_detail,
    js_liste,
    lies,
    node_ausfuehren,
    ohne_node,
)

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
INDEX_HTML = STATIC_DIR / "index.html"
STYLE_CSS = STATIC_DIR / "style.css"
APP_JS = STATIC_DIR / "js" / "app.js"
API_JS = STATIC_DIR / "js" / "api.js"

HTML_PAYLOAD = "<img src=x onerror=alert(1)>"
SCRIPT_PAYLOAD = "<script>alert(1)</script>"

ARBEITSSTAND = "Coder: Umsetzung Paket 2"


def _aufgabe(pfad: str, titel: str, status: str = "In Arbeit", **felder) -> dict:
    eintrag = {
        "path": pfad,
        "titel": titel,
        "typ": "Task",
        "status": status,
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-15T10:00:00",
    }
    eintrag.update(felder)
    return eintrag


MIT_ARBEITSSTAND = _aufgabe(
    "aufgaben/a30-arbeit.md",
    "A30: Was passiert gerade",
    arbeitsrolle="coder",
    arbeitsrolle_label="Coder",
    arbeitsstatus="Umsetzung Paket 2",
)
OHNE_ARBEITSSTAND = _aufgabe("aufgaben/a30-ohne.md", "A30: Ohne Arbeitsstand", status="Offen")

# --- Seiten-/Fetch-Gerüst für die Listen ----------------------------------

LISTEN_SEITE = r"""
// Ansichtsgerüst wie in index.html (A10/A11): je Ansicht ein Filterformular
// mit Status/owner/Zurücksetzen, ein Tabellencontainer und die Zusatzblöcke
// der Übersicht.
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

// Status-Zelle über ihre Marken (Klassen `status`/`arbeitsstand`) finden — nicht
// über den Spaltenindex; neue Spalten (z. B. „Welle") verschieben die Zelle (A31-H4).
const statusZelle = (zeile) => {
  const zelle = zeile.kinder.find((kind) =>
    sammle(kind).some(
      (knoten) =>
        knoten.classList.contains("status") || knoten.classList.contains("arbeitsstand"),
    ),
  );
  return zelle ? zelle.textContent : "";
};

// Zellenwerte über die Kopfzeile zuordnen — kein fester Spaltenindex (A42/T15):
// eine neue Spalte verschiebt die Zellen, der Kopf wandert mit.
const spalten = (id, zeile) => {
  const kopf = kopfzeilen(id);
  const werte = {};
  zeile.kinder.forEach((zelle, index) => {
    if (index < kopf.length) werte[kopf[index]] = zelle.textContent;
  });
  return werte;
};

// Zeilen einer Tabelle mit ihren Zelleninhalten und Arbeitsstand-Knoten.
const zeilen = (id) =>
  sammle(bei(id))
    .filter((knoten) => knoten.marke === "tr" && knoten.dataset.path)
    .map((zeile) => ({
      path: zeile.dataset.path,
      zellen: zeile.kinder.map((zelle) => zelle.textContent),
      spalten: spalten(id, zeile),
      status: statusZelle(zeile),
      arbeitsstaende: sammle(zeile)
        .filter((knoten) => knoten.classList.contains("arbeitsstand"))
        .map((knoten) => ({ marke: knoten.marke, text: knoten.textContent })),
    }));
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


# --- Detail-Gerüst -------------------------------------------------------

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
  aufrufe.push({ methode, endpunkt: adresse.split("?")[0], pfad: adresse });
  if (methode === "GET" && adresse.startsWith("/api/file")) return antworte(200, DATEI);
  if (methode === "GET" && adresse === "/api/wellen") return antworte(200, WELLEN);
  if (methode === "GET" && adresse === "/api/aufgaben") return antworte(200, AUFGABEN);
  return antworte(404, { error: "Nicht gefunden." });
};

// Felder des Kopfes (`dt`/`dd`-Paare in Reihenfolge).
const kopfFelder = () => {
  const kopf = sammle(bei("detail")).find((knoten) => knoten.classList.contains("detail-kopf"));
  return kopf
    ? sammle(kopf)
        .filter((knoten) => knoten.marke === "dt")
        .map((knoten) => ({ name: knoten.textContent }))
    : [];
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


def _datei(frontmatter: dict, markdown: str = "# Ziel\n\nFixture-Ziel.\n", **felder) -> dict:
    """Baut eine `/api/file`-Antwort; ``felder`` sind die abgeleiteten Top-Level-Felder."""
    daten = {"frontmatter": frontmatter, "markdown": markdown, "nachtraege": []}
    daten.update(felder)
    return daten


# --- T14: Formatter -------------------------------------------------------


@ohne_node
def test_t14_formatiere_arbeitsstand():
    assert js_liste(
        "liste.formatiereArbeitsstand({ arbeitsrolle_label: 'Coder',"
        " arbeitsstatus: 'Umsetzung Paket 2' })"
    ) == ARBEITSSTAND
    assert js_liste("liste.formatiereArbeitsstand({ arbeitsrolle_label: 'Coder' })") == "Coder"
    assert js_liste("liste.formatiereArbeitsstand({ arbeitsstatus: 'Umsetzung Paket 2' })") == (
        "Umsetzung Paket 2"
    )
    assert js_liste(
        "liste.formatiereArbeitsstand({ arbeitsrolle_label: 'Architekt', arbeitsstatus: 'Konzept' })"
    ) == "Architekt: Konzept"


@pytest.mark.parametrize("quelle", ["{}", "null", "undefined", "42", "[]", "'Coder'"])
@ohne_node
def test_t14_formatter_ohne_angabe_ist_leer(quelle):
    assert js_liste(f"liste.formatiereArbeitsstand({quelle})") == ""


# --- T15: Status-Zelle ---------------------------------------------------


@ohne_node
def test_t15_status_zelle_zeigt_arbeitsstand():
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
return {
  zeilen: zeilen("tabelle-aufgaben"),
  kopf: kopfzeilen("tabelle-aufgaben"),
  marken: marken(bei("tabelle-aufgaben")),
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt),
};
""",
        listen_antwort([MIT_ARBEITSSTAND, OHNE_ARBEITSSTAND], "/api/aufgaben"),
    )

    assert ergebnis["kopf"] == ["Titel", "Welle", "Status", "owner", "zuletzt geändert"]
    assert [zeile["path"] for zeile in ergebnis["zeilen"]] == [
        "aufgaben/a30-arbeit.md",
        "aufgaben/a30-ohne.md",
    ]
    mit, ohne = ergebnis["zeilen"]
    assert mit["arbeitsstaende"] == [{"marke": "div", "text": ARBEITSSTAND}]
    assert mit["status"].count(ARBEITSSTAND) == 1
    assert "In Arbeit" in mit["status"]
    # Titel-/owner-Zellen bleiben unverändert — über den Spaltenkopf zugeordnet,
    # nicht über den Index (A42/T15: eine neue Spalte verschiebt nur die Zellen).
    # Bewusst als Literal statt gegen `ergebnis["kopf"]`: sonst prüfte die
    # Assertion nur, dass der Helfer den Kopf gegen sich selbst hält.
    assert list(mit["spalten"]) == ["Titel", "Welle", "Status", "owner", "zuletzt geändert"]
    assert list(mit["spalten"].values()) == mit["zellen"]
    assert mit["spalten"]["Titel"] == "A30: Was passiert gerade"
    assert mit["spalten"]["owner"] == "ai"
    # Aufgabe ohne Angabe: keine Zusatzzeile.
    assert ohne["arbeitsstaende"] == []
    assert ohne["status"] == "Offen"
    assert "img" not in ergebnis["marken"]
    assert ergebnis["aufrufe"] == ["/api/aufgaben"]


# --- T15b: Grenzprobe „neue Spalte" --------------------------------------


@ohne_node
def test_t15_neue_spalte_verschiebt_zuordnung_nicht():
    """Grenzprobe (A42/T15): eine zusätzliche Spalte verschiebt die Zellen.

    Der Stab hängt nachträglich eine Spalte „Priorität" ein — im Kopf und in
    jeder Datenzeile, wie es eine echte neue Tabellenspalte täte. ``spalten``
    muss weiter über den Kopf zuordnen; ein fester Index (früher ``zellen[3]``
    für owner) träfe hier stattdessen die Status-Zelle. Werte jenseits der
    Kopfbreite verwirft ``spalten`` bewusst (dokumentierte Eigenheit des
    Helfers).
    """
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
const tabelle = bei("tabelle-aufgaben");
const spalte = document.createElement("th");
spalte.textContent = "Priorität";
const kopfZeile = sammle(tabelle).find((knoten) => knoten.marke === "tr");
kopfZeile.insertBefore(spalte, kopfZeile.kinder[1]);
const datenzeilen = sammle(tabelle).filter(
  (knoten) => knoten.marke === "tr" && knoten.dataset.path,
);
for (const zeile of datenzeilen) {
  const zelle = document.createElement("td");
  zelle.textContent = "hoch";
  zeile.insertBefore(zelle, zeile.kinder[1]);
}
// Wert jenseits der Kopfzeile: dokumentiert verworfen.
const extra = document.createElement("td");
extra.textContent = "JENSEITS";
datenzeilen[0].append(extra);
return {
  kopf: kopfzeilen("tabelle-aufgaben"),
  zeilen: zeilen("tabelle-aufgaben"),
};
""",
        listen_antwort([MIT_ARBEITSSTAND, OHNE_ARBEITSSTAND], "/api/aufgaben"),
    )

    assert ergebnis["kopf"] == [
        "Titel",
        "Priorität",
        "Welle",
        "Status",
        "owner",
        "zuletzt geändert",
    ]
    mit, ohne = ergebnis["zeilen"]
    # Kopfzuordnung bleibt flexibel: die Werte wandern mit ihrer Spalte.
    assert mit["spalten"]["Titel"] == "A30: Was passiert gerade"
    assert mit["spalten"]["Priorität"] == "hoch"
    assert "In Arbeit" in mit["spalten"]["Status"]
    assert mit["spalten"]["owner"] == "ai"
    assert ohne["spalten"]["Titel"] == "A30: Ohne Arbeitsstand"
    assert ohne["spalten"]["Priorität"] == "hoch"
    # Die Status-Zelle wird über Marken gefunden, nicht über die Spaltenlage.
    assert mit["status"].count(ARBEITSSTAND) == 1
    assert ohne["status"] == "Offen"
    # Eigenheit: `spalten` ordnet nur bis zur Kopfbreite zu, Überhang fällt weg.
    assert mit["zellen"][-1] == "JENSEITS"
    assert len(mit["spalten"]) == len(ergebnis["kopf"])
    assert "JENSEITS" not in mit["spalten"].values()


# --- T16: mehrere Aufgaben in Arbeit ------------------------------------


@ohne_node
def test_t16_mehrere_aufgaben_zeigen_ihre_eigene_rolle():
    daten = [
        _aufgabe(
            "aufgaben/a1.md",
            "A1: Erstes",
            arbeitsrolle="coder",
            arbeitsrolle_label="Coder",
            arbeitsstatus="Umsetzung Paket 2",
        ),
        _aufgabe(
            "aufgaben/a2.md",
            "A2: Zweites",
            arbeitsrolle="tester",
            arbeitsrolle_label="Tester",
            arbeitsstatus="Szenarien S1–S4",
        ),
        _aufgabe(
            "aufgaben/a3.md",
            "A3: Drittes",
            arbeitsrolle="reviewer",
            arbeitsrolle_label="Review",
            arbeitsstatus="Prüfung A27",
        ),
    ]
    antworten = {
        "/api/overview": {"status": 200, "koerper": daten},
        "/api/aufgaben": {"status": 200, "koerper": daten},
    }
    ergebnis = listen_lauf(
        r"""
await liste.ladeAufgaben();
const aufgaben = zeilen("tabelle-aufgaben");
await liste.ladeUebersicht();
const uebersicht = zeilen("tabelle");
const top5 = zeilen("uebersicht-zuletzt");
return { aufgaben, uebersicht, top5 };
""",
        antworten,
    )

    erwartet = [
        ("aufgaben/a1.md", "Coder: Umsetzung Paket 2"),
        ("aufgaben/a2.md", "Tester: Szenarien S1–S4"),
        ("aufgaben/a3.md", "Review: Prüfung A27"),
    ]
    gezeigt = [
        (zeile["path"], zeile["arbeitsstaende"][0]["text"]) for zeile in ergebnis["aufgaben"]
    ]
    assert gezeigt == erwartet
    # Keine Vermischung: jede Zelle enthält nur ihre eigene Rolle.
    for zeile, (_, text) in zip(ergebnis["aufgaben"], erwartet, strict=True):
        eigene = text.split(":")[0]
        fremde = [label for label, _ in (t.split(": ") for _, t in erwartet) if label != eigene]
        assert zeile["status"].count(text) == 1
        for label in fremde:
            assert f"{label}:" not in zeile["status"]
    # Übersicht und Top-5 zeigen dieselbe Zuordnung in gleicher Reihenfolge.
    assert [zeile["path"] for zeile in ergebnis["uebersicht"]] == [pfad for pfad, _ in erwartet]
    assert [
        (zeile["path"], zeile["arbeitsstaende"][0]["text"]) for zeile in ergebnis["top5"]
    ] == erwartet


# --- T17: Abgrenzung -----------------------------------------------------


@ohne_node
def test_t17_nicht_tasks_und_wellenliste_ohne_arbeitsstand():
    wellen_eintrag = {
        "path": "wellen/w1.md",
        "titel": "Welle 1",
        "typ": "Welle",
        "status": "In Arbeit",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-15T10:00:00",
        # Fehlerhafte Zusatzfelder dürfen in der Wellenliste nichts anzeigen.
        "arbeitsrolle": "coder",
        "arbeitsrolle_label": "Coder",
        "arbeitsstatus": "Umsetzung Paket 2",
    }
    projekt_eintrag = {
        "path": "projekt/phasen.md",
        "titel": "Phasen",
        "typ": "Playbook",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-15T10:00:00",
    }
    antworten = {
        "/api/overview": {
            "status": 200,
            "koerper": [MIT_ARBEITSSTAND, wellen_eintrag, projekt_eintrag],
        },
        "/api/wellen": {"status": 200, "koerper": [wellen_eintrag]},
    }
    ergebnis = listen_lauf(
        r"""
await liste.ladeUebersicht();
const uebersicht = zeilen("tabelle");
const anzahlVorher = sammle(bei("tabelle")).filter(
  (knoten) => knoten.classList.contains("arbeitsstand")
).length;
await liste.ladeUebersicht();
const anzahlNachher = sammle(bei("tabelle")).filter(
  (knoten) => knoten.classList.contains("arbeitsstand")
).length;
await liste.ladeWellen();
return {
  uebersicht,
  anzahlVorher,
  anzahlNachher,
  wellen: zeilen("tabelle-wellen"),
};
""",
        antworten,
    )

    assert [(zeile["path"], len(zeile["arbeitsstaende"])) for zeile in ergebnis["uebersicht"]] == [
        ("aufgaben/a30-arbeit.md", 1),
        ("wellen/w1.md", 0),
        ("projekt/phasen.md", 0),
    ]
    # Kein Duplikat beim erneuten Laden.
    assert ergebnis["anzahlVorher"] == 1
    assert ergebnis["anzahlNachher"] == 1
    # Die Wellenliste zeigt keinen Arbeitsstatus, auch wenn der Eintrag Felder trägt.
    assert [zeile["arbeitsstaende"] for zeile in ergebnis["wellen"]] == [[]]


# --- T18: Detail ---------------------------------------------------------


@ohne_node
def test_t18_detail_zeigt_arbeitsstatus_zwischen_status_und_owner():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a30-arbeit.md" });
const kopf = sammle(bei("detail")).find((knoten) => knoten.classList.contains("detail-kopf"));
const angaben = kopf.kinder.filter((knoten) => knoten.marke === "dl")[0];
const paare = [];
for (let i = 0; i < angaben.kinder.length; i += 2) {
  paare.push({ name: angaben.kinder[i].textContent, wert: angaben.kinder[i + 1].textContent });
}
return { paare, aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt) };
""",
        _datei(
            {
                "type": "Task",
                "title": "A30: Was passiert gerade",
                "task_status": "in Umsetzung",
                "owner": "ai",
                "welle": "wellen/w1.md",
                "aktuell": "coder: Umsetzung Paket 2",
            },
            arbeitsrolle="coder",
            arbeitsrolle_label="Coder",
            arbeitsstatus="Umsetzung Paket 2",
        ),
        wellen=[
            {"path": "wellen/w1.md", "titel": "Welle 1: Fixture", "typ": "Welle"},
        ],
    )

    namen = [paar["name"] for paar in ergebnis["paare"]]
    assert namen.index("Arbeitsstatus") == namen.index("Status") + 1
    assert namen.index("owner") == namen.index("Arbeitsstatus") + 1
    assert {"name": "Arbeitsstatus", "wert": ARBEITSSTAND} in ergebnis["paare"]
    assert "Welle" in namen
    assert namen.count("Arbeitsstatus") == 1


@ohne_node
@pytest.mark.parametrize(
    "pfad,frontmatter",
    [
        ("aufgaben/a30-ohne.md", {"type": "Task", "title": "Ohne", "task_status": "offen"}),
        (
            "wellen/w1.md",
            {
                "type": "Welle",
                "title": "Welle 1",
                "arbeitsrolle_label": "Coder",
                "arbeitsstatus": "Umsetzung Paket 2",
            },
        ),
        ("projekt/phasen.md", {"type": "Playbook", "title": "Phasen"}),
    ],
)
def test_t18_ohne_angabe_keine_zeile(pfad, frontmatter):
    ergebnis = detail_lauf(
        f"""
await detail.ladeDetail({{ unterpunkt: {json.dumps(pfad)} }});
const kopf = sammle(bei("detail")).find((knoten) => knoten.classList.contains("detail-kopf"));
const angaben = kopf.kinder.filter((knoten) => knoten.marke === "dl")[0];
return {{
  namen: angaben.kinder.filter((knoten) => knoten.marke === "dt").map((knoten) => knoten.textContent),
  inhalte: angaben.kinder.map((knoten) => knoten.textContent),
}};
""",
        _datei(frontmatter),
    )

    assert "Arbeitsstatus" not in ergebnis["namen"]
    assert ARBEITSSTAND not in ergebnis["inhalte"]


# --- T19: XSS ------------------------------------------------------------


@ohne_node
def test_t19_xss_bleibt_text():
    assert js_liste(
        f"liste.formatiereArbeitsstand({{ arbeitsrolle_label: {json.dumps(HTML_PAYLOAD)},"
        f" arbeitsstatus: {json.dumps(SCRIPT_PAYLOAD)} }})"
    ) == f"{HTML_PAYLOAD}: {SCRIPT_PAYLOAD}"

    xss_eintrag = _aufgabe(
        "aufgaben/xss.md",
        "A99: XSS",
        arbeitsrolle_label=HTML_PAYLOAD,
        arbeitsstatus=SCRIPT_PAYLOAD,
    )
    listen = listen_lauf(
        f"""
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await liste.ladeAufgaben();
const zeile = zeilen("tabelle-aufgaben")[0];
return {{
  arbeitsstaende: zeile.arbeitsstaende,
  marken: marken(bei("tabelle-aufgaben")),
  ausfuehrungen,
}};
""",
        listen_antwort([xss_eintrag], "/api/aufgaben"),
    )
    assert listen["arbeitsstaende"] == [
        {"marke": "div", "text": f"{HTML_PAYLOAD}: {SCRIPT_PAYLOAD}"}
    ]
    assert "img" not in listen["marken"]
    assert "script" not in listen["marken"]
    assert listen["ausfuehrungen"] == []

    detail = detail_lauf(
        """
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await detail.ladeDetail({ unterpunkt: "aufgaben/xss.md" });
return { text: bei("detail").textContent, marken: marken(bei("detail")), ausfuehrungen };
""",
        _datei(
            {"type": "Task", "title": "A99: XSS", "task_status": "in Umsetzung"},
            arbeitsrolle_label=HTML_PAYLOAD,
            arbeitsstatus=SCRIPT_PAYLOAD,
        ),
    )
    assert f"{HTML_PAYLOAD}: {SCRIPT_PAYLOAD}" in detail["text"]
    assert "img" not in detail["marken"]
    assert "script" not in detail["marken"]
    assert detail["ausfuehrungen"] == []


# --- T20: Quell-/Strukturprüfung ----------------------------------------


@pytest.mark.parametrize(
    "senke",
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write(", "eval("],
)
def test_t20_keine_html_senken(senke):
    for datei in (LISTE_JS, DETAIL_JS):
        quelle = lies(datei)
        assert senke not in quelle
        assert "textContent" in quelle


def test_t20_arbeitsstand_nur_ueber_textcontent_und_classlist():
    quelle = lies(LISTE_JS)
    assert 'formatiereArbeitsstand' in quelle
    assert '"arbeitsstand"' in quelle
    assert 'classList.add("arbeitsstand")' in quelle
    assert 'className = "arbeitsstand"' not in quelle

    detail = lies(DETAIL_JS)
    assert "formatiereArbeitsstand" in detail
    assert '"Arbeitsstatus"' in detail
    assert "innerHTML" not in detail
    assert "classList" in detail


def test_t20_index_html_ohne_arbeitsstand_und_ohne_neues_filterfeld():
    html = lies(INDEX_HTML)
    assert "arbeitsstand" not in html
    assert "Arbeitsstatus" not in html
    assert 'id="filter-welle"' not in html
    assert not re.search(r'id="filter-[a-z]+-rolle"', html)


def test_t20_style_css_unveraendert_ohne_arbeitsstand():
    assert "arbeitsstand" not in lies(STYLE_CSS)


def test_t20_rahmen_dateien_ohne_arbeitsstand():
    for datei in (APP_JS, API_JS):
        quelle = lies(datei)
        assert "arbeitsstand" not in quelle
        assert "Arbeitsstatus" not in quelle


@ohne_node
def test_t20_request_budget():
    listen = listen_lauf(
        r"""
await liste.ladeUebersicht();
const uebersicht = aufrufe.map((eintrag) => eintrag.endpunkt);
await liste.ladeAufgaben();
return { uebersicht, aufgaben: aufrufe.map((eintrag) => eintrag.endpunkt) };
""",
        {
            "/api/overview": {"status": 200, "koerper": [MIT_ARBEITSSTAND]},
            "/api/aufgaben": {"status": 200, "koerper": [MIT_ARBEITSSTAND]},
        },
    )
    assert listen["uebersicht"] == ["/api/overview"]
    assert listen["aufgaben"] == ["/api/overview", "/api/aufgaben"]

    detail = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a30-arbeit.md" });
return { aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt) };
""",
        _datei(
            {"type": "Task", "title": "A30", "task_status": "in Umsetzung"},
            arbeitsrolle_label="Coder",
            arbeitsstatus="Umsetzung Paket 2",
        ),
        wellen=[{"path": "wellen/w1.md", "titel": "Welle 1", "typ": "Welle"}],
    )
    # A34/T43: Aufgaben-Details laden zusätzlich ``/api/aufgaben`` (Unter-Aufgaben).
    assert detail["aufrufe"] == ["/api/file", "/api/wellen", "/api/aufgaben"]
