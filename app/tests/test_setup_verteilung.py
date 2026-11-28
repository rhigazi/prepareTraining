"""Tests für die App-Verteilung über ``setup.sh``/``verify.sh`` (Aufgabe A15).

Die Tests führen die Skripte aus ``definitions/`` gegen ``tmp_path``-Projekte aus
und prüfen Erstinstallation, Idempotenz, ``--force``, Bestandsschutz, die
Verify-Prüfungen und den Erhalt der bestehenden Setup-Abschnitte.

Eine Session-Installation dient als Vorlage; jeder Test arbeitet auf einer zügig
kopierten Arbeitskopie. Die Subprozesse laufen ohne Plugin-Autoload, damit der
Start von ``pytest`` in langsamen Container-Dateisystemen nicht dominiert.

Im verteilten Zielprojekt liegt diese Datei unter ``<ziel>/app/tests/``; dort
fehlt ``setup.sh`` im Projektwurzelverzeichnis, weshalb das Modul sich selbst
überspringt. So ruft kein verteilter Testlauf die Skripte erneut auf.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DEFINITIONS = Path(__file__).resolve().parents[2]
SETUP = DEFINITIONS / "setup.sh"
VERIFY = DEFINITIONS / "verify.sh"

pytestmark = pytest.mark.skipif(
    not (SETUP.is_file() and VERIFY.is_file()),
    reason="Setup-Skripte nur im Definitions-Repo vorhanden",
)


def _laeuft(befehl: list[str]) -> subprocess.CompletedProcess:
    """Führt einen Befehl mit Prozessumgebung aus und fängt die Ausgabe ab."""
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return subprocess.run(befehl, env=env, capture_output=True, text=True, check=False)


def _setup(ziel: Path, *optionen: str) -> subprocess.CompletedProcess:
    return _laeuft(["bash", str(SETUP), str(ziel), *optionen])


def _verify(ziel: Path) -> subprocess.CompletedProcess:
    return _laeuft(["bash", str(VERIFY), str(ziel)])


def _pytest(tests: Path) -> subprocess.CompletedProcess:
    return _laeuft(
        [sys.executable, "-m", "pytest", str(tests), "-q", "-p", "no:cacheprovider"]
    )


@pytest.fixture(scope="module")
def installation(tmp_path_factory):
    """Einmalige Installation mit ``--wissen`` als Vorlage für alle Tests."""
    # Cache-Artefakte der lokalen Testläufe sicherstellen (dürfen nicht mitverteilt werden).
    (DEFINITIONS / "app" / "__pycache__").mkdir(exist_ok=True)
    (DEFINITIONS / "app" / "tests" / ".pytest_cache").mkdir(exist_ok=True)
    (DEFINITIONS / "tools" / "__pycache__").mkdir(exist_ok=True)
    (DEFINITIONS / "tools" / "tests" / ".pytest_cache").mkdir(parents=True, exist_ok=True)
    ziel = tmp_path_factory.mktemp("vorlage") / "projekt"
    ergebnis = _setup(ziel, "--wissen")
    assert ergebnis.returncode == 0, ergebnis.stderr
    return ziel, ergebnis.stdout


@pytest.fixture()
def ziel(tmp_path, installation):
    """Arbeitskopie der Session-Installation unter ``tmp_path``."""
    vorlage, _ = installation
    kopie = tmp_path / "projekt"
    shutil.copytree(vorlage, kopie)
    return kopie


@pytest.fixture(scope="module")
def verify_lauf(tmp_path_factory, installation):
    """Ein Verify-Lauf auf einer Kopie der Session-Installation (von T5/T5b geteilt)."""
    vorlage, _ = installation
    kopie = tmp_path_factory.mktemp("verify") / "projekt"
    shutil.copytree(vorlage, kopie)
    return kopie, _verify(kopie)


# --- T1: Erstinstallation -------------------------------------------------


def test_t1_erstinstallation(installation):
    ziel, _ = installation

    for datei in (
        "app/server.py",
        "app/okf_bundle.py",
        "app/static/index.html",
        "app/static/style.css",
        "app/tests/test_server.py",
        "app/tests/conftest.py",
        "app/tests/fixtures/bundle_min/index.md",
    ):
        assert (ziel / datei).is_file(), f"{datei} fehlt nach der Installation"


def test_t1b_keine_cache_artefakte(installation):
    ziel, _ = installation
    app = ziel / "app"

    assert not list(app.rglob("__pycache__"))
    assert not list(app.rglob("*.pyc"))
    assert not list(app.rglob(".pytest_cache"))


def test_t1c_keine_cache_artefakte_in_tools(installation):
    ziel, _ = installation
    tools = ziel / "tools"

    assert (tools / "telegram_send.py").is_file()
    assert not list(tools.rglob("__pycache__"))
    assert not list(tools.rglob("*.pyc"))
    assert not list(tools.rglob(".pytest_cache"))


# --- T2: Idempotenz -------------------------------------------------------


def test_t2_idempotenz(ziel):
    server = ziel / "app/server.py"
    vorher = server.read_bytes()

    ergebnis = _setup(ziel)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "übersprungen (vorhanden):" in ergebnis.stdout
    assert "app/server.py" in ergebnis.stdout
    assert server.read_bytes() == vorher


# --- T3: --force ----------------------------------------------------------


def test_t3_force_setzt_zurueck(ziel):
    server = ziel / "app/server.py"
    conftest = ziel / "app/tests/conftest.py"
    original = server.read_bytes()
    original_conftest = conftest.read_bytes()
    server.write_text("# lokal verändert\n", encoding="utf-8")
    conftest.write_text("# lokal verändert\n", encoding="utf-8")

    ergebnis = _setup(ziel, "--force")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert server.read_bytes() == original
    assert conftest.read_bytes() == original_conftest
    assert not (ziel / "app/tests/tests").exists()


# --- T4: Bestandsschutz ---------------------------------------------------


def test_t4_bestandsschutz(ziel):
    agents = ziel / "AGENTS.md"
    agents.write_text("# Eigene Regeln\n\nMARKER-4711\n", encoding="utf-8")
    eigener_anhang = ziel / "app/tests/test_eigen.py"
    eigener_anhang.write_text("# eigener Test\n", encoding="utf-8")

    ergebnis = _setup(ziel)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "MARKER-4711" in agents.read_text(encoding="utf-8")
    assert eigener_anhang.read_text(encoding="utf-8") == "# eigener Test\n"


# --- T5: Verify grün ------------------------------------------------------


def test_t5_verify_app_abschnitt(verify_lauf):
    _, ergebnis = verify_lauf

    for datei in ("app/server.py", "app/static/index.html", "app/tests"):
        assert f"✓ {datei}" in ergebnis.stdout, f"Verify meldet {datei} nicht als vorhanden"


def test_t5b_verify_gruen(verify_lauf):
    _, ergebnis = verify_lauf

    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr


# --- T6: Verify rot -------------------------------------------------------


def test_t6_verify_nennt_fehlende_app_datei(ziel):
    (ziel / "app/server.py").unlink()

    ergebnis = _verify(ziel)

    assert ergebnis.returncode == 1
    assert "app/server.py" in ergebnis.stdout


# --- T7: Tests mitverteilt ------------------------------------------------


def test_t7_tests_mitverteilt(ziel):
    ergebnis = _pytest(ziel / "app/tests")

    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
    assert "passed" in ergebnis.stdout


# --- T8: Keine Regression der bestehenden Abschnitte ----------------------


def test_t8_bestehende_abschnitte(installation):
    _, ausgabe = installation

    for nummer in ("1)", "2)", "3)", "4)", "5)", "9)", "10)"):
        assert f"{nummer} " in ausgabe, f"Abschnitt {nummer} fehlt"
    quelle = SETUP.read_text(encoding="utf-8")
    assert "6) Global: Subagenten" in quelle
    assert "7) Global: Skill-Snapshots" in quelle
    assert "8) Global: Wichtige Skills & Browser" in quelle


# --- T9–T11: Härtung Moli in der --global-Sektion (A20) --------------------
# --global läuft in den Tests nicht echt (kein Netz, kein Download); das
# Verhalten wird über Quelltext-Marker abgesichert (wie T8).


def test_t9_moli_guard_kein_download_bei_vorhanden():
    quelle = SETUP.read_text(encoding="utf-8")

    assert "command -v moli" in quelle
    assert "übersprungen (vorhanden): moli" in quelle
    # Der Guard steht vor dem Download des Installers
    assert quelle.index("command -v moli") < quelle.index("moli-installer.sh")


def test_t10_moli_fehler_semantik_weich_und_hart():
    quelle = SETUP.read_text(encoding="utf-8")

    # Verfügbarkeitsfehler (Download/Installer): Warnung, Setup läuft weiter
    assert "Warnung: moli konnte nicht installiert werden" in quelle
    # Sicherheitsfehler (Checksummen-Abweichung): hart abbrechen
    assert "Fehler: Checksumme" in quelle
    abschnitt = quelle[quelle.index("command -v moli"):quelle.index('echo "9) Dev-Abhängigkeiten')]
    # Genau ein Abbruch im Moli-Block, und zwar auf die Checksummen-Meldung
    assert abschnitt.count("exit 1") == 1
    assert abschnitt.index("Fehler: Checksumme") < abschnitt.index("exit 1")


def test_t11_moli_installer_nur_geprueft_ausfuehren():
    quelle = SETUP.read_text(encoding="utf-8")

    # Feste Version statt "latest" (Herkunft: GitHub-Release lexmount/moli)
    assert "releases/download/v" in quelle
    assert "releases/latest" not in quelle
    # Checksummen-Prüfung vor der Ausführung, kein Pipe-in-sh
    assert "sha256sum" in quelle
    assert quelle.index("sha256sum") < quelle.index('sh "$installer"')
    assert not re.search(r"\|\s*sh\b", quelle)


# --- T12–T14: Verify-Hinweis bei fehlendem Wissensgerüst (A40) -------------


@pytest.fixture(scope="module")
def verteilung_ohne_wissen(tmp_path_factory):
    """Verteiltes Ziel ohne ``--wissen`` — das OKF-Gerüst fehlt bewusst."""
    ziel = tmp_path_factory.mktemp("ohne-wissen") / "projekt"
    ergebnis = _setup(ziel)
    assert ergebnis.returncode == 0, ergebnis.stderr
    return ziel, _verify(ziel)


def test_t12_fehlendes_wissensgeruest_nennt_setup_wissen(verteilung_ohne_wissen):
    ziel, ergebnis = verteilung_ohne_wissen

    assert not (ziel / "wissen/index.md").exists(), "--wissen wurde mitverteilt"
    assert ergebnis.returncode == 1, ergebnis.stdout + ergebnis.stderr
    assert "OKF-Wissensgerüst fehlt (8 von 8 Pflichtdateien)" in ergebnis.stdout
    assert "wissen/index.md" in ergebnis.stdout
    assert "setup.sh --wissen" in ergebnis.stdout


def test_t13_wissensgeruest_vorhanden_ohne_hinweis(verify_lauf):
    _, ergebnis = verify_lauf

    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
    assert "OKF-Wissensgerüst" not in ergebnis.stdout
    assert "setup.sh --wissen" not in ergebnis.stdout


def test_t14_teilgeruest_nennt_fehlende_dateien_exakt(ziel):
    (ziel / "wissen/projekt/phasen.md").unlink()

    ergebnis = _verify(ziel)

    assert ergebnis.returncode == 1, ergebnis.stdout + ergebnis.stderr
    assert (
        "OKF-Wissensgerüst unvollständig (1 von 8 Pflichtdateien fehlen): "
        "wissen/projekt/phasen.md"
    ) in ergebnis.stdout
    # Teilgerüst: setup.sh --wissen ist hier keine Lösung (A40-W1).
    assert "Teilgerüst" in ergebnis.stdout
    assert "Lösung: setup.sh --wissen" not in ergebnis.stdout


@pytest.mark.parametrize(
    "fehlend",
    [
        ["wissen/projekt/phasen.md", "wissen/projekt/konzept.md"],
        [
            "wissen/projekt/phasen.md",
            "wissen/projekt/konzept.md",
            "wissen/projekt/technische-spec.md",
        ],
        ["wissen/index.md", "wissen/log.md", "wissen/aufgaben/index.md"],
    ],
)
def test_t14b_mehrere_fehlende_dateien_vollstaendig_gelistet(ziel, fehlend):
    for datei in fehlend:
        (ziel / datei).unlink()

    ergebnis = _verify(ziel)

    assert ergebnis.returncode == 1, ergebnis.stdout + ergebnis.stderr
    # Exakte Liste: keine fehlende Datei darf in der Meldung fehlen.
    assert (
        f"OKF-Wissensgerüst unvollständig ({len(fehlend)} von 8 Pflichtdateien fehlen): "
        + ", ".join(fehlend)
    ) in ergebnis.stdout
