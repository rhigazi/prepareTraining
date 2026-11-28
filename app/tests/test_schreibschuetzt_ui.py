"""A36: Schreib-UI-Grenze — ``schreibgeschuetzt`` blendet Schreibaktionen aus.

Der Server markiert reservierte Dateien (``index.md``/``log.md``/``features.md``);
die Detailansicht zeigt dann nur noch Lese-Inhalte: kein Nachtragsformular, kein
owner-Umschalter, keine Statusknöpfe, keine Freigabe-Bedienung. Es gibt **keine**
zweite Namensliste im JavaScript — die UI folgt ausschließlich dem Server-Signal.
"""

import json
import re
import sys
from pathlib import Path

import pytest

from dom_helfer import DETAIL_JS, MINI_DOM, lies, node_ausfuehren, ohne_node

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

/** Frontmatter-Felder als dt → dd-Text. */
function felder() {
  const dl = sammle(bei("detail")).find((knoten) => knoten.marke === "dl");
  const kinder = dl ? dl.kinder : [];
  const ergebnis = {};
  for (let i = 0; i + 1 < kinder.length; i += 2) {
    ergebnis[kinder[i].textContent] = kinder[i + 1].textContent;
  }
  return ergebnis;
}

/** Alle Schreib-Bedienelemente der Detailansicht; ``anlegen`` ist der Bereich. */
function schreibAktionen() {
  return {
    nachtrag: bei("nachtrag-formular") !== null,
    textfeld: bei("nachtrag-text") !== null,
    ownerAuswahl: bei("detail-owner") !== null,
    wellenAuswahl: bei("detail-welle") !== null,
    statusKnoepfe: sammle(bei("detail")).filter((knoten) => knoten.dataset.status).length,
    freigabeKnopf: bei("detail-freigabe") !== null,
    wellenFreigabeKnopf: bei("detail-welle-freigabe") !== null,
    anlegen: bei("unteraufgabe-anlegen") !== null,
  };
}

/** Endpunkte der abgesetzten Aufrufe (ohne Query, für Guard-Assertions). */
function endpunkte() {
  return aufrufe.map((eintrag) => eintrag.endpunkt);
}
"""


def detail_lauf(ablauf: str, datei: dict, *, wellen=None, aufgaben=None) -> dict:
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


def _datei(frontmatter: dict, markdown: str = "# Inhalt\n\nFixture.\n", **felder) -> dict:
    daten = {"frontmatter": frontmatter, "markdown": markdown, "nachtraege": []}
    daten.update(felder)
    return daten


def _reserviert(frontmatter: dict, **felder) -> dict:
    return _datei(frontmatter, schreibgeschuetzt=True, owner_default="mensch", **felder)


def _frei(frontmatter: dict, **felder) -> dict:
    return _datei(frontmatter, schreibgeschuetzt=False, owner_default="mensch", **felder)


# --- T1: reservierte Datei — alle Schreibaktionen fehlen ------------------


@ohne_node
def test_t1_reservierte_datei_ohne_schreibaktionen():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "index.md" });
return {
  ...schreibAktionen(),
  aufrufe: endpunkte(),
  felder: felder(),
  inhalt: bei("detail").textContent,
};
""",
        _reserviert({"type": "Index", "title": "Mini-Bundle"}),
    )

    assert ergebnis["nachtrag"] is False
    assert ergebnis["textfeld"] is False
    assert ergebnis["ownerAuswahl"] is False
    assert ergebnis["wellenAuswahl"] is False
    assert ergebnis["statusKnoepfe"] == 0
    assert ergebnis["freigabeKnopf"] is False
    assert ergebnis["wellenFreigabeKnopf"] is False
    assert ergebnis["anlegen"] is False
    # Gesperrt: keine Wellenliste laden (kein Auswahl-Bedarf).
    assert "/api/wellen" not in ergebnis["aufrufe"]
    # Lesen bleibt vollständig: Inhalt und Kopfdaten stehen weiter da.
    assert "Fixture." in ergebnis["inhalt"]
    assert ergebnis["felder"]["Typ"] == "Index"
    assert ergebnis["felder"]["owner"] == "mensch"


@ohne_node
def test_t1_reservierte_datei_erklaert_die_fehlenden_aktionen():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "log.md" });
const hinweis = bei("detail-schreibgeschuetzt-hinweis");
return { text: hinweis?.textContent ?? null, sichtbar: hinweis ? !hinweis.hidden : false };
""",
        _reserviert({"type": "Log", "title": "Projekt-Log"}),
    )

    assert ergebnis["sichtbar"] is True
    assert "Schreibgeschützt" in ergebnis["text"]


# --- T2: reservierte Welle — Zustand ja, Knopf nein -----------------------


@ohne_node
def test_t2_reservierte_welle_ohne_freigabe_knopf():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "wellen/w1.md" });
return {
  ...schreibAktionen(),
  zustand: bei("detail-welle-freigabe-status")?.textContent ?? null,
};
""",
        _reserviert({"type": "Welle", "title": "Welle 1"}, freigabe=False),
    )

    assert ergebnis["wellenFreigabeKnopf"] is False
    assert ergebnis["freigabeKnopf"] is False
    assert ergebnis["nachtrag"] is False
    # Der reine Zustand bleibt lesbar (keine Bedienung, aber Information).
    assert ergebnis["zustand"] == "nicht freigegeben (Standard)"


# --- T3: Aufgabe mit Signal — Zustand statt Bedienung ---------------------


@ohne_node
def test_t3_reservierte_aufgabe_zeigt_werte_statt_bedienung():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
return {
  ...schreibAktionen(),
  aufrufe: endpunkte(),
  zustand: bei("detail-freigabe-status")?.textContent ?? null,
  felder: felder(),
};
""",
        _reserviert(
            {"type": "Task", "title": "A1: Aufgabe", "welle": "wellen/w1.md"},
            freigabe=False,
        ),
        wellen=[{"path": "wellen/w1.md", "titel": "Welle 1"}],
    )

    assert ergebnis["statusKnoepfe"] == 0
    assert ergebnis["ownerAuswahl"] is False
    assert ergebnis["wellenAuswahl"] is False
    assert ergebnis["freigabeKnopf"] is False
    assert ergebnis["nachtrag"] is False
    # Gesperrte Aufgabe: kein Anlegen-Bereich (M8).
    assert ergebnis["anlegen"] is False
    # A36-K4: Die Wellenliste wird nur noch für das lesbare Label geladen;
    # eine Auswahl entsteht daraus nicht (M9 bleibt für Dateien ohne Welle).
    assert ergebnis["aufrufe"].count("/api/wellen") == 1
    assert ergebnis["zustand"] == "Nicht freigegeben"
    # Werte bleiben als Text sichtbar (kein stilles Verschwinden).
    assert ergebnis["felder"]["owner"] == "mensch"
    assert ergebnis["felder"]["Welle"] == "Welle 1 (wellen/w1.md)"


@ohne_node
def test_t3_gesperrte_aufgabe_zeigt_welle_wie_ungesperrt():
    """A36-K4: gesperrt und ungesperrt nennen die Welle gleich (Titel (Pfad))."""
    arbeitsablauf = r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
const auswahl = bei("detail-welle");
const gewaehlt = auswahl ? auswahl.kinder.find((kind) => kind.value === "wellen/w1.md") : null;
return {
  text: felder()["Welle"],
  option: gewaehlt ? gewaehlt.textContent : null,
};
"""
    frontmatter = {"type": "Task", "title": "A1: Aufgabe", "welle": "wellen/w1.md"}
    wellen = [{"path": "wellen/w1.md", "titel": "Welle 1"}]

    gesperrt = detail_lauf(arbeitsablauf, _reserviert(frontmatter, freigabe=False), wellen=wellen)
    offen = detail_lauf(arbeitsablauf, _frei(frontmatter, freigabe=False), wellen=wellen)

    assert gesperrt["text"] == "Welle 1 (wellen/w1.md)"
    assert offen["option"] == gesperrt["text"]


@ohne_node
@pytest.mark.parametrize(
    "wellen",
    [
        pytest.param([], id="leere-liste"),
        pytest.param([{"path": "wellen/w1.md", "titel": "  "}], id="ohne-titel"),
    ],
)
def test_t3_gesperrte_aufgabe_faellt_auf_den_dateistamm_zurueck(wellen):
    """A36-K4 fail-safe: ohne lesbaren Titel bleibt der Dateistamm, nie der Pfad."""
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
return { text: felder()["Welle"] };
""",
        _reserviert(
            {"type": "Task", "title": "A1: Aufgabe", "welle": "wellen/w1.md"},
            freigabe=False,
        ),
        wellen=wellen,
    )

    assert ergebnis["text"] == "w1"
    assert "wellen/" not in ergebnis["text"]


@ohne_node
def test_t3_gesperrte_aufgabe_ohne_welle_laedt_keine_liste():
    """A36-K4: ohne Welle bleibt es beim bisherigen sparsamen Verhalten (M9)."""
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
return { text: felder()["Welle"], aufrufe: endpunkte() };
""",
        _reserviert({"type": "Task", "title": "A1: Aufgabe"}, freigabe=False),
    )

    assert ergebnis["text"] == "—"
    assert "/api/wellen" not in ergebnis["aufrufe"]


# --- T4: ohne Signal bleibt die volle Schreib-UI --------------------------


@ohne_node
@pytest.mark.parametrize("signal", [False, None, "true", 1])
def test_t4_ohne_exaktes_signal_bleibt_die_ui_bedienbar(signal):
    datei = _frei({"type": "Task", "title": "A1: Aufgabe"}, freigabe=False)
    if signal is None:
        datei.pop("schreibgeschuetzt")
    else:
        datei["schreibgeschuetzt"] = signal

    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
return {
  ...schreibAktionen(),
  aufrufe: endpunkte(),
  hinweis: bei("detail-schreibgeschuetzt-hinweis") !== null,
};
""",
        datei,
        wellen=[{"path": "wellen/w1.md", "titel": "Welle 1"}],
    )

    assert ergebnis["nachtrag"] is True
    assert ergebnis["ownerAuswahl"] is True
    assert ergebnis["wellenAuswahl"] is True
    assert ergebnis["statusKnoepfe"] == 2
    assert ergebnis["freigabeKnopf"] is True
    # Ungesperrte Kontrollprobe: Anlegen da, Wellenliste wird geladen (M8/M9).
    assert ergebnis["anlegen"] is True
    assert "/api/wellen" in ergebnis["aufrufe"]
    # K1: Der Sperrhinweis erscheint nur bei gesperrten Dateien.
    assert ergebnis["hinweis"] is False


# --- T5: keine zweite Namensliste im JavaScript ---------------------------


def test_t5_keine_reservierte_namensliste_im_detail_js():
    quelle = lies(DETAIL_JS)

    assert "schreibgeschuetzt" in quelle
    for name in ("index.md", "log.md", "features.md"):
        assert name not in quelle, f"detail.js dupliziert die reservierte Namensliste ({name})"
    assert re.search(r"ist_reserviert", quelle) is None
