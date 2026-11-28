"""A36: ``schreibgeschuetzt``-Signal der Lese-API (Schreib-UI-Grenze).

Die API markiert reservierte KI-Dateien (``index.md``, ``log.md``,
``features.md``) als ``schreibgeschuetzt: true``. Die UI blendet darauf ihre
Schreibaktionen aus; der Server-403 bleibt als zweite Barriere unverändert.
Die reservierte Namensliste lebt ausschließlich in :mod:`okf_bundle`.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import okf_bundle
import server

RESERVIERTE = ("index.md", "log.md", "features.md", "aufgaben/index.md")
NORMALE = ("aufgaben/a1.md", "wellen/w1.md")


@pytest.fixture()
def client(bundle):
    return server.create_app(bundle).test_client()


def _schreibe(bundle, pfad: str, text: str) -> Path:
    ziel = bundle / pfad
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    return ziel


def _detail(client, pfad: str) -> dict:
    antwort = client.get("/api/file", query_string={"path": pfad})
    assert antwort.status_code == 200, antwort.get_data(as_text=True)
    return antwort.get_json()


# --- T1/T2: Details markieren reservierte Dateien -------------------------


@pytest.mark.parametrize("pfad", RESERVIERTE)
def test_t1_reservierte_details_sind_schreibgeschuetzt(client, pfad):
    daten = _detail(client, pfad)

    assert daten["schreibgeschuetzt"] is True
    # Das Signal ergänzt die bestehende Antwort, es ersetzt nichts.
    assert set(daten) >= {"frontmatter", "markdown", "nachtraege", "ui_status", "hinweis", "owner_default"}


@pytest.mark.parametrize("pfad", NORMALE)
def test_t2_normale_details_sind_nicht_schreibgeschuetzt(client, pfad):
    daten = _detail(client, pfad)

    # Immer vorhanden (fail-loud für die UI), aber ausdrücklich ``False``.
    assert daten["schreibgeschuetzt"] is False


def test_t3_signal_bleibt_bei_reservierter_datei_lesbar(client):
    daten = _detail(client, "log.md")

    assert daten["frontmatter"]["type"] == "Log"
    assert daten["markdown"].lstrip().startswith("# Projekt-Log")


# --- T4: Auch ein Symlink auf eine reservierte Datei ist geschützt --------


def test_t4_symlink_auf_reservierte_datei_ist_schreibgeschuetzt(client, bundle):
    os.symlink(bundle / "log.md", bundle / "aufgaben/getarnt.md")

    daten = _detail(client, "aufgaben/getarnt.md")

    assert daten["schreibgeschuetzt"] is True


# --- T5: Listen führen keine reservierten Dateien -------------------------

# Begründung: ``okf_bundle.scan`` filtert reservierte Dateien namensbasiert aus;
# deshalb trägt kein Listeneintrag ``schreibgeschuetzt: true``. Das ist keine
# Aussage über die Existenz: Ein Symlink wie ``aufgaben/getarnt.md`` → ``log.md``
# kann sehr wohl als Kante in einer Liste erscheinen. Listen haben aber keine
# Schreibaktionen; dort entfällt die Schreib-UI ohnehin. Der Test hält diese
# Entscheidung fest (kein Listenfeld).
@pytest.mark.parametrize("endpunkt", ["/api/overview", "/api/aufgaben", "/api/wellen"])
def test_t5_listen_ohne_reservierte_und_ohne_schreibschutz_markierung(client, endpunkt):
    daten = client.get(endpunkt).get_json()

    pfade = {eintrag["path"] for eintrag in daten}
    assert pfade.isdisjoint(RESERVIERTE)
    for eintrag in daten:
        assert eintrag.get("schreibgeschuetzt", False) is False


# --- T6: Server-403 bleibt die zweite Barriere ----------------------------


@pytest.mark.parametrize("pfad", RESERVIERTE)
def test_t6_schreibzugriffe_bleiben_403(client, pfad):
    nachtrag = client.post("/api/nachtrag", json={"path": pfad, "text": "Test."})
    meta = client.post("/api/meta", json={"path": pfad, "owner": "mensch"})
    freigabe = client.post("/api/freigabe", json={"path": pfad, "wert": True})

    assert nachtrag.status_code == 403
    assert meta.status_code == 403
    assert freigabe.status_code == 403


def test_t7_signal_kommt_aus_okf_bundle_nicht_aus_overview(client, monkeypatch):
    # Keine zweite Namensliste: das Signal folgt der zentralen Prüffunktion.
    aufrufe = []
    echt = okf_bundle.ist_reserviert

    def zaehlend(pfad):
        aufrufe.append(str(pfad))
        return echt(pfad)

    monkeypatch.setattr(okf_bundle, "ist_reserviert", zaehlend)

    assert _detail(client, "log.md")["schreibgeschuetzt"] is True
    assert aufrufe, "overview.details fragt okf_bundle.ist_reserviert nicht"
