"""TDD-Tests für ``meta`` (Aufgabe A6): owner setzen und Status mit Rechteprüfung."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import meta
import okf_bundle
import status
from okf_bundle import BundlePfadFehler, FrontmatterFehler

AUFGABE = "aufgaben/a1.md"
WELLE = "wellen/w1.md"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _datei_hash(bundle, pfad: str) -> str:
    return _hash((bundle / pfad).read_text(encoding="utf-8"))


def _body(pfad: str) -> str:
    return okf_bundle.lesen(pfad)[1]


# --- owner ---------------------------------------------------------------


def test_t1_owner_ai(bundle):
    body_vorher = _body(AUFGABE)

    ergebnis = meta.setzen(AUFGABE, owner="ai")

    frontmatter, body_nachher = okf_bundle.lesen(AUFGABE)
    assert ergebnis["owner"] == "ai"
    assert frontmatter["owner"] == "ai"
    assert _hash(body_nachher) == _hash(body_vorher)


def test_t2_owner_mensch(bundle):
    """A33-T14 (A6-2): ``owner`` wechseln ändert den Body nicht und keine Keys."""
    body_vorher = _body(WELLE)
    frontmatter_vorher = okf_bundle.lesen(WELLE)[0]

    meta.setzen(WELLE, owner="mensch")

    frontmatter, body_nachher = okf_bundle.lesen(WELLE)
    assert frontmatter["owner"] == "mensch"
    assert frontmatter["type"] == "Welle"
    assert frontmatter["status"] == "Offen"
    assert set(frontmatter) == set(frontmatter_vorher)
    assert _hash(body_nachher) == _hash(body_vorher)


# --- Rechteprüfung -------------------------------------------------------


@pytest.mark.parametrize("owner", ["KI", "Mensch", "manager", "", " mensch", True])
def test_t3_owner_ungueltig(bundle, owner):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    with pytest.raises(meta.RechteFehler):
        meta.setzen(AUFGABE, owner=owner)

    assert _datei_hash(bundle, AUFGABE) == hash_vorher


def test_t7_pipeline_status_verboten(bundle):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    for verboten in ("In Arbeit", "Testing", "Dokumentation", "Offen"):
        with pytest.raises(meta.RechteFehler):
            meta.setzen(AUFGABE, status=verboten)

    assert _datei_hash(bundle, AUFGABE) == hash_vorher


@pytest.mark.parametrize(
    "pfad",
    ["index.md", "log.md", "features.md", "aufgaben/index.md"],
)
def test_t8_reservierte_dateien(bundle, pfad):
    hash_vorher = _datei_hash(bundle, pfad)

    with pytest.raises(meta.RechteFehler):
        meta.setzen(pfad, owner="mensch", status="Klarung")

    assert _datei_hash(bundle, pfad) == hash_vorher


def test_t9_fehlendes_frontmatter(bundle):
    volltext = "# Nur Text\n\nkein Frontmatter\n"
    (bundle / "ohne.md").write_text(volltext, encoding="utf-8")

    with pytest.raises(FrontmatterFehler):
        meta.setzen("ohne.md", owner="ai")

    assert (bundle / "ohne.md").read_text(encoding="utf-8") == volltext


def test_kombiniert_verboten_kein_schreibvorgang(bundle, monkeypatch):
    """Ungültiger ``status`` bricht ab, auch wenn ``owner`` gültig wäre."""
    aufrufe = []
    monkeypatch.setattr(okf_bundle, "set_meta", lambda *a, **k: aufrufe.append(a))
    hash_vorher = _datei_hash(bundle, AUFGABE)

    with pytest.raises(meta.RechteFehler):
        meta.setzen(AUFGABE, owner="mensch", status="In Arbeit")

    assert aufrufe == []
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


# --- Status --------------------------------------------------------------


def test_t4_status_klarung_aufgabe(bundle):
    body_vorher = _body(AUFGABE)

    meta.setzen(AUFGABE, status="Klarung")

    frontmatter, body_nachher = okf_bundle.lesen(AUFGABE)
    assert frontmatter["task_status"] == "in Klärung"
    assert "status" not in frontmatter
    assert _hash(body_nachher) == _hash(body_vorher)


def test_t5_status_geschlossen_aufgabe(bundle):
    meta.setzen(AUFGABE, status="Geschlossen")

    frontmatter, _ = okf_bundle.lesen(AUFGABE)
    assert frontmatter["task_status"] == "abgeschlossen"
    assert "status" not in frontmatter


def test_t6_status_klarung_welle(bundle):
    body_vorher = _body(WELLE)

    meta.setzen(WELLE, status="Klarung")

    frontmatter, body_nachher = okf_bundle.lesen(WELLE)
    assert frontmatter["status"] == "Klarung"
    assert "task_status" not in frontmatter
    assert _hash(body_nachher) == _hash(body_vorher)


def test_task_status_ziele_passen_zum_status_mapping():
    """``TASK_STATUS_ZIELE`` deckt genau ``STATUS_WERTE`` ab und passt zum ``status``-Mapping.

    Geprüft werden die Konstanten gegeneinander statt einer hartcodierten Liste:
    ein neuer Wert in ``STATUS_WERTE`` ohne passendes Ziel in
    ``TASK_STATUS_ZIELE`` lässt diesen Test fehlschlagen.
    """
    assert set(meta.TASK_STATUS_ZIELE) == set(meta.STATUS_WERTE)

    for ui_status in meta.STATUS_WERTE:
        ziel = meta.TASK_STATUS_ZIELE[ui_status]
        assert ziel in status.TASK_STATUS_MAPPING
        assert status.TASK_STATUS_MAPPING[ziel][0] == ui_status


# --- Atomarität, Zeitstempel, Pfadschutz ---------------------------------


def test_t10_kombiniert_ein_schreibvorgang(bundle, monkeypatch):
    aufrufe = []
    original = okf_bundle.set_meta

    def zaehlend(*args, **kwargs):
        aufrufe.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(okf_bundle, "set_meta", zaehlend)
    body_vorher = _body(AUFGABE)

    ergebnis = meta.setzen(AUFGABE, owner="mensch", status="Klarung")

    assert len(aufrufe) == 1
    assert aufrufe[0][0][1] == {"owner": "mensch", "task_status": "in Klärung"}
    assert ergebnis["owner"] == "mensch"
    assert ergebnis["task_status"] == "in Klärung"

    frontmatter, body_nachher = okf_bundle.lesen(AUFGABE)
    assert frontmatter["owner"] == "mensch"
    assert frontmatter["task_status"] == "in Klärung"
    assert frontmatter["title"] == "A1: Mini-Aufgabe"
    assert _hash(body_nachher) == _hash(body_vorher)


def test_t11_zeitstempel_aktualisiert(bundle):
    vorher = (bundle / AUFGABE).stat().st_mtime_ns

    meta.setzen(AUFGABE, owner="mensch")

    assert (bundle / AUFGABE).stat().st_mtime_ns >= vorher


@pytest.mark.parametrize(
    "pfad",
    ["../fremd.md", "../../etc/passwd", "/etc/passwd", "aufgaben/../x.md", "a/%2e%2e/b.md"],
)
def test_t12_pfad_ausserhalb(bundle, pfad):
    with pytest.raises(BundlePfadFehler):
        meta.setzen(pfad, owner="ai")


# --- Randfälle -----------------------------------------------------------


def test_ohne_aenderung_kein_schreibvorgang(bundle, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(okf_bundle, "set_meta", lambda *a, **k: aufrufe.append(a))
    hash_vorher = _datei_hash(bundle, AUFGABE)

    ergebnis = meta.setzen(AUFGABE)

    assert aufrufe == []
    assert ergebnis["task_status"] == "offen"
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


def test_owner_wird_nicht_doppelt_geschrieben(bundle):
    meta.setzen(WELLE, owner="mensch")
    meta.setzen(WELLE, owner="ai")

    zeilen = (bundle / WELLE).read_text(encoding="utf-8").splitlines()
    assert zeilen.count("owner: ai") == 1
    assert okf_bundle.lesen(WELLE)[0]["owner"] == "ai"


def test_fehlende_datei(bundle):
    """Nicht existierende Datei: ``FileNotFoundError`` statt Anlegen (A9 mappt auf 404/400)."""
    assert not (bundle / "gibtsnicht.md").exists()

    with pytest.raises(FileNotFoundError):
        meta.setzen("gibtsnicht.md", owner="ai")

    assert not (bundle / "gibtsnicht.md").exists()


def test_crlf_body_bleibt_bytegleich(bundle):
    """Body-Byte-Identität gilt auch für Dateien mit Windows-Zeilenenden."""
    volltext = (
        "---\r\n"
        "type: Task\r\n"
        'title: "CRLF-Aufgabe"\r\n'
        "task_status: offen\r\n"
        "---\r\n"
        "\r\n"
        "# Ziel\r\n"
        "\r\n"
        "Body mit CRLF.\r\n"
    )
    pfad = "aufgaben/crlf.md"
    (bundle / pfad).write_bytes(volltext.encode("utf-8"))
    body_vorher = okf_bundle.lesen(pfad)[1].encode("utf-8")
    assert b"\r\n" in body_vorher
    assert b"\n" not in body_vorher.replace(b"\r\n", b"")

    meta.setzen(pfad, owner="mensch", status="Klarung")

    roh_nachher = (bundle / pfad).read_bytes()
    frontmatter, body_nachher = okf_bundle.lesen(pfad)
    assert frontmatter["owner"] == "mensch"
    assert frontmatter["task_status"] == "in Klärung"
    assert frontmatter["title"] == "CRLF-Aufgabe"
    assert body_nachher.encode("utf-8") == body_vorher
    assert roh_nachher.endswith(b"---\r\n" + body_vorher)
    assert b"\n" not in roh_nachher.replace(b"\r\n", b"")


# --- Review A9: Schreibziel-Validierung (W1) -------------------------------


def test_nicht_md_ziel_ist_abgelehnt(bundle):
    pfad = bundle / "notiz.txt"
    pfad.write_text("---\ntype: Note\ntitle: Notiz\n---\n\nNur Text.\n", encoding="utf-8")
    vorher = pfad.read_bytes()

    with pytest.raises(BundlePfadFehler):
        meta.setzen("notiz.txt", owner="ai")

    assert pfad.read_bytes() == vorher


def test_verzeichnis_als_ziel_ist_abgelehnt(bundle):
    (bundle / "verz.md").mkdir()

    with pytest.raises(BundlePfadFehler):
        meta.setzen("verz.md", owner="ai")

    assert (bundle / "verz.md").is_dir()
    assert list((bundle / "verz.md").iterdir()) == []


# --- A27: Wellen-Zuordnung (modulnah, ohne Flask) --------------------------


def _aufgabe_mit_welle(bundle, welle: str = WELLE) -> None:
    (bundle / AUFGABE).write_text(
        "---\n"
        "type: Task\n"
        'title: "A1: Mini-Aufgabe"\n'
        "task_status: offen\n"
        f"welle: {welle}\n"
        "---\n\n"
        "# Ziel\n\nFixture-Ziel für Tests.\n",
        encoding="utf-8",
    )


def test_t17_welle_ist_keine_rechteklasse():
    assert "welle" not in meta.OWNER_WERTE
    assert "welle" not in meta.STATUS_WERTE


@pytest.mark.parametrize(
    "welle",
    ["wellen/gibtsnicht.md", "aufgaben/a1.md", "features.md", "../wellen/w1.md", 42, True],
)
def test_t17_ungueltige_welle_ist_eingabefehler(bundle, welle):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    with pytest.raises(okf_bundle.EingabeFehler) as fehler:
        meta.setzen(AUFGABE, welle=welle)

    assert not isinstance(fehler.value, meta.RechteFehler)
    assert str(fehler.value).strip()
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


def test_t17_welle_entfernen_und_nicht_uebergeben(bundle):
    _aufgabe_mit_welle(bundle)

    frontmatter = meta.setzen(AUFGABE, welle=None)
    assert "welle" not in frontmatter

    _aufgabe_mit_welle(bundle)
    # Ohne ``welle``-Argument bleibt das Feld unberührt.
    frontmatter = meta.setzen(AUFGABE, owner="mensch")
    assert frontmatter["welle"] == WELLE


def test_t17_welle_entfernen_ohne_feld_ist_kein_schreibvorgang(bundle, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(okf_bundle, "set_meta", lambda *a, **k: aufrufe.append((a, k)))
    hash_vorher = _datei_hash(bundle, AUFGABE)

    frontmatter = meta.setzen(AUFGABE, welle=None)

    assert aufrufe == []
    assert "welle" not in frontmatter
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


def test_t17_welle_setzen_schreibt_getrimmt(bundle):
    frontmatter = meta.setzen(AUFGABE, welle=f"  {WELLE}  ")

    assert frontmatter["welle"] == WELLE
    assert okf_bundle.lesen(AUFGABE)[0]["welle"] == WELLE


# --- A28: ``freigabe`` ist ein Menschen-Recht -----------------------------


@pytest.mark.parametrize("wert", [True, False, None, "true"])
def test_a28_freigabe_ueber_meta_ist_verboten(bundle, monkeypatch, wert):
    aufrufe = []
    monkeypatch.setattr(okf_bundle, "set_meta", lambda *a, **k: aufrufe.append((a, k)))
    hash_vorher = _datei_hash(bundle, AUFGABE)

    with pytest.raises(meta.RechteFehler):
        meta.setzen(AUFGABE, freigabe=wert)

    assert aufrufe == []
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


# --- A27-K1: kodierte Wellen-Pfade ----------------------------------------


@pytest.mark.parametrize("welle", ["wellen/%77%31.md", "wellen/w%31.md"])
def test_a27_k1_kodierter_wellenpfad_ist_eingabefehler(bundle, welle):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    with pytest.raises(okf_bundle.EingabeFehler) as fehler:
        meta.setzen(AUFGABE, welle=welle)

    assert not isinstance(fehler.value, meta.RechteFehler)
    assert str(fehler.value).strip()
    assert _datei_hash(bundle, AUFGABE) == hash_vorher
    assert "welle" not in okf_bundle.lesen(AUFGABE)[0]
    assert "welle" not in (bundle / AUFGABE).read_text(encoding="utf-8")


def test_a27_k1_normaler_pfad_bleibt_erlaubt(bundle):
    frontmatter = meta.setzen(AUFGABE, welle=WELLE)

    assert frontmatter["welle"] == WELLE
    assert okf_bundle.lesen(AUFGABE)[0]["welle"] == WELLE


def test_a27_k1_welle_null_entfernt_weiterhin(bundle):
    _aufgabe_mit_welle(bundle)

    frontmatter = meta.setzen(AUFGABE, welle=None)

    assert "welle" not in frontmatter
    assert "welle" not in (bundle / AUFGABE).read_text(encoding="utf-8")
