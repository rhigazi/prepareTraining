"""TDD-Tests für die Kennungsgrammatik (A34, Paket 1).

Top-Level: ``A12`` / ``a12-slug.md``; Unter-Aufgabe: ``A34.001`` /
``a34.001-slug.md``. Die Grammatik ist die einzige Quelle für ``overview``
(A28-Signale) und ``neu_aufgabe`` (Vergabe). Alle Läufe arbeiten gegen das
``bundle``-Fixture (``tmp_path``).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kennung
from okf_bundle import EingabeFehler

ELTERN = "aufgaben/a34-eltern.md"


def _aufgabe(bundle, pfad: str, titel: str, parent: str | None = None) -> Path:
    ziel = bundle / pfad
    ziel.parent.mkdir(parents=True, exist_ok=True)
    zeilen = [
        "---",
        "type: Task",
        f"title: {titel!r}",
        "task_status: offen",
        "owner: ai",
    ]
    if parent:
        zeilen.append(f"parent: {parent!r}")
    ziel.write_text("\n".join(zeilen) + "\n---\n\n# Ziel\n\nFixture.\n", encoding="utf-8")
    return ziel


# --- T1: Titel gültig -----------------------------------------------------


def test_t1_titel_gueltig():
    unter = kennung.zerlege_titel("A34.001: Erste Unter-Aufgabe")
    assert unter.nummer == 34
    assert unter.unter == 1
    assert unter.kennung == "A34.001"

    assert kennung.zerlege_titel("A34.001: X").kennung == "A34.001"
    # Nur Kennung (kein Titeltext) ist formatgültig.
    assert kennung.zerlege_titel("A34.001: ").kennung == "A34.001"

    top = kennung.zerlege_titel("A34: X")
    assert top.nummer == 34
    assert top.unter is None
    assert top.kennung == "A34"


# --- T2: Titel ungültig ---------------------------------------------------


@pytest.mark.parametrize(
    "wert",
    [
        "A34.000: X",
        "A34.1: X",
        "A34.0001: X",
        "A034.001: X",
        "A34.001.002: X",
        "A34.001:X",
        "a34.001: X",
        "A34 .001: X",
        "A: X",
        "",
        None,
    ],
)
def test_t2_titel_ungueltig(wert):
    assert kennung.zerlege_titel(wert).kennung is None


# --- T3: Dateiname --------------------------------------------------------


@pytest.mark.parametrize(
    "name,nummer,unter,kennungswert",
    [
        ("a34.001-x.md", 34, 1, "A34.001"),
        ("a34.001.md", 34, 1, "A34.001"),
        ("a34.001-x-2.md", 34, 1, "A34.001"),
        # Bindestrich gehört zum Slug: gültige Top-Level-Aufgabe A34.
        ("a34-001-x.md", 34, None, "A34"),
        ("a34.001-x-2", 34, 1, "A34.001"),
    ],
)
def test_t3_dateiname_gueltig(name, nummer, unter, kennungswert):
    ergebnis = kennung.zerlege_dateiname(name)
    assert ergebnis.nummer == nummer
    assert ergebnis.unter == unter
    assert ergebnis.kennung == kennungswert


@pytest.mark.parametrize(
    "name",
    [
        "a34.0001-x.md",
        "a34.1-x.md",
        "a34.001.002-x.md",
        "a034.001-x.md",
        "x.md",
        "",
    ],
)
def test_t3_dateiname_ungueltig(name):
    assert kennung.zerlege_dateiname(name).kennung is None


# --- T4: Konsistenz-Matrix ------------------------------------------------


@pytest.mark.parametrize(
    "titel,dateiname,erwartet",
    [
        ("A34.001: X", "a34.001-x.md", True),
        ("A34.001: X", "a34.001.md", True),
        ("A34.001: X", "a34-001-x.md", False),
        ("A34: X", "a34.001-x.md", False),
        ("A34.001: X", "a34.002-x.md", False),
        ("A34.001: X", "a35.001-x.md", False),
        ("A1: X", "a1.md", True),
        ("A12: X", "a12-x.md", True),
        ("A12: X", "x.md", False),
    ],
)
def test_t4_ist_zugewiesen(titel, dateiname, erwartet):
    assert kennung.ist_zugewiesen(titel, dateiname) is erwartet


# --- T5: Kennungs-Ausgaben ------------------------------------------------


def test_t5_kennung_ausgaben():
    assert kennung.kennung_aus_titel("A34.001: X") == "A34.001"
    assert kennung.kennung_aus_titel("A34: X") == "A34"
    assert kennung.kennung_aus_titel("Neu") is None

    assert kennung.kennung_aus_dateiname("a34.001-x.md") == "A34.001"
    assert kennung.kennung_aus_dateiname("a34-001-x.md") == "A34"

    assert kennung.eltern_kennung("aufgaben/a34-x.md", {"title": "A34: X"}) == "A34"
    assert kennung.eltern_kennung(ELTERN, {"title": "A34: X"}) == "A34"
    # Unter-Aufgabe, fehlende oder inkonsistente Kennung sind keine Eltern.
    assert kennung.eltern_kennung("aufgaben/a34.001-x.md", {"title": "A34.001: X"}) is None
    assert kennung.eltern_kennung(ELTERN, {"title": "Neue Aufgabe"}) is None
    assert kennung.eltern_kennung(ELTERN, {"title": "A35: X"}) is None


# --- T6: Kleinste freie Unter-Kennung -------------------------------------


def test_t6a_naechste_unterkennung_fuellt_luecken(bundle):
    _aufgabe(bundle, ELTERN, "A34: Eltern")
    assert kennung.naechste_unterkennung(ELTERN) == "A34.001"

    _aufgabe(bundle, "aufgaben/a34.001-a.md", "A34.001: A", parent=ELTERN)
    assert kennung.naechste_unterkennung(ELTERN) == "A34.002"

    _aufgabe(bundle, "aufgaben/a34.002-b.md", "A34.002: B", parent=ELTERN)
    assert kennung.naechste_unterkennung(ELTERN) == "A34.003"

    # Titel-Kennung ohne ``parent`` zählt ebenfalls als belegt.
    _aufgabe(bundle, "aufgaben/x.md", "A34.004: D")
    assert kennung.naechste_unterkennung(ELTERN) == "A34.003"

    # Fremde Eltern und Top-Level-Aufgaben mit Bindestrich-Slug zählen nicht.
    _aufgabe(bundle, "aufgaben/a35.001-c.md", "A35.001: C")
    _aufgabe(bundle, "aufgaben/a34-001-x.md", "A34: Top")
    assert kennung.naechste_unterkennung(ELTERN) == "A34.003"


def test_t6b_doppelte_unterkennung_zaehlt_einmal(bundle):
    _aufgabe(bundle, ELTERN, "A34: Eltern")
    _aufgabe(bundle, "aufgaben/a34.001-a.md", "A34.001: A")
    _aufgabe(bundle, "aufgaben/a34.001-b.md", "A34.001: B")

    assert kennung.naechste_unterkennung(ELTERN) == "A34.002"


# --- T7: Nummernraum erschöpft --------------------------------------------


def test_t7_nummernraum_erschoepft(bundle):
    _aufgabe(bundle, ELTERN, "A34: Eltern")
    for nummer in range(1, 1000):
        _aufgabe(
            bundle,
            f"aufgaben/a34.{nummer:03d}-k.md",
            f"A34.{nummer:03d}: K",
            parent=ELTERN,
        )

    with pytest.raises(EingabeFehler):
        kennung.naechste_unterkennung(ELTERN)


# --- T8: naechste_kennung bleibt top-level-only ---------------------------


def test_t8_naechste_kennung_top_level_only(bundle):
    _aufgabe(bundle, "aufgaben/a34-x.md", "A34: X")
    _aufgabe(bundle, "aufgaben/a34.001-y.md", "A34.001: Y")
    _aufgabe(bundle, "aufgaben/a35.002-z.md", "A35.002: Z")

    ergebnis = kennung.naechste_kennung()
    assert ergebnis == "A35"
    # Unter-Nummern erzeugen nie eine Unter-Kennung als Vorschlag.
    assert "." not in ergebnis

    for name in ("a1.md", "a34-x.md", "a34.001-y.md", "a35.002-z.md"):
        (bundle / "aufgaben" / name).unlink()
    assert kennung.naechste_kennung() == "A1"
