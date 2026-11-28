"""TDD-Tests für die Wahrnehmungssignale ``neu``/``kennung``/``naechste_kennung`` (A28, Paket 1).

Die Lese-API leitet deterministisch ab, ob eine Aufgabe noch keine gültige
Kennung trägt — Grundlage für die Marke „neu" und den Kennungs-Hinweis im
Detail. Alle Läufe arbeiten gegen das ``bundle``-Fixture (``tmp_path``).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import freigabe
import kennung
import okf_bundle
import server

AUFGABE = "aufgaben/a1.md"
WELLE = "wellen/w1.md"
NEU = "aufgaben/benachrichtigung-neue-aufgabe.md"
KAPUTT = "aufgaben/kaputt.md"
PROJEKT = "projekt/phasen.md"


@pytest.fixture()
def client(bundle):
    return server.create_app(bundle).test_client()


def _schreibe(bundle, pfad: str, text: str) -> Path:
    ziel = bundle / pfad
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    return ziel


def _aufgabe(bundle, pfad: str, titel: str, task_status: str = "offen") -> Path:
    return _schreibe(
        bundle,
        pfad,
        f"---\ntype: Task\ntitle: {titel!r}\ntask_status: {task_status}\nowner: ai\n"
        "---\n\n# Ziel\n\nFixture.\n",
    )


def _eintraege(client, endpunkt: str = "/api/aufgaben") -> dict:
    return {eintrag["path"]: eintrag for eintrag in client.get(endpunkt).get_json()}


# --- T1: neu ohne Kennung ------------------------------------------------


def test_t1_neu_ohne_kennung(client, bundle):
    _schreibe(
        bundle,
        NEU,
        "---\ntype: Task\ntitle: Benachrichtigung bei neuer Aufgabe\ntask_status: offen\n"
        "owner: ai\n---\n\n# Ziel\n\nOhne Kennung.\n",
    )

    aufgaben = _eintraege(client)
    assert aufgaben[NEU]["typ"] == "Task"
    assert aufgaben[NEU]["neu"] is True

    uebersicht = _eintraege(client, "/api/overview")
    assert uebersicht[NEU]["neu"] is True
    assert "neu" not in uebersicht[WELLE]


# --- T2: neu false bei konsistenter Kennung ------------------------------


def test_t2_neu_false_bei_konsistenter_kennung(client, bundle):
    _schreibe(
        bundle,
        "aufgaben/a2.md",
        "---\ntype: Task\ntitle: \"A2: Zweite\"\ntask_status: offen\nowner: ai\n"
        "welle: wellen/w1.md\n---\n\n# Ziel\n\nMit Kennung.\n",
    )

    eintrag = _eintraege(client)["aufgaben/a2.md"]

    assert eintrag["neu"] is False
    assert eintrag["status"] == "Offen"
    assert eintrag["owner"] == "ai"
    assert eintrag["welle"] == "wellen/w1.md"


# --- T3: halbe/inkonsistente Kennung ------------------------------------


@pytest.mark.parametrize(
    "pfad,titel,erwartet",
    [
        ("aufgaben/x.md", "A12: X", True),
        ("aufgaben/a12-x.md", "X", True),
        ("aufgaben/a13-x.md", "A12: X", True),
        ("aufgaben/a12-x.md", "A12: X", False),
        ("aufgaben/a12.md", "A12: X", False),
    ],
)
def test_t3_halbe_und_inkonsistente_kennung(client, bundle, pfad, titel, erwartet):
    _schreibe(
        bundle,
        pfad,
        f"---\ntype: Task\ntitle: {titel!r}\ntask_status: offen\n---\n\n# Ziel\n\nText.\n",
    )

    assert _eintraege(client)[pfad]["neu"] is erwartet


# --- T4: Formatstrenge ---------------------------------------------------


@pytest.mark.parametrize(
    "titel",
    ["A: X", "A12:X", "a12: X", "A12 - X", "A0: X", None, 42, "A12.1: X"],
)
def test_t4_formatstrenge_ist_neu(client, bundle, titel):
    zeilen = ["---", "type: Task", "task_status: offen"]
    if titel is not None:
        zeilen.append(f"title: {titel!r}" if isinstance(titel, str) else f"title: {titel}")
    zeilen += ["---", "", "# Ziel", "", "Text.", ""]
    _schreibe(bundle, "aufgaben/a12-x.md", "\n".join(zeilen))

    eintrag = _eintraege(client)["aufgaben/a12-x.md"]

    assert eintrag["neu"] is True


def test_t4_nur_kennung_ist_gueltig(client, bundle):
    _schreibe(
        bundle,
        "aufgaben/a12-x.md",
        "---\ntype: Task\ntitle: \"A12: \"\ntask_status: offen\n---\n\n# Ziel\n\nText.\n",
    )

    assert _eintraege(client)["aufgaben/a12-x.md"]["neu"] is False


# --- T5: naechste_kennung ------------------------------------------------


def test_t5_naechste_kennung_aus_titel_und_dateinamen(client, bundle):
    _schreibe(
        bundle,
        "aufgaben/a27-x.md",
        "---\ntype: Task\ntitle: \"A27: Alt\"\ntask_status: offen\n---\n\n# Ziel\n",
    )
    _schreibe(
        bundle,
        "aufgaben/a3-y.md",
        "---\ntype: Task\ntitle: \"A7: Titel zählt\"\ntask_status: offen\n---\n\n# Ziel\n",
    )
    _schreibe(bundle, KAPUTT, "---\ntype: Task\nbroken: [unclosed\n---\n\n# Ziel\n")

    daten = client.get(f"/api/file?path={AUFGABE}").get_json()

    assert daten["naechste_kennung"] == "A28"


def test_t5_einzige_aufgabe_ergibt_a2(client, bundle):
    for datei in (bundle / "aufgaben").iterdir():
        datei.unlink()
    _schreibe(
        bundle,
        AUFGABE,
        "---\ntype: Task\ntitle: \"A1: Einzige\"\ntask_status: offen\n---\n\n# Ziel\n",
    )

    assert client.get(f"/api/file?path={AUFGABE}").get_json()["naechste_kennung"] == "A2"


def test_t5_leerer_bestand_ist_a1(bundle):
    """Ohne jede Aufgaben-Datei schlägt die Kennungs-Hilfe ``A1`` vor (AK-2)."""
    for datei in (bundle / "aufgaben").iterdir():
        datei.unlink()

    assert kennung.naechste_kennung() == "A1"


@pytest.mark.parametrize("pfad", [WELLE, PROJEKT])
def test_t5_nicht_tasks_ohne_kennungsfelder(client, bundle, pfad):
    _schreibe(bundle, PROJEKT, "---\ntype: Projekt\ntitle: Phasen\n---\n\n# Phasen\n")

    daten = client.get(f"/api/file?path={pfad}").get_json()

    assert "neu" not in daten
    assert "kennung" not in daten
    assert "naechste_kennung" not in daten


def test_t5_zugewiesene_unterkennung_gilt_als_vergeben(client, bundle):
    _schreibe(
        bundle,
        "aufgaben/a34.001-x.md",
        "---\ntype: Task\ntitle: \"A34.001: Unterkennung\"\ntask_status: offen\n---\n\n# Ziel\n",
    )

    eintrag = _eintraege(client)["aufgaben/a34.001-x.md"]

    assert eintrag["neu"] is False
    assert client.get("/api/file?path=aufgaben/a34.001-x.md").get_json()["kennung"] == "A34.001"
    # ``naechste_kennung`` ist top-level-only (A34-AK-2): eine verwaiste
    # Unter-Kennung (ohne Eltern-Datei A34) beeinflusst den Vorschlag nicht.
    assert client.get(f"/api/file?path={AUFGABE}").get_json()["naechste_kennung"] == "A2"


@pytest.mark.parametrize("titel", ["A34: Ohne Slug", "Ohne Kennung"])
def test_t5_datei_ohne_slug_zaehlt_als_belegt(client, bundle, titel):
    """W1 (Review): ``a34.md`` ist auch ohne Slug eine belegte Kennung.

    Der alte ``overview``-Regex verlangte ``-`` (oder ``.``) nach der Nummer und
    ignorierte ``a34.md`` — daraus konnte eine Doppelkennung entstehen.
    """
    # Mutanten-Schärfe (W1): scharf ist die Variante ohne Titel-Kennung
    # (``titel = "Ohne Kennung"``) — sie deckt den Pfad ab, bei dem nur der
    # Dateiname ``a34.md`` die Kennung trägt; der andere Parametrisierungsfall
    # (``"A34: Ohne Slug"``) prüft den Titel-Pfad. Beide müssen grün sein,
    # sonst überlebt der Mutant ``_DATEI`` ohne ``(?:-|$)``-Alternative.
    _schreibe(
        bundle,
        "aufgaben/a34.md",
        f"---\ntype: Task\ntitle: {titel!r}\ntask_status: offen\n---\n\n# Ziel\n",
    )

    assert client.get(f"/api/file?path={AUFGABE}").get_json()["naechste_kennung"] == "A35"


def test_t5_unterdatei_ohne_slug_zaehlt_top_level_nicht(client, bundle):
    """W1-Gegenprobe: ``a34.001.md`` ist Unter-Kennung, keine Top-Level-Nummer."""
    _schreibe(
        bundle,
        "aufgaben/a34.001.md",
        "---\ntype: Task\ntitle: \"A34.001: Unter\"\ntask_status: offen\n---\n\n# Ziel\n",
    )

    assert client.get(f"/api/file?path={AUFGABE}").get_json()["naechste_kennung"] == "A2"


# --- T6: Detail-Felder ---------------------------------------------------


def test_t6_detail_felder(client):
    daten = client.get(f"/api/file?path={AUFGABE}").get_json()

    assert daten["neu"] is False
    assert daten["kennung"] == "A1"
    assert {"frontmatter", "markdown", "nachtraege"} <= set(daten)
    assert daten["frontmatter"]["title"] == "A1: Mini-Aufgabe"


def test_t6_ohne_kennung_kein_kennung_feld(client, bundle):
    _schreibe(
        bundle,
        NEU,
        "---\ntype: Task\ntitle: Benachrichtigung\ntask_status: offen\n---\n\n# Ziel\n",
    )

    daten = client.get(f"/api/file?path={NEU}").get_json()

    assert daten["neu"] is True
    assert "kennung" not in daten
    assert daten["naechste_kennung"] == "A2"


# --- T7: nicht lesbare Aufgabe ------------------------------------------


def test_t7_nicht_lesbare_aufgabe_ist_neu(client, bundle):
    _schreibe(bundle, KAPUTT, "---\ntype: Task\nbroken: [unclosed\n---\n\n# Ziel\n")

    antwort = client.get("/api/aufgaben")

    assert antwort.status_code == 200
    eintraege = {eintrag["path"]: eintrag for eintrag in antwort.get_json()}
    assert eintraege[KAPUTT]["hinweis"] == "nicht lesbar"
    assert eintraege[KAPUTT]["neu"] is True
    assert eintraege[AUFGABE]["neu"] is False
    # Kein stilles Weglassen: alle Dateien bleiben enthalten, Sortierung intakt.
    liste = antwort.get_json()
    assert {eintrag["path"] for eintrag in liste} >= {AUFGABE, KAPUTT}
    zeiten = [eintrag["zuletzt_geaendert"] for eintrag in liste]
    assert zeiten == sorted(zeiten, reverse=True)


# --- T22: Neuanlage (API) ------------------------------------------------


def test_t22_neue_aufgabe_ueber_die_app(client, bundle):
    antwort = client.post(
        "/api/task",
        json={
            "titel": "Benachrichtigung bei neuer Aufgabe",
            "ziel": "Ziel der neuen Aufgabe.",
            "akzeptanz": ["Erstes Kriterium."],
            "prioritaet": "hoch",
        },
    )

    assert antwort.status_code == 200
    pfad = antwort.get_json()["path"]
    inhalt = (bundle / pfad).read_text(encoding="utf-8")
    assert "freigabe: false" in inhalt
    assert freigabe.ist_freigegeben(okf_bundle.lesen(pfad)[0]) is False

    eintrag = _eintraege(client)[pfad]
    assert eintrag["neu"] is True
    assert eintrag["freigabe"] is False

    ueberschriften = [
        zeile.rstrip()
        for zeile in okf_bundle.lesen(pfad)[1].splitlines()
        if zeile.startswith("# ")
    ]
    assert ueberschriften == [
        "# Ziel",
        "# Akzeptanzkriterien",
        "# Testfälle (TDD)",
        "# Kontext",
        "# Betroffene Dateien",
        "# Ergebnisse",
    ]


# --- A34: Unter-Kennungen in neu/kennung (additiv) ------------------------


def test_t9_unterkennung_ist_zugewiesen(client, bundle):
    _schreibe(
        bundle,
        "aufgaben/a34.001-x.md",
        "---\ntype: Task\ntitle: \"A34.001: Unterkennung\"\ntask_status: offen\n---\n\n# Ziel\n",
    )

    for endpunkt in ("/api/aufgaben", "/api/overview"):
        eintrag = _eintraege(client, endpunkt)["aufgaben/a34.001-x.md"]
        assert eintrag["neu"] is False

    daten = client.get("/api/file?path=aufgaben/a34.001-x.md").get_json()
    assert daten["neu"] is False
    assert daten["kennung"] == "A34.001"


@pytest.mark.parametrize(
    "pfad,titel",
    [
        ("aufgaben/a34.001-x.md", "A34: X"),
        ("aufgaben/a34-x.md", "A34.001: X"),
        ("aufgaben/a34.002-x.md", "A34.001: X"),
        ("aufgaben/a34-001-x.md", "A34.001: X"),
    ],
)
def test_t10_unterkennung_abweichung_ist_neu(client, bundle, pfad, titel):
    _schreibe(
        bundle,
        pfad,
        f"---\ntype: Task\ntitle: {titel!r}\ntask_status: offen\n---\n\n# Ziel\n",
    )

    assert _eintraege(client)[pfad]["neu"] is True


def test_t11_detail_felder_unteraufgabe(client, bundle):
    _schreibe(
        bundle,
        "aufgaben/a34-x.md",
        "---\ntype: Task\ntitle: \"A34: Eltern\"\ntask_status: offen\n---\n\n# Ziel\n",
    )
    _schreibe(
        bundle,
        "aufgaben/a34.001-y.md",
        "---\ntype: Task\ntitle: \"A34.001: Kind\"\ntask_status: offen\n"
        "parent: aufgaben/a34-x.md\n---\n\n# Ziel\n",
    )

    daten = client.get("/api/file?path=aufgaben/a34.001-y.md").get_json()

    assert daten["kennung"] == "A34.001"
    assert daten["naechste_kennung"] == "A35"
    assert "naechste_unterkennung" not in daten
    assert {"frontmatter", "markdown", "nachtraege"} <= set(daten)

    welle = client.get(f"/api/file?path={WELLE}").get_json()
    assert "kennung" not in welle
    assert "naechste_kennung" not in welle


def test_t12_top_level_matrix_unveraendert(client, bundle):
    _schreibe(
        bundle,
        "aufgaben/x.md",
        "---\ntype: Task\ntitle: \"A12: X\"\ntask_status: offen\n---\n\n# Ziel\n",
    )
    _schreibe(
        bundle,
        "aufgaben/a12-x.md",
        "---\ntype: Task\ntitle: \"A12: X\"\ntask_status: offen\n---\n\n# Ziel\n",
    )
    _schreibe(
        bundle,
        "aufgaben/a13-x.md",
        "---\ntype: Task\ntitle: \"A13: \"\ntask_status: offen\n---\n\n# Ziel\n",
    )

    eintraege = _eintraege(client)
    assert eintraege["aufgaben/x.md"]["neu"] is True
    assert eintraege["aufgaben/a12-x.md"]["neu"] is False
    assert eintraege["aufgaben/a13-x.md"]["neu"] is False
