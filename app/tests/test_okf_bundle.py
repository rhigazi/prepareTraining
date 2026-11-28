"""TDD-Tests für ``okf_bundle`` (Aufgabe A1)."""

import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import okf_bundle
from okf_bundle import BundlePfadFehler, FrontmatterFehler, ReservierteDateiFehler


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ohne_zeile(text: str, prefix: str) -> list[str]:
    return [zeile for zeile in text.splitlines() if not zeile.startswith(prefix)]


# --- Pfadschutz -----------------------------------------------------------


def test_t1_pfad_im_bundle(bundle):
    pfad = okf_bundle.resolve_path("aufgaben/a1.md")

    assert isinstance(pfad, Path)
    assert pfad.is_absolute()
    assert pfad.resolve() == (bundle / "aufgaben/a1.md").resolve()


def test_t2_ausbruch_punkt_punkt(bundle):
    with pytest.raises(BundlePfadFehler):
        okf_bundle.resolve_path("../../etc/passwd")


def test_t3_absoluter_pfad(bundle):
    with pytest.raises(BundlePfadFehler):
        okf_bundle.resolve_path("/etc/passwd")


@pytest.mark.parametrize(
    "pfad",
    ["aufgaben/../../x.md", "a/%2e%2e/b.md", "../x.md", "aufgaben/../x.md"],
)
def test_t4_verschleierter_ausbruch(bundle, pfad):
    with pytest.raises(BundlePfadFehler):
        okf_bundle.resolve_path(pfad)


def test_t5_symlink_ausbruch(bundle, tmp_path):
    aussen = tmp_path / "aussen.md"
    aussen.write_text("---\ntype: Fremd\n---\n", encoding="utf-8")
    (bundle / "link.md").symlink_to(aussen)

    with pytest.raises(BundlePfadFehler):
        okf_bundle.resolve_path("link.md")


# --- Frontmatter lesen ----------------------------------------------------


def test_t6_frontmatter_lesen(bundle):
    frontmatter, body = okf_bundle.lesen("aufgaben/a1.md")

    assert frontmatter["type"] == "Task"
    assert frontmatter["title"] == "A1: Mini-Aufgabe"
    assert body.lstrip("\n").startswith("# Ziel")
    assert "---" not in body


def test_t7_frontmatter_fehlt_strikt(bundle):
    (bundle / "ohne.md").write_text("# Nur Text\n\nkein Frontmatter\n", encoding="utf-8")

    with pytest.raises(FrontmatterFehler):
        okf_bundle.lesen("ohne.md")


def test_t8_frontmatter_fehlt_tolerant(bundle):
    volltext = "# Nur Text\n\nkein Frontmatter\n"
    (bundle / "ohne.md").write_text(volltext, encoding="utf-8")

    frontmatter, body = okf_bundle.lesen_tolerant("ohne.md")

    assert frontmatter == {}
    assert body == volltext


# --- Schreiben ------------------------------------------------------------


def test_t9_frontmatter_erhalt(bundle):
    pfad = bundle / "aufgaben/a1.md"
    roh_vorher = pfad.read_text(encoding="utf-8")
    vorher, body_vorher = okf_bundle.lesen("aufgaben/a1.md")

    okf_bundle.set_meta("aufgaben/a1.md", {"owner": "ai"})

    nachher, body_nachher = okf_bundle.lesen("aufgaben/a1.md")
    for schluessel in ("type", "title", "user_story", "task_status"):
        assert nachher[schluessel] == vorher[schluessel]
    assert nachher["owner"] == "ai"
    assert _hash(body_nachher) == _hash(body_vorher)

    roh_nachher = pfad.read_text(encoding="utf-8")
    assert _ohne_zeile(roh_nachher, "owner:") == _ohne_zeile(roh_vorher, "owner:")


def test_t9b_set_meta_ist_idempotent(bundle):
    okf_bundle.set_meta("aufgaben/a1.md", {"owner": "mensch"})
    okf_bundle.set_meta("aufgaben/a1.md", {"owner": "ai"})

    zeilen = (bundle / "aufgaben/a1.md").read_text(encoding="utf-8").splitlines()
    assert zeilen.count("owner: ai") == 1
    assert okf_bundle.lesen("aufgaben/a1.md")[0]["owner"] == "ai"


def test_t10_atomaritaet(bundle, monkeypatch):
    pfad = bundle / "aufgaben/a1.md"
    vorher = pfad.read_bytes()

    def kaputt(*args, **kwargs):
        raise OSError("simulierter Schreibfehler")

    monkeypatch.setattr(os, "replace", kaputt)
    with pytest.raises(OSError):
        okf_bundle.set_meta("aufgaben/a1.md", {"owner": "ai"})

    assert pfad.read_bytes() == vorher
    assert list((bundle / "aufgaben").glob(".tmp-*")) == []


# --- Schreib-Guard für reservierte Dateien --------------------------------


@pytest.mark.parametrize(
    "pfad",
    ["index.md", "log.md", "features.md", "aufgaben/index.md"],
)
def test_guard_schreiben_weist_reservierte_ziele_ab(bundle, pfad):
    vorher = (bundle / pfad).read_bytes()

    with pytest.raises(ReservierteDateiFehler):
        okf_bundle.schreiben(pfad, "---\ntype: Fremd\n---\n\n# Ersetzt\n")

    assert (bundle / pfad).read_bytes() == vorher


@pytest.mark.parametrize(
    "pfad",
    ["index.md", "log.md", "features.md", "aufgaben/index.md"],
)
def test_guard_set_meta_weist_reservierte_ziele_ab(bundle, pfad):
    vorher = (bundle / pfad).read_bytes()

    with pytest.raises(ReservierteDateiFehler):
        okf_bundle.set_meta(pfad, {"owner": "ai"})

    assert (bundle / pfad).read_bytes() == vorher


def test_guard_greift_vor_jedem_zugriff(bundle):
    with pytest.raises(ReservierteDateiFehler):
        okf_bundle.schreiben("neu/index.md", "---\ntype: Index\n---\n")

    assert not (bundle / "neu").exists()


def test_guard_greift_auch_ueber_symlink_auf_reserviert(bundle):
    (bundle / "eintrag.md").symlink_to(bundle / "log.md")
    vorher = (bundle / "log.md").read_bytes()

    with pytest.raises(ReservierteDateiFehler):
        okf_bundle.schreiben("eintrag.md", "---\ntype: Fremd\n---\n")

    assert (bundle / "log.md").read_bytes() == vorher


def test_guard_prueft_auch_den_angefragten_namen(bundle):
    (bundle / "log.md").unlink()
    (bundle / "log.md").symlink_to(bundle / "aufgaben/a1.md")
    vorher = (bundle / "aufgaben/a1.md").read_bytes()

    with pytest.raises(ReservierteDateiFehler):
        okf_bundle.set_meta("log.md", {"owner": "ai"})

    assert (bundle / "aufgaben/a1.md").read_bytes() == vorher


# --- Review-Nachbesserungen -----------------------------------------------


def test_set_meta_erhaelt_crlf(bundle):
    pfad = bundle / "aufgaben/crlf.md"
    pfad.write_bytes(
        "---\r\ntype: Task\r\ntitle: CRLF\r\n---\r\n\r\n# Ziel\r\n\r\nBody.\r\n".encode("utf-8")
    )
    _, body_vorher = okf_bundle.lesen("aufgaben/crlf.md")

    okf_bundle.set_meta("aufgaben/crlf.md", {"owner": "ai"})

    roh = pfad.read_bytes().decode("utf-8")
    _, body_nachher = okf_bundle.lesen("aufgaben/crlf.md")
    assert _hash(body_nachher) == _hash(body_vorher)
    assert "\n" not in roh.replace("\r\n", "")


def test_set_meta_weist_ungueltiges_yaml_ab(bundle):
    pfad = bundle / "aufgaben/kaputt.md"
    pfad.write_text("---\ntype: Task\nbroken: [unclosed\n---\n\n# Ziel\n", encoding="utf-8")
    vorher = pfad.read_bytes()

    with pytest.raises(FrontmatterFehler):
        okf_bundle.set_meta("aufgaben/kaputt.md", {"owner": "ai"})

    assert pfad.read_bytes() == vorher


@pytest.mark.parametrize("schluessel", ["owner", "task_status", "x.y-z_1"])
def test_set_meta_akzeptiert_gueltige_schluessel(bundle, schluessel):
    frontmatter = okf_bundle.set_meta("aufgaben/a1.md", {schluessel: "wert"})

    assert frontmatter[schluessel] == "wert"


@pytest.mark.parametrize("schluessel", ["", "a:b", "böse", "a b", ".*"])
def test_set_meta_weist_ungueltige_schluessel_ab(bundle, schluessel):
    pfad = bundle / "aufgaben/a1.md"
    vorher = pfad.read_bytes()

    with pytest.raises(FrontmatterFehler):
        okf_bundle.set_meta("aufgaben/a1.md", {schluessel: "wert"})

    assert pfad.read_bytes() == vorher


def test_eingabefehler_ist_zentral_definiert():
    assert issubclass(okf_bundle.EingabeFehler, ValueError)
    assert okf_bundle.EingabeFehler.__doc__


# --- Scan und Reservate ---------------------------------------------------


def test_t11_scan(bundle):
    assert (bundle / "index.md").is_file()
    assert (bundle / "log.md").is_file()
    assert (bundle / "features.md").is_file()

    assert okf_bundle.scan() == ["aufgaben/a1.md", "wellen/w1.md"]


def test_scan_ignoriert_verzeichnisse_und_reste(bundle):
    (bundle / "leer.md").mkdir()
    (bundle / ".tmp-rest.md").write_text("---\ntype: Rest\n---\n", encoding="utf-8")

    assert okf_bundle.scan() == ["aufgaben/a1.md", "wellen/w1.md"]


@pytest.mark.parametrize(
    ("pfad", "erwartet"),
    [
        ("index.md", True),
        ("log.md", True),
        ("features.md", True),
        ("aufgaben/index.md", True),
        ("aufgaben/a1.md", False),
        ("wellen/w1.md", False),
    ],
)
def test_t12_reserviert(bundle, pfad, erwartet):
    assert okf_bundle.ist_reserviert(pfad) is erwartet


# --- Rahmenbedingung ------------------------------------------------------


def test_kein_flask_import():
    quelle = Path(okf_bundle.__file__).read_text(encoding="utf-8").lower()

    assert "flask" not in quelle


# --- Review A9/A7: neutrale Fehlermeldungen (K1) ---------------------------


def test_lesen_fehlende_datei_meldung_ist_neutral(bundle):
    with pytest.raises(FileNotFoundError) as fehler:
        okf_bundle.lesen("aufgaben/gibt-es-nicht.md")

    meldung = str(fehler.value)
    assert meldung == okf_bundle.MELDUNG_NICHT_GEFUNDEN
    assert str(bundle) not in meldung
    assert "No such file or directory" not in meldung
    assert "Errno" not in meldung


def test_lesen_tolerant_fehlende_datei_meldung_ist_neutral(bundle):
    with pytest.raises(FileNotFoundError) as fehler:
        okf_bundle.lesen_tolerant("aufgaben/gibt-es-nicht.md")

    assert str(fehler.value) == okf_bundle.MELDUNG_NICHT_GEFUNDEN
    assert str(bundle) not in str(fehler.value)


# --- Review A9: Schreibziel-Validierung (W1) -------------------------------


def test_schreiben_nicht_md_ist_abgelehnt(bundle):
    with pytest.raises(BundlePfadFehler):
        okf_bundle.schreiben("notiz.txt", "---\ntype: Note\n---\n\nText.\n")

    assert not (bundle / "notiz.txt").exists()


def test_schreiben_auf_verzeichnis_ist_abgelehnt(bundle):
    (bundle / "verz.md").mkdir()

    with pytest.raises(BundlePfadFehler):
        okf_bundle.schreiben("verz.md", "---\ntype: Note\n---\n")

    assert (bundle / "verz.md").is_dir()
    assert list((bundle / "verz.md").iterdir()) == []


def test_set_meta_nicht_md_ist_abgelehnt(bundle):
    (bundle / "notiz.txt").write_text("---\ntype: Note\n---\n\nText.\n", encoding="utf-8")
    vorher = (bundle / "notiz.txt").read_bytes()

    with pytest.raises(BundlePfadFehler):
        okf_bundle.set_meta("notiz.txt", {"owner": "ai"})

    assert (bundle / "notiz.txt").read_bytes() == vorher


def test_pruefe_zieldatei_verlangt_bestehende_md_datei(bundle):
    (bundle / "verz.md").mkdir()
    (bundle / "notiz.txt").write_text("---\ntype: Note\n---\n", encoding="utf-8")

    assert okf_bundle.pruefe_zieldatei("aufgaben/a1.md") == okf_bundle.resolve_path("aufgaben/a1.md")
    with pytest.raises(FileNotFoundError):
        okf_bundle.pruefe_zieldatei("aufgaben/gibt-es-nicht.md")
    with pytest.raises(BundlePfadFehler):
        okf_bundle.pruefe_zieldatei("verz.md")
    with pytest.raises(BundlePfadFehler):
        okf_bundle.pruefe_zieldatei("notiz.txt")


# --- Review A1: mehrzeilige Frontmatter-Werte mit Leerzeilen ---------------


def test_set_meta_ersetzt_mehrzeiligen_wert_mit_leerzeile(bundle):
    pfad = bundle / "aufgaben/mehrzeilig.md"
    pfad.write_text(
        "---\n"
        "type: Task\n"
        "description: |\n"
        "  Erster Absatz.\n"
        "\n"
        "  Zweiter Absatz.\n"
        "task_status: offen\n"
        "---\n\n# Ziel\n",
        encoding="utf-8",
    )

    frontmatter = okf_bundle.set_meta("aufgaben/mehrzeilig.md", {"description": "Kurz"})

    assert frontmatter["description"] == "Kurz"
    assert frontmatter["task_status"] == "offen"
    assert "Zweiter Absatz" not in pfad.read_text(encoding="utf-8")


def test_set_meta_ersetzt_blockliste_mit_leerzeile(bundle):
    pfad = bundle / "aufgaben/liste.md"
    pfad.write_text(
        "---\n"
        "type: Task\n"
        "akzeptanz:\n"
        "- Kriterium eins.\n"
        "\n"
        "- Kriterium zwei.\n"
        "task_status: offen\n"
        "---\n\n# Ziel\n",
        encoding="utf-8",
    )

    frontmatter = okf_bundle.set_meta("aufgaben/liste.md", {"akzeptanz": ["Nur noch eins."]})

    assert frontmatter["akzeptanz"] == ["Nur noch eins."]
    assert frontmatter["task_status"] == "offen"
    assert "Kriterium zwei" not in pfad.read_text(encoding="utf-8")


def test_set_meta_erhaelt_leerzeilen_vor_folgeschluessel(bundle):
    """Leerzeilen zwischen Wert und nächstem Key gehören nicht zum Wertblock."""
    pfad = bundle / "aufgaben/abstand.md"
    pfad.write_text(
        "---\n"
        "type: Task\n"
        "description: |\n"
        "  Nur ein Absatz.\n"
        "\n"
        "task_status: offen\n"
        "---\n\n# Ziel\n",
        encoding="utf-8",
    )

    frontmatter = okf_bundle.set_meta("aufgaben/abstand.md", {"description": "Kurz"})

    assert frontmatter["description"] == "Kurz"
    assert frontmatter["task_status"] == "offen"
    assert "description: Kurz\n\ntask_status: offen" in pfad.read_text(encoding="utf-8")


def test_lesen_tolerant_ungueltiges_yaml_liefert_body(bundle):
    pfad = bundle / "aufgaben/kaputt.md"
    pfad.write_text("---\ntype: Task\nbroken: [unclosed\n---\n\n# Ziel\n", encoding="utf-8")

    frontmatter, body = okf_bundle.lesen_tolerant("aufgaben/kaputt.md")

    assert frontmatter == {}
    assert body == "\n# Ziel\n"
    assert "broken" not in body


# --- A27: Frontmatter-Schlüssel gezielt entfernen --------------------------


def _mit_welle() -> str:
    return (
        "---\n"
        "type: Task\n"
        'title: "A1: Mini-Aufgabe"\n'
        "task_status: offen\n"
        "welle: wellen/w1.md\n"
        "---\n\n"
        "# Ziel\n\n"
        "Body bleibt.\n"
    )


def test_set_meta_entfernen_loescht_schluessel_und_erhaelt_body(bundle):
    pfad = bundle / "aufgaben/a1.md"
    pfad.write_text(_mit_welle(), encoding="utf-8")
    body_vorher = okf_bundle.lesen("aufgaben/a1.md")[1]

    frontmatter = okf_bundle.set_meta("aufgaben/a1.md", {}, entfernen=("welle",))

    assert "welle" not in frontmatter
    assert frontmatter["title"] == "A1: Mini-Aufgabe"
    assert frontmatter["task_status"] == "offen"
    roh = pfad.read_text(encoding="utf-8")
    assert "welle" not in roh
    assert _hash(okf_bundle.lesen("aufgaben/a1.md")[1]) == _hash(body_vorher)


def test_set_meta_entfernen_fehlender_schluessel_ist_no_op(bundle):
    pfad = bundle / "aufgaben/a1.md"
    vorher = pfad.read_bytes()

    frontmatter = okf_bundle.set_meta("aufgaben/a1.md", {}, entfernen=("welle",))

    assert "welle" not in frontmatter
    assert pfad.read_bytes() == vorher


def test_set_meta_entfernen_und_setzen_in_einem_vorgang(bundle):
    pfad = bundle / "aufgaben/a1.md"
    pfad.write_text(_mit_welle(), encoding="utf-8")
    body_vorher = okf_bundle.lesen("aufgaben/a1.md")[1]

    frontmatter = okf_bundle.set_meta(
        "aufgaben/a1.md", {"owner": "mensch"}, entfernen=("welle",)
    )

    assert "welle" not in frontmatter
    assert frontmatter["owner"] == "mensch"
    assert _hash(okf_bundle.lesen("aufgaben/a1.md")[1]) == _hash(body_vorher)
    assert list((bundle / "aufgaben").glob(".tmp-*")) == []


def test_set_meta_entfernen_erhaelt_crlf(bundle):
    volltext = (
        "---\r\n"
        "type: Task\r\n"
        'title: "CRLF-Aufgabe"\r\n'
        "welle: wellen/w1.md\r\n"
        "---\r\n\r\n"
        "# Ziel\r\n\r\n"
        "Body mit CRLF.\r\n"
    )
    pfad = bundle / "aufgaben/crlf-welle.md"
    pfad.write_bytes(volltext.encode("utf-8"))
    body_vorher = okf_bundle.lesen("aufgaben/crlf-welle.md")[1]

    okf_bundle.set_meta("aufgaben/crlf-welle.md", {}, entfernen=("welle",))

    roh = (bundle / "aufgaben/crlf-welle.md").read_bytes()
    assert b"welle" not in roh
    assert b"\n" not in roh.replace(b"\r\n", b"")
    assert okf_bundle.lesen("aufgaben/crlf-welle.md")[1] == body_vorher


def test_set_meta_entfernen_weist_ungueltigen_schluessel_ab(bundle):
    pfad = bundle / "aufgaben/a1.md"
    vorher = pfad.read_bytes()

    with pytest.raises(FrontmatterFehler):
        okf_bundle.set_meta("aufgaben/a1.md", {}, entfernen=("kein schlüssel",))

    assert pfad.read_bytes() == vorher


def test_set_meta_entfernen_default_ist_unveraendert(bundle):
    """Ohne ``entfernen`` bleibt das A1-Verhalten (Signatur additiv erweitert)."""
    okf_bundle.set_meta("aufgaben/a1.md", {"owner": "ai"})

    frontmatter, _ = okf_bundle.lesen("aufgaben/a1.md")
    assert frontmatter["owner"] == "ai"
    assert frontmatter["title"] == "A1: Mini-Aufgabe"
