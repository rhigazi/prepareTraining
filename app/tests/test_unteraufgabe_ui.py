"""Prüfungen für die Unter-Aufgaben-UI (A34, Paket 3).

Geprüft werden T32–T46: Anlegen-Knopf und Inline-Formular im Aufgaben-Detail,
Abschnitt „Unter-Aufgaben (n)" aus ``GET /api/aufgaben`` sowie die reinen
Helfer in ``unteraufgaben.js``. Der Harness (Mini-DOM + Node-Runner) liegt in
``dom_helfer.py`` — hier stehen nur das Seiten-/Fetch-Gerüst und die Prüfungen.

Alle Läufe arbeiten gegen Fetch-Antworten aus dem Stab — nie gegen ``wissen/``.
"""

import json
from pathlib import Path

import pytest

from dom_helfer import (
    DETAIL_JS,
    MINI_DOM,
    STATIC_DIR,
    lies,
    node_ausfuehren,
    ohne_node,
)

AUFGABE = "aufgaben/a34-unter-aufgaben.md"
AUFGABE_2 = "aufgaben/a1.md"
KIND_1 = "aufgaben/a34.001-erste.md"
KIND_2 = "aufgaben/a34.002-zweite.md"
KIND_NEU = "aufgaben/a34.001-erste-unter-aufgabe.md"
FREMD = "aufgaben/a35.001-fremd.md"
WELLE = "wellen/w1.md"
PROJEKT = "projekt/phasen.md"

ANLEGEN = "detail-unteraufgabe-anlegen"
BEREICH = "unteraufgabe-anlegen"
MELDUNG_ERFOLG = "Unter-Aufgabe angelegt."
LADE_FEHLER = "Unter-Aufgaben konnten nicht geladen werden."
FORMAT_FEHLER = "Unter-Aufgaben haben ein unerwartetes Format."

HTML_PAYLOAD = "<img src=x onerror=alert(1)>"
ARBEITSSTAND = "Coder: Umsetzung Paket 3"

INDEX_HTML = STATIC_DIR / "index.html"
STYLE_CSS = STATIC_DIR / "style.css"
APP_JS = STATIC_DIR / "js" / "app.js"
API_JS = STATIC_DIR / "js" / "api.js"
LISTE_JS = STATIC_DIR / "js" / "liste.js"
FORMULARE_JS = STATIC_DIR / "js" / "formulare.js"
UNTERAUFGABEN_JS = STATIC_DIR / "js" / "unteraufgaben.js"


def js_unteraufgaben(ausdruck: str, daten=None):
    """Wertet einen Ausdruck im Kontext von ``unteraufgaben.js`` über Node aus."""
    skript = (
        f"import * as unteraufgaben from {json.dumps(UNTERAUFGABEN_JS.as_uri())};\n"
        f"const daten = {json.dumps(daten, ensure_ascii=False)};\n"
        f"console.log(JSON.stringify({ausdruck}));"
    )
    return node_ausfuehren(skript)


def _aufgabe(pfad: str, titel: str, **felder) -> dict:
    eintrag = {
        "path": pfad,
        "titel": titel,
        "typ": "Task",
        "status": "Offen",
        "owner": "ai",
        "zuletzt_geaendert": "2026-11-15T10:00:00",
    }
    eintrag.update(felder)
    return eintrag


def _kind(pfad: str, titel: str, eltern: str = AUFGABE, **felder) -> dict:
    return _aufgabe(pfad, titel, parent=eltern, **felder)


def _datei(frontmatter: dict, markdown: str = "# Ziel\n\nFixture.\n", **felder) -> dict:
    daten = {"frontmatter": frontmatter, "markdown": markdown, "nachtraege": []}
    daten.update(felder)
    return daten


def _eltern_datei(**felder) -> dict:
    frontmatter = {
        "type": "Task",
        "title": "A34: Unter-Aufgaben",
        "task_status": "in Umsetzung",
        "welle": WELLE,
    }
    return _datei(frontmatter, **felder)


NEUES_KIND = _kind(KIND_NEU, "A34.001: Erste Unter-Aufgabe")

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
let aufgabenAntwort = AUFGABEN;
let freigeben = null;
const datei = { ...DATEI, frontmatter: { ...(DATEI.frontmatter || {}) } };
const antworte = (status, koerper) => ({
  ok: status < 400,
  status,
  headers: { get: () => "application/json" },
  text: async () => JSON.stringify(koerper ?? null),
});

function knopfZustand() {
  const speichern = bei("unteraufgabe-speichern");
  const oeffnen = bei("detail-unteraufgabe-anlegen");
  return {
    speichern: speichern ? speichern.disabled : null,
    oeffnen: oeffnen ? oeffnen.disabled : null,
  };
}

globalThis.fetch = async (pfad, optionen = {}) => {
  const adresse = String(pfad);
  const methode = optionen.method || "GET";
  const nutzlast = typeof optionen.body === "string" ? JSON.parse(optionen.body) : null;
  aufrufe.push({
    methode,
    endpunkt: adresse.split("?")[0],
    nutzlast,
    gesperrt: knopfZustand(),
  });

  if (methode === "GET" && adresse.startsWith("/api/file")) return antworte(200, datei);
  if (methode === "GET" && adresse === "/api/wellen") return antworte(200, WELLEN);
  if (methode === "GET" && adresse === "/api/aufgaben") return antworte(200, aufgabenAntwort);

  if (methode === "POST" && adresse === "/api/task") {
    if (GATE) await new Promise((fertig) => { freigeben = fertig; });
    if (TASK_STATUS >= 400) return antworte(TASK_STATUS, { error: TASK_FEHLER });
    if (Array.isArray(aufgabenAntwort)) aufgabenAntwort = [...aufgabenAntwort, NEUES_KIND];
    return antworte(200, { path: NEUES_KIND.path });
  }

  return antworte(404, { error: "Nicht gefunden." });
};

const kopf = () => sammle(bei("detail")).find((knoten) => knoten.classList.contains("detail-kopf"));
const unteraufgabeFormular = () =>
  sammle(bei("unteraufgabe-anlegen")).find((knoten) => knoten.marke === "form") ?? null;
const abschnitte = () => sammle(bei("detail")).filter((knoten) => knoten.marke === "section");
const ueberschriften = () =>
  sammle(bei("detail")).filter((knoten) => knoten.marke === "h3").map((knoten) => knoten.textContent);
const zeilenPfade = (bereich) =>
  bereich
    ? sammle(bereich)
        .filter((knoten) => knoten.marke === "tr" && knoten.dataset.path)
        .map((knoten) => knoten.dataset.path)
    : [];
const teile = () =>
  bei("detail").kinder.map((knoten) => {
    if (knoten.id) return knoten.id;
    if (knoten.classList.contains("detail-kopf")) return "kopf";
    if (knoten.classList.contains("detail-inhalt")) return "inhalt";
    if (knoten.classList.contains("detail-abschnitt")) return "abschnitt";
    return knoten.marke;
  });
"""


_UNSET = object()


def detail_lauf(
    ablauf: str,
    datei: dict,
    *,
    wellen=None,
    aufgaben=_UNSET,
    task_status: int = 200,
    task_fehler: str = "Anlegen nicht möglich.",
    gate: bool = False,
    neues_kind: dict | None = None,
) -> dict:
    aufgaben_wert = [] if aufgaben is _UNSET else aufgaben
    skript = (
        MINI_DOM
        + f"const DATEI = {json.dumps(datei, ensure_ascii=False)};\n"
        + f"const WELLEN = {json.dumps(wellen or [], ensure_ascii=False)};\n"
        + f"const AUFGABEN = {json.dumps(aufgaben_wert, ensure_ascii=False)};\n"
        + f"const NEUES_KIND = {json.dumps(neues_kind or NEUES_KIND, ensure_ascii=False)};\n"
        + f"const AUFGABE = {json.dumps(AUFGABE)};\n"
        + f"const KIND_1 = {json.dumps(KIND_1)};\n"
        + f"const WELLE = {json.dumps(WELLE)};\n"
        + f"const PROJEKT = {json.dumps(PROJEKT)};\n"
        + f"const TASK_STATUS = {task_status};\n"
        + f"const TASK_FEHLER = {json.dumps(task_fehler, ensure_ascii=False)};\n"
        + f"const GATE = {'true' if gate else 'false'};\n"
        + DETAIL_SEITE
        + f"\nimport * as detail from {json.dumps(DETAIL_JS.as_uri())};\n"
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


# --- T32: Knopf-Sichtbarkeit --------------------------------------------


@ohne_node
@pytest.mark.parametrize(
    "pfad,datei,aufgaben,erwartet",
    [
        (AUFGABE, _eltern_datei(), None, True),
        (
            WELLE,
            _datei({"type": "Welle", "title": "Welle 1"}),
            [_aufgabe(AUFGABE_2, "A1: Mini", welle=WELLE)],
            False,
        ),
        (PROJEKT, _datei({"type": "Projekt", "title": "Phasen"}), None, False),
        (
            KIND_1,
            _datei(
                {
                    "type": "Task",
                    "title": "A34.001: Erstes",
                    "task_status": "offen",
                    "parent": AUFGABE,
                }
            ),
            [_kind(KIND_2, "A34.002: Zweites", eltern=KIND_1)],
            False,
        ),
        (
            AUFGABE,
            _datei(
                {"type": "Task", "title": "A34: Zu", "task_status": "abgeschlossen"},
                ui_status="Geschlossen",
                hinweis=None,
                owner_default=None,
            ),
            None,
            False,
        ),
    ],
)
def test_t32_knopf_sichtbarkeit(pfad, datei, aufgaben, erwartet):
    ergebnis = detail_lauf(
        f"""
await detail.ladeDetail({{ unterpunkt: {json.dumps(pfad)} }});
const aktionen = sammle(bei("detail")).find((knoten) =>
  knoten.classList.contains("detail-aktionen")
);
const knopf = bei("detail-unteraufgabe-anlegen");
return {{
  anzahl: anzahl("detail", "detail-unteraufgabe-anlegen"),
  imAktionen: Boolean(aktionen && knopf && sammle(aktionen).includes(knopf)),
  text: knopf?.textContent ?? null,
  marke: knopf?.marke ?? null,
  formular: bei("unteraufgabe-anlegen") !== null,
  statusKnoepfe: aktionen
    ? sammle(aktionen)
        .filter((knoten) => knoten.marke === "button" && knoten.dataset.status)
        .map((knoten) => knoten.dataset.status)
    : [],
  owner: bei("detail-owner") !== null,
}};
""",
        datei,
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
        aufgaben=aufgaben or [],
    )

    assert ergebnis["anzahl"] == (1 if erwartet else 0)
    assert ergebnis["formular"] is erwartet
    assert ergebnis["statusKnoepfe"] == ["Klarung", "Geschlossen"]
    assert ergebnis["owner"] is True
    if erwartet:
        assert ergebnis["imAktionen"] is True
        assert ergebnis["marke"] == "button"
        assert ergebnis["text"] == "Unter-Aufgabe anlegen"


# --- T33: Formular öffnen und schließen ---------------------------------


@ohne_node
def test_t33_formular_oeffnen_und_schliessen():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: AUFGABE });
const knopf = bei("detail-unteraufgabe-anlegen");
const vorher = {
  versteckt: bei("unteraufgabe-anlegen").hidden,
  aufrufe: aufrufe.length,
  prioritaet: bei("unteraufgabe-prioritaet")?.value ?? null,
};
await ausloesen(knopf, "click");
const offen = {
  versteckt: bei("unteraufgabe-anlegen").hidden,
  aufrufe: aufrufe.length,
  felder: ["titel", "ziel", "akzeptanz", "prioritaet"].map((name) =>
    bei("unteraufgabe-" + name)?.marke ?? null
  ),
  speichern: bei("unteraufgabe-speichern")?.textContent ?? null,
  abbrechen: bei("unteraufgabe-abbrechen")?.textContent ?? null,
};
await ausloesen(bei("unteraufgabe-abbrechen"), "click");
const zu = bei("unteraufgabe-anlegen").hidden;
await ausloesen(bei("detail-unteraufgabe-anlegen"), "click");
return {
  vorher,
  offen,
  zu,
  wiederOffen: bei("unteraufgabe-anlegen").hidden,
  bereiche: anzahl("detail", "unteraufgabe-anlegen"),
  formulare: sammle(bei("detail")).filter((knoten) => knoten.marke === "form").length,
};
""",
        _eltern_datei(),
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
    )

    assert ergebnis["vorher"]["versteckt"] is True
    assert ergebnis["vorher"]["aufrufe"] == 3  # /api/file, /api/wellen, /api/aufgaben
    assert ergebnis["offen"]["versteckt"] is False
    # Kein Request beim Öffnen.
    assert ergebnis["offen"]["aufrufe"] == ergebnis["vorher"]["aufrufe"]
    assert ergebnis["offen"]["felder"] == ["input", "textarea", "textarea", "select"]
    assert ergebnis["offen"]["speichern"] == "Speichern"
    assert ergebnis["offen"]["abbrechen"] == "Abbrechen"
    assert ergebnis["vorher"]["prioritaet"] == "mittel"
    assert ergebnis["zu"] is True
    assert ergebnis["wiederOffen"] is False
    assert ergebnis["bereiche"] == 1
    # Kopf, Anlegeformular, Inhalt, Nachtragsformular.
    assert ergebnis["formulare"] == 2


# --- T34: Erfolg ---------------------------------------------------------


@ohne_node
def test_t34_erfolg_legt_genau_eine_unteraufgabe_an():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: AUFGABE });
await ausloesen(bei("detail-unteraufgabe-anlegen"), "click");
bei("unteraufgabe-titel").value = "Erste Unter-Aufgabe";
bei("unteraufgabe-ziel").value = "Ziel der Unter-Aufgabe";
bei("unteraufgabe-akzeptanz").value = "Kriterium A\nKriterium B";
await ausloesen(bei("unteraufgabe-speichern"), "click");
const bereich = abschnitte().find((knoten) =>
  knoten.textContent.includes("Unter-Aufgaben")
);
return {
  posts: aufrufe
    .filter((eintrag) => eintrag.methode === "POST")
    .map((eintrag) => ({
      endpunkt: eintrag.endpunkt,
      nutzlast: eintrag.nutzlast,
      schluessel: Object.keys(eintrag.nutzlast ?? {}),
      gesperrt: eintrag.gesperrt,
    })),
  dateiLadungen: aufrufe.filter((eintrag) => eintrag.endpunkt === "/api/file").length,
  meldung: { sichtbar: !bei("meldung").hidden, text: bei("meldung").textContent },
  ueberschriften: ueberschriften(),
  pfade: zeilenPfade(bereich),
  formular: {
    versteckt: bei("unteraufgabe-anlegen").hidden,
    titel: bei("unteraufgabe-titel").value,
    ziel: bei("unteraufgabe-ziel").value,
    akzeptanz: bei("unteraufgabe-akzeptanz").value,
    prioritaet: bei("unteraufgabe-prioritaet").value,
  },
  anlegen: {
    anzahl: anzahl("detail", "detail-unteraufgabe-anlegen"),
    bedienbar: bei("detail-unteraufgabe-anlegen")?.disabled === false,
  },
};
""",
        _eltern_datei(),
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
    )

    assert len(ergebnis["posts"]) == 1
    post = ergebnis["posts"][0]
    assert post["endpunkt"] == "/api/task"
    # `parent` ist das letzte Feld; kein `welle`, kein `user_story`.
    assert post["schluessel"] == ["titel", "ziel", "akzeptanz", "prioritaet", "parent"]
    assert post["nutzlast"] == {
        "titel": "Erste Unter-Aufgabe",
        "ziel": "Ziel der Unter-Aufgabe",
        "akzeptanz": ["Kriterium A", "Kriterium B"],
        "prioritaet": "mittel",
        "parent": AUFGABE,
    }
    # Beide Knöpfe sind während des Requests gesperrt.
    assert post["gesperrt"] == {"speichern": True, "oeffnen": True}
    assert ergebnis["meldung"] == {"sichtbar": True, "text": MELDUNG_ERFOLG}
    # Detail wurde neu geladen, das Kind erscheint im Abschnitt.
    assert ergebnis["dateiLadungen"] == 2
    assert "Unter-Aufgaben (1)" in ergebnis["ueberschriften"]
    assert ergebnis["pfade"] == [KIND_NEU]
    # Formular geschlossen und geleert.
    assert ergebnis["formular"] == {
        "versteckt": True,
        "titel": "",
        "ziel": "",
        "akzeptanz": "",
        "prioritaet": "mittel",
    }
    assert ergebnis["anlegen"] == {"anzahl": 1, "bedienbar": True}


# --- T35: Validierung ----------------------------------------------------


@ohne_node
@pytest.mark.parametrize(
    "werte,feld,erwartet",
    [
        (
            {"titel": "", "ziel": "Ziel", "akzeptanz": "Kriterium", "prioritaet": "mittel"},
            "titel",
            "Bitte einen Titel eingeben.",
        ),
        (
            {"titel": "Kind", "ziel": "   ", "akzeptanz": "Kriterium", "prioritaet": "mittel"},
            "ziel",
            "Bitte ein Ziel eingeben.",
        ),
        (
            {"titel": "Kind", "ziel": "Ziel", "akzeptanz": "\n  \n", "prioritaet": "mittel"},
            "akzeptanz",
            "Bitte mindestens ein Akzeptanzkriterium eingeben.",
        ),
        (
            {"titel": "Kind", "ziel": "Ziel", "akzeptanz": "Kriterium", "prioritaet": ""},
            "prioritaet",
            "Bitte eine Priorität wählen.",
        ),
        (
            {"titel": "Kind", "ziel": "Ziel", "akzeptanz": "Kriterium", "prioritaet": "dringend"},
            "prioritaet",
            "Unzulässige Priorität.",
        ),
    ],
)
def test_t35_validierung_ohne_post(werte, feld, erwartet):
    ergebnis = detail_lauf(
        f"""
await detail.ladeDetail({{ unterpunkt: AUFGABE }});
await ausloesen(bei("detail-unteraufgabe-anlegen"), "click");
const werte = {json.dumps(werte, ensure_ascii=False)};
for (const [name, wert] of Object.entries(werte)) {{
  bei("unteraufgabe-" + name).value = wert;
}}
await ausloesen(unteraufgabeFormular(), "submit");
const fehlerFelder = {{}};
for (const name of ["titel", "ziel", "akzeptanz", "prioritaet"]) {{
  const element = bei("unteraufgabe-fehler-" + name);
  fehlerFelder[name] = element
    ? {{ text: element.textContent, hidden: element.hidden }}
    : null;
}}
return {{
  posts: aufrufe.filter((eintrag) => eintrag.methode === "POST").length,
  fehlerFelder,
  sichtbar: !bei("unteraufgabe-anlegen").hidden,
  titelWert: bei("unteraufgabe-titel").value,
  speichern: bei("unteraufgabe-speichern")?.disabled ?? null,
  fokus: document.activeElement?.id ?? null,
}};
""",
        _eltern_datei(),
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
    )

    assert ergebnis["posts"] == 0
    assert ergebnis["fehlerFelder"][feld] == {"text": erwartet, "hidden": False}
    for anderes in ("titel", "ziel", "akzeptanz", "prioritaet"):
        if anderes == feld:
            continue
        assert ergebnis["fehlerFelder"][anderes] in (None, {"text": "", "hidden": True})
    # Eingaben bleiben erhalten, das Formular bleibt offen.
    assert ergebnis["sichtbar"] is True
    assert ergebnis["titelWert"] == werte["titel"]
    assert ergebnis["speichern"] is False
    # Fokus liegt auf dem ersten Fehlerfeld (A13-Muster).
    assert ergebnis["fokus"] == f"unteraufgabe-{feld}"


# --- T36: Doppelklick und Fehlerpfad ------------------------------------


@ohne_node
def test_t36_doppelklick_schreibt_nur_einmal():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: AUFGABE });
await ausloesen(bei("detail-unteraufgabe-anlegen"), "click");
bei("unteraufgabe-titel").value = "Erste Unter-Aufgabe";
bei("unteraufgabe-ziel").value = "Ziel";
bei("unteraufgabe-akzeptanz").value = "Kriterium";
const speichern = bei("unteraufgabe-speichern");
const erstes = ausloesen(speichern, "click");
const gesperrtWaehrend = knopfZustand();
const zweites = ausloesen(speichern, "click");
if (freigeben) freigeben();
await Promise.all([erstes, zweites]);
return {
  gesperrtWaehrend,
  posts: aufrufe.filter((eintrag) => eintrag.methode === "POST").length,
  danachBedienbar: knopfZustand(),
};
""",
        _eltern_datei(),
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
        gate=True,
    )

    assert ergebnis["gesperrtWaehrend"] == {"speichern": True, "oeffnen": True}
    assert ergebnis["posts"] == 1
    assert ergebnis["danachBedienbar"] == {"speichern": False, "oeffnen": False}


@ohne_node
def test_t36_fehlerpfad_behaelt_eingaben_und_laedt_nicht_neu():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: AUFGABE });
await ausloesen(bei("detail-unteraufgabe-anlegen"), "click");
bei("unteraufgabe-titel").value = "Erste Unter-Aufgabe";
bei("unteraufgabe-ziel").value = "Ziel";
bei("unteraufgabe-akzeptanz").value = "Kriterium";
await ausloesen(unteraufgabeFormular(), "submit");
return {
  posts: aufrufe.filter((eintrag) => eintrag.methode === "POST").length,
  dateiLadungen: aufrufe.filter((eintrag) => eintrag.endpunkt === "/api/file").length,
  fehler: { sichtbar: !bei("fehler").hidden, text: bei("fehler").textContent },
  meldung: { sichtbar: !bei("meldung").hidden },
  sichtbar: !bei("unteraufgabe-anlegen").hidden,
  titelWert: bei("unteraufgabe-titel").value,
  bedienbar: knopfZustand(),
};
""",
        _eltern_datei(),
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
        task_status=400,
        task_fehler="Eltern-Aufgabe ist nicht zulässig.",
    )

    assert ergebnis["posts"] == 1
    assert ergebnis["dateiLadungen"] == 1
    assert ergebnis["fehler"] == {
        "sichtbar": True,
        "text": "Eltern-Aufgabe ist nicht zulässig.",
    }
    assert ergebnis["meldung"] == {"sichtbar": False}
    assert ergebnis["sichtbar"] is True
    assert ergebnis["titelWert"] == "Erste Unter-Aufgabe"
    assert ergebnis["bedienbar"] == {"speichern": False, "oeffnen": False}


# --- T37: Abschnitt mit Kindern -----------------------------------------


@ohne_node
def test_t37_abschnitt_mit_kindern_sortiert_nach_unter_nummer():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: AUFGABE });
const bereich = abschnitte().find((knoten) =>
  knoten.textContent.includes("Unter-Aufgaben")
);
return {
  ueberschriften: ueberschriften(),
  abschnitte: abschnitte().length,
  klassen: bereich?.klassen() ?? [],
  spalten: bereich
    ? sammle(bereich).filter((knoten) => knoten.marke === "th").map((knoten) => knoten.textContent)
    : [],
  pfade: zeilenPfade(bereich),
  text: bereich?.textContent ?? null,
  teile: teile(),
  anlegen: anzahl("detail", "detail-unteraufgabe-anlegen"),
};
""",
        _eltern_datei(),
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
        aufgaben=[
            _kind(
                KIND_2,
                "A34.002: Zweites",
                zuletzt_geaendert="2026-11-15T12:00:00",
            ),
            _kind(
                KIND_1,
                "A34.001: Erstes",
                zuletzt_geaendert="2026-11-14T08:00:00",
                arbeitsrolle="coder",
                arbeitsrolle_label="Coder",
                arbeitsstatus="Umsetzung Paket 3",
            ),
            _kind(FREMD, "A35.001: Fremdes", eltern="aufgaben/a35-x.md"),
        ],
    )

    assert ergebnis["ueberschriften"].count("Unter-Aufgaben (2)") == 1
    assert "detail-abschnitt" in ergebnis["klassen"]
    assert "uebersicht-block" in ergebnis["klassen"]
    assert ergebnis["spalten"] == ["Titel", "Status", "owner", "zuletzt geändert"]
    # Ordnung ist die Unter-Nummer, nicht die mtime.
    assert ergebnis["pfade"] == [KIND_1, KIND_2]
    # A30-Arbeitsstatus erscheint automatisch in der Status-Zelle.
    assert ARBEITSSTAND in ergebnis["text"]
    # Abschnitt nach dem Inhalt und vor dem Nachtragsformular.
    teile = ergebnis["teile"]
    assert teile.index("kopf") < teile.index("inhalt")
    assert teile.index("inhalt") < teile.index("abschnitt")
    assert teile.index("abschnitt") < teile.index("nachtrag-formular")
    assert ergebnis["anlegen"] == 1


# --- T38: keine Kinder ---------------------------------------------------


@ohne_node
def test_t38_ohne_kinder_kein_abschnitt():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: AUFGABE });
return {
  ueberschriften: ueberschriften(),
  abschnitte: abschnitte().length,
  text: bei("detail").textContent,
  anlegen: anzahl("detail", "detail-unteraufgabe-anlegen"),
  formular: bei("unteraufgabe-anlegen") !== null,
};
""",
        _eltern_datei(),
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
        aufgaben=[],
    )

    assert ergebnis["ueberschriften"] == []
    assert ergebnis["abschnitte"] == 0
    assert "Unter-Aufgaben (" not in ergebnis["text"]
    assert "keine Unter-Aufgaben" not in ergebnis["text"].lower()
    assert ergebnis["anlegen"] == 1
    assert ergebnis["formular"] is True


# --- T39: Fehler/Format fail-loud ---------------------------------------


@ohne_node
@pytest.mark.parametrize(
    "aufgaben,erwartet",
    [
        (None, LADE_FEHLER),
        ({}, FORMAT_FEHLER),
    ],
)
def test_t39_fehler_und_format_sind_sichtbar(aufgaben, erwartet):
    ergebnis = detail_lauf(
        r"""
let geworfen = null;
try {
  await detail.ladeDetail({ unterpunkt: AUFGABE });
} catch (fehler) {
  geworfen = String(fehler);
}
const bereich = abschnitte().find((knoten) =>
  knoten.textContent.includes("Unter-Aufgaben")
);
return {
  geworfen,
  ueberschriften: ueberschriften(),
  pfade: zeilenPfade(bereich),
  text: bereich?.textContent ?? null,
  tabellen: bereich
    ? sammle(bereich).filter((knoten) => knoten.marke === "table").length
    : 0,
};
""",
        _eltern_datei(),
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
        aufgaben=aufgaben,
    )

    assert ergebnis["geworfen"] is None
    assert erwartet in ergebnis["text"]
    assert ergebnis["pfade"] == []
    assert ergebnis["tabellen"] == 0


# --- T40: Abgrenzung -----------------------------------------------------


@ohne_node
def test_t40_abgrenzung_wellen_projekt_und_unteraufgabe():
    welle = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "wellen/w1.md" });
return {
  ueberschriften: ueberschriften(),
  abschnitte: abschnitte().length,
  unteraufgabenKnopf: bei("detail-unteraufgabe-anlegen") !== null,
};
""",
        _datei({"type": "Welle", "title": "Welle 1", "status": "Offen"}),
        aufgaben=[_kind(KIND_1, "A34.001: Erstes", eltern="wellen/w1.md")],
    )
    assert welle["ueberschriften"] == ["Aufgaben dieser Welle (0)"]
    assert "Unter-Aufgaben" not in " ".join(welle["ueberschriften"])
    assert welle["unteraufgabenKnopf"] is False

    projekt = detail_lauf(
        """
await detail.ladeDetail({ unterpunkt: "projekt/phasen.md" });
return {
  ueberschriften: ueberschriften(),
  abschnitte: abschnitte().length,
  unteraufgabenKnopf: bei("detail-unteraufgabe-anlegen") !== null,
};
""",
        _datei({"type": "Projekt", "title": "Phasen"}),
    )
    assert projekt["ueberschriften"] == []
    assert projekt["abschnitte"] == 0
    assert projekt["unteraufgabenKnopf"] is False

    # Unter-Aufgabe mit (fehlerhaft) gesetzten Kind-Daten: kein Abschnitt.
    unter = detail_lauf(
        f"""
await detail.ladeDetail({{ unterpunkt: {json.dumps(KIND_1)} }});
return {{
  ueberschriften: ueberschriften(),
  abschnitte: abschnitte().length,
  unteraufgabenKnopf: bei("detail-unteraufgabe-anlegen") !== null,
  wellenAuswahl: bei("detail-welle") !== null,
}};
""",
        _datei(
            {
                "type": "Task",
                "title": "A34.001: Erstes",
                "task_status": "offen",
                "parent": AUFGABE,
            }
        ),
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
        aufgaben=[_kind(KIND_2, "A34.002: Zweites", eltern=KIND_1)],
    )
    assert unter["ueberschriften"] == []
    assert unter["abschnitte"] == 0
    assert unter["unteraufgabenKnopf"] is False
    # A27-Wellen-Auswahl bleibt unverändert vorhanden.
    assert unter["wellenAuswahl"] is True


@ohne_node
def test_t40_wellen_dropdown_unveraendert():
    ergebnis = detail_lauf(
        """
await detail.ladeDetail({ unterpunkt: "aufgaben/a34-unter-aufgaben.md" });
return {
  werte: optionenwerte(bei("detail-welle")),
  texte: optionstexte(bei("detail-welle")),
};
""",
        _eltern_datei(),
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
    )

    assert ergebnis["werte"][0] == ""
    assert WELLE in ergebnis["werte"]
    assert ergebnis["texte"][0] == "keine"


# --- T41: geschlossene Aufgabe mit Kindern ------------------------------


@ohne_node
def test_t41_geschlossene_aufgabe_zeigt_kinder_ohne_knopf():
    ergebnis = detail_lauf(
        """
await detail.ladeDetail({ unterpunkt: "aufgaben/a34-unter-aufgaben.md" });
const bereich = abschnitte().find((knoten) =>
  knoten.textContent.includes("Unter-Aufgaben")
);
return {
  ueberschriften: ueberschriften(),
  pfade: zeilenPfade(bereich),
  anlegen: anzahl("detail", "detail-unteraufgabe-anlegen"),
  formular: bei("unteraufgabe-anlegen") !== null,
};
""",
        _datei(
            {"type": "Task", "title": "A34: Zu", "task_status": "abgeschlossen"},
            ui_status="Geschlossen",
            hinweis=None,
            owner_default=None,
        ),
        aufgaben=[_kind(KIND_1, "A34.001: Erstes")],
    )

    assert "Unter-Aufgaben (1)" in ergebnis["ueberschriften"]
    assert ergebnis["pfade"] == [KIND_1]
    assert ergebnis["anlegen"] == 0
    assert ergebnis["formular"] is False


# --- T42: XSS ------------------------------------------------------------


@ohne_node
def test_t42_xss_bleibt_text():
    ergebnis = detail_lauf(
        """
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await detail.ladeDetail({ unterpunkt: "aufgaben/a34-unter-aufgaben.md" });
const bereich = abschnitte().find((knoten) =>
  knoten.textContent.includes("Unter-Aufgaben")
);
return {
  text: bereich?.textContent ?? null,
  ueberschriften: ueberschriften(),
  marken: marken(bei("detail")),
  ausfuehrungen,
};
""",
        _eltern_datei(),
        aufgaben=[_kind(KIND_1, HTML_PAYLOAD)],
    )

    assert HTML_PAYLOAD in ergebnis["text"]
    assert "Unter-Aufgaben (1)" in ergebnis["ueberschriften"]
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []


# --- T43: Request-Zähler -------------------------------------------------


@ohne_node
@pytest.mark.parametrize(
    "pfad,datei,endpunkte",
    [
        (AUFGABE, _eltern_datei(), ["/api/file", "/api/wellen", "/api/aufgaben"]),
        (
            KIND_1,
            _datei(
                {
                    "type": "Task",
                    "title": "A34.001: Erstes",
                    "task_status": "offen",
                    "parent": AUFGABE,
                }
            ),
            ["/api/file", "/api/wellen", "/api/aufgaben"],
        ),
        (PROJEKT, _datei({"type": "Projekt", "title": "Phasen"}), ["/api/file"]),
    ],
)
def test_t43_request_budget(pfad, datei, endpunkte):
    ergebnis = detail_lauf(
        f"""
await detail.ladeDetail({{ unterpunkt: {json.dumps(pfad)} }});
return {{ aufrufe: aufrufe.map((eintrag) => eintrag.endpunkt) }};
""",
        datei,
        wellen=[{"path": WELLE, "titel": "Welle 1", "typ": "Welle"}],
        aufgaben=[_kind(KIND_2, "A34.002: Zweites")],
    )

    assert ergebnis["aufrufe"] == endpunkte


# --- T44: Quell-/Strukturprüfung ----------------------------------------


@pytest.mark.parametrize(
    "senke",
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write(", "eval("],
)
def test_t44_unteraufgaben_js_ohne_html_senken(senke):
    quelle = lies(UNTERAUFGABEN_JS)
    assert senke not in quelle
    assert "textContent" in quelle
    assert "createElement" in quelle
    assert "classList" in quelle


def test_t44_detail_js_importiert_den_aufbau():
    detail = lies(DETAIL_JS)
    assert 'from "./unteraufgaben.js"' in detail
    assert "erstelleUnteraufgabenSicht" in detail
    assert "erstelleAnlegeSicht" in detail
    for senke in ("innerHTML", "insertAdjacentHTML", "document.write(", "eval("):
        assert senke not in detail


def test_t44_rahmen_dateien_ohne_neues_markup():
    html = lies(INDEX_HTML).lower()
    assert "unteraufgabe" not in html
    assert "detail-unteraufgabe" not in html
    for datei in (STYLE_CSS, APP_JS, API_JS, LISTE_JS, FORMULARE_JS):
        assert "unteraufgabe" not in lies(datei).lower(), datei.name


# --- T45: Idempotenz -----------------------------------------------------


@ohne_node
def test_t45_zweimal_laden_erzeugt_keine_duplikate():
    ergebnis = detail_lauf(
        """
await detail.ladeDetail({ unterpunkt: "aufgaben/a34-unter-aufgaben.md" });
await detail.ladeDetail({ unterpunkt: "aufgaben/a34-unter-aufgaben.md" });
const bereich = abschnitte().find((knoten) =>
  knoten.textContent.includes("Unter-Aufgaben")
);
return {
  anlegen: anzahl("detail", "detail-unteraufgabe-anlegen"),
  bereiche: anzahl("detail", "unteraufgabe-anlegen"),
  ueberschriften: ueberschriften(),
  pfade: zeilenPfade(bereich),
  formulare: sammle(bei("detail")).filter((knoten) => knoten.marke === "form").length,
};
""",
        _eltern_datei(),
        aufgaben=[
            _kind(KIND_1, "A34.001: Erstes"),
            _kind(KIND_2, "A34.002: Zweites"),
        ],
    )

    assert ergebnis["anlegen"] == 1
    assert ergebnis["bereiche"] == 1
    assert ergebnis["ueberschriften"].count("Unter-Aufgaben (2)") == 1
    assert ergebnis["ueberschriften"].count("Unter-Aufgaben (2)") == len(ergebnis["ueberschriften"])
    assert ergebnis["pfade"] == [KIND_1, KIND_2]
    assert ergebnis["formulare"] == 2


# --- T46: Payload/Sortierung (Unit) -------------------------------------


@ohne_node
def test_t46_erstelle_payload_mit_parent_zuletzt():
    ergebnis = js_unteraufgaben(
        "unteraufgaben.erstellePayload("
        "{ titel: ' Kind ', ziel: 'Ziel', akzeptanz: 'A\\n\\nB', prioritaet: 'hoch',"
        " welle: 'wellen/w1.md', user_story: 'US' },"
        " 'aufgaben/a34-x.md')"
    )
    assert list(ergebnis) == ["titel", "ziel", "akzeptanz", "prioritaet", "parent"]
    assert ergebnis == {
        "titel": "Kind",
        "ziel": "Ziel",
        "akzeptanz": ["A", "B"],
        "prioritaet": "hoch",
        "parent": "aufgaben/a34-x.md",
    }


@ohne_node
def test_t46_unteraufgaben_von_filtert_und_sortiert():
    daten = [
        _kind(KIND_2, "A34.002: Zweites"),
        _aufgabe(AUFGABE, "A34: Eltern"),
        _kind(KIND_1, "A34.001: Erstes"),
        _kind(FREMD, "A35.001: Fremdes", eltern="aufgaben/a35-x.md"),
        "kein Objekt",
        {"path": "aufgaben/ohne.md", "parent": None},
    ]
    ergebnis = js_unteraufgaben(
        "unteraufgaben.sortiereUnteraufgaben("
        "unteraufgaben.unteraufgabenVon(daten, 'aufgaben/a34-unter-aufgaben.md'))"
        ".map((eintrag) => eintrag.path)",
        daten,
    )
    assert ergebnis == [KIND_1, KIND_2]

    for quelle in ("null", "undefined", "'kein Array'", "{}", "42"):
        assert js_unteraufgaben(f"unteraufgaben.unteraufgabenVon({quelle}, 'aufgaben/a34-x.md')") == []
        assert js_unteraufgaben(f"unteraufgaben.sortiereUnteraufgaben({quelle})") == []


@ohne_node
def test_t46_sortierung_ohne_nummer_nach_pfad():
    daten = [
        _kind("aufgaben/b.md", "Ohne Nummer B"),
        _kind("aufgaben/a.md", "A34.005: Fünf"),
        _kind("aufgaben/c.md", "Ohne Nummer C"),
    ]
    ergebnis = js_unteraufgaben(
        "unteraufgaben.sortiereUnteraufgaben(daten).map((eintrag) => eintrag.path)",
        daten,
    )
    # Nummerierte zuerst, dann nach Pfad.
    assert ergebnis == ["aufgaben/a.md", "aufgaben/b.md", "aufgaben/c.md"]
