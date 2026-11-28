"""TDD-Tests für den Desktop-Modus ``desktop.py`` (Aufgabe A21).

Kein Test öffnet ein echtes Fenster: ``webview`` ist immer ein Fake, der
Fensterstart ist an der Modulnaht ersetzt. Der einzige echte Server (T8) bindet
Port 0; Port 5000 wird nie belegt. Bundles liegen ausschließlich unter
``tmp_path`` — das echte ``wissen/`` wird nie angefasst.
"""

import hashlib
import importlib
import importlib.util
import json
import socket
import subprocess
import sys
import time
import types
import urllib.request
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import desktop  # noqa: E402
import server  # noqa: E402

TITEL = "OKF Projekt-Manager"


class FakeWebview:
    """Ersatz für ``webview``: zeichnet ``create_window``/``start`` auf."""

    def __init__(self, start_fehler: BaseException | None = None):
        self.fenster: list[dict] = []
        self.starts = 0
        self.start_fehler = start_fehler

    def create_window(self, titel, url, **optionen):
        self.fenster.append({"titel": titel, "url": url, "optionen": optionen})
        return types.SimpleNamespace(titel=titel, url=url)

    def start(self, *args, **kwargs):
        self.starts += 1
        if self.start_fehler is not None:
            raise self.start_fehler


class FakeServerHandle:
    """Ersatz für den Werkzeug-Server: zählt ``shutdown``/``server_close``."""

    def __init__(self):
        self.shutdowns = 0
        self.schliessungen = 0

    def shutdown(self):
        self.shutdowns += 1

    def server_close(self):
        self.schliessungen += 1


def _freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _baum_hash(wurzel: Path) -> str:
    """Hash über Pfade und Inhalte aller Dateien (ohne ``__pycache__``)."""
    pruefer = hashlib.sha256()
    for pfad in sorted(wurzel.rglob("*")):
        if "__pycache__" in pfad.parts or not pfad.is_file():
            continue
        pruefer.update(str(pfad.relative_to(wurzel)).encode())
        pruefer.update(pfad.read_bytes())
    return pruefer.hexdigest()


def _lade_desktop_kopie(wurzel: Path, layout: str):
    """Kopie von ``desktop.py`` unter ``definitions/app/`` bzw. ``app/`` laden."""
    app_dir = wurzel / ("definitions/app" if layout == "dev" else "app")
    app_dir.mkdir(parents=True)
    ziel = app_dir / "desktop.py"
    ziel.write_text(Path(desktop.__file__).read_text(encoding="utf-8"), encoding="utf-8")

    name = f"desktop_kopie_{layout}_{abs(hash(wurzel))}"
    spez = importlib.util.spec_from_file_location(name, ziel)
    modul = importlib.util.module_from_spec(spez)
    spez.loader.exec_module(modul)
    return modul


@pytest.fixture()
def fake_fenster(monkeypatch):
    """Ersetzt ``_lade_webview`` durch eine aufzeichnende Fake-Webview."""
    fake = FakeWebview()
    monkeypatch.setattr(desktop, "_lade_webview", lambda: fake)
    return fake


@pytest.fixture()
def server_handle(monkeypatch):
    """Ersetzt ``_starte_server``; zeichnet Aufrufe auf und liefert einen Fake-Handle."""
    handle = FakeServerHandle()
    aufrufe: list[dict] = []

    def starte(app, port):
        aufrufe.append({"app": app, "port": port})
        return handle

    monkeypatch.setattr(desktop, "_starte_server", starte)
    return types.SimpleNamespace(handle=handle, aufrufe=aufrufe)


def _startfaehig(monkeypatch, bundle: Path, *, port: int | None = None) -> int:
    """Setzt Bundle, freien Port und einen freien Portprüfer für ``main()``."""
    gewaehlt = port if port is not None else _freier_port()
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.setenv("PORT", str(gewaehlt))
    monkeypatch.setattr(desktop, "_port_belegt", lambda p: False)
    return gewaehlt


# --- A. Import-Guard und Konfiguration (T1–T5) ----------------------------


def test_t1_import_ohne_pywebview(monkeypatch):
    """Ohne ``webview`` bleibt der Import möglich; erst der Start scheitert."""
    monkeypatch.setitem(sys.modules, "webview", None)

    modul = importlib.reload(desktop)

    with pytest.raises(modul.DesktopFehler):
        modul._lade_webview()


def test_t2_meldung_ohne_paket(monkeypatch):
    monkeypatch.setattr(desktop, "_webview_installiert", lambda: False)

    meldung = desktop._meldung_webview()

    assert "pywebview" in meldung
    assert "optional" in meldung
    assert "python3 -m pip install pywebview" in meldung
    assert "Server-/Browser-Betrieb" in meldung
    assert "funktioniert" in meldung


def test_t2_meldung_installiert_aber_nicht_ladbar(monkeypatch):
    monkeypatch.setattr(desktop, "_webview_installiert", lambda: True)

    meldung = desktop._meldung_webview()

    assert "pywebview" in meldung
    assert "installiert" in meldung
    assert "nicht ladbar" in meldung
    assert "Fenster-Backend" in meldung


def test_t3_start_ohne_pywebview(monkeypatch, capsys):
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setattr(desktop, "_webview_installiert", lambda: False)
    server_aufrufe: list = []
    fenster_aufrufe: list = []
    monkeypatch.setattr(desktop, "_starte_server", lambda *a, **k: server_aufrufe.append(a), raising=False)
    monkeypatch.setattr(desktop, "_starte_fenster", lambda *a, **k: fenster_aufrufe.append(a), raising=False)

    assert desktop.main() == 1

    ausgabe = capsys.readouterr()
    assert "Start abgebrochen" in ausgabe.err
    assert "pywebview" in ausgabe.err
    assert "Traceback" not in ausgabe.out + ausgabe.err
    assert server_aufrufe == []
    assert fenster_aufrufe == []


def test_t4_bundle_root_wird_abgeleitet(tmp_path, monkeypatch):
    monkeypatch.delenv("BUNDLE_ROOT", raising=False)
    modul = _lade_desktop_kopie(tmp_path / "pmTool-test", "dev")

    assert modul.REPO_ROOT == tmp_path / "pmTool-test"
    assert modul.BUNDLE_ROOT == tmp_path / "pmTool-test" / "wissen"
    assert modul._bundle_root() == tmp_path / "pmTool-test" / "wissen"


def test_t4_env_bundle_root_hat_vorrang(tmp_path, monkeypatch):
    modul = _lade_desktop_kopie(tmp_path / "pmTool-test", "dev")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BUNDLE_ROOT", "relatives-bundle")

    assert modul._bundle_root() == (tmp_path / "relatives-bundle").resolve()


def test_t4_env_bundle_root_loest_tilde_auf(tmp_path, monkeypatch):
    modul = _lade_desktop_kopie(tmp_path / "pmTool-test", "dev")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("BUNDLE_ROOT", "~/wissen")

    assert modul._bundle_root() == tmp_path / "wissen"


def test_t4_verteiltes_projekt_ist_analog(tmp_path, monkeypatch):
    monkeypatch.delenv("BUNDLE_ROOT", raising=False)
    modul = _lade_desktop_kopie(tmp_path / "zielprojekt", "verteilt")

    assert modul.REPO_ROOT == tmp_path / "zielprojekt"
    assert modul.BUNDLE_ROOT == tmp_path / "zielprojekt" / "wissen"


def test_t5_port_aus_umgebung(monkeypatch):
    monkeypatch.setenv("PORT", "8123")
    assert desktop._port_aus_umgebung() == 8123

    monkeypatch.delenv("PORT")
    assert desktop._port_aus_umgebung() == 5000


@pytest.mark.parametrize("wert", ["abc", "70000"])
def test_t5_ungueltiger_port_bricht_ab(monkeypatch, capsys, fake_fenster, wert):
    monkeypatch.setenv("PORT", wert)
    server_aufrufe: list = []
    fenster_aufrufe: list = []
    monkeypatch.setattr(desktop, "_starte_server", lambda *a, **k: server_aufrufe.append(a), raising=False)
    monkeypatch.setattr(desktop, "_starte_fenster", lambda *a, **k: fenster_aufrufe.append(a), raising=False)

    assert desktop.main() == 1

    ausgabe = capsys.readouterr()
    assert "Start abgebrochen" in ausgabe.err
    assert "PORT" in ausgabe.err
    assert "Traceback" not in ausgabe.out + ausgabe.err
    assert fake_fenster.fenster == []
    assert server_aufrufe == []
    assert fenster_aufrufe == []


# --- B. Server, Fenster und Lebenszyklus (T6–T11) -------------------------


def test_t6_fenster_laedt_loopback_url(bundle, monkeypatch, fake_fenster, server_handle, capsys):
    port = _startfaehig(monkeypatch, bundle)

    assert desktop.main() == 0

    assert len(fake_fenster.fenster) == 1
    assert fake_fenster.fenster[0]["titel"] == TITEL
    assert fake_fenster.fenster[0]["url"] == f"http://127.0.0.1:{port}"
    assert fake_fenster.starts == 1
    assert server_handle.aufrufe[0]["port"] == port
    assert server_handle.handle.shutdowns == 1
    assert capsys.readouterr().err == ""


def test_t7a_fenster_geschlossen_raeumt_auf(bundle, monkeypatch, fake_fenster, server_handle, capsys):
    _startfaehig(monkeypatch, bundle)

    assert desktop.main() == 0

    assert server_handle.handle.shutdowns == 1
    assert "Desktop-Fenster beendet." in capsys.readouterr().out


def test_t7b_keyboardinterrupt_raeumt_auf(bundle, monkeypatch, server_handle, capsys):
    _startfaehig(monkeypatch, bundle)
    fake = FakeWebview(start_fehler=KeyboardInterrupt())
    monkeypatch.setattr(desktop, "_lade_webview", lambda: fake)

    assert desktop.main() == 0

    assert server_handle.handle.shutdowns == 1
    assert "Traceback" not in capsys.readouterr().err


def test_t7c_fensterfehler_exit_eins(bundle, monkeypatch, server_handle, capsys):
    _startfaehig(monkeypatch, bundle)
    fake = FakeWebview(start_fehler=RuntimeError("kein Display"))
    monkeypatch.setattr(desktop, "_lade_webview", lambda: fake)

    assert desktop.main() == 1

    ausgabe = capsys.readouterr()
    assert server_handle.handle.shutdowns == 1
    assert "Fenster" in ausgabe.err
    assert "Traceback" not in ausgabe.err


def test_t7d_server_thread_laeuft_als_daemon(monkeypatch):
    """K2: Der Server-Thread ist ein Daemon — sonst blockiert er den Prozess-Exit."""
    from werkzeug import serving

    erzeugte_threads: list = []

    class ErfassenderThread:
        """Stub statt echtem Thread: zeichnet ``daemon``/``name`` auf."""

        def __init__(self, *args, **kwargs):
            self.daemon = kwargs.get("daemon")
            self.name = kwargs.get("name")
            self.gestartet = False
            erzeugte_threads.append(self)

        def start(self):
            self.gestartet = True

    handle = FakeServerHandle()
    monkeypatch.setattr(serving, "make_server", lambda *a, **k: handle)
    monkeypatch.setattr(desktop.threading, "Thread", ErfassenderThread)

    assert desktop._starte_server(object(), 0) is handle

    assert len(erzeugte_threads) == 1
    assert erzeugte_threads[0].gestartet is True
    assert erzeugte_threads[0].name == "okf-desktop-server"
    assert erzeugte_threads[0].daemon is True


def test_t8_echter_inprozess_server(bundle, monkeypatch):
    app = server.create_app(bundle)
    prozess_aufrufe: list = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: prozess_aufrufe.append(a))

    handle = desktop._starte_server(app, 0)
    port = handle.server_port
    try:
        # K1: Der Server bindet nur Loopback — 0.0.0.0 wäre eine LAN-Freigabe.
        assert desktop.HOST == "127.0.0.1"
        assert handle.server_address[0] == "127.0.0.1"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as antwort:
            assert antwort.status == 200
            assert "<html" in antwort.read().decode("utf-8").lower()
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/overview", timeout=10
        ) as antwort:
            assert antwort.status == 200
            assert isinstance(json.load(antwort), list)
    finally:
        handle.shutdown()

    _warte_bis_port_frei(port)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    assert prozess_aufrufe == []


def _warte_bis_port_frei(port: int, frist_sekunden: float = 5.0) -> None:
    """Kurze Warteschleife statt fester Pause: Port muss wieder bindbar sein."""
    ende = time.monotonic() + frist_sekunden
    while time.monotonic() < ende:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                time.sleep(0.02)
            else:
                return
    raise AssertionError("Port wurde nach shutdown() nicht wieder frei")


def test_t9_belegter_port_bricht_ab(bundle, monkeypatch, fake_fenster, capsys):
    with socket.socket() as belegung:
        belegung.bind(("127.0.0.1", 0))
        belegung.listen(1)
        port = belegung.getsockname()[1]
        monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
        monkeypatch.setenv("PORT", str(port))
        server_aufrufe: list = []
        monkeypatch.setattr(
            desktop, "_starte_server", lambda *a, **k: server_aufrufe.append(a)
        )

        assert desktop.main() == 1

    ausgabe = capsys.readouterr()
    assert "belegt" in ausgabe.err
    assert "PORT=" in ausgabe.err
    assert fake_fenster.fenster == []
    assert server_aufrufe == []


def test_t10_ungueltiges_bundle_bricht_ab(tmp_path, monkeypatch, fake_fenster, capsys):
    fehlend = tmp_path / "gibt-es-nicht"
    _startfaehig(monkeypatch, fehlend)
    server_aufrufe: list = []
    monkeypatch.setattr(desktop, "_starte_server", lambda *a, **k: server_aufrufe.append(a))

    assert desktop.main() == 1

    ausgabe = capsys.readouterr()
    assert "Start abgebrochen" in ausgabe.err
    assert "kein Verzeichnis" in ausgabe.err
    assert str(fehlend) not in ausgabe.err
    assert fake_fenster.fenster == []
    assert server_aufrufe == []


def test_t11_bundle_bleibt_unveraendert(bundle, monkeypatch, fake_fenster, server_handle):
    _startfaehig(monkeypatch, bundle)
    vorher = _baum_hash(bundle)
    dateien_vorher = sorted(p.relative_to(bundle) for p in bundle.rglob("*"))

    assert desktop.main() == 0

    assert _baum_hash(bundle) == vorher
    assert sorted(p.relative_to(bundle) for p in bundle.rglob("*")) == dateien_vorher
