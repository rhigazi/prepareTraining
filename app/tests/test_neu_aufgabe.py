"""TDD-Tests für ``neu_aufgabe`` (Aufgabe A4)."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import neu_aufgabe
import okf_bundle
import slug
import status
from okf_bundle import EingabeFehler

GUELTIG = {
    "titel": "A4: Neue Aufgabe",
    "ziel": "Aufgaben-Datei aus Formulardaten anlegen.",
    "akzeptanz": ["Erste Bedingung", "Zweite Bedingung", "Dritte Bedingung"],
    "prioritaet": "hoch",
    "user_story": "/projekt/user-stories/us-3.md",
}

UEBERSCHRIFTEN = [
    "# Ziel",
    "# Akzeptanzkriterien",
    "# Testfälle (TDD)",
    "# Kontext",
    "# Betroffene Dateien",
    "# Ergebnisse",
]


def _dateien(bundle: Path) -> list[str]:
    return sorted(p.name for p in (bundle / "aufgaben").glob("*.md"))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _abschnitt(body: str, ueberschrift: str, naechste: str | None) -> list[str]:
    """Zeilen eines Body-Abschnitts (ohne Überschrift), bis zur nächsten Überschrift."""
    zeilen = body.splitlines()
    start = zeilen.index(ueberschrift) + 1
    ende = zeilen.index(naechste) if naechste else len(zeilen)
    return [zeile for zeile in zeilen[start:ende] if zeile.strip()]


# --- T1 Happy Path --------------------------------------------------------


def test_t1_happy_path(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG))

    assert pfad == "aufgaben/a4-neue-aufgabe.md"
    assert (bundle / pfad).is_file()


# --- T2 Frontmatter -------------------------------------------------------


def test_t2_frontmatter(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG))

    frontmatter, _body = okf_bundle.lesen(pfad)

    assert frontmatter["type"] == "Task"
    assert frontmatter["title"] == GUELTIG["titel"]
    assert frontmatter["task_status"] == "offen"
    assert frontmatter["phase"] == "2 Planung"
    assert frontmatter["priority"] == GUELTIG["prioritaet"]
    assert frontmatter["assigned_to"] == "coder"
    assert frontmatter["owner"] == "ai"
    # A28: neue Aufgaben sind nicht freigegeben (Menschen-Recht).
    assert frontmatter["freigabe"] is False


def test_t2_description_wird_aus_dem_ziel_abgeleitet(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG))

    frontmatter, _body = okf_bundle.lesen(pfad)

    assert frontmatter["description"] == GUELTIG["ziel"]


# --- T3 user_story-Verweis ------------------------------------------------


def test_t3_user_story_verweis(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG))
    frontmatter, _body = okf_bundle.lesen(pfad)

    assert frontmatter["user_story"] == "/projekt/user-stories/us-3.md"


def test_t3_ohne_user_story_kein_feld(bundle):
    daten = dict(GUELTIG)
    del daten["user_story"]

    pfad = neu_aufgabe.anlegen(daten)
    frontmatter, _body = okf_bundle.lesen(pfad)

    assert "user_story" not in frontmatter


def test_t3_welle_wird_uebernommen(bundle):
    daten = dict(GUELTIG, welle="/wellen/w1.md")

    pfad = neu_aufgabe.anlegen(daten)
    frontmatter, body = okf_bundle.lesen(pfad)

    assert frontmatter["welle"] == "/wellen/w1.md"
    assert "/wellen/w1.md" in body


# --- A33-T10/T11: Wellen-Linktext (A13-3) ---------------------------------


def _welle_schreiben(bundle: Path, name: str, inhalt: str) -> str:
    pfad = f"wellen/{name}"
    (bundle / pfad).write_text(inhalt, encoding="utf-8")
    return pfad


def _kontext(body: str) -> list[str]:
    return _abschnitt(body, "# Kontext", "# Betroffene Dateien")


def test_a33_t10_welle_linktext_ist_der_titel(bundle):
    _welle_schreiben(
        bundle,
        "w2.md",
        '---\ntype: Welle\ntitle: "W2"\nstatus: Offen\nowner: ai\n---\n\n# Ziel\n\nZweite Welle.\n',
    )

    pfad = neu_aufgabe.anlegen(dict(GUELTIG, welle="wellen/w2.md"))

    kontext = _kontext(okf_bundle.lesen(pfad)[1])
    assert "- Welle: [W2](wellen/w2.md)" in kontext
    # Der ``user_story``-Linktext bleibt der Dateistamm.
    assert "- User Story: [us-3](/projekt/user-stories/us-3.md)" in kontext


@pytest.mark.parametrize(
    ("name", "inhalt"),
    [
        ("w3.md", None),  # Datei fehlt
        ("w4.md", "# Nur Text\n\nkein Frontmatter\n"),
        ("w5.md", "---\ntype: Welle\ntitle: 42\n---\n\n# Ziel\n"),
        ("w6.md", "---\ntype: Welle\ntitle:\n---\n\n# Ziel\n"),
    ],
)
def test_a33_t11_fallback_linktext_bleibt_dateistamm(bundle, name, inhalt):
    if inhalt is not None:
        _welle_schreiben(bundle, name, inhalt)
    stamm = name.removesuffix(".md")

    pfad = neu_aufgabe.anlegen(dict(GUELTIG, welle=f"wellen/{name}"))

    assert (bundle / pfad).is_file()
    assert f"- Welle: [{stamm}](wellen/{name})" in _kontext(okf_bundle.lesen(pfad)[1])


def test_a33_t11_leere_welle_bleibt_ohne_zeile(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG, welle="   "))

    frontmatter, body = okf_bundle.lesen(pfad)
    assert "welle" not in frontmatter
    assert not any(zeile.startswith("- Welle:") for zeile in _kontext(body))


# --- T4 Body-Abschnitte ---------------------------------------------------


def test_t4_body_abschnitte(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG))
    _frontmatter, body = okf_bundle.lesen(pfad)

    ueberschriften = [zeile for zeile in body.splitlines() if zeile.startswith("# ")]
    assert ueberschriften == UEBERSCHRIFTEN


def test_t4_ziel_und_akzeptanz_im_body(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG))
    _frontmatter, body = okf_bundle.lesen(pfad)

    assert GUELTIG["ziel"] in _abschnitt(body, "# Ziel", "# Akzeptanzkriterien")


# --- T5 Akzeptanzliste ----------------------------------------------------


def test_t5_akzeptanzliste_als_aufzaehlung(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG))
    _frontmatter, body = okf_bundle.lesen(pfad)

    eintraege = _abschnitt(body, "# Akzeptanzkriterien", "# Testfälle (TDD)")
    assert eintraege == [
        "- Erste Bedingung",
        "- Zweite Bedingung",
        "- Dritte Bedingung",
    ]


# --- T6 Slug --------------------------------------------------------------


@pytest.mark.parametrize(
    ("titel", "erwarteter_slug"),
    [
        ("Übersicht: Status & owner!", "uebersicht-status-owner"),
        ("Größere Änderung", "groessere-aenderung"),
        ("../../etc/passwd", "etc-passwd"),
        ("  Doppelte   Leerzeichen  ", "doppelte-leerzeichen"),
        ("A4: Aufgabe / neu", "a4-aufgabe-neu"),
    ],
)
def test_t6_slug_normalisierung(titel, erwarteter_slug):
    assert slug.slug_aus_titel(titel) == erwarteter_slug


def test_t6_slug_maximal_60_zeichen():
    slug_wert = slug.slug_aus_titel("Wort " * 40)

    assert len(slug_wert) <= 60
    assert not slug_wert.endswith("-")


# --- A33-T15: gemeinsame Slug-Regel (A5-B4) -------------------------------

SLUG_MATRIX = [
    ("Übersicht: Status & owner!", "uebersicht-status-owner"),
    ("Größen-Übersicht", "groessen-uebersicht"),
    ("Straße & Maß", "strasse-mass"),
    ("Café déjà vu", "cafe-deja-vu"),
    # Exotische Zeichen: die Variante aus ``neu_aufgabe`` ist maßgeblich.
    ("Smørrebrød", "sm-rrebr-d"),
    ("../../etc/passwd", "etc-passwd"),
    ("  Doppelte   Leerzeichen  ", "doppelte-leerzeichen"),
    ("A" * 80, "a" * 60),
    ("!!!", ""),
    ("", ""),
]


@pytest.mark.parametrize(("titel", "erwartet"), SLUG_MATRIX)
def test_a33_t15_slug_matrix(titel, erwartet):
    assert slug.slug_aus_titel(titel) == erwartet


@pytest.mark.parametrize(("titel", "erwartet"), SLUG_MATRIX)
def test_a33_t15_anlegen_nutzt_gemeinsamen_slug(bundle, titel, erwartet):
    if not erwartet:
        vorher = _dateien(bundle)

        with pytest.raises(EingabeFehler):
            neu_aufgabe.anlegen(dict(GUELTIG, titel=titel))

        assert _dateien(bundle) == vorher
        return

    pfad = neu_aufgabe.anlegen(dict(GUELTIG, titel=titel))

    assert pfad == f"aufgaben/{erwartet}.md"


# --- T7 Kollision ---------------------------------------------------------


def test_t7_kollision_bekommt_suffix_2(bundle):
    erster = neu_aufgabe.anlegen(dict(GUELTIG))
    inhalt_erster = (bundle / erster).read_text(encoding="utf-8")

    zweiter = neu_aufgabe.anlegen(dict(GUELTIG))

    assert erster == "aufgaben/a4-neue-aufgabe.md"
    assert zweiter == "aufgaben/a4-neue-aufgabe-2.md"
    assert _hash((bundle / erster).read_text(encoding="utf-8")) == _hash(inhalt_erster)


def test_t7_kollision_zaehlt_hoch(bundle):
    pfaede = [neu_aufgabe.anlegen(dict(GUELTIG)) for _ in range(3)]

    assert pfaede == [
        "aufgaben/a4-neue-aufgabe.md",
        "aufgaben/a4-neue-aufgabe-2.md",
        "aufgaben/a4-neue-aufgabe-3.md",
    ]
    assert len(_dateien(bundle)) == 5  # a1.md + index.md + drei neue


def test_t7_reservierte_index_wird_nicht_ueberschrieben(bundle):
    index = bundle / "aufgaben/index.md"
    vorher = index.read_bytes()

    pfad = neu_aufgabe.anlegen(dict(GUELTIG, titel="Index"))

    assert pfad == "aufgaben/index-2.md"
    assert index.read_bytes() == vorher


def test_t7_kandidatenlimit_erschoepft(bundle, monkeypatch):
    monkeypatch.setattr(neu_aufgabe, "MAX_KANDIDATEN", 2)
    for name in ("a4-neue-aufgabe.md", "a4-neue-aufgabe-2.md"):
        (bundle / "aufgaben" / name).write_text("---\ntype: Task\n---\n", encoding="utf-8")
    vorher = _dateien(bundle)

    with pytest.raises(EingabeFehler):
        neu_aufgabe.anlegen(dict(GUELTIG))

    assert _dateien(bundle) == vorher


def test_t7_letzter_kandidat_wird_noch_genutzt(bundle, monkeypatch):
    """``MAX_KANDIDATEN`` zählt Kandidaten inklusive des letzten Versuchs."""
    monkeypatch.setattr(neu_aufgabe, "MAX_KANDIDATEN", 3)
    for name in ("a4-neue-aufgabe.md", "a4-neue-aufgabe-2.md"):
        (bundle / "aufgaben" / name).write_text("---\ntype: Task\n---\n", encoding="utf-8")

    pfad = neu_aufgabe.anlegen(dict(GUELTIG))

    assert pfad == "aufgaben/a4-neue-aufgabe-3.md"


# --- T8 Ungültige Eingaben ------------------------------------------------


@pytest.mark.parametrize(
    "daten",
    [
        {},
        {"titel": "", "ziel": "Ziel", "akzeptanz": ["A"], "prioritaet": "hoch"},
        {"titel": "   ", "ziel": "Ziel", "akzeptanz": ["A"], "prioritaet": "hoch"},
        {"titel": "Titel", "ziel": "", "akzeptanz": ["A"], "prioritaet": "hoch"},
        {"titel": "Titel", "ziel": "Ziel", "akzeptanz": [], "prioritaet": "hoch"},
        {"titel": "Titel", "ziel": "Ziel", "akzeptanz": ["  "], "prioritaet": "hoch"},
        {"titel": "Titel", "ziel": "Ziel", "akzeptanz": "A", "prioritaet": "hoch"},
        {"titel": "Titel", "ziel": "Ziel", "akzeptanz": ["A"], "prioritaet": "dringend"},
        {"titel": "Titel", "ziel": "Ziel", "akzeptanz": ["A"], "prioritaet": ""},
    ],
)
def test_t8_ungueltige_eingaben(bundle, daten):
    vorher = _dateien(bundle)

    with pytest.raises(EingabeFehler):
        neu_aufgabe.anlegen(daten)

    assert _dateien(bundle) == vorher


def test_t8_leerer_titel_ohne_slug(bundle):
    daten = dict(GUELTIG, titel="!!!")
    vorher = _dateien(bundle)

    with pytest.raises(EingabeFehler):
        neu_aufgabe.anlegen(daten)

    assert _dateien(bundle) == vorher


# --- T9 Pfad-Traversal ----------------------------------------------------


def test_t9_pfad_traversal_bleibt_im_aufgaben_ordner(bundle):
    daten = dict(GUELTIG, titel="../../etc/passwd")

    pfad = neu_aufgabe.anlegen(daten)

    assert pfad == "aufgaben/etc-passwd.md"
    assert (bundle / pfad).is_file()
    assert not Path(pfad).is_absolute()
    assert not (bundle.parent / "etc").exists()


# --- T10 Zeilenende & OKF-Konformität ------------------------------------


def test_t10_zeilenende_und_beginn(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG))
    roh = (bundle / pfad).read_bytes()

    assert roh.startswith(b"---\n")
    assert roh.endswith(b"\n")
    assert not roh.endswith(b"\n\n")
    assert b"\r\n" not in roh


# --- Integration: sofort als Offen/ai sichtbar ----------------------------


def test_integration_sofort_offen_und_ai(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG))
    frontmatter, _body = okf_bundle.lesen(pfad)

    assert status.ui_status(frontmatter) == ("Offen", None)
    assert status.owner_default(frontmatter) == "ai"


def test_neue_datei_ist_im_scan_enthalten(bundle):
    pfad = neu_aufgabe.anlegen(dict(GUELTIG))

    assert pfad in okf_bundle.scan()
