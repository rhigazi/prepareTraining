"""Tests für das Status-/owner-Mapping in status.py (reine Logik, keine Dateizugriffe)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import status  # noqa: E402

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

UI_STATUS_WERTE = [
    "Klarung",
    "Offen",
    "In Arbeit",
    "Testing",
    "Dokumentation",
    "Geschlossen",
]

# Wellen/Punkte ohne task_status: status -> owner-Default
OWNER_JE_STATUS = [
    ("Klarung", "mensch"),
    ("Offen", "ai"),
    ("In Arbeit", "ai"),
    ("Testing", "ai"),
    ("Dokumentation", "ai"),
    ("Geschlossen", None),
]


@pytest.mark.parametrize("task_status, erwarteter_status, erwarteter_hinweis, _owner", MAPPING)
def test_t1_mapping_vollstaendig(task_status, erwarteter_status, erwarteter_hinweis, _owner):
    assert status.ui_status({"task_status": task_status}) == (
        erwarteter_status,
        erwarteter_hinweis,
    )


def test_t2_abgeschlossen_ist_geschlossen_ohne_owner():
    frontmatter = {"type": "Task", "task_status": "abgeschlossen", "phase": "8 Abgeschlossen"}

    assert status.ui_status(frontmatter) == ("Geschlossen", None)
    assert status.owner_default(frontmatter) is None


def test_t3_pausiert_zeigt_hinweis():
    assert status.ui_status({"task_status": "pausiert"}) == ("Offen", "pausiert")


def test_t4_welle_ohne_task_status_nutzt_status():
    assert status.ui_status({"type": "Welle", "status": "In Arbeit"}) == ("In Arbeit", None)


def test_t5_ohne_statusfeld():
    assert status.ui_status({"type": "Welle", "title": "Ohne Status"}) == ("Offen", "ohne Status")


def test_t6_unbekannter_task_status_ohne_exception():
    assert status.ui_status({"task_status": "irgendwann"}) == ("Offen", "irgendwann")


def test_t7_owner_defaults():
    assert status.owner_default({"task_status": "offen"}) == "ai"
    assert status.owner_default({"task_status": "in Klärung"}) == "mensch"
    assert status.owner_default({"status": "Klarung"}) == "mensch"


def test_t8_owner_default_ohne_angaben():
    assert status.owner_default({"type": "Welle", "title": "Ohne Angaben"}) is None


@pytest.mark.parametrize("task_status, _status, _hinweis, erwarteter_owner", MAPPING)
def test_owner_default_aus_mapping(task_status, _status, _hinweis, erwarteter_owner):
    assert status.owner_default({"task_status": task_status}) == erwarteter_owner


@pytest.mark.parametrize("status_wert, erwarteter_owner", OWNER_JE_STATUS)
def test_owner_default_aus_status(status_wert, erwarteter_owner):
    assert status.owner_default({"status": status_wert}) == erwarteter_owner


@pytest.mark.parametrize("status_wert", UI_STATUS_WERTE)
def test_status_wird_direkt_uebernommen(status_wert):
    assert status.ui_status({"status": status_wert}) == (status_wert, None)


def test_task_status_none_faellt_auf_status_zurueck():
    assert status.ui_status({"task_status": None, "status": "Testing"}) == ("Testing", None)


def test_unbekannter_status_ohne_exception():
    assert status.ui_status({"status": "unbekannt"}) == ("Offen", "unbekannt")


def test_gesetztes_owner_feld_hat_vorrang():
    assert status.owner_default({"task_status": "in Umsetzung", "owner": "mensch"}) == "mensch"
