"""TDD-Tests für ``nachtrag`` (Aufgabe A3)."""

import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import okf_bundle
from nachtrag import anfuegen
from okf_bundle import BundlePfadFehler, EingabeFehler, ReservierteDateiFehler

MARKER = re.compile(r"^> \*\*Nachtrag \(Mensch, \d{4}-\d{2}-\d{2}\):\*\* .+$")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lies(pfad: Path) -> str:
    with open(pfad, encoding="utf-8", newline="") as datei:
        return datei.read()


def _marker_zeilen(text: str) -> list[str]:
    return [zeile for zeile in text.splitlines() if MARKER.match(zeile)]


# --- Anfügen --------------------------------------------------------------


def test_t1_abschnitt_fehlt(bundle):
    pfad = bundle / "aufgaben/a1.md"
    vorher = _lies(pfad)

    anfuegen("aufgaben/a1.md", "Bitte präzisieren.", "2026-11-14")

    nachher = _lies(pfad)
    assert nachher.startswith(vorher)
    zeilen = [zeile for zeile in nachher.splitlines() if zeile.strip()]
    assert zeilen[-2] == "# Nachträge"
    assert MARKER.match(zeilen[-1])


def test_t2_markerformat(bundle):
    anfuegen("aufgaben/a1.md", "Mehr Kontext bitte.", "2026-11-14")

    letzte = _lies(bundle / "aufgaben/a1.md").strip().splitlines()[-1]
    assert letzte == "> **Nachtrag (Mensch, 2026-11-14):** Mehr Kontext bitte."
    assert MARKER.match(letzte)


def test_t3_abschnitt_vorhanden(bundle):
    pfad = bundle / "aufgaben/notiz.md"
    alt = (
        "---\ntype: Note\ntitle: Notiz\n---\n\n# Ziel\n\nText.\n\n"
        "# Nachträge\n\n> **Nachtrag (Mensch, 2026-11-01):** Alt.\n"
    )
    pfad.write_text(alt, encoding="utf-8")

    anfuegen("aufgaben/notiz.md", "Neu.", "2026-11-14")

    nachher = _lies(pfad)
    assert nachher.startswith(alt)
    assert _marker_zeilen(nachher) == [
        "> **Nachtrag (Mensch, 2026-11-01):** Alt.",
        "> **Nachtrag (Mensch, 2026-11-14):** Neu.",
    ]


def test_a3_2_abschnitt_in_dateimitte(bundle):
    """Steht ``# Nachträge`` vor weiteren Überschriften, bleibt alles darunter erhalten."""
    pfad = bundle / "aufgaben/notiz.md"
    kopf = (
        "---\ntype: Note\ntitle: Notiz\n---\n\n# Ziel\n\nText.\n\n"
        "# Nachträge\n\n> **Nachtrag (Mensch, 2026-11-01):** Alt.\n\n"
    )
    rest = "# Kontext\n\nBleibt stehen.\n"
    pfad.write_text(kopf + rest, encoding="utf-8")

    anfuegen("aufgaben/notiz.md", "Neu.", "2026-11-14")

    nachher = _lies(pfad)
    assert nachher.startswith(kopf)
    assert nachher.endswith(rest)
    assert _marker_zeilen(nachher) == [
        "> **Nachtrag (Mensch, 2026-11-01):** Alt.",
        "> **Nachtrag (Mensch, 2026-11-14):** Neu.",
    ]


def test_t4_inhaltsschutz(bundle):
    pfad = bundle / "aufgaben/a1.md"
    vorher = _lies(pfad)

    anfuegen("aufgaben/a1.md", "Zusatz.", "2026-11-14")

    nachher = _lies(pfad)
    assert _hash(nachher[: len(vorher)]) == _hash(vorher)


def test_t5_frontmatter_unveraendert(bundle):
    vorher, _ = okf_bundle.lesen("aufgaben/a1.md")

    anfuegen("aufgaben/a1.md", "Zusatz.", "2026-11-14")

    nachher, _ = okf_bundle.lesen("aufgaben/a1.md")
    assert nachher == vorher
    assert nachher["type"] == "Task"


@pytest.mark.parametrize("text", [None, "", "   ", "\n\t\n"])
def test_t6_leere_eingabe(bundle, text):
    pfad = bundle / "aufgaben/a1.md"
    vorher = _lies(pfad)

    with pytest.raises(EingabeFehler):
        anfuegen("aufgaben/a1.md", text, "2026-11-14")

    assert _hash(_lies(pfad)) == _hash(vorher)


def test_t7_mehrzeilig(bundle):
    anfuegen("aufgaben/a1.md", "Zeile eins.\nZeile zwei.", "2026-11-14")

    zeilen = [zeile for zeile in _lies(bundle / "aufgaben/a1.md").splitlines() if zeile.strip()]
    assert zeilen[-2:] == [
        "> **Nachtrag (Mensch, 2026-11-14):** Zeile eins.",
        "> Zeile zwei.",
    ]


@pytest.mark.parametrize("pfad", ["../aussen.md", "/etc/passwd", "aufgaben/../../x.md"])
def test_t8_pfad_ausserhalb(bundle, pfad):
    with pytest.raises(BundlePfadFehler):
        anfuegen(pfad, "Text", "2026-11-14")


def test_t8b_pfad_ausserhalb_legt_keine_datei_an(bundle, tmp_path):
    with pytest.raises(BundlePfadFehler):
        anfuegen("../aussen.md", "Text", "2026-11-14")

    assert not (tmp_path / "aussen.md").exists()


@pytest.mark.parametrize("rel", ["index.md", "log.md", "features.md"])
def test_t9_reservierte_dateien_schreibgeschuetzt(bundle, rel):
    pfad = bundle / rel
    vorher = pfad.read_bytes()

    with pytest.raises(ReservierteDateiFehler):
        anfuegen(rel, "Eintrag der Projektleitung.", "2026-11-14")

    assert pfad.read_bytes() == vorher


# --- Datum ----------------------------------------------------------------


def test_t10_datum_default_utc(bundle):
    anfuegen("aufgaben/a1.md", "Ohne Datum.")

    erwartet = datetime.now(timezone.utc).date().isoformat()
    assert f"> **Nachtrag (Mensch, {erwartet}):** Ohne Datum." in _lies(bundle / "aufgaben/a1.md")


@pytest.mark.parametrize("datum", ["14.11.2026", "2026-13-01", ""])
def test_t11_ungueltiges_datum(bundle, datum):
    pfad = bundle / "aufgaben/a1.md"
    vorher = _lies(pfad)

    with pytest.raises(EingabeFehler):
        anfuegen("aufgaben/a1.md", "Text", datum)

    assert _hash(_lies(pfad)) == _hash(vorher)


# --- Review A9: Schreibziel-Validierung (W1) -------------------------------


def test_nicht_md_ziel_aendert_nichts(bundle):
    pfad = bundle / "notiz.txt"
    pfad.write_text("---\ntype: Note\n---\n\nText.\n", encoding="utf-8")
    vorher = pfad.read_bytes()

    with pytest.raises(BundlePfadFehler):
        anfuegen("notiz.txt", "Nachtrag.", "2026-11-14")

    assert pfad.read_bytes() == vorher


def test_verzeichnis_als_ziel_ist_abgelehnt(bundle):
    (bundle / "verz.md").mkdir()

    with pytest.raises(BundlePfadFehler):
        anfuegen("verz.md", "Nachtrag.", "2026-11-14")

    assert (bundle / "verz.md").is_dir()
    assert list((bundle / "verz.md").iterdir()) == []


def test_fehlende_datei_ist_neutral(bundle):
    with pytest.raises(FileNotFoundError) as fehler:
        anfuegen("aufgaben/gibt-es-nicht.md", "Nachtrag.", "2026-11-14")

    assert str(fehler.value) == okf_bundle.MELDUNG_NICHT_GEFUNDEN
    assert str(bundle) not in str(fehler.value)
