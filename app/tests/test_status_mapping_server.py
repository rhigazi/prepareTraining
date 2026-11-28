"""A35: Status-Mapping kommt server-seitig aus ``status.py`` (A12-1).

``GET /api/file`` liefert die abgeleiteten Felder ``ui_status``, ``hinweis``
und ``owner_default`` top-level — für Aufgaben und Punkte ohne ``task_status``.
Diese Matrix ist die verbindliche Sicht auf ``status.TASK_STATUS_MAPPING``;
der JS-Spiegel in ``detail.js`` entfällt (siehe ``test_status_mapping_ui.py``).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import overview
import server

# Mapping-Tabelle der Technischen Spec: task_status -> (UI-Status, Hinweis, owner-Default)
MAPPING = [
    ("offen", "Offen", None, "ai"),
    ("in Klärung", "Klarung", None, "mensch"),
    ("in Planung", "Offen", None, "ai"),
    ("geplant", "Offen", None, "ai"),
    ("in Umsetzung", "In Arbeit", None, "ai"),
    ("im Review", "Testing", None, "ai"),
    ("im Test", "Testing", None, "ai"),
    ("in Doku", "Dokumentation", None, "ai"),
    ("zur Abnahme", "Klarung", None, "mensch"),
    ("abgeschlossen", "Geschlossen", None, None),
    ("pausiert", "Offen", "pausiert", None),
]


@pytest.fixture()
def client(bundle):
    return server.create_app(bundle).test_client()


def _schreibe(bundle, pfad: str, text: str) -> Path:
    ziel = bundle / pfad
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    return ziel


def _aufgabe(bundle, task_status: str, **felder) -> Path:
    """Aufgabe ohne ``owner`` (damit der Default sichtbar wird)."""
    zeilen = ["---", "type: Task", 'title: "A1: Fixture"', f"task_status: {task_status}"]
    zeilen.extend(f"{name}: {wert}" for name, wert in felder.items())
    zeilen.extend(["---", "", "# Ziel", "", "Fixture.", ""])
    return _schreibe(bundle, "aufgaben/a1.md", "\n".join(zeilen))


def _detail(client, pfad: str = "aufgaben/a1.md") -> dict:
    antwort = client.get("/api/file", query_string={"path": pfad})
    assert antwort.status_code == 200
    return antwort.get_json()


# --- Mapping-Matrix über die API -----------------------------------------


@pytest.mark.parametrize("task_status, erwarteter_status, erwarteter_hinweis, owner", MAPPING)
def test_t1_matrix_ueber_api(client, bundle, task_status, erwarteter_status, erwarteter_hinweis, owner):
    _aufgabe(bundle, task_status)

    daten = _detail(client)

    assert daten["ui_status"] == erwarteter_status
    assert daten["hinweis"] == erwarteter_hinweis
    assert daten["owner_default"] == owner
    # Roh-Frontmatter bleibt unverändert (kein Schreibpfad, keine Umbenennung).
    assert daten["frontmatter"]["task_status"] == task_status


def test_t2_explizites_owner_hat_vorrang(client, bundle):
    _aufgabe(bundle, "in Klärung", owner="ai")
    assert _detail(client)["owner_default"] == "ai"

    _aufgabe(bundle, "offen", owner="mensch")
    assert _detail(client)["owner_default"] == "mensch"


def test_t3_unbekannter_task_status_bleibt_offen_mit_hinweis(client, bundle):
    _aufgabe(bundle, "irgendwann")

    daten = _detail(client)

    assert daten["ui_status"] == "Offen"
    assert daten["hinweis"] == "irgendwann"
    assert daten["owner_default"] is None


def test_t4_welle_ohne_task_status_nutzt_status_feld(client, bundle):
    _schreibe(
        bundle,
        "wellen/w2.md",
        "---\ntype: Welle\ntitle: W2\nstatus: In Arbeit\n---\n\n# Ziel\n",
    )

    daten = _detail(client, "wellen/w2.md")

    assert daten["ui_status"] == "In Arbeit"
    assert daten["hinweis"] is None
    assert daten["owner_default"] == "ai"


def test_t5_unbekannter_status_bekommt_offen_und_hinweis(client, bundle):
    _schreibe(bundle, "wellen/w2.md", "---\ntype: Welle\ntitle: W2\nstatus: kaputt\n---\n")

    daten = _detail(client, "wellen/w2.md")

    assert daten["ui_status"] == "Offen"
    assert daten["hinweis"] == "kaputt"
    assert daten["owner_default"] is None


def test_t6_ohne_statusfelder_offen_mit_ohne_status_hinweis(client, bundle):
    _schreibe(bundle, "wellen/w2.md", "---\ntype: Welle\ntitle: W2\n---\n")

    daten = _detail(client, "wellen/w2.md")

    assert daten["ui_status"] == "Offen"
    assert daten["hinweis"] == "ohne Status"
    assert daten["owner_default"] is None


def test_t7_hinweis_ist_immer_vorhanden(client, bundle):
    _aufgabe(bundle, "offen")

    daten = _detail(client)

    assert "hinweis" in daten
    assert daten["hinweis"] is None


def test_t8_details_liefert_dieselben_werte_wie_die_api(client, bundle):
    _aufgabe(bundle, "pausiert")

    direkt = overview.details("aufgaben/a1.md")

    assert direkt["ui_status"] == "Offen"
    assert direkt["hinweis"] == "pausiert"
    assert direkt["owner_default"] is None
    assert client.get("/api/file?path=aufgaben/a1.md").get_json()["ui_status"] == "Offen"


def test_t9_uebersicht_bleibt_unveraendert(client, bundle):
    """Die Liste trägt die Felder nicht — A35 erweitert nur das Detail."""
    _aufgabe(bundle, "in Umsetzung")

    eintrag = client.get("/api/overview").get_json()[0]

    assert set(eintrag).isdisjoint({"ui_status", "owner_default"})
    assert eintrag["status"] == "In Arbeit"
    assert eintrag["owner"] == "ai"
