"""TDD-Tests für das Server-Gerüst ``server.py`` (Aufgabe A7)."""

import socket
import sys
from pathlib import Path

import pytest
from flask import abort

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
import meta
import okf_bundle


@pytest.fixture()
def app(bundle):
    return server.create_app(bundle)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def unterdruecke_start(monkeypatch):
    """Fängt ``app.run`` ab und übergeht die Portprüfung (T5 deckt sie separat ab)."""
    aufruf = {}
    monkeypatch.setattr("flask.Flask.run", lambda self, **optionen: aufruf.update(optionen))
    monkeypatch.setattr(server, "_port_belegt", lambda host, port: False)
    return aufruf


# --- Statische Auslieferung ----------------------------------------------


def test_t1_index_erreichbar(client):
    antwort = client.get("/")

    assert antwort.status_code == 200
    assert "<html" in antwort.get_data(as_text=True)


def test_t2_statik_wird_ausgeliefert(client):
    antwort = client.get("/static/style.css")

    assert antwort.status_code == 200
    assert antwort.mimetype == "text/css"


# --- Fehlerformat ---------------------------------------------------------


def test_t3_unbekannte_route_ist_json_404(client):
    antwort = client.get("/diese-route-gibt-es-nicht")

    assert antwort.status_code == 404
    assert antwort.mimetype == "application/json"
    assert "Nicht gefunden" in antwort.get_json()["error"]


def test_t3_eigene_meldung_hat_vorrang(app):
    @app.route("/eigener-fehler")
    def eigener_fehler():
        abort(400, description="Pfad fehlt")

    antwort = app.test_client().get("/eigener-fehler")

    assert antwort.status_code == 400
    assert antwort.get_json()["error"] == "Pfad fehlt"


def test_t4_interner_fehler_ist_json_500(app):
    @app.route("/fehler-probe")
    def fehler_probe():
        raise RuntimeError("absichtlich provoziert")

    antwort = app.test_client().get("/fehler-probe")
    body = antwort.get_data(as_text=True)

    assert antwort.status_code == 500
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"]
    assert "Traceback" not in body
    assert "absichtlich provoziert" not in body


# --- Start über main() ----------------------------------------------------


def test_t5_belegter_port_bricht_ab(bundle, monkeypatch, capsys):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as belegung:
        belegung.bind(("127.0.0.1", 0))
        belegung.listen(1)
        port = belegung.getsockname()[1]

        monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
        monkeypatch.setenv("PORT", str(port))

        assert server.main() != 0

    assert "belegt" in capsys.readouterr().err


def test_t6_fehlendes_bundle_root_bricht_ab(monkeypatch, capsys):
    monkeypatch.delenv("BUNDLE_ROOT", raising=False)

    assert server.main() != 0
    assert "BUNDLE_ROOT" in capsys.readouterr().err


def test_a33_t12_startfehler_ohne_pfad_leak(tmp_path, monkeypatch, capsys):
    """A33-T12 (A7-2): Die Startmeldung nennt den Grund, aber keinen absoluten Pfad."""
    fehlend = tmp_path / "gibt-es-nicht"
    monkeypatch.setenv("BUNDLE_ROOT", str(fehlend))

    assert server.main() != 0

    fehler = capsys.readouterr().err
    assert "Start abgebrochen" in fehler
    assert "BUNDLE_ROOT" in fehler
    assert "kein Verzeichnis" in fehler
    assert str(tmp_path) not in fehler
    assert str(fehlend) not in fehler


def test_a33_t12_datei_statt_verzeichnis_ohne_pfad_leak(tmp_path, monkeypatch, capsys):
    """A33-T12: Auch eine Datei als Wurzel wird ohne Pfadangabe abgelehnt."""
    datei = tmp_path / "wissen.md"
    datei.write_text("# Datei statt Ordner\n", encoding="utf-8")
    monkeypatch.setenv("BUNDLE_ROOT", str(datei))

    assert server.main() != 0

    fehler = capsys.readouterr().err
    assert "kein Verzeichnis" in fehler
    assert str(tmp_path) not in fehler


@pytest.mark.parametrize("wert", [None, "", "   "])
def test_a33_t13_fehlendes_bundle_root_meldung_unveraendert(wert, monkeypatch, capsys):
    """A33-T13 (A7-2): Fehlendes/leeres ``BUNDLE_ROOT`` meldet unverändert „nicht gesetzt"."""
    if wert is None:
        monkeypatch.delenv("BUNDLE_ROOT", raising=False)
    else:
        monkeypatch.setenv("BUNDLE_ROOT", wert)

    assert server.main() != 0
    assert "BUNDLE_ROOT ist nicht gesetzt" in capsys.readouterr().err


def test_a33_t13_gueltige_wurzel_startet_weiterhin(bundle, monkeypatch, unterdruecke_start, capsys):
    """A33-T13: Eine gültige Wurzel startet unverändert (keine Abbruchmeldung)."""
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.delenv("PORT", raising=False)

    assert server.main() == 0
    assert unterdruecke_start["host"] == "0.0.0.0"
    assert "Start abgebrochen" not in capsys.readouterr().err


def test_t6_ungueltiger_port_bricht_ab(bundle, monkeypatch, capsys):
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.setenv("PORT", "keine-zahl")

    assert server.main() != 0
    assert "PORT" in capsys.readouterr().err


def test_t7_bindet_an_alle_schnittstellen(bundle, monkeypatch, unterdruecke_start):
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.delenv("PORT", raising=False)

    assert server.main() == 0
    assert unterdruecke_start["host"] == "0.0.0.0"


def test_t8_port_kommt_aus_der_umgebung(bundle, monkeypatch, unterdruecke_start):
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.setenv("PORT", "8123")

    assert server.main() == 0
    assert unterdruecke_start["port"] == 8123


def test_t8_standard_port_ist_5000(bundle, monkeypatch, unterdruecke_start):
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.delenv("PORT", raising=False)

    assert server.main() == 0
    assert unterdruecke_start["port"] == 5000


# --- Fehler-Mapping der Domänen-Exceptions (A8, aus dem A7-Review) --------


@pytest.mark.parametrize(
    ("fehler_typ", "code"),
    [
        (okf_bundle.BundlePfadFehler, 400),
        (okf_bundle.FrontmatterFehler, 400),
        (okf_bundle.EingabeFehler, 400),
        (okf_bundle.ReservierteDateiFehler, 403),
        (meta.RechteFehler, 403),
        (FileNotFoundError, 404),
    ],
)
def test_domaenen_fehler_werden_json(app, fehler_typ, code):
    def probe():
        raise fehler_typ("Domänenmeldung")

    name = fehler_typ.__name__
    app.add_url_rule(f"/domaene/{name}", endpoint=name, view_func=probe)

    antwort = app.test_client().get(f"/domaene/{name}")

    assert antwort.status_code == code
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"] == "Domänenmeldung"


def test_domaenen_fehler_ohne_meldung_nutzt_standardtext(app):
    def probe():
        raise FileNotFoundError

    app.add_url_rule("/ohne-meldung", endpoint="ohne_meldung", view_func=probe)

    antwort = app.test_client().get("/ohne-meldung")

    assert antwort.status_code == 404
    assert antwort.get_json()["error"] == server.DEUTSCHE_MELDUNGEN[404]


def test_static_pfadausbruch_ist_json_404(client):
    antwort = client.get("/static/../server.py")

    assert antwort.status_code == 404
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"]


def test_abort_403_ist_json(app):
    @app.route("/verboten")
    def verboten():
        abort(403, description="Nicht erlaubt")

    antwort = app.test_client().get("/verboten")

    assert antwort.status_code == 403
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"] == "Nicht erlaubt"


def test_unbekannter_code_hat_deutsche_meldung(app):
    @app.route("/teekanne")
    def teekanne():
        abort(418)

    antwort = app.test_client().get("/teekanne")
    meldung = antwort.get_json()["error"]

    assert antwort.status_code == 418
    assert "Anfrage fehlgeschlagen" in meldung
    assert "418" in meldung
    assert "teapot" not in meldung.lower()


def test_abbruch_per_tastatur_beendet_sauber(bundle, monkeypatch):
    def abbruch(self, **optionen):
        raise KeyboardInterrupt

    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.setattr("flask.Flask.run", abbruch)
    monkeypatch.setattr(server, "_port_belegt", lambda host, port: False)

    assert server.main() == 0
