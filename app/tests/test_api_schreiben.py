"""TDD-Tests für die Schreib-API ``POST /api/nachtrag|task|welle|meta`` (Aufgabe A9)."""

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import okf_bundle
import server

AUFGABE = "aufgaben/a1.md"
WELLE = "wellen/w1.md"

ENDPUNKTE = ("/api/nachtrag", "/api/task", "/api/welle", "/api/meta", "/api/freigabe")
RESERVIERTE = ("index.md", "log.md", "features.md", "aufgaben/index.md")
TRAVERSAL = (
    "../fremd.md",
    "../../etc/passwd",
    "/etc/passwd",
    "aufgaben/../../etc/passwd",
    "a/%2e%2e/b.md",
)


@pytest.fixture()
def client(bundle):
    return server.create_app(bundle).test_client()


def _aufgabe_daten(**abweichungen) -> dict:
    daten = {
        "titel": "A99: Neue Aufgabe",
        "ziel": "Ziel der neuen Aufgabe.",
        "akzeptanz": ["Erstes Kriterium.", "Zweites Kriterium."],
        "prioritaet": "hoch",
    }
    daten.update(abweichungen)
    return daten


def _welle_daten(**abweichungen) -> dict:
    daten = {
        "titel": "Welle 2: Neu",
        "ziel": "Ziel der neuen Welle.",
        "status": "Offen",
        "owner": "ai",
    }
    daten.update(abweichungen)
    return daten


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lies(bundle, pfad: str) -> str:
    with open(bundle / pfad, encoding="utf-8", newline="") as datei:
        return datei.read()


def _datei_hash(bundle, pfad: str) -> str:
    return _hash(_lies(bundle, pfad))


def _bestand(bundle) -> list[str]:
    """Alle Dateien und Verzeichnisse im Bundle (Teilzustand wäre hier sichtbar)."""
    return sorted(pfad.relative_to(bundle).as_posix() for pfad in bundle.rglob("*"))


def _aussen(bundle) -> list[str]:
    """Alles neben dem Bundle-Verzeichnis (dort darf nie etwas entstehen)."""
    return sorted(pfad.name for pfad in bundle.parent.iterdir() if pfad.name != bundle.name)


# --- T1/T2: Nachtrag ------------------------------------------------------


def test_t1_nachtrag_anfuegen(client, bundle):
    antwort = client.post("/api/nachtrag", json={"path": AUFGABE, "text": "Bitte präzisieren."})

    assert antwort.status_code == 200
    assert antwort.mimetype == "application/json"
    daten = antwort.get_json()
    assert daten["path"] == AUFGABE
    assert "Bitte präzisieren." in daten["markdown"]
    assert daten["frontmatter"]["type"] == "Task"
    letzter = daten["nachtraege"][-1]
    assert letzter["autor"] == "Mensch"
    assert letzter["text"] == "Bitte präzisieren."
    assert letzter["datum"] == datetime.now(timezone.utc).date().isoformat()

    inhalt = _lies(bundle, AUFGABE)
    assert inhalt.startswith("---\ntype: Task")
    assert "> **Nachtrag (Mensch, " in inhalt
    assert "Bitte präzisieren." in inhalt


@pytest.mark.parametrize("text", [None, "", "   ", "\n\t\n"])
def test_t2_nachtrag_leer_ist_400(client, bundle, text):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/nachtrag", json={"path": AUFGABE, "text": text})

    assert antwort.status_code == 400
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"]
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


# --- T3/T4: Aufgabe ------------------------------------------------------


def test_t3_aufgabe_anlegen(client):
    antwort = client.post("/api/task", json=_aufgabe_daten())

    assert antwort.status_code == 200
    assert antwort.mimetype == "application/json"
    pfad = antwort.get_json()["path"]
    assert pfad == "aufgaben/a99-neue-aufgabe.md"

    eintraege = {eintrag["path"]: eintrag for eintrag in client.get("/api/overview").get_json()}
    assert eintraege[pfad]["typ"] == "Task"
    assert eintraege[pfad]["status"] == "Offen"
    assert eintraege[pfad]["owner"] == "ai"


@pytest.mark.parametrize("feld", ["titel", "ziel", "akzeptanz", "prioritaet"])
def test_t4_aufgabe_unvollstaendig_ist_400(client, bundle, feld):
    daten = _aufgabe_daten()
    del daten[feld]
    bestand_vorher = _bestand(bundle)

    antwort = client.post("/api/task", json=daten)

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]
    assert _bestand(bundle) == bestand_vorher


def test_t4_aufgabe_ungueltige_prioritaet_ist_400(client, bundle):
    bestand_vorher = _bestand(bundle)

    antwort = client.post("/api/task", json=_aufgabe_daten(prioritaet="dringend"))

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]
    assert _bestand(bundle) == bestand_vorher


# --- T5/T6: Welle --------------------------------------------------------


def test_t5_welle_anlegen(client):
    antwort = client.post("/api/welle", json=_welle_daten())

    assert antwort.status_code == 200
    assert antwort.mimetype == "application/json"
    pfad = antwort.get_json()["path"]
    assert pfad == "wellen/welle-2-neu.md"

    pfade = [eintrag["path"] for eintrag in client.get("/api/wellen").get_json()]
    assert pfad in pfade


def test_welle_legt_wellen_ordner_bei_erstanlage(client, bundle):
    (bundle / WELLE).unlink()
    (bundle / "wellen").rmdir()

    antwort = client.post("/api/welle", json=_welle_daten())

    assert antwort.status_code == 200
    assert antwort.get_json()["path"].startswith("wellen/")
    assert (bundle / "wellen").is_dir()


@pytest.mark.parametrize("status_wert", ["In Umsetzung", "offen", "Unbekannt", "", None])
def test_t6_welle_ungueltiger_status_ist_400(client, bundle, status_wert):
    bestand_vorher = _bestand(bundle)

    antwort = client.post("/api/welle", json=_welle_daten(status=status_wert))

    assert antwort.status_code == 400
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"]
    assert _bestand(bundle) == bestand_vorher


# --- T7/T8/T9: Meta ------------------------------------------------------


@pytest.mark.parametrize("owner", ["mensch", "ai"])
def test_t7_meta_owner(client, bundle, owner):
    antwort = client.post("/api/meta", json={"path": AUFGABE, "owner": owner})

    assert antwort.status_code == 200
    assert antwort.mimetype == "application/json"
    daten = antwort.get_json()
    assert daten["path"] == AUFGABE
    assert daten["frontmatter"]["owner"] == owner
    assert f"owner: {owner}" in _lies(bundle, AUFGABE)


def test_t8_meta_erlaubter_status(client, bundle):
    antwort = client.post("/api/meta", json={"path": AUFGABE, "status": "Klarung"})

    assert antwort.status_code == 200
    assert antwort.get_json()["frontmatter"]["task_status"] == "in Klärung"
    assert "task_status: in Klärung" in _lies(bundle, AUFGABE)


@pytest.mark.parametrize("verboten", ["Testing", "In Arbeit", "Offen", "Dokumentation"])
def test_t8_meta_pipeline_status_ist_403(client, bundle, verboten):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, "status": verboten})

    assert antwort.status_code == 403
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"]
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


@pytest.mark.parametrize("pfad", RESERVIERTE)
def test_t9_meta_reserviert_ist_geschuetzt(client, bundle, pfad):
    hash_vorher = _datei_hash(bundle, pfad)

    antwort = client.post("/api/meta", json={"path": pfad, "owner": "mensch"})

    assert antwort.status_code in (400, 403)
    assert antwort.get_json()["error"]
    assert _datei_hash(bundle, pfad) == hash_vorher


@pytest.mark.parametrize("pfad", RESERVIERTE)
def test_t9_nachtrag_reserviert_ist_403(client, bundle, pfad):
    hash_vorher = _datei_hash(bundle, pfad)

    antwort = client.post("/api/nachtrag", json={"path": pfad, "text": "Eintrag der App."})

    assert antwort.status_code == 403
    assert antwort.get_json()["error"]
    assert _datei_hash(bundle, pfad) == hash_vorher


# --- T10: Pfadausbruch ---------------------------------------------------


@pytest.mark.parametrize("pfad", TRAVERSAL)
@pytest.mark.parametrize(
    ("endpunkt", "nutzlast"),
    [
        ("/api/nachtrag", {"text": "Text"}),
        ("/api/meta", {"owner": "ai"}),
    ],
)
def test_t10_traversal_ist_400(client, bundle, endpunkt, nutzlast, pfad):
    aussen_vorher = _aussen(bundle)

    antwort = client.post(endpunkt, json={"path": pfad, **nutzlast})

    assert antwort.status_code == 400
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"]
    assert "root:" not in antwort.get_data(as_text=True)
    assert _aussen(bundle) == aussen_vorher


@pytest.mark.parametrize("pfad", TRAVERSAL)
@pytest.mark.parametrize(
    ("endpunkt", "daten"),
    [
        ("/api/task", _aufgabe_daten),
        ("/api/welle", _welle_daten),
    ],
)
def test_t10_traversal_anlegen_ist_400(client, bundle, endpunkt, daten, pfad):
    bestand_vorher = _bestand(bundle)
    aussen_vorher = _aussen(bundle)

    antwort = client.post(endpunkt, json={**daten(), "path": pfad})

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]
    assert _bestand(bundle) == bestand_vorher
    assert _aussen(bundle) == aussen_vorher


# --- T11: JSON-Fehlerformat ----------------------------------------------


@pytest.mark.parametrize("endpunkt", ENDPUNKTE)
def test_t11_leerer_body_ist_json_400(client, endpunkt):
    antwort = client.post(endpunkt, json={})

    assert antwort.status_code == 400
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"].strip()


@pytest.mark.parametrize("endpunkt", ENDPUNKTE)
def test_t11_ungueltiges_json_ist_400(client, endpunkt):
    antwort = client.post(endpunkt, data="kein json", content_type="application/json")

    assert antwort.status_code == 400
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"].strip()


@pytest.mark.parametrize("endpunkt", ENDPUNKTE)
def test_t11_body_kein_objekt_ist_400(client, endpunkt):
    antwort = client.post(endpunkt, json=["keine", "objekt"])

    assert antwort.status_code == 400
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"].strip()


# --- T12: Kein Teilzustand ------------------------------------------------


@pytest.mark.parametrize(
    ("endpunkt", "daten", "code"),
    [
        ("/api/task", {"titel": "Ohne Ziel", "akzeptanz": ["Kriterium."], "prioritaet": "hoch"}, 400),
        ("/api/task", {"titel": "Ohne Akzeptanz", "ziel": "Ziel.", "prioritaet": "hoch"}, 400),
        (
            "/api/task",
            {"titel": "Falsche Priorität", "ziel": "Ziel.", "akzeptanz": ["K."], "prioritaet": "dringend"},
            400,
        ),
        ("/api/welle", {"titel": "Ohne Status", "ziel": "Ziel.", "owner": "ai"}, 400),
        ("/api/welle", {"titel": "Ohne owner", "ziel": "Ziel.", "status": "Offen"}, 400),
        ("/api/welle", {"titel": "  ", "ziel": "Ziel.", "status": "Offen", "owner": "ai"}, 400),
        ("/api/nachtrag", {"path": AUFGABE, "text": ""}, 400),
        ("/api/meta", {"path": AUFGABE, "status": "Testing"}, 403),
    ],
)
def test_t12_kein_teilzustand(client, bundle, endpunkt, daten, code):
    bestand_vorher = _bestand(bundle)
    aussen_vorher = _aussen(bundle)

    antwort = client.post(endpunkt, json=daten)

    assert antwort.status_code == code
    assert antwort.get_json()["error"]
    assert _bestand(bundle) == bestand_vorher
    assert _aussen(bundle) == aussen_vorher


def test_t12_welle_fehler_legt_keinen_ordner_an(client, bundle):
    (bundle / WELLE).unlink()
    (bundle / "wellen").rmdir()

    antwort = client.post("/api/welle", json=_welle_daten(status="In Umsetzung"))

    assert antwort.status_code == 400
    assert not (bundle / "wellen").exists()


# --- Randfälle -----------------------------------------------------------


@pytest.mark.parametrize(
    ("endpunkt", "nutzlast"),
    [
        ("/api/nachtrag", {"text": "Text"}),
        ("/api/meta", {"owner": "ai"}),
    ],
)
def test_fehlende_datei_ist_404(client, bundle, endpunkt, nutzlast):
    antwort = client.post(endpunkt, json={"path": "aufgaben/gibt-es-nicht.md", **nutzlast})

    assert antwort.status_code == 404
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"]
    assert not (bundle / "aufgaben/gibt-es-nicht.md").exists()


@pytest.mark.parametrize(
    ("endpunkt", "nutzlast"),
    [
        ("/api/nachtrag", {"text": "Text"}),
        ("/api/meta", {"owner": "ai"}),
    ],
)
def test_fehlender_path_ist_400(client, endpunkt, nutzlast):
    antwort = client.post(endpunkt, json=nutzlast)

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]


# --- K1: Keine Pfade oder OS-Details in Fehlermeldungen --------------------


@pytest.mark.parametrize(
    ("endpunkt", "nutzlast"),
    [
        ("/api/nachtrag", {"text": "Text"}),
        ("/api/meta", {"owner": "ai"}),
    ],
)
def test_k1_fehlermeldung_ohne_pfad_und_os_details(client, bundle, endpunkt, nutzlast):
    antwort = client.post(endpunkt, json={"path": "aufgaben/gibt-es-nicht.md", **nutzlast})

    assert antwort.status_code == 404
    text = antwort.get_data(as_text=True)
    assert antwort.get_json()["error"].strip()
    assert str(bundle) not in text
    assert "gibt-es-nicht" not in text
    assert "No such file or directory" not in text
    assert "Errno" not in text


# --- W1: Schreibziel wird vor dem Schreiben validiert ----------------------


NICHT_MD = "aufgaben/notiz.txt"
NICHT_MD_INHALT = "---\ntype: Note\ntitle: Notiz\n---\n\nNur Text.\n"


@pytest.mark.parametrize(
    ("endpunkt", "nutzlast"),
    [
        ("/api/nachtrag", {"text": "Nachtrag."}),
        ("/api/meta", {"owner": "ai"}),
    ],
)
def test_w1_nicht_md_ziel_wird_nicht_beschrieben(client, bundle, endpunkt, nutzlast):
    (bundle / NICHT_MD).write_text(NICHT_MD_INHALT, encoding="utf-8")
    vorher = (bundle / NICHT_MD).read_bytes()

    antwort = client.post(endpunkt, json={"path": NICHT_MD, **nutzlast})

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]
    assert (bundle / NICHT_MD).read_bytes() == vorher


@pytest.mark.parametrize("ziel", ["verz.md", "aufgaben"])
@pytest.mark.parametrize(
    ("endpunkt", "nutzlast"),
    [
        ("/api/nachtrag", {"text": "Nachtrag."}),
        ("/api/meta", {"owner": "ai"}),
    ],
)
def test_w1_verzeichnis_als_ziel_ist_400(client, bundle, endpunkt, nutzlast, ziel):
    (bundle / "verz.md").mkdir()
    bestand_vorher = _bestand(bundle)

    antwort = client.post(endpunkt, json={"path": ziel, **nutzlast})

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]
    assert _bestand(bundle) == bestand_vorher


# --- K2: /api/meta ohne setzbare Felder ist 400 ----------------------------


@pytest.mark.parametrize(
    "daten",
    [
        {},
        {"owner": None},
        {"owner": None, "status": None},
        {"unbekannt": "x", "auch_unbekannt": 1},
    ],
)
def test_k2_meta_ohne_setzbare_felder_ist_400(client, bundle, daten):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, **daten})

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


def test_k2_meta_mit_setzbarem_feld_trotz_null(client, bundle):
    antwort = client.post("/api/meta", json={"path": AUFGABE, "owner": None, "status": "Klarung"})

    assert antwort.status_code == 200
    assert antwort.get_json()["frontmatter"]["task_status"] == "in Klärung"


# --- N2: Fail-Closed-Reihenfolge (Whitelist vor Pfad-Check) ----------------


def test_n2_verbotener_status_vor_fehlender_datei_ist_403(client, bundle):
    assert not (bundle / "gibtsnicht.md").exists()

    antwort = client.post("/api/meta", json={"path": "gibtsnicht.md", "status": "Testing"})

    assert antwort.status_code == 403
    assert antwort.get_json()["error"]
    assert not (bundle / "gibtsnicht.md").exists()


# --- A27: Wellen-Zuordnung über POST /api/meta ----------------------------

WELLE_2 = "wellen/w2.md"
WELLE_2_INHALT = (
    "---\n"
    "type: Welle\n"
    'title: "Welle 2: Zweite Fixture"\n'
    "status: Offen\n"
    "owner: ai\n"
    "---\n\n"
    "# Ziel\n\nZweite Fixture-Welle.\n\n"
    "# Aufgaben\n"
)


def _welle_zwei_anlegen(bundle) -> None:
    (bundle / WELLE_2).write_text(WELLE_2_INHALT, encoding="utf-8")


def _welle_entfernen(client, pfad: str = AUFGABE):
    return client.post("/api/meta", json={"path": pfad, "welle": None})


def _body_hash(bundle, pfad: str) -> str:
    return _hash(okf_bundle.lesen(pfad)[1])


def test_t1_welle_setzen(client, bundle):
    body_vorher = _body_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": WELLE})

    assert antwort.status_code == 200
    assert antwort.mimetype == "application/json"
    daten = antwort.get_json()
    assert daten["path"] == AUFGABE
    assert daten["frontmatter"]["welle"] == WELLE
    zeilen = [zeile for zeile in _lies(bundle, AUFGABE).splitlines() if zeile.startswith("welle:")]
    assert zeilen == [f"welle: {WELLE}"]
    assert _body_hash(bundle, AUFGABE) == body_vorher


def test_t2_join_beleg_ueber_lese_api(client, bundle):
    client.post("/api/meta", json={"path": AUFGABE, "welle": WELLE})

    aufgaben = {eintrag["path"]: eintrag for eintrag in client.get("/api/aufgaben").get_json()}
    assert aufgaben[AUFGABE]["welle"] == WELLE

    uebersicht = {eintrag["path"]: eintrag for eintrag in client.get("/api/overview").get_json()}
    assert uebersicht[AUFGABE]["welle"] == WELLE


def test_t3_welle_wechseln(client, bundle):
    _welle_zwei_anlegen(bundle)
    client.post("/api/meta", json={"path": AUFGABE, "welle": WELLE})
    body_vorher = _body_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": WELLE_2})

    assert antwort.status_code == 200
    assert antwort.get_json()["frontmatter"]["welle"] == WELLE_2
    inhalt = _lies(bundle, AUFGABE)
    assert inhalt.count("\nwelle:") == 1
    assert f"welle: {WELLE_2}" in inhalt
    assert _body_hash(bundle, AUFGABE) == body_vorher


def test_t4_entfernen_mit_null(client, bundle):
    client.post("/api/meta", json={"path": AUFGABE, "welle": WELLE})
    body_vorher = _body_hash(bundle, AUFGABE)

    antwort = _welle_entfernen(client)

    assert antwort.status_code == 200
    assert "welle" not in antwort.get_json()["frontmatter"]
    assert "welle" not in _lies(bundle, AUFGABE)
    uebersicht = {eintrag["path"]: eintrag for eintrag in client.get("/api/overview").get_json()}
    assert "welle" not in uebersicht[AUFGABE]
    assert _body_hash(bundle, AUFGABE) == body_vorher


def test_t4b_entfernen_ist_idempotent(client, bundle, monkeypatch):
    aufrufe = []
    original = okf_bundle.set_meta

    def zaehlend(*args, **kwargs):
        aufrufe.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(okf_bundle, "set_meta", zaehlend)
    hash_vorher = _datei_hash(bundle, AUFGABE)
    mtime_vorher = (bundle / AUFGABE).stat().st_mtime_ns

    antwort = _welle_entfernen(client)

    assert antwort.status_code == 200
    assert aufrufe == []
    assert _datei_hash(bundle, AUFGABE) == hash_vorher
    assert (bundle / AUFGABE).stat().st_mtime_ns == mtime_vorher


@pytest.mark.parametrize("leer", ["", "   ", "\t\n"])
def test_t5_entfernen_mit_leerem_wert(client, bundle, leer):
    client.post("/api/meta", json={"path": AUFGABE, "welle": WELLE})
    body_vorher = _body_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": leer})

    assert antwort.status_code == 200
    assert "welle" not in antwort.get_json()["frontmatter"]
    assert "welle" not in _lies(bundle, AUFGABE)
    assert _body_hash(bundle, AUFGABE) == body_vorher


def test_t6_unbekannte_welle_ist_400(client, bundle):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": "wellen/gibtsnicht.md"})

    assert antwort.status_code == 400
    assert antwort.get_json()["error"].strip()
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


@pytest.mark.parametrize("welle", ["aufgaben/a1.md", "features.md", "index.md", "log.md"])
def test_t7_fremder_ordner_ist_400(client, bundle, welle):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": welle})

    assert antwort.status_code == 400
    assert antwort.get_json()["error"].strip()
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


@pytest.mark.parametrize(
    "welle",
    [
        "../wellen/w1.md",
        "wellen/../aufgaben/a1.md",
        "/etc/passwd",
        "wellen/%2e%2e/aufgaben/a1.md",
    ],
)
def test_t8_traversal_ist_400(client, bundle, welle):
    aussen_vorher = _aussen(bundle)
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": welle})

    assert antwort.status_code == 400
    assert antwort.get_json()["error"].strip()
    assert _aussen(bundle) == aussen_vorher
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


def test_t9_reserviertes_wellen_ziel_ist_400(client, bundle):
    ziel = bundle / "wellen/index.md"
    ziel.write_text("---\ntype: Welle\ntitle: Index\n---\n\n# Ziel\n", encoding="utf-8")
    vorher = ziel.read_bytes()
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": "wellen/index.md"})

    assert antwort.status_code == 400
    assert antwort.get_json()["error"].strip()
    assert ziel.read_bytes() == vorher
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


@pytest.mark.parametrize(
    "welle",
    [42, True, [], {}, "wellen/", "wellen", "wellen/w1", "wellen/w1.txt", "wellen/w1.md/"],
)
def test_t10_form_und_typfehler_sind_400(client, bundle, welle):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": welle})

    assert antwort.status_code == 400
    assert antwort.get_json()["error"].strip()
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


@pytest.mark.parametrize("welle", [" wellen/w1.md ", "\nwellen/w1.md\t"])
def test_t11_welle_wird_getrimmt(client, bundle, welle):
    antwort = client.post("/api/meta", json={"path": AUFGABE, "welle": welle})

    assert antwort.status_code == 200
    assert antwort.get_json()["frontmatter"]["welle"] == WELLE
    assert f"welle: {WELLE}" in _lies(bundle, AUFGABE)


@pytest.mark.parametrize(
    "daten",
    [
        {"status": "Testing", "welle": "wellen/gibtsnicht.md"},
        {"owner": "x", "welle": "wellen/gibtsnicht.md"},
    ],
)
def test_t12_whitelist_vor_welle_ist_403(client, bundle, daten):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, **daten})

    assert antwort.status_code == 403
    assert antwort.get_json()["error"].strip()
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


def test_t13_welle_vor_zieldatei(client, bundle):
    assert not (bundle / "gibtsnicht.md").exists()

    fehlende_datei = client.post(
        "/api/meta", json={"path": "gibtsnicht.md", "welle": WELLE}
    )
    ungueltige_welle = client.post(
        "/api/meta", json={"path": "gibtsnicht.md", "welle": "wellen/gibtsnicht.md"}
    )

    assert fehlende_datei.status_code == 404
    assert ungueltige_welle.status_code == 400
    assert not (bundle / "gibtsnicht.md").exists()


def test_t14_kombination_in_einem_schreibvorgang(client, bundle, monkeypatch):
    aufrufe = []
    original = okf_bundle.set_meta

    def zaehlend(*args, **kwargs):
        aufrufe.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(okf_bundle, "set_meta", zaehlend)
    body_vorher = _body_hash(bundle, AUFGABE)

    antwort = client.post(
        "/api/meta",
        json={"path": AUFGABE, "owner": "mensch", "status": "Klarung", "welle": WELLE},
    )

    assert antwort.status_code == 200
    assert len(aufrufe) == 1
    assert aufrufe[0][0][1] == {
        "owner": "mensch",
        "task_status": "in Klärung",
        "welle": WELLE,
    }
    frontmatter = antwort.get_json()["frontmatter"]
    assert frontmatter["owner"] == "mensch"
    assert frontmatter["task_status"] == "in Klärung"
    assert frontmatter["welle"] == WELLE
    assert _body_hash(bundle, AUFGABE) == body_vorher


@pytest.mark.parametrize("daten", [{"unbekannt": "x"}, {"owner": None}, {"welle_x": None}])
def test_t15_keine_setzbaren_felder_ist_400(client, bundle, daten):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, **daten})

    assert antwort.status_code == 400
    assert antwort.get_json()["error"].strip()
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


def test_t16_reservierte_zieldatei_ist_403(client, bundle):
    hash_vorher = _datei_hash(bundle, "features.md")

    antwort = client.post("/api/meta", json={"path": "features.md", "welle": WELLE})

    assert antwort.status_code == 403
    assert antwort.get_json()["error"].strip()
    assert _datei_hash(bundle, "features.md") == hash_vorher


def test_t18_endpunkt_inventar_und_welle_anlegen(client, bundle):
    assert ENDPUNKTE == (
        "/api/nachtrag",
        "/api/task",
        "/api/welle",
        "/api/meta",
        "/api/freigabe",
    )

    regeln = {regel.rule for regel in client.application.url_map.iter_rules()}
    assert {
        "/",
        "/api/overview",
        "/api/file",
        "/api/aufgaben",
        "/api/wellen",
        "/api/nachtrag",
        "/api/task",
        "/api/welle",
        "/api/meta",
        "/api/freigabe",
    } <= regeln

    antwort = client.post("/api/welle", json=_welle_daten(welle=WELLE))

    assert antwort.status_code == 200
    pfad = antwort.get_json()["path"]
    assert pfad.startswith("wellen/")
    assert "welle:" not in _lies(bundle, pfad)


# --- A28: Freigabe ist ein Menschen-Recht ---------------------------------


@pytest.mark.parametrize(
    "nutzlast",
    [{"freigabe": True}, {"freigabe": False}, {"owner": "mensch", "freigabe": True}],
)
def test_a28_freigabe_ueber_meta_ist_403(client, bundle, nutzlast):
    hash_vorher = _datei_hash(bundle, AUFGABE)

    antwort = client.post("/api/meta", json={"path": AUFGABE, **nutzlast})

    assert antwort.status_code == 403
    assert antwort.get_json()["error"].strip()
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


def test_a28_freigabe_endpunkt_setzt_und_entzieht(client, bundle):
    setzen = client.post("/api/freigabe", json={"path": AUFGABE, "wert": True})
    entziehen = client.post("/api/freigabe", json={"path": AUFGABE, "wert": False})

    assert setzen.status_code == 200
    assert setzen.get_json()["freigabe"] is True
    assert entziehen.status_code == 200
    assert entziehen.get_json()["freigabe"] is False
    assert _lies(bundle, AUFGABE).count("\nfreigabe:") == 1
