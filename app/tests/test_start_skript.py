"""TDD-Tests für das Startskript ``start.sh`` (Aufgaben A18, A32).

``start.sh`` ist ein Repo-Werkzeug im Projektwurzelverzeichnis (neben
``definitions/``) und wird von ``setup.sh`` **nicht** verteilt. Im verteilten
Zielprojekt fehlt es daher; dort überspringt sich dieses Modul selbst.

Die Tests zu A32 (Neues-Projekt-Flow) laufen ausschließlich in ``tmp_path``:
Dort wird ein vollständiges Mini-Projekt (``wissen/``, ``tools/neues_projekt.py``,
``definitions/wissen-vorlage/``, Dummy-Server) aufgebaut. Das echte ``wissen/``
des Repositories wird nie angefasst — der Reset löscht es.
"""

import os
import pty
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parents[3]
START = PROJEKT / "start.sh"
VORLAGE = PROJEKT / "definitions" / "wissen-vorlage"

# Marker des mitgelieferten pmTool-Projekts (siehe start.sh) — die Vorlage
# legt keinen davon an.
MARKER = (
    Path("aufgaben") / "a1-okf-bundle.md",
    Path("features") / "okf-projekt-manager-spa.md",
)

pytestmark = pytest.mark.skipif(
    not (PROJEKT / "definitions" / "setup.sh").is_file(),
    reason="start.sh ist ein Repo-Root-Werkzeug und wird nicht mitverteilt",
)


def starte(
    *argumente: str, umgebung: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """Führt ``start.sh`` mit Argumenten im Projektwurzelverzeichnis aus."""
    return subprocess.run(
        ["bash", str(START), *argumente],
        cwd=PROJEKT,
        capture_output=True,
        text=True,
        timeout=120,
        env=umgebung,
    )


def test_skript_existiert_ausfuehrbar_und_nutzt_bash():
    assert START.is_file()
    assert os.access(START, os.X_OK)
    assert START.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")


def test_bash_syntax_ist_gueltig():
    pruefung = subprocess.run(["bash", "-n", str(START)], capture_output=True, text=True)
    assert pruefung.returncode == 0, pruefung.stderr


def test_colab_modus_ruft_start_colab_auf():
    ergebnis = starte("--colab", "--dry-run")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "definitions/app/start_colab.py" in ergebnis.stdout


def test_lokal_modus_bereitet_serverstart_vor():
    ergebnis = starte("--dry-run")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "server.py" in ergebnis.stdout
    assert "würde starten" in ergebnis.stdout
    assert "http://localhost:5000" in ergebnis.stdout
    assert "BUNDLE_ROOT" in ergebnis.stdout


def test_dry_run_startet_keinen_server():
    ergebnis = starte("--dry-run")

    assert "Server startet" not in ergebnis.stdout


def test_telegram_hinweis_wird_gegeben():
    ergebnis = starte("--dry-run")

    assert "config.json" in ergebnis.stdout
    assert "docs/colab-start.md" in ergebnis.stdout


def test_unbekannte_option_bricht_ab():
    ergebnis = starte("--gibt-es-nicht")

    assert ergebnis.returncode != 0
    assert "Unbekannte Option" in ergebnis.stderr


def test_help_zeigt_hilfe_ohne_shelloptionen():
    ergebnis = starte("--help")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "--colab" in ergebnis.stdout
    assert "--neu" in ergebnis.stdout
    assert "--dry-run" in ergebnis.stdout
    # Die Hilfe endet mit der letzten Kommentarzeile, nicht mit dem Skriptkopf.
    assert "set -euo" not in ergebnis.stdout


def test_dry_run_installiert_keine_pakete(tmp_path):
    """Der Dry-Run zeigt fehlende Pakete nur an und ruft pip nicht auf."""
    protokoll = tmp_path / "pip-aufrufe.txt"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f'  *"-m pip install"*) printf "%s\\n" "$*" >> "{protokoll}"; exit 0 ;;\n'
        "  *importlib.util*) exit 1 ;;\n"
        "esac\n"
        'exec "$ECHTES_PYTHON" "$@"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    umgebung = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "ECHTES_PYTHON": sys.executable,
    }

    ergebnis = starte("--dry-run", umgebung=umgebung)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "würde installieren: flask pyyaml pytest" in ergebnis.stdout
    assert not protokoll.exists(), protokoll.read_text(encoding="utf-8")


# --- A32: Neues-Projekt-Flow ----------------------------------------------
#
# Testisolation: Jedes Szenario bekommt ein eigenes Mini-Projekt unter
# ``tmp_path``. Der Reset löscht dort ``wissen/`` — nie das des Repositories.


def _werkzeug_quelle() -> Path:
    """``neues_projekt.py`` aus der Quelle (dev: definitions/tools) oder dem Spiegel."""
    for kandidat in (
        PROJEKT / "definitions" / "tools" / "neues_projekt.py",
        PROJEKT / "tools" / "neues_projekt.py",
    ):
        if kandidat.is_file():
            return kandidat
    raise AssertionError("neues_projekt.py nicht gefunden")


def _freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _umgebung(*, bundle_root: Path | str | None = None, port: int | None = None) -> dict[str, str]:
    """Umgebung ohne geerbtes ``BUNDLE_ROOT``/``PORT``; freier Port für den Dummy-Server."""
    geerbt = {"BUNDLE_ROOT", "PORT"}
    umgebung = {schlüssel: wert for schlüssel, wert in os.environ.items() if schlüssel not in geerbt}
    umgebung["PORT"] = str(port if port is not None else _freier_port())
    if bundle_root is not None:
        umgebung["BUNDLE_ROOT"] = str(bundle_root)
    return umgebung


def baue_testprojekt(
    tmp_path: Path,
    *,
    vorbefuellt: bool = True,
    mit_werkzeug: bool = True,
    mit_wissen: bool = True,
) -> Path:
    """Baut ein startfähiges Mini-Projekt (Dummy-Server, echte Vorlage, tmp-``wissen/``)."""
    projekt = tmp_path / "projekt"
    app = projekt / "definitions" / "app"
    app.mkdir(parents=True)
    (projekt / "definitions" / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (app / "server.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (app / "start_colab.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (app / "desktop.py").write_text("raise SystemExit(0)\n", encoding="utf-8")

    shutil.copy2(START, projekt / "start.sh")
    (projekt / "start.sh").chmod(0o755)

    if mit_werkzeug:
        (projekt / "tools").mkdir()
        shutil.copy2(_werkzeug_quelle(), projekt / "tools" / "neues_projekt.py")

    shutil.copytree(VORLAGE, projekt / "definitions" / "wissen-vorlage")

    if mit_wissen:
        shutil.copytree(VORLAGE, projekt / "wissen")
        if vorbefuellt:
            _marker_anlegen(projekt / "wissen", MARKER[0])
    return projekt


def _marker_anlegen(wissen: Path, marker: Path) -> None:
    ziel = wissen / marker
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text("---\ntype: Task\ntitle: A1\n---\n", encoding="utf-8")


def starte_im(
    projekt: Path,
    *argumente: str,
    eingabe: str = "",
    bundle_root: Path | str | None = None,
    port: int | None = None,
) -> subprocess.CompletedProcess:
    """Führt ``start.sh`` im Mini-Projekt aus; stdin ist eine Pipe (kein TTY)."""
    return subprocess.run(
        ["bash", str(projekt / "start.sh"), *argumente],
        cwd=projekt,
        capture_output=True,
        text=True,
        timeout=120,
        input=eingabe,
        env=_umgebung(bundle_root=bundle_root, port=port),
    )


def starte_mit_tty(
    projekt: Path,
    *argumente: str,
    eingabe: str | None,
    bundle_root: Path | None = None,
    port: int | None = None,
) -> subprocess.CompletedProcess:
    """Führt ``start.sh`` an einem echten Terminal aus (``read`` sieht ein TTY).

    ``eingabe=None`` sendet Strg+D (Eingabe-Abbruch/EOF).
    """
    master, slave = pty.openpty()
    prozess = subprocess.Popen(
        ["bash", str(projekt / "start.sh"), *argumente],
        cwd=projekt,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=_umgebung(bundle_root=bundle_root, port=port),
        close_fds=True,
    )
    os.close(slave)
    os.write(master, b"\x04" if eingabe is None else eingabe.encode("utf-8"))

    gesammelt: list[bytes] = []

    def lesen() -> None:
        while True:
            try:
                daten = os.read(master, 4096)
            except OSError:
                break
            if not daten:
                break
            gesammelt.append(daten)

    leser = threading.Thread(target=lesen)
    leser.start()
    try:
        status = prozess.wait(timeout=120)
    finally:
        leser.join(timeout=30)
        os.close(master)

    ausgabe = b"".join(gesammelt).decode("utf-8", errors="replace").replace("\r\n", "\n")
    return subprocess.CompletedProcess(prozess.args, status, ausgabe, "")


def _backups(projekt: Path) -> list[Path]:
    return sorted(projekt.glob("wissen-backup-*.tar.gz"))


def _server_mit_startprotokoll(projekt: Path, protokoll: Path) -> None:
    """Dummy-Server, der jeden Start in ``protokoll`` festhält (H6)."""
    (projekt / "definitions" / "app" / "server.py").write_text(
        "import pathlib\n"
        f"pathlib.Path({str(protokoll)!r}).write_text('gestartet\\n', encoding='utf-8')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )


def _desktop_mit_startprotokoll(projekt: Path, protokoll: Path) -> None:
    """Dummy-Desktop, der den Fensterstart in ``protokoll`` festhält."""
    (projekt / "definitions" / "app" / "desktop.py").write_text(
        "import pathlib\n"
        f"pathlib.Path({str(protokoll)!r}).write_text('gestartet\\n', encoding='utf-8')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )


def test_erststart_hinweis_ohne_tty_setzt_nichts_zurueck(tmp_path):
    """Vorbefülltes wissen/ + kein TTY: nur Hinweis, kein Prompt, keine Löschung."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_im(projekt, "--skip-verify")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Projekt-Daten" in ergebnis.stdout
    assert "Kein interaktives Terminal" in ergebnis.stdout
    assert "--neu" in ergebnis.stdout
    assert "beginnen? [j/N]" not in ergebnis.stdout
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []
    assert "Server startet" in ergebnis.stdout


def test_dry_run_zeigt_nie_einen_prompt(tmp_path):
    """Der Trockenlauf fragt nicht und löscht nichts — auch mit vorbefülltem wissen/."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_im(projekt, "--dry-run")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Projekt-Daten" in ergebnis.stdout
    assert "würde starten" in ergebnis.stdout
    assert "beginnen? [j/N]" not in ergebnis.stdout
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []


def test_frische_vorlage_zeigt_keinen_hinweis(tmp_path):
    """Ein bereits leeres Vorlagen-wissen/ löst weder Hinweis noch Rückfrage aus."""
    projekt = baue_testprojekt(tmp_path, vorbefuellt=False)

    ergebnis = starte_im(projekt, "--dry-run")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Projekt-Daten" not in ergebnis.stdout
    assert "start.sh --neu" not in ergebnis.stdout


@pytest.mark.parametrize("marker", MARKER)
def test_jeder_marker_erkennt_vorbefuelltes_wissen(tmp_path, marker):
    """Die Marker-Liste bleibt stabil, wenn eine der Referenzdateien fehlt."""
    projekt = baue_testprojekt(tmp_path, vorbefuellt=False)
    _marker_anlegen(projekt / "wissen", marker)

    ergebnis = starte_im(projekt, "--dry-run")

    assert "Projekt-Daten" in ergebnis.stdout


def test_interaktiv_nein_startet_unveraendert(tmp_path):
    """Antwort Nein: nichts wird gelöscht, die App startet normal."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_mit_tty(projekt, "--skip-verify", eingabe="nein\n")

    assert ergebnis.returncode == 0
    assert "beginnen? [j/N]" in ergebnis.stdout
    assert "tools/neues_projekt.py" in ergebnis.stdout
    assert "Nein" in ergebnis.stdout
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []
    assert "Server startet" in ergebnis.stdout


def test_interaktiv_abbruch_ist_wie_nein(tmp_path):
    """Eingabe-Abbruch (Strg+D) zählt als Nein — fail-safe ohne Löschung."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_mit_tty(projekt, "--skip-verify", eingabe=None)

    assert ergebnis.returncode == 0
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []
    assert "Server startet" in ergebnis.stdout


def test_interaktiv_ja_setzt_zurueck_und_startet(tmp_path):
    """Antwort Ja: Reset über neues_projekt.py (mit Backup), dann Start mit leerem Projekt."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_mit_tty(projekt, "--skip-verify", eingabe="ja\n")

    assert ergebnis.returncode == 0
    assert "wissen/ zurückgesetzt auf Vorlage" in ergebnis.stdout
    assert not (projekt / "wissen" / MARKER[0]).exists()
    assert (projekt / "wissen" / "index.md").is_file()
    backups = _backups(projekt)
    assert len(backups) == 1
    assert "Server startet" in ergebnis.stdout


def test_neu_setzt_ohne_rueckfrage_zurueck_und_startet(tmp_path):
    """``--neu``: Reset ohne Rückfrage (Backup-Pflicht), danach Start."""
    projekt = baue_testprojekt(tmp_path)
    eigene = projekt / "wissen" / "aufgaben" / "eigene-aufgabe.md"
    eigene.write_text("---\ntype: Task\ntitle: Eigene\n---\n", encoding="utf-8")

    ergebnis = starte_im(projekt, "--neu", "--skip-verify")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "wissen/ zurückgesetzt auf Vorlage" in ergebnis.stdout
    assert "beginnen? [j/N]" not in ergebnis.stdout
    assert not eigene.exists()
    assert _backups(projekt), "Backup ist Pflicht"
    assert "Server startet" in ergebnis.stdout


def test_neu_dry_run_zeigt_nur_den_plan(tmp_path):
    """``--neu --dry-run`` ruft das Werkzeug ohne ``--ja``: Plan, keine Änderung."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_im(projekt, "--neu", "--dry-run")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Neues Projekt beginnen — Plan (nichts wurde verändert)" in ergebnis.stdout
    assert "wissen/ zurückgesetzt" not in ergebnis.stdout
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []
    assert "würde starten" in ergebnis.stdout


def test_neu_ist_mit_colab_kombinierbar(tmp_path):
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_im(projekt, "--neu", "--colab", "--dry-run")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Neues Projekt beginnen — Plan" in ergebnis.stdout
    assert "definitions/app/start_colab.py" in ergebnis.stdout
    assert _backups(projekt) == []


def test_reset_fehler_bricht_den_start_ab(tmp_path):
    """Fehler des Reset-Werkzeugs: fail-loud, kein Start, kein Halbzustand."""
    projekt = baue_testprojekt(tmp_path)
    shutil.rmtree(projekt / "definitions" / "wissen-vorlage")

    ergebnis = starte_im(projekt, "--neu", "--skip-verify")

    assert ergebnis.returncode != 0
    assert "Fehler" in ergebnis.stderr
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []
    assert "Server startet" not in ergebnis.stdout


def test_ohne_reset_werkzeug_kein_loeschen(tmp_path):
    """Ohne ``tools/neues_projekt.py`` gibt es keine zweite Lösch-Implementierung."""
    projekt = baue_testprojekt(tmp_path, mit_werkzeug=False)

    ergebnis = starte_im(projekt, "--neu", "--skip-verify")

    assert ergebnis.returncode != 0
    assert "Werkzeug fehlt: tools/neues_projekt.py" in ergebnis.stderr
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []
    assert "Server startet" not in ergebnis.stdout


def test_kein_fallback_auf_definitions_tools(tmp_path):
    """K1: Die Quelle unter definitions/tools/ ersetzt den installierten Pfad nicht."""
    projekt = baue_testprojekt(tmp_path, mit_werkzeug=False)
    (projekt / "definitions" / "tools").mkdir()
    shutil.copy2(_werkzeug_quelle(), projekt / "definitions" / "tools" / "neues_projekt.py")

    ergebnis = starte_im(projekt, "--neu", "--skip-verify")

    assert ergebnis.returncode != 0
    assert "Werkzeug fehlt: tools/neues_projekt.py" in ergebnis.stderr
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []
    assert "Server startet" not in ergebnis.stdout


# --- A32 Nachbesserung: Reset-Ziel, BUNDLE_ROOT, Port, --neu ohne wissen/ ---


def test_fremdes_bundle_loest_keinen_reset_aus(tmp_path):
    """W1: Marker im fremden BUNDLE_ROOT dürfen den lokalen Reset nicht auslösen."""
    projekt = baue_testprojekt(tmp_path, vorbefuellt=False)
    fremd = tmp_path / "fremdes-bundle"
    _marker_anlegen(fremd, MARKER[0])

    ergebnis = starte_im(projekt, "--dry-run", bundle_root=fremd)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Projekt-Daten" not in ergebnis.stdout


def test_lokale_marker_bleiben_trotz_fremdem_bundle_ausloeser(tmp_path):
    """W1: Marker am Reset-Ziel zählen — auch wenn BUNDLE_ROOT woanders hinzeigt."""
    projekt = baue_testprojekt(tmp_path)
    fremd = tmp_path / "fremdes-bundle"
    fremd.mkdir()

    ergebnis = starte_im(projekt, "--dry-run", bundle_root=fremd)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Projekt-Daten" in ergebnis.stdout
    assert "Reset wirkt auf" in ergebnis.stdout
    assert str(projekt / "wissen") in ergebnis.stdout
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []


def test_neu_setzt_lokales_wissen_trotz_fremdem_bundle_zurueck(tmp_path):
    """W1/K5: ``--neu`` resettet <Projekt>/wissen und nennt das abweichende BUNDLE_ROOT."""
    projekt = baue_testprojekt(tmp_path)
    fremd = tmp_path / "fremdes-bundle"
    fremd.mkdir()

    ergebnis = starte_im(projekt, "--neu", "--skip-verify", bundle_root=fremd)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Reset wirkt auf" in ergebnis.stdout
    assert str(projekt / "wissen") in ergebnis.stdout
    assert not (projekt / "wissen" / MARKER[0]).exists()
    assert len(_backups(projekt)) == 1
    assert "Server startet" in ergebnis.stdout


def test_belegter_port_verhindert_reset_vor_der_rueckfrage(tmp_path):
    """K7: Bei belegtem Port kommt der Hinweis vor der Rückfrage — kein Reset."""
    projekt = baue_testprojekt(tmp_path)
    protokoll = tmp_path / "serverstarts.txt"
    _server_mit_startprotokoll(projekt, protokoll)
    with socket.socket() as belegung:
        belegung.bind(("127.0.0.1", 0))
        belegung.listen(1)
        port = belegung.getsockname()[1]

        ergebnis = starte_mit_tty(projekt, "--skip-verify", eingabe="ja\n", port=port)

    assert ergebnis.returncode == 0
    assert "bereits belegt" in ergebnis.stdout
    assert "kein Projekt-Reset" in ergebnis.stdout
    assert "beginnen? [j/N]" not in ergebnis.stdout
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []
    # H6: kein Startversuch — der Stub hätte sich sonst protokolliert.
    assert not protokoll.exists(), protokoll.read_text(encoding="utf-8")


def test_neu_ohne_wissen_legt_bundle_ohne_backup_an(tmp_path):
    """K3: ``--neu`` funktioniert auch ohne wissen/ — das Werkzeug legt es an."""
    projekt = baue_testprojekt(tmp_path, vorbefuellt=False, mit_wissen=False)

    ergebnis = starte_im(projekt, "--neu", "--skip-verify")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "wissen/ zurückgesetzt auf Vorlage" in ergebnis.stdout
    assert (projekt / "wissen" / "index.md").is_file()
    assert _backups(projekt) == []
    assert "Server startet" in ergebnis.stdout


def test_ohne_wissen_ohne_neu_bricht_ab(tmp_path):
    """Ohne ``--neu`` bleibt der Abbruch bei fehlendem wissen/ unverändert."""
    projekt = baue_testprojekt(tmp_path, vorbefuellt=False, mit_wissen=False)

    ergebnis = starte_im(projekt, "--dry-run")

    assert ergebnis.returncode != 0
    assert "wissen/ fehlt" in ergebnis.stdout
    assert "würde starten" not in ergebnis.stdout


def test_interaktiv_leere_eingabe_ist_nein(tmp_path):
    """K5: Nur Enter (leere Eingabe) zählt als Nein — nichts wird gelöscht."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_mit_tty(projekt, "--skip-verify", eingabe="\n")

    assert ergebnis.returncode == 0
    assert "beginnen? [j/N]" in ergebnis.stdout
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []
    assert "Server startet" in ergebnis.stdout


@pytest.mark.parametrize("antwort", ["y\n", "Y\n", "YES\n", "yes\n"])
def test_zustimmung_ignoriert_gross_kleinschreibung(tmp_path, antwort):
    """K5: ``y``/``Y``/``YES``/``yes`` sind Zustimmung (wie ``ja``)."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_mit_tty(projekt, "--skip-verify", eingabe=antwort)

    assert ergebnis.returncode == 0
    assert not (projekt / "wissen" / MARKER[0]).exists()
    assert len(_backups(projekt)) == 1


# --- A33-Nachträge A32-H1/H2/H3: start.sh-Polish ---------------------------


def test_belegter_port_meldet_nur_einmal(tmp_path):
    """H1: Der Port-Hinweis aus Schritt 5 ist die einzige Meldung — Schritt 7 schweigt."""
    projekt = baue_testprojekt(tmp_path)
    with socket.socket() as belegung:
        belegung.bind(("127.0.0.1", 0))
        belegung.listen(1)
        port = belegung.getsockname()[1]

        ergebnis = starte_im(projekt, "--skip-verify", port=port)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "ist bereits belegt" in ergebnis.stdout
    assert ergebnis.stdout.count("Kein zweiter Start") == 1, ergebnis.stdout
    assert "Kein zweiter Start: Port" not in ergebnis.stdout


def test_neu_bei_belegtem_port_bricht_mit_hinweis_ab(tmp_path):
    """H2: ``--neu`` bei belegtem Port ist fail-loud — kein Reset, kein Start, Exit ≠ 0."""
    projekt = baue_testprojekt(tmp_path)
    protokoll = tmp_path / "serverstarts.txt"
    _server_mit_startprotokoll(projekt, protokoll)
    with socket.socket() as belegung:
        belegung.bind(("127.0.0.1", 0))
        belegung.listen(1)
        port = belegung.getsockname()[1]

        ergebnis = starte_im(projekt, "--neu", "--skip-verify", port=port)

    assert ergebnis.returncode != 0
    assert "Server zuerst beenden, dann --neu" in ergebnis.stderr
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []
    assert "App starten" not in ergebnis.stdout
    assert not protokoll.exists(), protokoll.read_text(encoding="utf-8")


def test_neu_bei_belegtem_port_bricht_auch_in_colab_ab(tmp_path):
    """H2: Der Abbruch gilt modusunabhängig — auch ``--neu --colab`` startet nichts."""
    projekt = baue_testprojekt(tmp_path)
    with socket.socket() as belegung:
        belegung.bind(("127.0.0.1", 0))
        belegung.listen(1)
        port = belegung.getsockname()[1]

        ergebnis = starte_im(projekt, "--neu", "--colab", "--skip-verify", port=port)

    assert ergebnis.returncode != 0
    assert "Server zuerst beenden, dann --neu" in ergebnis.stderr
    assert (projekt / "wissen" / MARKER[0]).is_file()
    assert _backups(projekt) == []


def test_keine_fehlwarnung_bei_trailing_slash(tmp_path):
    """H3: ``wissen/`` mit Trailing-Slash ist dasselbe Reset-Ziel — keine Warnung."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_im(projekt, "--dry-run", bundle_root=f"{projekt / 'wissen'}/")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Projekt-Daten" in ergebnis.stdout
    assert "Reset wirkt auf" not in ergebnis.stdout


def test_keine_fehlwarnung_bei_relativem_bundle_root(tmp_path):
    """H3: Ein relativer ``BUNDLE_ROOT`` zeigt auf dasselbe Ziel — keine Warnung."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_im(projekt, "--dry-run", bundle_root="wissen")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Projekt-Daten" in ergebnis.stdout
    assert "Reset wirkt auf" not in ergebnis.stdout


def test_keine_fehlwarnung_ueber_symlink(tmp_path):
    """H3: ``pwd -P`` löst Symlinks auf — ein Link auf ``wissen/`` ist kein anderes Ziel."""
    projekt = baue_testprojekt(tmp_path)
    verknuepfung = tmp_path / "wissen-link"
    verknuepfung.symlink_to(projekt / "wissen", target_is_directory=True)

    ergebnis = starte_im(projekt, "--dry-run", bundle_root=verknuepfung)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Projekt-Daten" in ergebnis.stdout
    assert "Reset wirkt auf" not in ergebnis.stdout


def test_fehlwarnung_bleibt_bei_echt_abweichendem_ziel(tmp_path):
    """H3-Gegenprobe: Ein wirklich anderes Verzeichnis warnt weiterhin."""
    projekt = baue_testprojekt(tmp_path)
    fremd = tmp_path / "fremdes-bundle"
    fremd.mkdir()

    ergebnis = starte_im(projekt, "--dry-run", bundle_root=str(fremd) + "/")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Reset wirkt auf" in ergebnis.stdout


# --- A21: Desktop-Modus (--desktop) ----------------------------------------
#
# Der Fensterstart selbst wird nie ausgeführt: Im Mini-Projekt liegt ein
# ``desktop.py``-Stub, der nur einen Marker schreibt bzw. sofort endet.


def test_desktop_dry_run_zeigt_den_plan(tmp_path):
    """T12: ``--desktop --dry-run`` nennt das Skript und startet nichts."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_im(projekt, "--desktop", "--dry-run")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "desktop.py" in ergebnis.stdout
    assert "würde starten" in ergebnis.stdout
    assert "BUNDLE_ROOT" in ergebnis.stdout
    assert "Server startet" not in ergebnis.stdout
    assert "Desktop-Fenster startet" not in ergebnis.stdout


def test_desktop_startet_nur_desktop_stub(tmp_path):
    """T13: ``--desktop --skip-verify`` startet ausschließlich ``desktop.py``."""
    projekt = baue_testprojekt(tmp_path)
    desktop_marker = tmp_path / "desktop-gestartet.txt"
    server_marker = tmp_path / "server-gestartet.txt"
    _desktop_mit_startprotokoll(projekt, desktop_marker)
    _server_mit_startprotokoll(projekt, server_marker)

    ergebnis = starte_im(projekt, "--desktop", "--skip-verify")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert desktop_marker.is_file()
    assert not server_marker.exists(), "der Browser-Server darf nicht starten"
    assert "Server startet" not in ergebnis.stdout


def test_desktop_und_colab_schliessen_sich_aus(tmp_path):
    """T14: ``--desktop --colab`` ist fail-loud — vor jedem Start."""
    projekt = baue_testprojekt(tmp_path)
    desktop_marker = tmp_path / "desktop-gestartet.txt"
    server_marker = tmp_path / "server-gestartet.txt"
    _desktop_mit_startprotokoll(projekt, desktop_marker)
    _server_mit_startprotokoll(projekt, server_marker)

    ergebnis = starte_im(projekt, "--desktop", "--colab", "--skip-verify")

    assert ergebnis.returncode != 0
    assert "schließen sich aus" in ergebnis.stderr
    assert not desktop_marker.exists()
    assert not server_marker.exists()
    assert "App starten" not in ergebnis.stdout


def test_desktop_mit_neu_zeigt_reset_und_desktop_plan(tmp_path):
    """T15a: Modus und Reset bleiben orthogonal."""
    projekt = baue_testprojekt(tmp_path)

    ergebnis = starte_im(projekt, "--desktop", "--neu", "--dry-run")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "Neues Projekt beginnen — Plan" in ergebnis.stdout
    assert "desktop.py" in ergebnis.stdout
    assert _backups(projekt) == []
    assert (projekt / "wissen" / MARKER[0]).is_file()


def test_desktop_mit_skip_verify_startet_ohne_rueckfrage(tmp_path):
    """T15b: Frisches Mini-Projekt startet den Desktop-Stub ohne Rückfrage."""
    projekt = baue_testprojekt(tmp_path, vorbefuellt=False)
    desktop_marker = tmp_path / "desktop-gestartet.txt"
    _desktop_mit_startprotokoll(projekt, desktop_marker)

    ergebnis = starte_im(projekt, "--desktop", "--skip-verify")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert desktop_marker.is_file()
    assert "beginnen? [j/N]" not in ergebnis.stdout


def test_desktop_bei_belegtem_port_startet_kein_fenster(tmp_path):
    """T16: Der bestehende Schritt-5-Guard gilt auch für ``--desktop``."""
    projekt = baue_testprojekt(tmp_path)
    desktop_marker = tmp_path / "desktop-gestartet.txt"
    _desktop_mit_startprotokoll(projekt, desktop_marker)
    with socket.socket() as belegung:
        belegung.bind(("127.0.0.1", 0))
        belegung.listen(1)
        port = belegung.getsockname()[1]

        ergebnis = starte_im(projekt, "--desktop", "--skip-verify", port=port)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert ergebnis.stdout.count("bereits belegt") == 1, ergebnis.stdout
    assert ergebnis.stdout.count("Kein zweiter Start") == 1, ergebnis.stdout
    assert not desktop_marker.exists(), "ohne Server kein Fenster"


def test_help_nennt_desktop_und_zeigt_keine_shelloptionen():
    """T17a: Hilfe vollständig, ``hilfe()``-Range passt zu den Kopfzeilen."""
    ergebnis = starte("--help")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "--desktop" in ergebnis.stdout
    assert "--colab" in ergebnis.stdout
    assert "--neu" in ergebnis.stdout
    assert "--dry-run" in ergebnis.stdout
    # Beide Grenzen der ``hilfe()``-Range sind sichtbar: die letzte Kommentarzeile
    # (fail-safe) muss enthalten sein, die erste Shell-Zeile (Shebang) nicht.
    # Damit sterben zu enge (2,17p) und nach oben zu weite (1,18p) Ranges.
    assert "fail-safe" in ergebnis.stdout
    assert "!/usr/bin/env bash" not in ergebnis.stdout
    assert "set -euo" not in ergebnis.stdout


def test_dry_run_ohne_desktop_bleibt_beim_server():
    """T17b: Der Browser-Weg bleibt unverändert."""
    ergebnis = starte("--dry-run")

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "server.py" in ergebnis.stdout
    assert "desktop.py" not in ergebnis.stdout


def test_desktop_dry_run_installiert_kein_pywebview(tmp_path):
    """T18: pywebview bleibt aus ``PAKETE`` — kein pip-Aufruf (AK-2/AK-6)."""
    protokoll = tmp_path / "pip-aufrufe.txt"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f'  *"-m pip install"*) printf "%s\\n" "$*" >> "{protokoll}"; exit 0 ;;\n'
        "  *importlib.util*) exit 1 ;;\n"
        "esac\n"
        'exec "$ECHTES_PYTHON" "$@"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    umgebung = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "ECHTES_PYTHON": sys.executable,
    }

    ergebnis = starte("--desktop", "--dry-run", umgebung=umgebung)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "würde installieren: flask pyyaml pytest" in ergebnis.stdout
    assert "pywebview" not in ergebnis.stdout
    assert not protokoll.exists(), protokoll.read_text(encoding="utf-8")
