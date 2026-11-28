"""Tests für den App-Fallback in ``verify.sh`` Abschnitt „7) App" (Aufgabe A19).

Die Prüfung findet die App unter ``app/`` (verteiltes Ziel) **oder** unter
``definitions/app/`` (Dev-Repo, Fallback analog zu ``start.sh``). ``bad`` darf
bei den Datei-Prüfungen nur noch ausgelöst werden, wenn beide Varianten
fehlen; eine rote App-Test-Suite bleibt dagegen ein Befund (``bad``, Exit 1).
Die App-Test-Suite wird konsequenterweise im gefundenen Verzeichnis gesucht
(``app/tests`` bzw. ``definitions/app/tests``).

Die Tests legen minimale Ziele unter ``/tmp/opencode/`` an und führen
``definitions/verify.sh`` dagegen aus — nie gegen das echte Projekt
(insbesondere nicht gegen ``wissen/``). Die Ziele enthalten Stubs für die
Verify-Abschnitte 1–5, damit der Exit-Code allein durch Abschnitt 7 bestimmt
wird; als App-Test-Suite dient je ein trivialer Test, damit die Läufe schnell
bleiben.

Im verteilten Ziel liegt diese Datei unter ``<ziel>/app/tests/``; dort fehlen
``setup.sh``/``verify.sh`` im Projektwurzelverzeichnis, weshalb das Modul sich
selbst überspringt (wie ``test_setup_verteilung.py``).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

DEFINITIONS = Path(__file__).resolve().parents[2]
SETUP = DEFINITIONS / "setup.sh"
VERIFY = DEFINITIONS / "verify.sh"

pytestmark = pytest.mark.skipif(
    not (SETUP.is_file() and VERIFY.is_file()),
    reason="Verify-Skript nur im Definitions-Repo vorhanden",
)

TMP_BASE = Path("/tmp/opencode")

TRIVIAL_SUITE = "def test_trivial():\n    assert True\n"
ROT_SUITE = "def test_rot():\n    assert False\n"
CLI_STUB = '"""CLI-Stub: --help → Exit 0, ohne Argument → Exit 1."""\nimport sys\n\nsys.exit(0 if len(sys.argv) > 1 else 1)\n'
STUB_TEST = "def test_stub():\n    assert True\n"


def _laeuft(befehl: list[str]) -> subprocess.CompletedProcess:
    """Führt einen Befehl mit Prozessumgebung aus und fängt die Ausgabe ab."""
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return subprocess.run(befehl, env=env, capture_output=True, text=True, check=False)


def _verify(ziel: Path) -> subprocess.CompletedProcess:
    return _laeuft(["bash", str(VERIFY), str(ziel)])


def _schreibe(pfad: Path, inhalt: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(inhalt, encoding="utf-8")


def _basis(ziel: Path) -> None:
    """Stubs für die Verify-Abschnitte 1–5 (grün, damit Abschnitt 7 zählt)."""
    for datei in (
        "AGENTS.md",
        "opencode.jsonc",
        "wissen/index.md",
        "wissen/features.md",
        "wissen/log.md",
        "wissen/entscheidungen/log.md",
        "wissen/aufgaben/index.md",
        "wissen/projekt/phasen.md",
        "wissen/projekt/konzept.md",
        "wissen/projekt/technische-spec.md",
    ):
        _schreibe(ziel / datei, "# Stub\n")
    for agent in ("planner", "coder", "reviewer", "tester", "documenter"):
        _schreibe(ziel / ".opencode" / "agents" / f"{agent}.md", "# Stub\n")
    _schreibe(ziel / "tools" / "telegram_send.py", CLI_STUB)
    _schreibe(ziel / "tools" / "tests" / "test_telegram_send.py", STUB_TEST)


def _lege_app_ab(ziel: Path, lage: str) -> None:
    """Legt die App-Dateien in den gewünschten Ablageort(en) ab.

    ``lage`` ist ``"app"``, ``"definitions"``, ``"beide"`` oder ``"keine"``.
    """
    wurzeln = []
    if lage in ("app", "beide"):
        wurzeln.append(ziel / "app")
    if lage in ("definitions", "beide"):
        wurzeln.append(ziel / "definitions" / "app")
    for wurzel in wurzeln:
        _schreibe(wurzel / "server.py", "# Stub\n")
        _schreibe(wurzel / "static" / "index.html", "<!doctype html>\n")
        _schreibe(wurzel / "tests" / "test_trivial.py", TRIVIAL_SUITE)


def _projekt(ziel: Path, lage: str) -> Path:
    _basis(ziel)
    _lege_app_ab(ziel, lage)
    return ziel


def _abschnitt7(ausgabe: str) -> str:
    """Liefert die Ausgabezeilen des Abschnitts „7) App" (bis zur Leerzeile)."""
    zeilen = ausgabe.splitlines()
    for i, zeile in enumerate(zeilen):
        if zeile.startswith("7)"):
            rest = zeilen[i + 1 :]
            ende = next((n for n, z in enumerate(rest) if not z.strip()), len(rest))
            return "\n".join(rest[:ende])
    return ""


@pytest.fixture()
def projekt():
    """Temporäres Ziel-Projekt unter ``/tmp/opencode`` (wird danach entfernt)."""
    TMP_BASE.mkdir(parents=True, exist_ok=True)
    wurzel = Path(tempfile.mkdtemp(prefix="a19-verify-fallback-", dir=TMP_BASE))
    yield wurzel / "projekt"
    shutil.rmtree(wurzel, ignore_errors=True)


# --- T1: Dev-Repo-Lage (nur definitions/app/) ------------------------------


def test_t1_nur_definitions_app(projekt):
    ziel = _projekt(projekt, "definitions")

    ergebnis = _verify(ziel)

    block = _abschnitt7(ergebnis.stdout)
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
    for treffer in (
        "definitions/app/server.py",
        "definitions/app/static/index.html",
        "definitions/app/tests",
    ):
        assert f"✓ {treffer}" in block, f"Abschnitt 7 meldet {treffer} nicht"
    assert "✓ App-Test-Suite bestanden" in block
    assert "✗" not in block


# --- T2: Verteiltes Ziel (nur app/) ----------------------------------------


def test_t2_nur_app(projekt):
    ziel = _projekt(projekt, "app")

    ergebnis = _verify(ziel)

    block = _abschnitt7(ergebnis.stdout)
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
    for treffer in ("app/server.py", "app/static/index.html", "app/tests"):
        assert f"✓ {treffer}" in block, f"Abschnitt 7 meldet {treffer} nicht"
    assert "✗" not in block


# --- T3: Beide Varianten vorhanden -----------------------------------------


def test_t3_beide_varianten(projekt):
    ziel = _projekt(projekt, "beide")

    ergebnis = _verify(ziel)

    block = _abschnitt7(ergebnis.stdout)
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
    assert "✓ app/server.py" in block
    # app/ hat Vorrang vor dem Fallback (analog zu start.sh).
    assert "✓ definitions/app/server.py" not in block
    assert "✗" not in block


# --- T4: Beide Varianten fehlen --------------------------------------------


def test_t4_keine_app(projekt):
    ziel = _projekt(projekt, "keine")

    ergebnis = _verify(ziel)

    block = _abschnitt7(ergebnis.stdout)
    assert ergebnis.returncode == 1
    for f in ("server.py", "static/index.html", "tests"):
        meldung = f"✗ app/{f} und definitions/app/{f} fehlen"
        assert meldung in block, f"Abschnitt 7 nennt nicht beide Pfade zu {f}"
    assert "✗ App-Test-Suite fehlgeschlagen oder nicht vorhanden" in block


# --- T5: Test-Suite rot ist ein Befund (bad) --------------------------------


def test_t5_test_suite_rot_ist_bad(projekt):
    ziel = _projekt(projekt, "definitions")
    _schreibe(ziel / "definitions" / "app" / "tests" / "test_trivial.py", ROT_SUITE)

    ergebnis = _verify(ziel)

    block = _abschnitt7(ergebnis.stdout)
    assert ergebnis.returncode == 1
    assert "✗ App-Test-Suite fehlgeschlagen" in block
