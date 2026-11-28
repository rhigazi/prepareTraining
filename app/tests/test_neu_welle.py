"""TDD-Tests für ``neu_welle`` (Aufgabe A5)."""

import hashlib
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nachtrag  # noqa: E402
import neu_aufgabe  # noqa: E402
import neu_welle  # noqa: E402
import okf_bundle  # noqa: E402
import slug  # noqa: E402
import status  # noqa: E402

GUELTIG = {
    "titel": "Wave 1 — MVP",
    "ziel": "Erste Welle: MVP des Projekt-Managers.",
    "status": "Offen",
    "owner": "ai",
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _wellen_dateien(bundle: Path) -> list[str]:
    return sorted(p.name for p in (bundle / "wellen").glob("*.md"))


# --- T1 Happy Path --------------------------------------------------------


def test_t1_happy_path(bundle):
    pfad = neu_welle.anlegen(GUELTIG)

    assert pfad == "wellen/wave-1-mvp.md"
    assert (bundle / pfad).is_file()


# --- T2 Frontmatter -------------------------------------------------------


def test_t2_frontmatter(bundle):
    pfad = neu_welle.anlegen(GUELTIG)

    frontmatter, _body = okf_bundle.lesen(pfad)

    assert frontmatter["type"] == "Welle"
    assert frontmatter["title"] == "Wave 1 — MVP"
    assert frontmatter["status"] == "Offen"
    assert frontmatter["owner"] == "ai"
    # A29: Wellen sind standardmäßig nicht freigegeben (Menschen-Recht).
    assert frontmatter["freigabe"] is False


@pytest.mark.parametrize("status_wert", status.UI_STATUS_WERTE)
def test_t2b_alle_ui_status_erlaubt(bundle, status_wert):
    pfad = neu_welle.anlegen({**GUELTIG, "titel": f"Welle {status_wert}", "status": status_wert})

    assert okf_bundle.lesen(pfad)[0]["status"] == status_wert


# --- T3 Ordner-Erstanlage -------------------------------------------------


def test_t3_ordner_erstanlage(bundle):
    shutil.rmtree(bundle / "wellen")

    pfad = neu_welle.anlegen(GUELTIG)

    assert (bundle / "wellen").is_dir()
    assert (bundle / pfad).is_file()


# --- T4 Ungültiger Status -------------------------------------------------


@pytest.mark.parametrize("status_wert", ["erledigt", "offen", "InBearbeitung", "In Arbeit.", "", None])
def test_t4_ungueltiger_status(bundle, status_wert):
    vorher = _wellen_dateien(bundle)

    with pytest.raises(neu_welle.EingabeFehler):
        neu_welle.anlegen({**GUELTIG, "status": status_wert})

    assert _wellen_dateien(bundle) == vorher


def test_t4b_status_wird_getrimmt(bundle):
    pfad = neu_welle.anlegen({**GUELTIG, "status": " In Arbeit "})

    assert okf_bundle.lesen(pfad)[0]["status"] == "In Arbeit"


# --- T5 Ungültiger owner --------------------------------------------------


@pytest.mark.parametrize("owner", ["bot", "AI", "Mensch", "", None, 42])
def test_t5_ungueltiger_owner(bundle, owner):
    vorher = _wellen_dateien(bundle)

    with pytest.raises(neu_welle.EingabeFehler):
        neu_welle.anlegen({**GUELTIG, "owner": owner})

    assert _wellen_dateien(bundle) == vorher


@pytest.mark.parametrize("owner", ["mensch", "ai"])
def test_t5b_gueltige_owner(bundle, owner):
    pfad = neu_welle.anlegen({**GUELTIG, "titel": f"Welle {owner}", "owner": owner})

    assert okf_bundle.lesen(pfad)[0]["owner"] == owner


# --- T6 Leerer Titel ------------------------------------------------------


@pytest.mark.parametrize("titel", ["", "   ", None, 42])
def test_t6_leerer_titel(bundle, titel):
    vorher = _wellen_dateien(bundle)

    with pytest.raises(neu_welle.EingabeFehler):
        neu_welle.anlegen({**GUELTIG, "titel": titel})

    assert _wellen_dateien(bundle) == vorher


# --- T6b Leeres Ziel ------------------------------------------------------


@pytest.mark.parametrize("ziel", ["", "   ", None, 42])
def test_t6b_leeres_ziel(bundle, ziel):
    vorher = _wellen_dateien(bundle)

    with pytest.raises(neu_welle.EingabeFehler):
        neu_welle.anlegen({**GUELTIG, "ziel": ziel})

    assert _wellen_dateien(bundle) == vorher


# --- T7 Kollision ---------------------------------------------------------


def test_t7_kollision(bundle):
    erst = neu_welle.anlegen(GUELTIG)
    roh_erst = (bundle / erst).read_text(encoding="utf-8")

    zweit = neu_welle.anlegen({**GUELTIG, "titel": "Wave 1 — MVP"})
    dritt = neu_welle.anlegen({**GUELTIG, "titel": "Wave 1 — MVP"})

    assert erst == "wellen/wave-1-mvp.md"
    assert zweit == "wellen/wave-1-mvp-2.md"
    assert dritt == "wellen/wave-1-mvp-3.md"
    assert (bundle / erst).read_text(encoding="utf-8") == roh_erst


# --- T7b Reservierte Dateinamen --------------------------------------------


@pytest.mark.parametrize("titel", ["Log", "Features", "Index"])
def test_t7_reservierte_kuerzel_bekommen_suffix(bundle, titel):
    vorher = _wellen_dateien(bundle)

    pfad = neu_welle.anlegen({**GUELTIG, "titel": titel})

    assert pfad == f"wellen/{titel.lower()}-2.md"
    assert (bundle / pfad).is_file()
    assert _wellen_dateien(bundle) == sorted(vorher + [Path(pfad).name])


def test_t7_reservierte_existierende_datei_bleibt_unveraendert(bundle):
    reserviert = bundle / "wellen/features.md"
    reserviert.write_text("---\ntype: Meta\n---\n\n# Features\n", encoding="utf-8")
    vorher = reserviert.read_bytes()

    pfad = neu_welle.anlegen({**GUELTIG, "titel": "Features"})

    assert pfad == "wellen/features-2.md"
    assert reserviert.read_bytes() == vorher


def test_t7_reserviert_naechster_freier_suffix(bundle):
    (bundle / "wellen/log-2.md").write_text("---\n---\n", encoding="utf-8")

    pfad = neu_welle.anlegen({**GUELTIG, "titel": "Log"})

    assert pfad == "wellen/log-3.md"


def test_t7_kandidatenlimit_erschoepft(bundle, monkeypatch):
    monkeypatch.setattr(neu_welle, "MAX_KANDIDATEN", 2)
    (bundle / "wellen/log-2.md").write_text("---\n---\n", encoding="utf-8")
    vorher = _wellen_dateien(bundle)

    with pytest.raises(neu_welle.EingabeFehler):
        neu_welle.anlegen({**GUELTIG, "titel": "Log"})

    assert _wellen_dateien(bundle) == vorher


def test_t7_letzter_kandidat_wird_noch_genutzt(bundle, monkeypatch):
    """``MAX_KANDIDATEN`` zählt Kandidaten inklusive des letzten Versuchs."""
    monkeypatch.setattr(neu_welle, "MAX_KANDIDATEN", 3)
    (bundle / "wellen/log-2.md").write_text("---\n---\n", encoding="utf-8")

    pfad = neu_welle.anlegen({**GUELTIG, "titel": "Log"})

    assert pfad == "wellen/log-3.md"


# --- T8 Body --------------------------------------------------------------


def test_t8_body(bundle):
    pfad = neu_welle.anlegen(GUELTIG)

    _frontmatter, body = okf_bundle.lesen(pfad)

    assert "# Ziel" in body
    assert GUELTIG["ziel"] in body
    assert "# Aufgaben" in body
    assert body.index("# Ziel") < body.index("# Aufgaben")


def test_t8b_aufgabenliste_startet_leer(bundle):
    pfad = neu_welle.anlegen(GUELTIG)

    body = okf_bundle.lesen(pfad)[1]
    aufgaben = body[body.index("# Aufgaben") :]

    assert [zeile for zeile in aufgaben.splitlines() if zeile.startswith("- ")] == []


def test_t8c_okf_format(bundle):
    pfad = neu_welle.anlegen(GUELTIG)

    roh = (bundle / pfad).read_text(encoding="utf-8")

    assert roh.startswith("---\n")
    assert roh.endswith("\n")
    assert not roh.endswith("\n\n")


# --- T9 Kürzel (Slug-Regel R2) --------------------------------------------


@pytest.mark.parametrize(
    ("titel", "erwartet"),
    [
        ("Wave 1 — MVP", "wave-1-mvp"),
        ("Übersicht: Status & owner!", "uebersicht-status-owner"),
        ("Größen-Übersicht", "groessen-uebersicht"),
        ("  Wave   2  ", "wave-2"),
        ("!!!", "welle"),
        ("../../etc/passwd", "etc-passwd"),
        ("A" * 80, "a" * 60),
    ],
)
def test_t9_kuerzel(bundle, titel, erwartet):
    pfad = neu_welle.anlegen({**GUELTIG, "titel": titel})

    assert pfad == f"wellen/{erwartet}.md"
    assert (bundle / pfad).is_file()


def test_t9b_kuerzel_max_60_zeichen(bundle):
    pfad = neu_welle.anlegen({**GUELTIG, "titel": "Irgendein sehr langer Wellentitel der einfach nicht enden will und weiterläuft"})

    kuerzel = Path(pfad).stem
    assert len(kuerzel) <= 60
    assert not kuerzel.endswith("-")


# --- A33-T15: gemeinsame Slug-Regel (A5-B4) -------------------------------


@pytest.mark.parametrize(
    ("titel", "erwartet"),
    [
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
    ],
)
def test_a33_t15_kuerzel_ist_slug_mit_fallback(titel, erwartet):
    assert slug.slug_aus_titel(titel) == erwartet
    assert neu_welle.kuerzel(titel) == (erwartet or neu_welle.FALLBACK_KUERZEL)


@pytest.mark.parametrize("titel", [None, 42, ["Welle"]])
def test_a33_t15_nicht_text_faellt_auf_welle(titel):
    assert neu_welle.kuerzel(titel) == neu_welle.FALLBACK_KUERZEL


@pytest.mark.parametrize(
    ("titel", "erwartet"),
    [
        ("Smørrebrød", "sm-rrebr-d"),
        ("Café déjà vu", "cafe-deja-vu"),
        ("Straße & Maß", "strasse-mass"),
    ],
)
def test_a33_t15_anlegen_nutzt_gemeinsamen_slug(bundle, titel, erwartet):
    pfad = neu_welle.anlegen({**GUELTIG, "titel": titel})

    assert pfad == f"wellen/{erwartet}.md"
    assert (bundle / pfad).is_file()


def test_a33_t15_beide_aufrufer_nutzen_dieselbe_funktion(bundle, monkeypatch):
    """Beide Aufrufer delegieren an ``slug.slug_aus_titel`` (keine Duplikate)."""
    monkeypatch.setattr(slug, "slug_aus_titel", lambda titel: "gemeinsam")
    aufgabe = {
        "titel": "Irgendein Titel",
        "ziel": "Ziel",
        "akzeptanz": ["Kriterium"],
        "prioritaet": "hoch",
    }

    assert neu_aufgabe.anlegen(aufgabe) == "aufgaben/gemeinsam.md"
    assert Path(neu_welle.anlegen(GUELTIG)).stem == "gemeinsam"


# --- description (A33-T8/T9, A5-B3) --------------------------------------


@pytest.mark.parametrize(
    ("ziel", "erwartet"),
    [
        ("Erste Zeile\nzweite Zeile mit Details", "Erste Zeile"),
        ("Übersicht: Größen & Maßnahmen", "Übersicht: Größen & Maßnahmen"),
        ("\n\n  Erste echte Zeile  \nRest des Ziels", "Erste echte Zeile"),
    ],
)
def test_a33_t8_description_aus_erster_ziel_zeile(bundle, ziel, erwartet):
    pfad = neu_welle.anlegen({**GUELTIG, "ziel": ziel})

    frontmatter, body = okf_bundle.lesen(pfad)

    assert frontmatter["description"] == erwartet
    assert frontmatter["title"] == GUELTIG["titel"]
    assert frontmatter["status"] == GUELTIG["status"]
    assert frontmatter["owner"] == GUELTIG["owner"]
    assert "# Ziel" in body
    assert "# Aufgaben" in body
    assert body.index("# Ziel") < body.index("# Aufgaben")


def test_a33_t9_description_kuerzung(bundle):
    ziel = "W" * 200

    pfad = neu_welle.anlegen({**GUELTIG, "ziel": ziel})

    description = okf_bundle.lesen(pfad)[0]["description"]

    assert len(description) <= neu_welle.MAX_KURZBESCHREIBUNG
    assert len(description) == neu_welle.MAX_KURZBESCHREIBUNG
    assert description == "W" * 159 + "…"


@pytest.mark.parametrize("ziel", ["", "   ", None, 42])
def test_a33_t9_leeres_ziel_bleibt_eingabefehler(bundle, ziel):
    vorher = _wellen_dateien(bundle)

    with pytest.raises(neu_welle.EingabeFehler):
        neu_welle.anlegen({**GUELTIG, "ziel": ziel, "description": "Eigene Kurzfassung"})

    assert _wellen_dateien(bundle) == vorher


def test_a33_t9_explizite_description_hat_vorrang(bundle):
    pfad = neu_welle.anlegen({**GUELTIG, "description": "  Eigene Kurzfassung  "})

    frontmatter, _body = okf_bundle.lesen(pfad)

    assert frontmatter["description"] == "Eigene Kurzfassung"


@pytest.mark.parametrize("description", ["", "   ", None])
def test_a33_t9_leere_description_faellt_auf_ziel_zurueck(bundle, description):
    pfad = neu_welle.anlegen({**GUELTIG, "description": description})

    assert okf_bundle.lesen(pfad)[0]["description"] == GUELTIG["ziel"]


@pytest.mark.parametrize("description", [42, ["Zeile"], {"a": 1}, True])
def test_a33_t9_description_typfehler(bundle, description):
    vorher = _wellen_dateien(bundle)

    with pytest.raises(neu_welle.EingabeFehler):
        neu_welle.anlegen({**GUELTIG, "description": description})

    assert _wellen_dateien(bundle) == vorher


def test_a33_t9_description_einzeilig_und_keine_frontmatter_injektion(bundle):
    pfad = neu_welle.anlegen(
        {**GUELTIG, "description": "---\ntype: Hack\nstatus: Geschlossen"}
    )

    frontmatter, _body = okf_bundle.lesen(pfad)
    roh = (bundle / pfad).read_text(encoding="utf-8")

    assert frontmatter["type"] == "Welle"
    assert frontmatter["status"] == GUELTIG["status"]
    assert "\n" not in frontmatter["description"]
    assert frontmatter["description"] == "--- type: Hack status: Geschlossen"
    assert roh.count("type: Welle") == 1


# --- Rahmenbedingungen ----------------------------------------------------


def test_unbekannte_felder_ignoriert(bundle):
    pfad = neu_welle.anlegen({**GUELTIG, "unbekannt": "egal"})

    assert okf_bundle.lesen(pfad)[0]["type"] == "Welle"


def test_zieldatei_bleibt_in_wellen(bundle):
    pfad = neu_welle.anlegen({**GUELTIG, "titel": "../../etc/passwd"})

    assert pfad.startswith("wellen/")


def test_bestehende_welle_unveraendert(bundle):
    vorher = _hash((bundle / "wellen/w1.md").read_text(encoding="utf-8"))

    neu_welle.anlegen(GUELTIG)

    assert _hash((bundle / "wellen/w1.md").read_text(encoding="utf-8")) == vorher


def test_kein_flask_import():
    quelle = Path(neu_welle.__file__).read_text(encoding="utf-8").lower()

    assert "flask" not in quelle


def test_eingabefehler_ist_zentral_definiert():
    assert neu_welle.EingabeFehler is okf_bundle.EingabeFehler
    assert neu_aufgabe.EingabeFehler is okf_bundle.EingabeFehler
    assert nachtrag.EingabeFehler is okf_bundle.EingabeFehler
