"""A35: Die Detailansicht nutzt das server-seitige Status-Mapping (A12-1).

Der JS-Spiegel ``TASK_STATUS_UI``/``OWNER_DEFAULTS`` ist entfernt. Die UI zeigt
ausschließlich ``ui_status``/``hinweis``/``owner_default`` aus ``GET /api/file``
und leitet selbst keinen ``task_status`` mehr ab. Die Läufe nutzen den
gemeinsamen Mini-DOM-Harness (``dom_helfer.py``) und einen Fetch-Stab — nie
``wissen/``.
"""

import json
from pathlib import Path

import pytest

from dom_helfer import (
    DETAIL_JS,
    MINI_DOM,
    js_detail,
    lies,
    node_ausfuehren,
    ohne_node,
)

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

HTML_PAYLOAD = "<img src=x onerror=alert(1)>"
SCRIPT_PAYLOAD = "<script>alert(1)</script>"


# --- Quell-/Strukturprüfung ----------------------------------------------


@pytest.mark.parametrize("spiegel", ["TASK_STATUS_UI", "OWNER_DEFAULTS", "UI_STATUS_WERTE"])
def test_t1_js_spiegel_ist_entfernt(spiegel):
    assert spiegel not in lies(DETAIL_JS)


@pytest.mark.parametrize("feld", ["ui_status", "hinweis", "owner_default"])
def test_t2_js_nutzt_server_felder(feld):
    assert feld in lies(DETAIL_JS)


def test_t3_keine_html_senken_in_der_detailansicht():
    quelle = lies(DETAIL_JS)
    for senke in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write(", "eval("):
        assert senke not in quelle
    assert "textContent" in quelle


# --- Reine Logik (Server-Felder) -----------------------------------------


@ohne_node
def test_t4_status_kommt_aus_ui_status():
    assert js_detail("detail.ermittleStatus({ ui_status: 'Klarung', hinweis: 'pausiert' })") == {
        "status": "Klarung",
        "hinweis": "pausiert",
    }
    assert js_detail("detail.ermittleStatus({ ui_status: 'In Arbeit', hinweis: null })") == {
        "status": "In Arbeit",
        "hinweis": None,
    }


@ohne_node
@pytest.mark.parametrize(
    "daten",
    [
        {},
        {"task_status": "in Umsetzung"},
        {"frontmatter": {"task_status": "abgeschlossen"}},
        # Der alte Wellen-Zweig las `frontmatter.status` (und `status`). Beide
        # Formen bleiben ohne Serverfeld wirkungslos — auch ein gültiger
        # UI-Status darf nicht clientseitig gemappt werden.
        {"status": "Geschlossen"},
        {"frontmatter": {"status": "Geschlossen"}},
        {"ui_status": None},
    ],
)
def test_t5_ohne_server_status_kein_js_mapping(daten):
    # Ohne Server-Feld wird nichts abgeleitet: keine zweite Mapping-Quelle.
    assert js_detail("detail.ermittleStatus(daten)", daten) == {
        "status": "Offen",
        "hinweis": None,
    }


@ohne_node
def test_t6_owner_kommt_aus_owner_default():
    assert js_detail("detail.ermittleOwner({ owner_default: 'mensch', frontmatter: {} })") == (
        "mensch"
    )
    # Der Server löst das explizite owner-Feld bereits auf; sein Wert hat Vorrang.
    assert js_detail(
        "detail.ermittleOwner({ owner_default: 'ai', frontmatter: { owner: 'mensch' } })"
    ) == "ai"


@ohne_node
def test_t7_owner_fallback_auf_rohes_frontmatter():
    assert js_detail("detail.ermittleOwner({ frontmatter: { owner: 'bot' } })") == "bot"
    assert js_detail("detail.ermittleOwner({})") is None


# --- DOM-Regression -------------------------------------------------------

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
  if (methode === "GET" && adresse === "/api/wellen") return antworte(200, []);
  if (methode === "GET" && adresse === "/api/aufgaben") return antworte(200, []);
  return antworte(404, { error: "Nicht gefunden." });
};

const statusZeile = () => {
  const marke = sammle(bei("detail")).find((knoten) => knoten.classList.contains("status"));
  return marke ? marke.parentElement.textContent : null;
};
"""


def detail_lauf(ablauf: str, datei: dict) -> dict:
    skript = (
        MINI_DOM
        + f"const DATEI = {json.dumps(datei, ensure_ascii=False)};\n"
        + DETAIL_SEITE
        + f"\nimport * as detail from {json.dumps(DETAIL_JS.as_uri())};\n"
        + "const ergebnis = await (async () => {\n"
        + ablauf
        + "\n})();\n"
        + "console.log(JSON.stringify(ergebnis));\n"
    )
    return node_ausfuehren(skript)


def _datei(frontmatter: dict, **felder) -> dict:
    daten = {"frontmatter": frontmatter, "markdown": "# Ziel\n\nFixture.\n", "nachtraege": []}
    daten.update(felder)
    return daten


@ohne_node
def test_t8_dom_zeigt_server_status_und_hinweis():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
return {
  status: statusZeile(),
  marken: marken(bei("detail")),
  fehler: { sichtbar: !fehler.hidden, text: fehler.textContent },
};
""",
        _datei(
            {"type": "Task", "title": "A1: Fixture", "task_status": "in Umsetzung"},
            ui_status="Testing",
            hinweis="pausiert",
            owner_default="ai",
        ),
    )

    assert "Testing" in ergebnis["status"]
    assert "(pausiert)" in ergebnis["status"]
    assert ergebnis["fehler"] == {"sichtbar": False, "text": ""}


@ohne_node
def test_t9_dom_ignoriert_abweichenden_task_status():
    """Der frühere JS-Spiegel hätte „In Arbeit" gezeigt — jetzt gilt der Server."""
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
return { status: statusZeile() };
""",
        _datei(
            {"type": "Task", "title": "A1: Fixture", "task_status": "in Umsetzung"},
            ui_status="Klarung",
            hinweis=None,
            owner_default="mensch",
        ),
    )

    assert "Klarung" in ergebnis["status"]
    assert "In Arbeit" not in ergebnis["status"]


@ohne_node
def test_t10_dom_owner_kommt_aus_owner_default():
    ergebnis = detail_lauf(
        r"""
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
return { owner: bei("detail-owner").value };
""",
        _datei(
            {"type": "Task", "title": "A1: Fixture", "task_status": "offen"},
            ui_status="Offen",
            hinweis=None,
            owner_default="mensch",
        ),
    )

    assert ergebnis["owner"] == "mensch"


@ohne_node
def test_t11_dom_hinweis_bleibt_text():
    ergebnis = detail_lauf(
        """
const ausfuehrungen = [];
globalThis.alert = (wert) => ausfuehrungen.push(String(wert));
await detail.ladeDetail({ unterpunkt: "aufgaben/a1.md" });
return { status: statusZeile(), marken: marken(bei("detail")), ausfuehrungen };
""",
        _datei(
            {"type": "Task", "title": "A1: Fixture", "task_status": "offen"},
            ui_status="Offen",
            hinweis=f"{HTML_PAYLOAD} {SCRIPT_PAYLOAD}",
            owner_default="ai",
        ),
    )

    assert HTML_PAYLOAD in ergebnis["status"]
    assert SCRIPT_PAYLOAD in ergebnis["status"]
    assert "img" not in ergebnis["marken"]
    assert "script" not in ergebnis["marken"]
    assert ergebnis["ausfuehrungen"] == []
