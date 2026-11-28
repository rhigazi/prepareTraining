"""TDD-Tests für die Colab-Startzelle ``start_colab.py`` (Aufgabe A16).

Alle externen Wirkungen sind gemockt: Colab-Port-Freigabe, ``subprocess`` und
die Portprüfung. Ein echter ``server.py``-Prozess wird nie gestartet.
"""

import builtins
import hashlib
import importlib.util
import socket
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import start_colab  # noqa: E402


class FakePopen:
    """Ersatz für ``subprocess.Popen``: merkt Aufrufe, startet keinen Prozess."""

    def __init__(self):
        self.aufrufe = []

    def __call__(self, befehl, env=None, **optionen):
        self.aufrufe.append({"befehl": befehl, "env": env})
        return types.SimpleNamespace(pid=4242)


@pytest.fixture()
def popen(monkeypatch):
    fake = FakePopen()
    monkeypatch.setattr(subprocess, "Popen", fake)
    return fake


@pytest.fixture()
def port_frei(monkeypatch):
    monkeypatch.setattr(start_colab, "_port_belegt", lambda port: False)


def _fake_colab(monkeypatch, eval_js=None, fenster=None, iframe=None):
    """Registriert ein Fake-``google.colab.output`` mit den gegebenen Port-Funktionen."""
    modul_google = types.ModuleType("google")
    modul_colab = types.ModuleType("google.colab")
    modul_output = types.ModuleType("google.colab.output")
    if eval_js is not None:
        modul_output.eval_js = eval_js
    if fenster is not None:
        modul_output.serve_kernel_port_as_window = fenster
    if iframe is not None:
        modul_output.serve_kernel_port_as_iframe = iframe
    modul_google.colab = modul_colab
    modul_colab.output = modul_output
    monkeypatch.setitem(sys.modules, "google", modul_google)
    monkeypatch.setitem(sys.modules, "google.colab", modul_colab)
    monkeypatch.setitem(sys.modules, "google.colab.output", modul_output)


@pytest.fixture()
def colab(monkeypatch):
    """Fake-Colab mit allen Wegen: sammelt JS-, Fenster- und iframe-Aufrufe."""
    aufrufe = types.SimpleNamespace(js=[], fenster=[], iframe=[])

    def js(ausdruck):
        aufrufe.js.append(ausdruck)
        return "https://5000-colab.googleusercontent.com/"

    _fake_colab(
        monkeypatch,
        eval_js=js,
        fenster=aufrufe.fenster.append,
        iframe=aufrufe.iframe.append,
    )
    return aufrufe


@pytest.fixture()
def colab_nur_fenster(monkeypatch):
    """Colab-Laufzeit ohne ``eval_js``: Nutzer-Snippet bleibt der Weg."""
    aufrufe = []
    _fake_colab(monkeypatch, fenster=aufrufe.append)
    return aufrufe


@pytest.fixture()
def colab_nur_iframe(monkeypatch):
    """Colab-Laufzeit ohne ``eval_js`` und ohne Fenster-Funktion."""
    aufrufe = []
    _fake_colab(monkeypatch, iframe=aufrufe.append)
    return aufrufe


@pytest.fixture()
def ohne_colab(monkeypatch):
    """Erzwingt einen fehlgeschlagenen ``google.colab``-Import."""
    for name in ("google", "google.colab", "google.colab.output"):
        monkeypatch.setitem(sys.modules, name, None)


@pytest.fixture()
def colab_ohne_kernel(monkeypatch):
    """Colab-Laufzeit vorhanden, aber ohne Kernel-Kanal (Aufruf im Unterprozess)."""

    def ohne_kanal(*args):
        raise RuntimeError("no kernel channel")

    _fake_colab(monkeypatch, eval_js=ohne_kanal, fenster=ohne_kanal, iframe=ohne_kanal)


@pytest.fixture()
def colab_ohne_funktion(monkeypatch):
    """``google.colab.output`` ohne jede Port-Freigabe-Funktion."""
    _fake_colab(monkeypatch)


def _baum_hash(wurzel: Path) -> str:
    """Hash über Pfade und Inhalte aller Dateien (ohne ``__pycache__``)."""
    pruefer = hashlib.sha256()
    for pfad in sorted(wurzel.rglob("*")):
        if "__pycache__" in pfad.parts or not pfad.is_file():
            continue
        pruefer.update(str(pfad.relative_to(wurzel)).encode())
        pruefer.update(pfad.read_bytes())
    return pruefer.hexdigest()


def _lade_skript_kopie(repo_wurzel: Path):
    """Lädt ``start_colab.py`` aus einem simulierten Klon ``<repo>/definitions/app/``."""
    app_dir = repo_wurzel / "definitions" / "app"
    app_dir.mkdir(parents=True)
    skript = app_dir / "start_colab.py"
    skript.write_text(Path(start_colab.__file__).read_text(encoding="utf-8"), encoding="utf-8")

    spez = importlib.util.spec_from_file_location("start_colab_kopie", skript)
    modul = importlib.util.module_from_spec(spez)
    spez.loader.exec_module(modul)
    return modul


# --- T1 Port-Freigabe -----------------------------------------------------


def test_t1_port_freigabe_genau_einmal(popen, port_frei, colab, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)

    assert start_colab.main() == 0
    assert len(colab.js) == 1
    assert "google.colab.kernel.proxyPort(5000)" in colab.js[0]
    assert colab.fenster == []
    assert colab.iframe == []
    assert len(popen.aufrufe) == 1


# --- T2 Subprozess-Env ----------------------------------------------------


def test_t2_subprozess_erhaelt_bundle_root_und_port(popen, port_frei, ohne_colab, monkeypatch):
    monkeypatch.delenv("BUNDLE_ROOT", raising=False)
    monkeypatch.setenv("PORT", "8123")

    assert start_colab.main() == 0
    aufruf = popen.aufrufe[0]
    # Ableitung aus dem Skriptpfad — kein hart kodierter Klon-Pfad.
    assert aufruf["env"]["BUNDLE_ROOT"] == str(Path(start_colab.BUNDLE_ROOT).resolve())
    assert aufruf["env"]["PORT"] == "8123"
    assert aufruf["befehl"][0] == sys.executable
    assert Path(aufruf["befehl"][1]).name == "server.py"


# --- T12 Bundle-Wurzel aus dem Skriptpfad ableiten (A16) ------------------


def test_t12_bundle_root_wird_abgeleitet(tmp_path, monkeypatch):
    """Anderer Klon-Pfad (z. B. /content/pmTool-test) liefert dessen ``wissen/``."""
    monkeypatch.delenv("BUNDLE_ROOT", raising=False)
    modul = _lade_skript_kopie(tmp_path / "pmTool-test")

    assert modul.REPO_ROOT == tmp_path / "pmTool-test"
    assert modul.BUNDLE_ROOT == tmp_path / "pmTool-test" / "wissen"
    assert modul._bundle_root() == tmp_path / "pmTool-test" / "wissen"


def test_t12_env_bundle_root_hat_vorrang(tmp_path, monkeypatch):
    """Ein gesetztes ``BUNDLE_ROOT`` (wie ``server.py``) schlägt die Ableitung."""
    monkeypatch.setenv("BUNDLE_ROOT", str(tmp_path / "anderes-bundle"))

    assert start_colab._bundle_root() == (tmp_path / "anderes-bundle").resolve()


def test_t12_env_bundle_root_geht_an_den_subprozess(popen, port_frei, ohne_colab, tmp_path, monkeypatch):
    monkeypatch.setenv("BUNDLE_ROOT", str(tmp_path / "anderes-bundle"))

    assert start_colab.main() == 0
    assert popen.aufrufe[0]["env"]["BUNDLE_ROOT"] == str((tmp_path / "anderes-bundle").resolve())


def test_t2_standard_port_ist_5000(popen, port_frei, ohne_colab, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)

    assert start_colab.main() == 0
    assert popen.aufrufe[0]["env"]["PORT"] == "5000"


# --- T3 Ohne Colab --------------------------------------------------------


def test_t3_ohne_colab_exit_null_und_url(popen, port_frei, ohne_colab, monkeypatch, capsys):
    monkeypatch.delenv("PORT", raising=False)

    assert start_colab.main() == 0
    ausgabe = capsys.readouterr().out
    assert "http://localhost:5000" in ausgabe
    assert "%run" not in ausgabe
    assert len(popen.aufrufe) == 1


# --- T9 Port-Freigabe scheitert ohne Kernel-Kanal (A16) -------------------


def _pruefe_handlungsanweisung(ausgabe: str) -> None:
    """Der Hinweis nennt den absoluten Skriptpfad und beide Nachhol-Varianten."""
    pfad = Path(start_colab.__file__).resolve()
    assert pfad.is_absolute()
    assert f"%run {pfad}" in ausgabe
    assert "%run definitions/" not in ausgabe
    assert "serve_kernel_port_as_window(5000)" in ausgabe
    assert "proxyPort(5000)" in ausgabe


def test_t9_unterprozess_meldet_handlungsanweisung(popen, port_frei, colab_ohne_kernel, monkeypatch, capsys):
    """Ohne Kernel-Kanal (z. B. Unterprozess) nennt die Ausgabe den Ausweg."""
    monkeypatch.delenv("PORT", raising=False)

    assert start_colab.main() == 0

    ausgabe = capsys.readouterr().out
    _pruefe_handlungsanweisung(ausgabe)
    assert "localhost" not in ausgabe
    assert len(popen.aufrufe) == 1


def test_t9_colab_ohne_funktion_meldet_handlungsanweisung(popen, port_frei, colab_ohne_funktion, monkeypatch, capsys):
    monkeypatch.delenv("PORT", raising=False)

    assert start_colab.main() == 0

    ausgabe = capsys.readouterr().out
    _pruefe_handlungsanweisung(ausgabe)
    assert len(popen.aufrufe) == 1


# --- T10 Kernel-Erkennung (A16) ------------------------------------------


def test_t10_kernel_erkennung_ohne_kernel(monkeypatch):
    monkeypatch.delattr(builtins, "get_ipython", raising=False)

    assert start_colab._laeuft_im_kernel() is False


def test_t10_kernel_erkennung_im_kernel(monkeypatch):
    monkeypatch.setattr(builtins, "get_ipython", lambda: object(), raising=False)

    assert start_colab._laeuft_im_kernel() is True


# --- T11 Neuer Tab primär, Fenster-Fallback, iframe nur Notbehelf (A16) ---


def test_t11_proxylink_oeffnet_neuen_tab_ohne_localhost(popen, port_frei, colab, monkeypatch, capsys):
    """Primär: proxyPort-Link per eval_js in einem neuen Tab; keine iframe-Anzeige."""
    monkeypatch.delenv("PORT", raising=False)

    assert start_colab.main() == 0

    ausgabe = capsys.readouterr().out
    assert len(colab.js) == 1
    skript = colab.js[0]
    assert "google.colab.kernel.proxyPort(5000)" in skript
    assert "window.open(" in skript
    assert "_blank" in skript
    assert colab.fenster == []
    assert colab.iframe == []
    assert "neuen Browser-Tab" in ausgabe
    assert "Port 5000" in ausgabe
    assert "localhost" not in ausgabe


def test_t11_fallback_auf_fenster_ohne_eval_js(popen, port_frei, colab_nur_fenster, monkeypatch, capsys):
    """Ohne ``eval_js`` greift das Nutzer-Snippet ``serve_kernel_port_as_window``."""
    monkeypatch.delenv("PORT", raising=False)

    assert start_colab.main() == 0

    ausgabe = capsys.readouterr().out
    assert colab_nur_fenster == [5000]
    assert "Browser-Tab" in ausgabe
    assert "localhost" not in ausgabe


def test_t11_iframe_nur_wenn_alles_andere_fehlt(popen, port_frei, colab_nur_iframe, monkeypatch, capsys):
    """iframe ist nur Notbehelf — die Meldung sagt das ehrlich."""
    monkeypatch.delenv("PORT", raising=False)

    assert start_colab.main() == 0

    ausgabe = capsys.readouterr().out
    assert colab_nur_iframe == [5000]
    assert "Fallback: Anzeige in der Zelle" in ausgabe
    assert "localhost" not in ausgabe


def test_t11_eval_js_fehler_faellt_auf_fenster_zurueck(popen, port_frei, monkeypatch, capsys):
    """Scheitert ``eval_js``, bleibt der Fenster-Aufruf als Fallback."""
    fenster_aufrufe = []

    def js_fehler(ausdruck):
        raise RuntimeError("kein Kernel-Kanal")

    _fake_colab(monkeypatch, eval_js=js_fehler, fenster=fenster_aufrufe.append)
    monkeypatch.delenv("PORT", raising=False)

    assert start_colab.main() == 0

    ausgabe = capsys.readouterr().out
    assert fenster_aufrufe == [5000]
    assert "Browser-Tab" in ausgabe
    assert "localhost" not in ausgabe


# --- T4 Port belegt -------------------------------------------------------


def test_t4_belegter_port_meldet_laeuft_bereits(popen, ohne_colab, monkeypatch, capsys):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as belegung:
        belegung.bind(("127.0.0.1", 0))
        belegung.listen(1)
        monkeypatch.setenv("PORT", str(belegung.getsockname()[1]))

        assert start_colab.main() == 0

    assert "läuft bereits" in capsys.readouterr().out
    assert popen.aufrufe == []


# --- T5 Fehlende Pakete ---------------------------------------------------


def test_t5_fehlende_pakete_loesen_pip_install_aus(popen, port_frei, ohne_colab, monkeypatch):
    fehlend = {"flask", "yaml"}
    monkeypatch.setattr(
        start_colab.importlib.util,
        "find_spec",
        lambda name: None if name in fehlend else object(),
    )
    installiert = []

    def pip_install(befehl, **optionen):
        installiert.append(befehl)
        fehlend.clear()
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", pip_install)

    assert start_colab.main() == 0

    assert len(installiert) == 1
    befehl = installiert[0]
    assert befehl[:2] == [sys.executable, "-m"]
    assert "pip" in befehl
    assert "install" in befehl
    assert "flask" in befehl
    assert "pyyaml" in befehl


def test_t5_vorhandene_pakete_loesen_kein_pip_aus(popen, port_frei, ohne_colab, monkeypatch):
    monkeypatch.setattr(start_colab.importlib.util, "find_spec", lambda name: object())
    installiert = []
    monkeypatch.setattr(subprocess, "run", lambda befehl, **optionen: installiert.append(befehl))

    assert start_colab.main() == 0
    assert installiert == []


# --- T7 Installation schlägt fehl (A16-2) ---------------------------------


def test_t7_pip_fehler_beendet_ohne_serverstart(popen, port_frei, ohne_colab, monkeypatch, capsys):
    monkeypatch.setattr(start_colab.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda befehl, **optionen: types.SimpleNamespace(returncode=1),
    )

    assert start_colab.main() != 0
    assert popen.aufrufe == []
    ausgabe = capsys.readouterr()
    assert "fehlgeschlagen" in ausgabe.err
    assert "Server gestartet" not in ausgabe.out


def test_t7_fehlendes_paket_nach_install_beendet_ohne_serverstart(popen, port_frei, ohne_colab, monkeypatch, capsys):
    monkeypatch.setattr(start_colab.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda befehl, **optionen: types.SimpleNamespace(returncode=0),
    )

    assert start_colab.main() != 0
    assert popen.aufrufe == []
    ausgabe = capsys.readouterr()
    assert "flask" in ausgabe.err
    assert "Server gestartet" not in ausgabe.out


# --- T8 Portprüfung nutzt alle Schnittstellen (A16-3) ---------------------


def test_t8_portpruefung_bindet_an_alle_schnittstellen(monkeypatch):
    gebunden = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def setsockopt(self, *args):
            pass

        def bind(self, adresse):
            gebunden.append(adresse)

    monkeypatch.setattr(start_colab.socket, "socket", lambda *args, **kwargs: FakeSocket())

    assert start_colab._port_belegt(5000) is False
    assert start_colab.HOST == "0.0.0.0"
    assert gebunden == [("0.0.0.0", 5000)]


# --- T6 Kein Bundle-Schreibzugriff ---------------------------------------


def test_t6_bundle_wird_nicht_beschrieben(popen, port_frei, colab, monkeypatch):
    bundle = Path(start_colab.BUNDLE_ROOT)
    if not bundle.is_dir():
        pytest.skip(f"Bundle fehlt: {bundle}")
    monkeypatch.delenv("PORT", raising=False)
    vorher = _baum_hash(bundle)

    assert start_colab.main() == 0

    assert _baum_hash(bundle) == vorher
