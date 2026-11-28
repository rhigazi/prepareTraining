"""Tests für das CLI-Werkzeug neues_projekt.py (Arbeit ausschließlich auf tmp-Kopien).

Alle Tests bauen die Projektstruktur (``definitions/wissen-vorlage/``, ``wissen/``,
``definitions/verify.sh``) in ``tmp_path`` nach und übergeben die Wurzel per
``root=`` an :func:`neues_projekt.main`. Das echte ``wissen/`` des Repositories
wird nie angefasst.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import neues_projekt  # noqa: E402


def _projektwurzel(start):
    """Wurzel, unter der ``definitions/wissen-vorlage/`` liegt.

    Die Datei liegt im Dev-Repo unter ``tools/tests`` oder ``definitions/tools/tests``
    und im installierten Zielprojekt unter ``tools/tests`` — die feste Tiefe
    ``parents[2]`` wäre nur für einen der Orte korrekt.
    """
    for kandidat in start.parents:
        if (kandidat / "definitions" / "wissen-vorlage").is_dir():
            return kandidat
    return start.parents[2]


REPO_ROOT = _projektwurzel(Path(__file__).resolve())
VORLAGE_QUELLE = REPO_ROOT / "definitions" / "wissen-vorlage"
VERIFY_QUELLE = REPO_ROOT / "definitions" / "verify.sh"

ALTE_DATEI = "aufgaben/a1-alt.md"
ALTE_VERSTECKTE_DATEI = ".alt-geheim"


def baum(wurzel):
    """Inhalt eines Baums als ``{relativer Pfad: Inhalt-Hash}`` (inkl. Verzeichnisse)."""
    ergebnis = {}
    for pfad in sorted(wurzel.rglob("*")):
        rel = pfad.relative_to(wurzel).as_posix()
        if pfad.is_dir():
            ergebnis[rel] = "<verzeichnis>"
        else:
            ergebnis[rel] = hashlib.sha256(pfad.read_bytes()).hexdigest()
    return ergebnis


def alte_wissen_struktur(wissen):
    """Legt einen realistischen Altbestand an (inkl. versteckter Dateien)."""
    dateien = {
        "index.md": "# Altbestand\n",
        "features.md": "# Features\n",
        "log.md": "# Log\n",
        "entscheidungen/log.md": "# Entscheidungen\n",
        "aufgaben/index.md": "# Aufgaben\n",
        ALTE_DATEI: "# Alte Aufgabe\n",
        "projekt/konzept.md": "# Altes Konzept\n",
        ALTE_VERSTECKTE_DATEI: "geheim\n",
        ".versteckt/notiz.md": "# versteckte Notiz\n",
    }
    for rel, inhalt in dateien.items():
        ziel = wissen / rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(inhalt, encoding="utf-8")
    (wissen / "leerer-ordner").mkdir()


def projekt_bauen(root):
    """Baut eine Projektkopie mit Vorlage, verify.sh und Altbestand in ``wissen/``."""
    vorlage = root / "definitions" / "wissen-vorlage"
    shutil.copytree(VORLAGE_QUELLE, vorlage)
    # Versteckte Datei: muss beim Reset mitkommen.
    (vorlage / ".vorlage-versteckt").write_text("versteckt\n", encoding="utf-8")
    shutil.copy2(VERIFY_QUELLE, root / "definitions" / "verify.sh")

    wissen = root / "wissen"
    wissen.mkdir()
    alte_wissen_struktur(wissen)
    return root


@pytest.fixture
def projekt(tmp_path):
    root = tmp_path / "projekt"
    root.mkdir()
    return projekt_bauen(root)


def backups(root):
    return sorted(root.glob("wissen-backup-*.tar.gz"))


def reset(root, *argumente):
    return neues_projekt.main(list(argumente), root=root)


# --- T1: Plan-Lauf ohne --ja verändert nichts ---------------------------------


def test_plan_ohne_ja_aendert_nichts(projekt, capsys):
    vorher = baum(projekt)

    exit_code = reset(projekt)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert baum(projekt) == vorher
    assert backups(projekt) == []
    assert captured.err == ""


def test_plan_nennt_umfang_vorlage_und_backupziel(projekt, capsys):
    reset(projekt)

    ausgabe = capsys.readouterr().out
    assert "Plan" in ausgabe
    assert "wissen/" in ausgabe
    assert "Dateien" in ausgabe
    assert "Ordner" in ausgabe
    assert "definitions/wissen-vorlage/" in ausgabe
    assert "Backup" in ausgabe
    assert "wissen-backup-" in ausgabe
    assert "--ja" in ausgabe


def test_plan_weist_auf_loeschung_hin(projekt, capsys):
    reset(projekt)

    ausgabe = capsys.readouterr().out
    assert "löscht" in ausgabe or "gelöscht" in ausgabe
    assert "nichts" in ausgabe.lower()


# --- T2: --ja sichert alten Stand und setzt auf die Vorlage -------------------


def test_ja_erzeugt_backup_mit_alten_dateien(projekt, capsys):
    exit_code = reset(projekt, "--ja")

    angelegte_backups = backups(projekt)
    assert exit_code == 0
    assert len(angelegte_backups) == 1

    with tarfile.open(angelegte_backups[0]) as archiv:
        namen = archiv.getnames()
        inhalt = archiv.extractfile(f"wissen/{ALTE_DATEI}").read().decode("utf-8")
    assert f"wissen/{ALTE_DATEI}" in namen
    assert f"wissen/{ALTE_VERSTECKTE_DATEI}" in namen
    assert inhalt == "# Alte Aufgabe\n"
    assert capsys.readouterr().out.count("Backup") >= 1


def test_ja_setzt_wissen_auf_vorlage(projekt, capsys):
    reset(projekt, "--ja")

    wissen = projekt / "wissen"
    vorlage = projekt / "definitions" / "wissen-vorlage"
    assert not (wissen / ALTE_DATEI).exists()
    assert not (wissen / ALTE_VERSTECKTE_DATEI).exists()
    assert baum(wissen) == baum(vorlage)
    assert "zurückgesetzt auf Vorlage" in capsys.readouterr().out


def test_ja_nennt_naechste_schritte_und_sicherheitshinweis(projekt, capsys):
    reset(projekt, "--ja")

    ausgabe = capsys.readouterr().out
    assert "Nächste Schritte" in ausgabe
    assert "start.sh" in ausgabe
    assert "Projekt" in ausgabe
    assert "leer" in ausgabe
    assert "verify.sh" in ausgabe


def test_eigener_backup_pfad_wird_genutzt(projekt, capsys):
    ziel = projekt / "sicherungen" / "stand.tar.gz"

    exit_code = reset(projekt, "--ja", "--backup", str(ziel))

    assert exit_code == 0
    assert ziel.is_file()
    assert backups(projekt) == []
    assert str(ziel) in capsys.readouterr().out


def test_ohne_wissen_kein_backup_noetig(projekt, capsys):
    vorlage = projekt / "definitions" / "wissen-vorlage"
    shutil.rmtree(projekt / "wissen")

    exit_code = reset(projekt, "--ja")

    ausgabe = capsys.readouterr().out
    assert exit_code == 0
    assert baum(projekt / "wissen") == baum(vorlage)
    assert backups(projekt) == []
    assert "nicht nötig" in ausgabe


def test_neues_wissen_ist_fuer_andere_lesbar(projekt, capsys):
    reset(projekt, "--ja")

    modus = (projekt / "wissen").stat().st_mode & 0o777
    assert modus == 0o755, f"wissen/ hat Modus {modus:o} (mkdtemp hinterlässt 0700)"


def test_erfolgsmeldung_enthaelt_keine_unbelegte_verify_behauptung(projekt, capsys):
    """H1: Eigenschaft statt Wortlaut — nur belegbare Aussagen in der Ausgabe."""
    reset(projekt, "--ja")

    ausgabe = capsys.readouterr().out
    assert re.search(r"verify[^.\n]*(grün|bestanden|erfolgreich|ok)", ausgabe, re.I) is None
    # Schärfung: auch über die Endung hinweg darf keine Verify-Behauptung stehen.
    assert re.search(r"verify(?:\.sh)?[^\n]{0,40}(grün|bestanden|erfolgreich|ok)", ausgabe, re.I) is None
    assert re.search(r"geprüfte[rmn]?\s+Vorlage", ausgabe)
    assert "Setup prüfen: bash definitions/verify.sh" in ausgabe


def test_backup_pfad_ausserhalb_des_repos_wird_abgelehnt(projekt, tmp_path_factory, capsys):
    vorher = baum(projekt / "wissen")
    aussen = tmp_path_factory.mktemp("aussen") / "backup.tar.gz"

    exit_code = reset(projekt, "--ja", "--backup", str(aussen))

    assert exit_code == 1
    assert not aussen.exists()
    assert baum(projekt / "wissen") == vorher
    assert "Fehler" in capsys.readouterr().err


def test_relative_traversale_als_backup_pfad_wird_abgelehnt(projekt, capsys):
    vorher = baum(projekt / "wissen")

    exit_code = reset(projekt, "--ja", "--backup", "../aussen.tar.gz")

    assert exit_code == 1
    assert not (projekt.parent / "aussen.tar.gz").exists()
    assert baum(projekt / "wissen") == vorher
    assert "außerhalb" in capsys.readouterr().err


def test_vorhandenes_backup_ziel_wird_abgelehnt(projekt, capsys):
    vorher = baum(projekt / "wissen")
    ziel = projekt / "sicherungen" / "stand.tar.gz"
    ziel.parent.mkdir()
    ziel.write_bytes(b"altes backup")

    exit_code = reset(projekt, "--ja", "--backup", str(ziel))

    captured = capsys.readouterr()
    assert exit_code != 0
    assert ziel.read_bytes() == b"altes backup"
    assert baum(projekt / "wissen") == vorher
    assert "existiert" in captured.err


def test_symlink_als_backup_ziel_wird_abgelehnt(projekt, capsys):
    vorher = baum(projekt / "wissen")
    (projekt / "link.tar.gz").symlink_to(projekt / "fehlt.tar.gz")

    exit_code = reset(projekt, "--ja", "--backup", "link.tar.gz")

    captured = capsys.readouterr()
    assert exit_code != 0
    assert (projekt / "link.tar.gz").is_symlink()
    assert not (projekt / "fehlt.tar.gz").exists()
    assert baum(projekt / "wissen") == vorher
    assert "Symlink" in captured.err


def test_backup_pfad_im_wissen_verzeichnis_wird_abgelehnt(projekt, capsys):
    vorher = baum(projekt / "wissen")
    ziel = projekt / "wissen" / "backup.tar.gz"

    exit_code = reset(projekt, "--ja", "--backup", str(ziel))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert baum(projekt / "wissen") == vorher
    assert not ziel.exists()
    assert "Fehler" in captured.err
    # Zielpfad-Verifikation (B1-K1): Ablehnung erfolgt wegen des Ziel-Pfads
    # innerhalb von wissen/, nicht nur als generischer Fehler.
    assert "wissen" in captured.err


def test_wissen_als_datei_wird_abgelehnt(projekt, capsys):
    shutil.rmtree(projekt / "wissen")
    (projekt / "wissen").write_text("keine Struktur\n", encoding="utf-8")

    exit_code = reset(projekt, "--ja")

    assert exit_code == 1
    assert (projekt / "wissen").read_text(encoding="utf-8") == "keine Struktur\n"
    assert "Verzeichnis" in capsys.readouterr().err


def test_wissen_als_symlink_wird_abgelehnt(projekt, tmp_path_factory, capsys):
    ziel = tmp_path_factory.mktemp("aussen") / "wissen"
    ziel.mkdir()
    (ziel / "wichtig.md").write_text("bleibt\n", encoding="utf-8")
    shutil.rmtree(projekt / "wissen")
    (projekt / "wissen").symlink_to(ziel, target_is_directory=True)

    exit_code = reset(projekt, "--ja")

    assert exit_code == 1
    assert (ziel / "wichtig.md").is_file()
    assert "Symlink" in capsys.readouterr().err


# --- T3: Backup-Fehler verhindert das Löschen ---------------------------------


def test_backup_fehler_verhindert_loeschen(projekt, capsys, monkeypatch):
    vorher = baum(projekt / "wissen")

    def kaputtes_backup(*args, **kwargs):
        raise OSError("Speicher voll")

    monkeypatch.setattr(neues_projekt.tarfile, "open", kaputtes_backup)

    exit_code = reset(projekt, "--ja")

    captured = capsys.readouterr()
    assert exit_code != 0
    assert baum(projekt / "wissen") == vorher
    assert "Backup" in captured.err
    assert "Speicher voll" in captured.err
    assert backups(projekt) == []


def test_backup_fehler_laesst_kein_halbfertiges_archiv_zurueck(projekt, capsys, monkeypatch):
    def kaputtes_backup(*args, **kwargs):
        # R8: tarfile schreibt in den bereits exklusiv geöffneten Deskriptor.
        kwargs["fileobj"].write(b"halb")
        raise OSError("Schreiben fehlgeschlagen")

    monkeypatch.setattr(neues_projekt.tarfile, "open", kaputtes_backup)

    reset(projekt, "--ja")

    assert backups(projekt) == []


def test_backup_ziel_als_verzeichnis_wird_abgelehnt(projekt, capsys):
    vorher = baum(projekt / "wissen")
    ziel = projekt / "backup-verzeichnis"
    ziel.mkdir()

    exit_code = reset(projekt, "--ja", "--backup", str(ziel))

    assert exit_code == 1
    assert baum(projekt / "wissen") == vorher
    assert "Verzeichnis" in capsys.readouterr().err


# --- K1/K2: zweite Barriere und baumelnde Symlinks ---------------------------


def test_backup_erstellen_lehnt_vorhandenes_ziel_ab(projekt):
    """K1: die Barriere steht auch direkt in ``backup_erstellen`` (nicht nur im CLI)."""
    vorher = baum(projekt / "wissen")
    ziel = projekt / "vorhanden.tar.gz"
    ziel.write_bytes(b"alt")

    with pytest.raises(neues_projekt.BackupFehler):
        neues_projekt.backup_erstellen(projekt / "wissen", ziel)

    assert ziel.read_bytes() == b"alt"
    assert baum(projekt / "wissen") == vorher


def test_baumelnder_symlink_auf_automatischem_namen_wird_umgangen(projekt, capsys, monkeypatch):
    """K2: ein baumelnder Symlink auf dem Auto-Namen wird nie überschrieben."""
    jetzt = datetime(2026, 1, 1, 12, 0, 0)

    class FesteZeit(datetime):
        @classmethod
        def now(cls, tz=None):
            return jetzt

    monkeypatch.setattr(neues_projekt, "datetime", FesteZeit)
    link = projekt / "wissen-backup-20260101-120000.tar.gz"
    linkziel = projekt / "nicht-angelegt.tar.gz"
    link.symlink_to(linkziel)
    vorlage = projekt / "definitions" / "wissen-vorlage"

    exit_code = reset(projekt, "--ja")

    ausweich = projekt / "wissen-backup-20260101-120000-2.tar.gz"
    assert exit_code == 0
    assert ausweich.is_file()
    assert tarfile.is_tarfile(ausweich)
    assert link.is_symlink()
    assert os.readlink(link) == str(linkziel)
    assert not linkziel.exists(), "das Linkziel wurde angelegt (durch den Link geschrieben)"
    assert baum(projekt / "wissen") == baum(vorlage)


def test_backup_erstellen_lehnt_baumelnden_symlink_ab(projekt):
    """K2: auch die direkte Barriere erkennt einen baumelnden Symlink."""
    vorher = baum(projekt / "wissen")
    ziel = projekt / "baumelnd.tar.gz"
    linkziel = projekt / "fehlt.tar.gz"
    ziel.symlink_to(linkziel)

    with pytest.raises(neues_projekt.BackupFehler):
        neues_projekt.backup_erstellen(projekt / "wissen", ziel)

    assert ziel.is_symlink()
    assert os.readlink(ziel) == str(linkziel)
    assert not linkziel.exists()
    assert baum(projekt / "wissen") == vorher


# --- R8: exklusives Öffnen (O_EXCL) gegen den Rest-TOCTOU -------------------


def _lexists_vergessen(monkeypatch, ziel):
    """Simuliert den Wettlauf: ``lexists`` sieht das Ziel frei, obwohl es belegt ist.

    Nur der exakte Zielpfad wird „übersehen"; alle anderen Pfade (etwa die
    Ausweichnamen in ``_backup_name``) behalten das echte Verhalten.
    """
    echt = os.path.lexists
    ziel = Path(ziel)
    monkeypatch.setattr(
        neues_projekt.os.path,
        "lexists",
        lambda pfad: False if Path(pfad) == ziel else echt(pfad),
    )


def test_backup_erstellen_oeffnet_exklusiv_trotz_verlorenem_wettlauf(projekt, monkeypatch):
    """R8: erscheint das Ziel nach ``lexists``, wird es nicht truncatet."""
    vorher = baum(projekt / "wissen")
    ziel = projekt / "wettlauf.tar.gz"
    ziel.write_bytes(b"fremde sicherung")
    _lexists_vergessen(monkeypatch, ziel)

    with pytest.raises(neues_projekt.BackupFehler) as fehler:
        neues_projekt.backup_erstellen(projekt / "wissen", ziel)

    assert ziel.read_bytes() == b"fremde sicherung"
    assert "existiert" in str(fehler.value)
    assert baum(projekt / "wissen") == vorher


def test_backup_erstellen_oeffnet_exklusiv_gegen_symlink_rennen(
    projekt, tmp_path_factory, monkeypatch
):
    """R8: ein nach ``lexists`` untergeschobener Symlink wird nicht beschrieben."""
    ziel = projekt / "wettlauf.tar.gz"
    aussen = tmp_path_factory.mktemp("aussen") / "fremd.tar.gz"
    ziel.symlink_to(aussen)
    _lexists_vergessen(monkeypatch, ziel)

    with pytest.raises(neues_projekt.BackupFehler):
        neues_projekt.backup_erstellen(projekt / "wissen", ziel)

    assert ziel.is_symlink()
    assert not aussen.exists(), "das Archiv wurde durch den Link nach außen geschrieben"


def test_backup_name_zaehlt_vorhandene_backups_hoch(projekt):
    """K3: deterministische Ausweichnamen — Basis und ``-2`` belegt → ``-3``."""
    zeitpunkt = datetime(2026, 1, 1, 12, 0, 0)
    stamm = "wissen-backup-20260101-120000"
    (projekt / f"{stamm}.tar.gz").write_bytes(b"1")
    (projekt / f"{stamm}-2.tar.gz").write_bytes(b"2")

    assert neues_projekt._backup_name(projekt, zeitpunkt) == f"{stamm}-3.tar.gz"


def test_backup_name_fuellt_die_erste_freie_nummer(projekt):
    """K3: eine Lücke wird geschlossen (``-2`` fehlt, ``-3`` belegt → ``-2``)."""
    zeitpunkt = datetime(2026, 1, 1, 12, 0, 0)
    stamm = "wissen-backup-20260101-120000"
    (projekt / f"{stamm}.tar.gz").write_bytes(b"1")
    (projekt / f"{stamm}-3.tar.gz").write_bytes(b"3")

    assert neues_projekt._backup_name(projekt, zeitpunkt) == f"{stamm}-2.tar.gz"


def test_backup_name_ueberspringt_baumelnden_symlink(projekt):
    """K3: ``lexists`` statt ``exists`` — auch ein toter Link belegt den Namen."""
    zeitpunkt = datetime(2026, 1, 1, 12, 0, 0)
    stamm = "wissen-backup-20260101-120000"
    linkziel = projekt / "fehlt.tar.gz"
    (projekt / f"{stamm}.tar.gz").symlink_to(linkziel)

    assert neues_projekt._backup_name(projekt, zeitpunkt) == f"{stamm}-2.tar.gz"
    assert not linkziel.exists()


# --- T4: fehlende oder unvollständige Vorlage --------------------------------


def test_fehlende_vorlage_bricht_ohne_loeschung_ab(projekt, capsys):
    vorher = baum(projekt / "wissen")
    shutil.rmtree(projekt / "definitions" / "wissen-vorlage")

    exit_code = reset(projekt, "--ja")

    captured = capsys.readouterr()
    assert exit_code == 1
    assert baum(projekt / "wissen") == vorher
    assert "Vorlage" in captured.err
    assert backups(projekt) == []


def test_unvollstaendige_vorlage_nennt_fehlende_datei(projekt, capsys):
    vorher = baum(projekt / "wissen")
    (projekt / "definitions" / "wissen-vorlage" / "features.md").unlink()

    exit_code = reset(projekt, "--ja")

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "features.md" in captured.err
    assert baum(projekt / "wissen") == vorher
    assert backups(projekt) == []


@pytest.mark.parametrize("pflichtdatei", neues_projekt.PFLICHTDATEIEN)
def test_fehlende_pflichtdatei_der_vorlage_wird_gemeldet(projekt, capsys, pflichtdatei):
    """B1-K2: jede Pflichtdatei der Vorlage wird einzeln als fehlend erkannt."""
    vorher = baum(projekt / "wissen")
    (projekt / "definitions" / "wissen-vorlage" / pflichtdatei).unlink()

    exit_code = reset(projekt, "--ja")

    captured = capsys.readouterr()
    assert exit_code == 1
    assert pflichtdatei in captured.err
    assert "unvollständig" in captured.err
    assert baum(projekt / "wissen") == vorher
    assert backups(projekt) == []


def test_fehlende_pflichtdatei_im_neuaufbau_bricht_ab(projekt, capsys, monkeypatch):
    """B1-K2: fehlt eine Pflichtdatei im aufgebauten Baum, wird nicht getauscht."""
    vorher = baum(projekt / "wissen")
    echt = neues_projekt.kopiere_vorlage

    def ohne_features(quelle, ziel):
        echt(quelle, ziel)
        (ziel / "features.md").unlink()

    monkeypatch.setattr(neues_projekt, "kopiere_vorlage", ohne_features)

    exit_code = reset(projekt, "--ja")

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "features.md" in captured.err
    assert "Pflichtdatei" in captured.err
    assert baum(projekt / "wissen") == vorher
    # Das vorher erstellte Backup bleibt erhalten: nichts wurde ohne Backup gelöscht.
    assert len(backups(projekt)) == 1


def test_leere_vorlage_bricht_ohne_loeschung_ab(projekt, capsys):
    vorher = baum(projekt / "wissen")
    vorlage = projekt / "definitions" / "wissen-vorlage"
    shutil.rmtree(vorlage)
    vorlage.mkdir()

    exit_code = reset(projekt, "--ja")

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Vorlage" in captured.err
    assert baum(projekt / "wissen") == vorher
    assert backups(projekt) == []


def test_plan_meldet_fehlende_vorlage_ebenfalls(projekt, capsys):
    shutil.rmtree(projekt / "definitions" / "wissen-vorlage")

    exit_code = reset(projekt)

    assert exit_code == 1
    assert "Vorlage" in capsys.readouterr().err


def test_symlink_in_der_vorlage_bricht_ab(projekt, capsys):
    vorher = baum(projekt / "wissen")
    (projekt / "definitions" / "wissen-vorlage" / "verknuepfung.md").symlink_to("index.md")

    exit_code = reset(projekt, "--ja")

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "Symlink" in captured.err
    assert baum(projekt / "wissen") == vorher
    assert backups(projekt) == []


# --- T5: keine Cache-Artefakte, keine Reste ----------------------------------


def test_reset_enthaelt_keine_cache_artefakte(projekt, capsys):
    vorlage = projekt / "definitions" / "wissen-vorlage"
    (vorlage / "__pycache__").mkdir()
    (vorlage / "__pycache__" / "modul.cpython-313.pyc").write_bytes(b"cache")
    (vorlage / ".pytest_cache" / "v" / "cache").mkdir(parents=True)
    (vorlage / ".pytest_cache" / "v" / "cache" / "nodeids").write_text("x", encoding="utf-8")
    (vorlage / "alt.pyc").write_bytes(b"cache")

    exit_code = reset(projekt, "--ja")

    inhalte = baum(projekt / "wissen")
    assert exit_code == 0
    assert not any("__pycache__" in pfad for pfad in inhalte)
    assert not any(".pytest_cache" in pfad for pfad in inhalte)
    assert not any(pfad.endswith(".pyc") for pfad in inhalte)


def test_reset_laesst_keine_temporaeren_verzeichnisse_zurueck(projekt, capsys):
    reset(projekt, "--ja")

    reste = [
        pfad.name
        for pfad in projekt.iterdir()
        if pfad.is_dir() and pfad.name.startswith(".")
    ]
    assert reste == []


def test_vorlage_bleibt_unveraendert(projekt, capsys):
    vorlage = projekt / "definitions" / "wissen-vorlage"
    vorher = baum(vorlage)

    reset(projekt, "--ja")

    assert baum(vorlage) == vorher


def test_fehlgeschlagener_rollback_erhaelt_den_altbestand(projekt, capsys, monkeypatch):
    """Scheitern Tausch *und* Rollback, darf der Altbaum nicht gelöscht werden."""
    vorher = baum(projekt / "wissen")
    echt = neues_projekt._ersetze
    aufrufe = {"n": 0}

    def ersetze(quelle, ziel):
        aufrufe["n"] += 1
        if aufrufe["n"] == 2:
            raise OSError(13, "Tausch verweigert")
        if aufrufe["n"] == 3:
            raise OSError(13, "Rollback verweigert")
        return echt(quelle, ziel)

    monkeypatch.setattr(neues_projekt, "_ersetze", ersetze)

    exit_code = reset(projekt, "--ja")

    captured = capsys.readouterr()
    assert exit_code != 0
    assert not (projekt / "wissen").exists()
    assert not any(p.name.startswith(".wissen-neu-") for p in projekt.iterdir())
    alts = sorted(p for p in projekt.iterdir() if p.name.startswith(".wissen-alt-"))
    assert len(alts) == 1, "Altbestand wurde trotz fehlgeschlagenem Rollback gelöscht"
    assert baum(alts[0]) == vorher
    assert "gesichert" in captured.err
    assert str(alts[0]) in captured.err
    schritte = [zeile for zeile in captured.err.splitlines() if "Wiederherstellen" in zeile]
    assert schritte, "stderr nennt keinen konkreten Wiederherstellungsschritt"
    assert "mv" in schritte[0]
    assert "wissen" in schritte[0]


# --- T6: E2E — Reset auf Testkopie, danach verify.sh -------------------------


def verify_kopie_bauen(root):
    """Ergänzt die Projektkopie um alles, was ``definitions/verify.sh`` prüft.

    Die App wird als Minimal-Stub angelegt: ``verify.sh`` prüft nur Existenz und
    eine grüne Test-Suite. Die echte App-Suite bleibt den App-Tests vorbehalten
    (und würde hier nur zusätzlich Zeit kosten); die eigene Testdatei wird
    bewusst NICHT kopiert, weil ``verify.sh`` sonst rekursiv diesen Test startet.
    """
    shutil.copy2(REPO_ROOT / "AGENTS.md", root / "AGENTS.md")
    shutil.copy2(REPO_ROOT / "opencode.jsonc", root / "opencode.jsonc")
    # Quellen liegen im Dev-Repo unter definitions/, im installierten Zielprojekt
    # nur unter .opencode/agents/ — beide Layouts müssen den E2E-Test tragen.
    agenten_quelle = REPO_ROOT / "definitions" / "agents"
    if not agenten_quelle.is_dir():
        agenten_quelle = REPO_ROOT / ".opencode" / "agents"
    agenten = root / ".opencode" / "agents"
    agenten.mkdir(parents=True)
    for quelle in sorted(agenten_quelle.glob("*.md")):
        shutil.copy2(quelle, agenten / quelle.name)

    (root / "tools" / "tests").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "tools" / "telegram_send.py", root / "tools" / "telegram_send.py")
    shutil.copy2(
        REPO_ROOT / "tools" / "tests" / "test_telegram_send.py",
        root / "tools" / "tests" / "test_telegram_send.py",
    )

    (root / "app" / "static").mkdir(parents=True)
    (root / "app" / "server.py").write_text("", encoding="utf-8")
    (root / "app" / "static" / "index.html").write_text("", encoding="utf-8")
    (root / "app" / "tests").mkdir()
    (root / "app" / "tests" / "test_smoke.py").write_text(
        "def test_smoke():\n    assert True\n", encoding="utf-8"
    )


def test_verify_nach_reset_ist_gruen(projekt, capsys):
    verify_kopie_bauen(projekt)

    assert reset(projekt, "--ja") == 0

    ergebnis = subprocess.run(
        ["bash", str(projekt / "definitions" / "verify.sh"), str(projekt)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr
    assert "Setup vollständig" in ergebnis.stdout


# --- T7: zweiter Aufruf ist idempotent ---------------------------------------


def test_zweiter_aufruf_ist_idempotent(projekt, capsys):
    reset(projekt, "--ja")
    erster_stand = baum(projekt / "wissen")

    exit_code = reset(projekt, "--ja")

    assert exit_code == 0
    assert baum(projekt / "wissen") == erster_stand
    assert baum(projekt / "wissen") == baum(projekt / "definitions" / "wissen-vorlage")
    assert len(backups(projekt)) == 2


def test_zweites_backup_ueberschreibt_das_erste_nicht(projekt, capsys):
    reset(projekt, "--ja")
    erstes = backups(projekt)[0]
    groesse = erstes.stat().st_size

    reset(projekt, "--ja")

    assert erstes.is_file()
    assert erstes.stat().st_size == groesse
    assert len(backups(projekt)) == 2
