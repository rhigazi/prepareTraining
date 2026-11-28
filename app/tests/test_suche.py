"""Prüfungen für die Suche in den Listenansichten (A25).

Die UI-Szenarien S1–S6 spielt der ``tester`` mit dem Moli-Browser durch; hier
werden ``liste.js`` und seine Verdrahtung ohne Browser geprüft. Die reine
Such-/Filter-/Anzeigelogik läuft über Node (keine neue Abhängigkeit), die
Montage des Suchfelds und der Live-Filter über den gemeinsamen Mini-DOM-Harness
aus ``dom_helfer.py``; hier bleibt nur das Seiten-/Fetch-Gerüst.
Alle Läufe arbeiten gegen Fetch-Antworten aus dem Stab — nie gegen ``wissen/``.
"""

import json
import re
from pathlib import Path

import pytest

from dom_helfer import MINI_DOM, js_liste as js, lies, node_ausfuehren, ohne_node

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
LISTE_JS = STATIC_DIR / "js" / "liste.js"
INDEX_HTML = STATIC_DIR / "index.html"
STYLE_CSS = STATIC_DIR / "style.css"
SERVER_PY = Path(__file__).resolve().parents[1] / "server.py"

KEINE_TREFFER = "Keine Treffer."
KEINE_EINTRAEGE = "Keine Einträge."
LADE_FEHLER = "Einträge konnten nicht geladen werden."
FORMAT_FEHLER = "Einträge haben ein unerwartetes Format."

SUCHE_IDS = {
    "uebersicht": "suche-uebersicht",
    "wellen": "suche-wellen",
    "aufgaben": "suche-aufgaben",
}


# --- Fixtures -------------------------------------------------------------

SUCH_EINTRAEGE = [
    {
        "path": "aufgaben/a23-feature-liste.md",
        "titel": "A23: Feature-Liste",
        "typ": "Aufgabe",
        "status": "In Arbeit",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-14T10:00:00",
        "welle": "w3",
    },
    {
        "path": "aufgaben/a11-liste.md",
        "titel": "A11: Listenansicht",
        "typ": "Aufgabe",
        "status": "Klarung",
        "owner": "mensch",
        "hinweis": "pausiert",
        "zuletzt_geaendert": "2026-11-13T10:00:00",
        "welle": "w3",
    },
    {
        "path": "aufgaben/suche.md",
        "titel": "Suche",
        "typ": "Aufgabe",
        "status": "Offen",
        "owner": None,
        "zuletzt_geaendert": "2026-11-12T10:00:00",
        "welle": "w7",
    },
    {
        "path": "wellen/w3.md",
        "titel": "Welle 3",
        "typ": "Welle",
        "status": "Klarung",
        "owner": "mensch",
        "zuletzt_geaendert": "2026-11-11T10:00:00",
        "welle": "w3",
    },
]

FALT_EINTRAEGE = [
    {"path": "aufgaben/p1.md", "titel": "Prüfung", "status": "Offen", "owner": "ai"},
    {"path": "aufgaben/s1.md", "titel": "Straße", "status": "Offen", "owner": "ai"},
    {"path": "aufgaben/u1.md", "titel": "Über", "status": "Offen", "owner": "ai"},
    {"path": "aufgaben/a23.md", "titel": "A23", "status": "Offen", "owner": "ai"},
]

SONDER_EINTRAEGE = [
    {"path": "aufgaben/x1.md", "titel": "Klammer (offen", "status": "Offen", "owner": "ai"},
    {"path": "aufgaben/x2.md", "titel": "Stern *", "status": "Offen", "owner": "ai"},
    {"path": "aufgaben/x3.md", "titel": "Punkt.*", "status": "Offen", "owner": "ai"},
    {"path": "aufgaben/x4.md", "titel": "Normal", "status": "Offen", "owner": "ai"},
]

ROBUST_EINTRAEGE = [
    {"path": "aufgaben/robust-eins.md", "titel": None, "owner": "ai"},
    {"path": "aufgaben/robust-zwei.md", "welle": 3, "status": "Offen"},
    {"path": "aufgaben/robust-drei.md", "titel": "Drei", "owner": None, "hinweis": None,
     "status": None},
    {"titel": "Ohne Pfad"},
]

DOM_EINTRAEGE = [
    {
        "path": "aufgaben/a20.md",
        "titel": "A20",
        "typ": "Aufgabe",
        "status": "Klarung",
        "owner": "mensch",
        "zuletzt_geaendert": "2026-11-14T10:00:00",
    },
    {
        "path": "aufgaben/a21.md",
        "titel": "A21",
        "typ": "Aufgabe",
        "status": "In Arbeit",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-13T10:00:00",
    },
    {
        "path": "aufgaben/b1.md",
        "titel": "B1",
        "typ": "Aufgabe",
        "status": "Klarung",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-12T10:00:00",
    },
    {
        "path": "wellen/w1.md",
        "titel": "W1",
        "typ": "Welle",
        "status": "Klarung",
        "owner": "mensch",
        "zuletzt_geaendert": "2026-11-11T10:00:00",
    },
]

HTML_PAYLOAD = "<img src=x onerror=alert(1)>"

# --- Seiten-Gerüst (Mini-DOM aus dom_helfer.py) --------------------------

SEITEN_DOM = r"""
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

FETCH_STAB = r"""
// Fetch-Stab: protokolliert jeden Aufruf und liefert Antworten je Endpunkt.
const aufrufe = [];
const antworten = __ANTWORTEN__;
globalThis.fetch = async (pfad, optionen = {}) => {
  const ziel = String(pfad);
  aufrufe.push({ endpunkt: ziel, methode: optionen.method ?? "GET" });
  const vorgabe = antworten[ziel] ?? { status: 404, koerper: { error: "Nicht gefunden." } };
  return {
    ok: vorgabe.status < 400,
    status: vorgabe.status,
    headers: { get: () => "application/json" },
    text: async () => JSON.stringify(vorgabe.koerper ?? null),
  };
};
"""


def dom(ablauf: str, antworten: dict | None = None) -> dict:
    """Führt einen Ablauf im DOM-Harness aus; Antworten kommen aus dem Stab."""
    skript = (
        MINI_DOM
        + SEITEN_DOM
        + FETCH_STAB.replace("__ANTWORTEN__", json.dumps(antworten or {}, ensure_ascii=False))
        + f"\nimport * as liste from {json.dumps(LISTE_JS.as_uri())};\n"
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


def antwort(daten) -> dict:
    return {"/api/overview": {"status": 200, "koerper": daten}}


# --- A. Suchfeld-Montage --------------------------------------------------


@ohne_node
def test_t1_suchfeld_wird_dynamisch_vor_der_tabelle_montiert():
    ergebnis = dom(
        r"""
await liste.ladeUebersicht();
const feld = bei("suche-uebersicht");
const feldEltern = feld?.parentElement;
const gruppe = feldEltern?.parentElement;
const tabelle = bei("tabelle");
const label = gruppe ? sammle(gruppe).find((knoten) => knoten.marke === "label") : null;
return {
  anzahl: anzahl("ansicht-uebersicht", "suche-uebersicht"),
  marke: feld?.marke ?? null,
  typ: feld?.type ?? null,
  labelText: label?.textContent ?? null,
  labelFor: label?.htmlFor || label?.getAttribute("for") || null,
  gruppeKlassen: gruppe?.klassen() ?? [],
  feldKlassen: feldEltern?.klassen() ?? [],
  imFilterformular: sammle(bei("filter")).some((knoten) => knoten === feld),
  gleicherElternknoten: gruppe?.parentElement === tabelle?.parentElement,
  vorTabelle:
    gruppe && tabelle
      ? gruppe.parentElement.kinder.indexOf(gruppe) < gruppe.parentElement.kinder.indexOf(tabelle)
      : false,
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt),
};
""",
        antwort(DOM_EINTRAEGE),
    )
    assert ergebnis["anzahl"] == 1
    assert ergebnis["marke"] == "input"
    assert ergebnis["typ"] == "search"
    assert ergebnis["labelText"] == "Suche"
    assert ergebnis["labelFor"] == "suche-uebersicht"
    assert ergebnis["gruppeKlassen"] == ["filter"]
    assert ergebnis["feldKlassen"] == ["filter-feld"]
    assert ergebnis["imFilterformular"] is False
    assert ergebnis["gleicherElternknoten"] is True
    assert ergebnis["vorTabelle"] is True
    assert ergebnis["aufrufe"] == ["/api/overview"]


@ohne_node
def test_t2_montage_ist_idempotent_und_behaelt_den_wert():
    ergebnis = dom(
        r"""
await liste.ladeUebersicht();
const erstesFeld = bei("suche-uebersicht");
erstesFeld.value = "a2";
await ausloesen(erstesFeld, "input");
const nachEingabe = pfade("tabelle");
await liste.ladeUebersicht();
const zweitesFeld = bei("suche-uebersicht");
return {
  anzahl: anzahl("ansicht-uebersicht", "suche-uebersicht"),
  gleichesObjekt: zweitesFeld === erstesFeld,
  wert: zweitesFeld?.value ?? null,
  nachEingabe,
  nachNeuladen: pfade("tabelle"),
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt),
};
""",
        antwort(DOM_EINTRAEGE),
    )
    assert ergebnis["anzahl"] == 1
    assert ergebnis["gleichesObjekt"] is True
    assert ergebnis["wert"] == "a2"
    assert ergebnis["nachEingabe"] == ["aufgaben/a20.md", "aufgaben/a21.md"]
    assert ergebnis["nachNeuladen"] == ["aufgaben/a20.md", "aufgaben/a21.md"]
    assert ergebnis["aufrufe"] == ["/api/overview", "/api/overview"]


@pytest.mark.parametrize("basis", ["uebersicht", "wellen", "aufgaben"])
def test_t3_ansichten_kennen_ihr_suchfeld(basis):
    # Vertrag: jede der drei Listen hat eine eigene Suchfeld-ID (geteilter Code).
    quelle = lies(LISTE_JS)
    assert f'suche: "{SUCHE_IDS[basis]}"' in quelle


@pytest.mark.parametrize(
    "basis,aufruf,tabelle,endpunkt",
    [
        ("wellen", "liste.ladeWellen()", "tabelle-wellen", "/api/wellen"),
        ("aufgaben", "liste.ladeAufgaben()", "tabelle-aufgaben", "/api/aufgaben"),
    ],
)
@ohne_node
def test_t3_wellen_und_aufgaben_montieren_eigenes_feld(basis, aufruf, tabelle, endpunkt):
    ergebnis = dom(
        f"""
await {aufruf};
const feld = bei("{SUCHE_IDS[basis]}");
feld.value = "wellen/w1";
await ausloesen(feld, "input");
return {{
  feld: feld !== null,
  anzahl: anzahl("ansicht-{basis}", "{SUCHE_IDS[basis]}"),
  pfade: pfade("{tabelle}"),
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt),
}};
""",
        {endpunkt: {"status": 200, "koerper": DOM_EINTRAEGE}},
    )
    assert ergebnis["feld"] is True
    assert ergebnis["anzahl"] == 1
    assert ergebnis["pfade"] == ["wellen/w1.md"]
    assert ergebnis["aufrufe"] == [endpunkt]


@ohne_node
def test_t3_ohne_tabellencontainer_kein_feld_und_kein_extra_request():
    ergebnis = dom(
        r"""
REGISTRIERT.delete("tabelle");
await liste.ladeUebersicht();
return {
  feld: bei("suche-uebersicht") !== null,
  fehler: { sichtbar: bei("fehler").hidden === false, text: bei("fehler").textContent },
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt),
};
""",
        antwort(DOM_EINTRAEGE),
    )
    assert ergebnis["feld"] is False
    assert ergebnis["fehler"] == {"sichtbar": False, "text": ""}
    # Nur der reguläre Ladeaufruf, kein zusätzlicher Request durch die Suche.
    assert ergebnis["aufrufe"] == ["/api/overview"]


def test_t4_liste_js_nutzt_nur_bekannte_endpunkte():
    # N1: kein neuer Server-Endpunkt.
    assert set(re.findall(r"/api/[a-z_-]+", lies(LISTE_JS))) == {
        "/api/overview",
        "/api/aufgaben",
        "/api/wellen",
    }


@pytest.mark.parametrize(
    "senke",
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write(", "eval("],
)
def test_t4_liste_js_bleibt_ohne_html_senken(senke):
    quelle = lies(LISTE_JS)
    assert senke not in quelle
    assert "textContent" in quelle
    assert "classList" in quelle


def test_t4_liste_js_ohne_submit_handler():
    # Der A11-Guard bleibt scharf: Suche liegt außerhalb des Formulars.
    assert 'addEventListener("submit"' not in lies(LISTE_JS)


def test_t4_index_html_ohne_suche_markup():
    # N1: kein neues Markup, kein neuer Container in index.html.
    html = lies(INDEX_HTML)
    assert 'id="suche' not in html
    assert not re.search(r"suche-(uebersicht|wellen|aufgaben)", html)


def test_t4_server_ohne_suche_endpunkt():
    assert "/api/suche" not in lies(SERVER_PY)


def test_t4_style_css_ohne_suche_selektoren():
    # Angestrebt: style.css unverändert (Wiederverwendung von .filter/.leer).
    assert not re.search(r"suche-(uebersicht|wellen|aufgaben)", lies(STYLE_CSS))


# --- B. Reine Suchlogik ---------------------------------------------------


@pytest.mark.parametrize("begriff", ["a23", "A23", "FEATURE", "feature"])
@ohne_node
def test_t5_einzelbegriff_im_titel_ist_case_insensitiv(begriff):
    pfade = js(
        f"liste.filtereEintraege(daten, {{ suche: {json.dumps(begriff)} }}).map((e) => e.path)",
        SUCH_EINTRAEGE,
    )
    assert pfade == ["aufgaben/a23-feature-liste.md"]


@pytest.mark.parametrize(
    "begriff,erwartet",
    [
        ("a11", ["aufgaben/a11-liste.md"]),
        ("Welle", ["wellen/w3.md"]),
        ("Klarung", ["aufgaben/a11-liste.md", "wellen/w3.md"]),
        ("mensch", ["aufgaben/a11-liste.md", "wellen/w3.md"]),
        ("pausiert", ["aufgaben/a11-liste.md"]),
        ("w3", ["aufgaben/a23-feature-liste.md", "aufgaben/a11-liste.md", "wellen/w3.md"]),
        (
            "aufgaben/",
            ["aufgaben/a23-feature-liste.md", "aufgaben/a11-liste.md", "aufgaben/suche.md"],
        ),
    ],
)
@ohne_node
def test_t6_feldabdeckung_der_overview_felder(begriff, erwartet):
    pfade = js(
        f"liste.filtereEintraege(daten, {{ suche: {json.dumps(begriff)} }}).map((e) => e.path)",
        SUCH_EINTRAEGE,
    )
    assert pfade == erwartet


@ohne_node
def test_t7_mehrere_begriffe_sind_und_verknuepft():
    pfade = js(
        "liste.filtereEintraege(daten, { suche: 'feature arbeit' }).map((e) => e.path)",
        SUCH_EINTRAEGE,
    )
    assert pfade == ["aufgaben/a23-feature-liste.md"]

    leer = js(
        "liste.filtereEintraege(daten, { suche: 'a23 gibtsnicht' }).map((e) => e.path)",
        SUCH_EINTRAEGE,
    )
    assert leer == []


@pytest.mark.parametrize("suche", ["", "   ", "\t\n", None])
@ohne_node
def test_t8_leere_suche_liefert_den_vollbestand(suche):
    pfade = js(
        f"liste.filtereEintraege(daten, {{ suche: {json.dumps(suche)} }}).map((e) => e.path)",
        SUCH_EINTRAEGE,
    )
    assert pfade == [eintrag["path"] for eintrag in SUCH_EINTRAEGE]


@ohne_node
def test_t8_suche_ohne_eigenschaft_liefert_den_vollbestand():
    pfade = js("liste.filtereEintraege(daten, {}).map((e) => e.path)", SUCH_EINTRAEGE)
    assert pfade == [eintrag["path"] for eintrag in SUCH_EINTRAEGE]


@pytest.mark.parametrize(
    "begriff,erwartet",
    [
        ("prüfung", "aufgaben/p1.md"),
        ("PRÜFUNG", "aufgaben/p1.md"),
        ("prufung", "aufgaben/p1.md"),
        ("strasse", "aufgaben/s1.md"),
        ("Straße", "aufgaben/s1.md"),
        ("uber", "aufgaben/u1.md"),
        ("a23", "aufgaben/a23.md"),
    ],
)
@ohne_node
def test_t9_umlaute_und_scharfes_s_werden_gefaltet(begriff, erwartet):
    pfade = js(
        f"liste.filtereEintraege(daten, {{ suche: {json.dumps(begriff)} }}).map((e) => e.path)",
        FALT_EINTRAEGE,
    )
    assert pfade == [erwartet]


@pytest.mark.parametrize("begriff", ["(", ")", "[", "*", "?", "\\", ".*", "a23(", "^$", "+"])
@ohne_node
def test_t10_sonderzeichen_werfen_nicht(begriff):
    pfade = js(
        f"liste.filtereEintraege(daten, {{ suche: {json.dumps(begriff)} }}).map((e) => e.path)",
        SONDER_EINTRAEGE,
    )
    assert isinstance(pfade, list)


@ohne_node
def test_t10_regex_zeichen_werden_literal_verglichen():
    # Kein `RegExp`: ".*" trifft nur die Zelle, die die Zeichenfolge enthält.
    pfade = js(
        "liste.filtereEintraege(daten, { suche: '.*' }).map((e) => e.path)",
        SONDER_EINTRAEGE,
    )
    assert pfade == ["aufgaben/x3.md"]

    klammer = js(
        "liste.filtereEintraege(daten, { suche: '(' }).map((e) => e.path)",
        SONDER_EINTRAEGE,
    )
    assert klammer == ["aufgaben/x1.md"]


@ohne_node
def test_t11_kombination_mit_status_und_owner_filter():
    pfade = js(
        "liste.filtereEintraege(daten, { status: 'Klarung', owner: 'mensch', suche: 'a1' })"
        ".map((e) => e.path)",
        SUCH_EINTRAEGE,
    )
    assert pfade == ["aufgaben/a11-liste.md"]

    # A11-Regression: leere Suche ändert das Filterergebnis nicht.
    mit_suche = js(
        "liste.filtereEintraege(daten, { status: 'Klarung', owner: 'mensch', suche: '' })"
        ".map((e) => e.path)",
        SUCH_EINTRAEGE,
    )
    ohne_suche = js(
        "liste.filtereEintraege(daten, { status: 'Klarung', owner: 'mensch' }).map((e) => e.path)",
        SUCH_EINTRAEGE,
    )
    assert mit_suche == ohne_suche == ["aufgaben/a11-liste.md", "wellen/w3.md"]


@ohne_node
def test_t11_suche_mutiert_die_eingabe_nicht():
    unveraendert = js(
        "(() => { const vorher = daten.map((e) => e.path).join(',');"
        " liste.filtereEintraege(daten, { status: 'Klarung', suche: 'a1' });"
        " return daten.map((e) => e.path).join(',') === vorher; })()",
        SUCH_EINTRAEGE,
    )
    assert unveraendert is True


# --- C. Anzeige- und Leerzustand -----------------------------------------


@ohne_node
def test_t12_treffer_zeigt_tabelle():
    anzeige = js("liste.waehleAnzeige(daten, { suche: 'a11' })", SUCH_EINTRAEGE)
    assert anzeige["art"] == "tabelle"
    assert [eintrag["path"] for eintrag in anzeige["eintraege"]] == ["aufgaben/a11-liste.md"]
    assert anzeige["text"] == ""


@ohne_node
def test_t13_ohne_treffer_keine_treffer():
    anzeige = js("liste.waehleAnzeige(daten, { suche: 'xyzgibtsnicht' })", SUCH_EINTRAEGE)
    assert anzeige["art"] == "leer"
    assert anzeige["text"] == KEINE_TREFFER
    assert anzeige["eintraege"] == []


@ohne_node
def test_t14_leere_daten_bleiben_keine_eintraege():
    anzeige = js("liste.waehleAnzeige([], { suche: 'irgendwas' })", None)
    assert anzeige["art"] == "leer"
    assert anzeige["text"] == KEINE_EINTRAEGE


@ohne_node
def test_t14_filter_ohne_treffer_bleibt_keine_eintraege():
    anzeige = js("liste.waehleAnzeige(daten, { status: 'Geschlossen' })", SUCH_EINTRAEGE)
    assert anzeige["art"] == "leer"
    assert anzeige["text"] == KEINE_EINTRAEGE


@pytest.mark.parametrize(
    "daten,erwartet",
    [
        ("null", LADE_FEHLER),
        ("{}", FORMAT_FEHLER),
        ("42", FORMAT_FEHLER),
        ('"text"', FORMAT_FEHLER),
    ],
)
@ohne_node
def test_t15_fehlerzustand_hat_vorrang_vor_der_suche(daten, erwartet):
    anzeige = js(f"liste.waehleAnzeige({daten}, {{ suche: 'a23' }})", None)
    assert anzeige["art"] == "fehler"
    assert anzeige["text"] == erwartet
    assert anzeige["text"] != KEINE_TREFFER
    assert anzeige["eintraege"] == []


# --- D. DOM-Verdrahtung: Live-Filter --------------------------------------


@ohne_node
def test_t16_live_filter_ohne_nachladen():
    ergebnis = dom(
        r"""
await liste.ladeUebersicht();
const kopfVorher = kopfzeilen("tabelle");
const feld = bei("suche-uebersicht");
feld.value = "a2";
await ausloesen(feld, "input");
return {
  pfade: pfade("tabelle"),
  kopfVorher,
  kopfNachher: kopfzeilen("tabelle"),
  aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt),
};
""",
        antwort(DOM_EINTRAEGE),
    )
    assert ergebnis["pfade"] == ["aufgaben/a20.md", "aufgaben/a21.md"]
    assert ergebnis["kopfVorher"] == ["Titel", "Welle", "Status", "owner", "zuletzt geändert"]
    assert ergebnis["kopfNachher"] == ergebnis["kopfVorher"]
    # Genau ein Ladeaufruf: kein Request pro Tastendruck.
    assert ergebnis["aufrufe"] == ["/api/overview"]


@ohne_node
def test_t17_leeren_und_zuruecksetzen_stellen_den_vollbestand_her():
    ergebnis = dom(
        r"""
await liste.ladeUebersicht();
const feld = bei("suche-uebersicht");
feld.value = "a2";
await ausloesen(feld, "input");
const nachSuche = pfade("tabelle");
feld.value = "";
await ausloesen(feld, "input");
const nachLeeren = pfade("tabelle");
bei("filter-status").value = "Klarung";
bei("filter-owner").value = "mensch";
feld.value = "a2";
await ausloesen(feld, "input");
await ausloesen(bei("filter-zuruecksetzen"), "click");
return {
  nachSuche,
  nachLeeren,
  status: bei("filter-status").value,
  owner: bei("filter-owner").value,
  suche: feld.value,
  nachReset: pfade("tabelle"),
  aufrufe: aufrufe.length,
};
""",
        antwort(DOM_EINTRAEGE),
    )
    assert ergebnis["nachSuche"] == ["aufgaben/a20.md", "aufgaben/a21.md"]
    assert ergebnis["nachLeeren"] == [eintrag["path"] for eintrag in DOM_EINTRAEGE]
    assert ergebnis["status"] == ""
    assert ergebnis["owner"] == ""
    assert ergebnis["suche"] == ""
    assert ergebnis["nachReset"] == [eintrag["path"] for eintrag in DOM_EINTRAEGE]
    assert ergebnis["aufrufe"] == 1


@ohne_node
def test_t18_suche_und_statusfilter_kombiniert_im_dom():
    ergebnis = dom(
        r"""
await liste.ladeUebersicht();
const feld = bei("suche-uebersicht");
feld.value = "a2";
await ausloesen(feld, "input");
bei("filter-status").value = "Klarung";
await ausloesen(bei("filter-status"), "change");
const kombination = pfade("tabelle");
const wertNachFilter = feld.value;
bei("filter-status").value = "";
await ausloesen(bei("filter-status"), "change");
return {
  kombination,
  wertNachFilter,
  nachStatuswechsel: pfade("tabelle"),
};
""",
        antwort(DOM_EINTRAEGE),
    )
    assert ergebnis["kombination"] == ["aufgaben/a20.md"]
    assert ergebnis["wertNachFilter"] == "a2"
    assert ergebnis["nachStatuswechsel"] == ["aufgaben/a20.md", "aufgaben/a21.md"]


@ohne_node
def test_t19_leerzustand_im_dom_ist_keine_treffer():
    ergebnis = dom(
        r"""
await liste.ladeUebersicht();
const feld = bei("suche-uebersicht");
feld.value = "xyzgibtsnicht";
await ausloesen(feld, "input");
const bereich = bei("tabelle");
return {
  text: bereich.textContent,
  tabellen: sammle(bereich).filter((knoten) => knoten.marke === "table").length,
  fehler: { sichtbar: bei("fehler").hidden === false, text: bei("fehler").textContent },
};
""",
        antwort(DOM_EINTRAEGE),
    )
    assert ergebnis["text"] == KEINE_TREFFER
    assert ergebnis["tabellen"] == 0
    assert ergebnis["fehler"] == {"sichtbar": False, "text": ""}


@ohne_node
def test_t20_zusatzbloecke_bleiben_ungefiltert():
    ergebnis = dom(
        r"""
await liste.ladeUebersicht();
const feld = bei("suche-uebersicht");
feld.value = "a2";
await ausloesen(feld, "input");
return {
  tabelle: pfade("tabelle"),
  zuletzt: pfade("uebersicht-zuletzt"),
  klarung: sammle(bei("uebersicht-klarung"))
    .filter((knoten) => knoten.marke === "li")
    .map((knoten) => knoten.textContent),
};
""",
        antwort(DOM_EINTRAEGE),
    )
    assert ergebnis["tabelle"] == ["aufgaben/a20.md", "aufgaben/a21.md"]
    assert ergebnis["zuletzt"] == [eintrag["path"] for eintrag in DOM_EINTRAEGE]
    assert ergebnis["klarung"] == ["A20", "B1", "W1"]


# --- E. Robustheit und XSS ------------------------------------------------


@ohne_node
def test_t21_xss_payload_als_suchbegriff_bleibt_text():
    ergebnis = dom(
        f"""
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await liste.ladeUebersicht();
const feld = bei("suche-uebersicht");
feld.value = {json.dumps(HTML_PAYLOAD)};
await ausloesen(feld, "input");
return {{
  marken: sammle(bei("ansicht-uebersicht")).map((knoten) => knoten.marke),
  text: bei("tabelle").textContent,
  ausfuehrungen,
  aufrufe: aufrufe.length,
}};
""",
        antwort(DOM_EINTRAEGE),
    )
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []
    assert ergebnis["text"] == KEINE_TREFFER
    assert ergebnis["aufrufe"] == 1


@ohne_node
def test_t22_xss_payload_als_daten_wird_als_text_gerendert():
    daten = [
        {"path": "aufgaben/xss.md", "titel": HTML_PAYLOAD, "status": "Offen", "owner": "ai"},
        {"path": "aufgaben/sauber.md", "titel": "Sauber", "status": "Offen", "owner": "ai"},
    ]
    ergebnis = dom(
        r"""
await liste.ladeUebersicht();
const feld = bei("suche-uebersicht");
feld.value = "img";
await ausloesen(feld, "input");
const alle = sammle(bei("tabelle"));
return {
  pfade: pfade("tabelle"),
  zellen: alle.filter((knoten) => knoten.marke === "td").map((knoten) => knoten.textContent),
  marken: alle.map((knoten) => knoten.marke),
};
""",
        antwort(daten),
    )
    assert ergebnis["pfade"] == ["aufgaben/xss.md"]
    assert HTML_PAYLOAD in ergebnis["zellen"]
    assert "img" not in ergebnis["marken"]


@ohne_node
def test_t23_fremde_und_fehlende_feldtypen_werfen_nicht():
    alle = js("liste.filtereEintraege(daten, {}).length", ROBUST_EINTRAEGE)
    assert alle == len(ROBUST_EINTRAEGE)

    zahl = js(
        "liste.filtereEintraege(daten, { suche: '3' }).map((e) => e.path)",
        ROBUST_EINTRAEGE,
    )
    assert zahl == ["aufgaben/robust-zwei.md"]

    # null/undefined werden zu "" — sie sind keine Suchtreffer.
    assert js("liste.filtereEintraege(daten, { suche: 'null' })", ROBUST_EINTRAEGE) == []
    assert js("liste.filtereEintraege(daten, { suche: 'undefined' })", ROBUST_EINTRAEGE) == []


# --- F. Regression --------------------------------------------------------


@ohne_node
def test_t24_a11_vertraege_bleiben_wortgleich():
    # Ohne Suchparameter gilt unverändert das A11-Verhalten.
    treffer = js("liste.waehleAnzeige(daten)", DOM_EINTRAEGE)
    assert treffer["art"] == "tabelle"
    assert len(treffer["eintraege"]) == len(DOM_EINTRAEGE)

    assert js("liste.waehleAnzeige([]).text", None) == KEINE_EINTRAEGE
    assert js("liste.waehleAnzeige(null).text", None) == LADE_FEHLER
    assert js("liste.waehleAnzeige({}).text", None) == FORMAT_FEHLER

    quelle = lies(LISTE_JS)
    assert f'"{KEINE_EINTRAEGE}"' in quelle
    assert f'"{KEINE_TREFFER}"' in quelle
