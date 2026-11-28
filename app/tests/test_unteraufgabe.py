"""TDD-Tests für Unter-Aufgaben (A34): Anlage, Read-Modell, Validierung.

Alle Läufe arbeiten gegen das ``bundle``-Fixture (``tmp_path``-Kopie); zusätzliche
Dateien entstehen ausschließlich im Test-Bundle, nie in ``wissen/``.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import okf_bundle
import server

ELTERN = "aufgaben/a34-eltern.md"
KIND = "aufgaben/a34.001-kind.md"
WELLE = "wellen/w1.md"
PROJEKT = "projekt/phasen.md"


@pytest.fixture()
def client(bundle):
    return server.create_app(bundle).test_client()


def _schreibe(bundle, pfad: str, inhalt: str) -> Path:
    ziel = bundle / pfad
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(inhalt, encoding="utf-8")
    return ziel


def _frontmatter(**felder) -> str:
    zeilen = ["---"]
    for name, wert in felder.items():
        if isinstance(wert, bool):
            wert = "true" if wert else "false"
        zeilen.append(f"{name}: {json.dumps(wert, ensure_ascii=False)}")
    zeilen.append("---")
    return "\n".join(zeilen) + "\n\n# Ziel\n\nFixture.\n"


def _aufgabe(bundle, pfad: str, titel: str, **felder) -> Path:
    werte = {"type": "Task", "title": titel, "task_status": "offen", "owner": "ai"}
    werte.update(felder)
    return _schreibe(bundle, pfad, _frontmatter(**werte))


def _hash(bundle) -> str:
    """SHA256 über alle Bundle-Dateien (Name + Inhalt) — Byte-Identität."""
    teiler = hashlib.sha256()
    for datei in sorted(bundle.rglob("*")):
        if datei.is_file():
            teiler.update(datei.relative_to(bundle).as_posix().encode("utf-8"))
            teiler.update(datei.read_bytes())
    return teiler.hexdigest()


def _eintraege(client, endpunkt: str = "/api/aufgaben") -> dict:
    return {eintrag["path"]: eintrag for eintrag in client.get(endpunkt).get_json()}


# --- T28: parent im Read-Modell (Liste) -----------------------------------


def test_t28_parent_in_aufgabenliste(client, bundle):
    _aufgabe(bundle, ELTERN, "A34: Eltern", welle=WELLE)
    _aufgabe(bundle, KIND, "A34.001: Kind", parent=ELTERN)
    _schreibe(bundle, PROJEKT, _frontmatter(type="Projekt", title="Phasen", owner="ai"))

    eintraege = _eintraege(client)

    assert eintraege[KIND]["parent"] == ELTERN
    assert "parent" not in eintraege[ELTERN]
    assert "parent" not in _eintraege(client, "/api/overview")[WELLE]
    assert "parent" not in _eintraege(client, "/api/overview")[PROJEKT]
    # Übrige Felder bleiben unverändert.
    assert eintraege[KIND]["typ"] == "Task"
    assert eintraege[KIND]["status"] == "Offen"
    assert eintraege[KIND]["owner"] == "ai"
    assert eintraege[ELTERN]["welle"] == WELLE


# --- T29: parent im Read-Modell (Übersicht) -------------------------------


def test_t29_parent_in_uebersicht(client, bundle):
    _aufgabe(bundle, ELTERN, "A34: Eltern")
    _aufgabe(bundle, KIND, "A34.001: Kind", parent=ELTERN)

    antwort = client.get("/api/overview")
    eintraege = {eintrag["path"]: eintrag for eintrag in antwort.get_json()}

    assert antwort.status_code == 200
    assert eintraege[KIND]["parent"] == ELTERN
    assert "parent" not in eintraege[ELTERN]
    assert "parent" not in eintraege[WELLE]

# --- T30: parent im Detail, nicht über /api/meta schreibbar --------------


def test_t30_detail_und_meta(client, bundle):
    _aufgabe(bundle, ELTERN, "A34: Eltern")
    _aufgabe(bundle, KIND, "A34.001: Kind", parent=ELTERN)
    vorher = _hash(bundle)

    daten = client.get(f"/api/file?path={KIND}").get_json()

    assert daten["frontmatter"]["parent"] == ELTERN
    assert "parent" not in daten

    antwort = client.post("/api/meta", json={"path": KIND, "parent": ELTERN})

    assert antwort.status_code == 400
    assert _hash(bundle) == vorher


# --- T31: ungültige Bestandswerte ----------------------------------------


@pytest.mark.parametrize("rohwert", ["", "42", "[]", "null"])
def test_t31_ungueltige_bestandswerte(client, bundle, rohwert):
    _schreibe(
        bundle,
        "aufgaben/alt.md",
        f"---\ntype: Task\ntitle: \"Alt\"\ntask_status: offen\nparent: {rohwert}\n"
        "---\n\n# Ziel\n\nAlt.\n",
    )

    eintraege = _eintraege(client)

    assert "parent" not in eintraege["aufgaben/alt.md"]
    assert eintraege["aufgaben/alt.md"]["typ"] == "Task"
    assert client.get("/api/overview").status_code == 200


# --- Anlage mit parent (A34, Paket 2) -------------------------------------


def _daten(**werte) -> dict:
    daten = {
        "titel": "Erste Unter-Aufgabe",
        "ziel": "Ziel der Unter-Aufgabe.",
        "akzeptanz": ["Erstes Kriterium."],
        "prioritaet": "hoch",
        "parent": ELTERN,
    }
    daten.update(werte)
    return daten


def _post(client, **werte):
    return client.post("/api/task", json=_daten(**werte))


def _eltern_aufgabe(bundle, pfad: str = ELTERN, titel: str = "A34: Unter-Aufgaben", **felder):
    return _aufgabe(bundle, pfad, titel, **felder)


def _ueberschriften(markdown: str) -> list[str]:
    return [zeile.rstrip() for zeile in markdown.splitlines() if zeile.startswith("# ")]


def _anzahl_dateien(bundle) -> int:
    return len([datei for datei in bundle.rglob("*") if datei.is_file()])


# --- T13: Happy Path ------------------------------------------------------


def test_t13_anlegen_happy_path(client, bundle):
    _eltern_aufgabe(bundle)

    antwort = _post(client)

    assert antwort.status_code == 200
    pfad = antwort.get_json()["path"]
    assert pfad == "aufgaben/a34.001-erste-unter-aufgabe.md"

    frontmatter, body = okf_bundle.lesen(pfad)
    assert frontmatter["type"] == "Task"
    assert frontmatter["title"] == "A34.001: Erste Unter-Aufgabe"
    assert frontmatter["description"] == "Ziel der Unter-Aufgabe."
    assert frontmatter["parent"] == ELTERN
    assert frontmatter["owner"] == "ai"
    assert frontmatter["task_status"] == "offen"
    assert frontmatter["phase"] == "2 Planung"
    assert frontmatter["assigned_to"] == "coder"
    assert frontmatter["priority"] == "hoch"
    assert frontmatter["freigabe"] is False
    assert _ueberschriften(body) == [
        "# Ziel",
        "# Akzeptanzkriterien",
        "# Testfälle (TDD)",
        "# Kontext",
        "# Betroffene Dateien",
        "# Ergebnisse",
    ]

    eintrag = _eintraege(client)[pfad]
    assert eintrag["neu"] is False
    assert eintrag["kennung"] == "A34.001"
    assert eintrag["parent"] == ELTERN


# --- T14: Kennung und Slug ------------------------------------------------


def test_t14_titel_und_slug(client, bundle):
    _eltern_aufgabe(bundle)

    antwort = _post(client, titel="Übersicht: Status & owner!")

    assert antwort.status_code == 200
    pfad = antwort.get_json()["path"]
    assert pfad == "aufgaben/a34.001-uebersicht-status-owner.md"
    assert okf_bundle.lesen(pfad)[0]["title"] == "A34.001: Übersicht: Status & owner!"


def test_t14_titel_nur_kennung_ist_400(client, bundle):
    _eltern_aufgabe(bundle)
    vorher = _hash(bundle)

    antwort = _post(client, titel="A34.001: ")

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]
    assert _hash(bundle) == vorher


# --- T15: Nummerierung, Lücken, fremde Eltern -----------------------------


def test_t15_nummerierung_und_luecken(client, bundle):
    _eltern_aufgabe(bundle)
    pfad_1 = _post(client).get_json()["path"]
    pfad_2 = _post(client, titel="Zweite Unter-Aufgabe").get_json()["path"]

    assert pfad_1.endswith("a34.001-erste-unter-aufgabe.md")
    assert pfad_2.endswith("a34.002-zweite-unter-aufgabe.md")

    (bundle / pfad_1).unlink()
    pfad_3 = _post(client, titel="Dritte Unter-Aufgabe").get_json()["path"]
    assert pfad_3.endswith("a34.001-dritte-unter-aufgabe.md")

    _eltern_aufgabe(bundle, "aufgaben/a35-eltern.md", "A35: Andere Eltern")
    antwort = client.post(
        "/api/task",
        json=_daten(parent="aufgaben/a35-eltern.md"),
    )
    assert antwort.status_code == 200
    assert antwort.get_json()["path"].endswith("a35.001-erste-unter-aufgabe.md")


# --- T16: Präfix-Normalisierung -------------------------------------------

@pytest.mark.parametrize(
    "titel,erwartet",
    [
        ("A34.007: Eigener Titel", "A34.001: Eigener Titel"),
        ("A35.001: Fremd", "A34.001: Fremd"),
        ("A34.001:Fremd", "A34.001: Fremd"),
    ],
)
def test_t16_praefix_wird_normalisiert(client, bundle, titel, erwartet):
    _eltern_aufgabe(bundle)

    antwort = _post(client, titel=titel)

    assert antwort.status_code == 200
    pfad = antwort.get_json()["path"]
    assert okf_bundle.lesen(pfad)[0]["title"] == erwartet
    assert okf_bundle.lesen(pfad)[0]["title"].count("A34.001") == 1


# --- T17: welle erben -----------------------------------------------------


def test_t17_welle_wird_geerbt(client, bundle):
    _eltern_aufgabe(bundle, welle="wellen/w3.md")

    antwort = _post(client)

    assert antwort.status_code == 200
    frontmatter, body = okf_bundle.lesen(antwort.get_json()["path"])
    assert frontmatter["welle"] == "wellen/w3.md"
    assert "wellen/w3.md" in body


def test_t17_ohne_welle_kein_schluessel(client, bundle):
    _eltern_aufgabe(bundle)

    antwort = _post(client)

    assert antwort.status_code == 200
    assert "welle" not in okf_bundle.lesen(antwort.get_json()["path"])[0]


def test_t17_welle_und_parent_ist_400(client, bundle):
    _eltern_aufgabe(bundle, welle="wellen/w3.md")
    vorher = _hash(bundle)

    antwort = _post(client, welle="wellen/w3.md")

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]
    assert _hash(bundle) == vorher


# --- T18: parent-Typen ----------------------------------------------------


@pytest.mark.parametrize("parent", [None, "", "   "])
def test_t18_leeres_parent_ist_top_level(client, bundle, parent):
    antwort = _post(client, parent=parent, titel="Top-Level-Aufgabe")

    assert antwort.status_code == 200
    frontmatter, _ = okf_bundle.lesen(antwort.get_json()["path"])
    assert "parent" not in frontmatter
    assert frontmatter["title"] == "Top-Level-Aufgabe"


@pytest.mark.parametrize("parent", [42, [], {}, True])
def test_t18_falscher_typ_ist_400(client, bundle, parent):
    vorher = _hash(bundle)

    antwort = _post(client, parent=parent)

    assert antwort.status_code == 400
    assert _hash(bundle) == vorher


def test_t18_path_bleibt_verboten(client, bundle):
    vorher = _hash(bundle)

    antwort = _post(client, path="aufgaben/x.md")

    assert antwort.status_code == 400
    assert _hash(bundle) == vorher


# --- T19/T20: parent fehlt, falscher Ort, reserviert, Ausbruch ------------


def test_t19_parent_fehlt_ist_400(client, bundle):
    vorher = _hash(bundle)

    antwort = _post(client, parent="aufgaben/gibtsnicht.md")

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]
    assert _hash(bundle) == vorher


@pytest.mark.parametrize(
    "parent",
    [
        "wellen/w1.md",
        "projekt/phasen.md",
        "aufgaben/index.md",
        "../aufgaben/a1.md",
        "/etc/passwd",
        "aufgaben/../wellen/w1.md",
    ],
)
def test_t20_parent_falscher_ort_ist_400(client, bundle, parent):
    vorher = _hash(bundle)

    antwort = _post(client, parent=parent)

    assert antwort.status_code == 400
    assert "error" in antwort.get_json()
    assert _hash(bundle) == vorher


# --- T21: kein Task / kaputtes Frontmatter --------------------------------


@pytest.mark.parametrize(
    "pfad,inhalt",
    [
        ("aufgaben/notiz.md", "---\ntitle: \"Notiz\"\nowner: ai\n---\n\n# Notiz\n"),
        ("aufgaben/kaputt.md", "---\ntype: Task\ntitle: [kaputt\n---\n\n# Ziel\n"),
    ],
)
def test_t21_parent_kein_task_ist_400(client, bundle, pfad, inhalt):
    _schreibe(bundle, pfad, inhalt)
    vorher = _hash(bundle)

    antwort = _post(client, parent=pfad)

    assert antwort.status_code == 400
    assert _hash(bundle) == vorher


# --- T22: Tiefe > 1 -------------------------------------------------------


def test_t22_tiefe_ist_400(client, bundle):
    _eltern_aufgabe(bundle)
    _aufgabe(bundle, KIND, "A34.001: Kind", parent=ELTERN)
    _aufgabe(bundle, "aufgaben/a34-oberflaeche.md", "A34: Oberfläche", parent=ELTERN)
    vorher = _hash(bundle)

    for pfad in (KIND, "aufgaben/a34-oberflaeche.md"):
        antwort = _post(client, parent=pfad)
        assert antwort.status_code == 400, pfad

    assert _hash(bundle) == vorher


# --- T23: Eltern ohne gültige Kennung ------------------------------------


@pytest.mark.parametrize(
    "pfad,titel",
    [
        ("aufgaben/a34-ohne.md", "Neue Aufgabe"),
        ("aufgaben/a34-inkonsistent.md", "A99: X"),
        ("aufgaben/a34.001-kind.md", "A34.001: Kind"),
    ],
)
def test_t23_eltern_ohne_gueltige_kennung_ist_400(client, bundle, pfad, titel):
    _aufgabe(bundle, pfad, titel)
    vorher = _hash(bundle)

    antwort = _post(client, parent=pfad)

    assert antwort.status_code == 400
    assert _hash(bundle) == vorher


# --- T24: abgeschlossene Eltern ------------------------------------------


def test_t24_abgeschlossene_eltern_ist_400(client, bundle):
    _eltern_aufgabe(bundle, task_status="abgeschlossen")
    vorher = _hash(bundle)

    antwort = _post(client)

    assert antwort.status_code == 400
    assert _hash(bundle) == vorher


def test_t24_zur_abnahme_ist_erlaubt(client, bundle):
    _eltern_aufgabe(bundle, task_status="zur Abnahme")

    assert _post(client).status_code == 200


# --- T25: Erschöpfung über die API ---------------------------------------


def test_t25_erschoepfung_ist_400(client, bundle, monkeypatch):
    _eltern_aufgabe(bundle)
    vorher = _hash(bundle)

    def erschoepft(_pfad):
        raise okf_bundle.EingabeFehler("Der Nummernraum ist erschöpft")

    monkeypatch.setattr("kennung.naechste_unterkennung", erschoepft)

    antwort = _post(client)

    assert antwort.status_code == 400
    assert antwort.get_json()["error"]
    assert _hash(bundle) == vorher


# --- T26: Kennungskollision im Bestand -----------------------------------


def test_t26_kollision_im_bestand(client, bundle):
    _eltern_aufgabe(bundle)
    _aufgabe(bundle, "aufgaben/a34.001-manuell-a.md", "A34.001: Manuell A")
    _aufgabe(bundle, "aufgaben/a34.001-manuell-b.md", "A34.001: Manuell B")
    vorher_a = (bundle / "aufgaben/a34.001-manuell-a.md").read_bytes()
    vorher_b = (bundle / "aufgaben/a34.001-manuell-b.md").read_bytes()

    antwort = _post(client)

    assert antwort.status_code == 200
    assert antwort.get_json()["path"].endswith("a34.002-erste-unter-aufgabe.md")
    assert (bundle / "aufgaben/a34.001-manuell-a.md").read_bytes() == vorher_a
    assert (bundle / "aufgaben/a34.001-manuell-b.md").read_bytes() == vorher_b
    assert okf_bundle.lesen(antwort.get_json()["path"])[0]["freigabe"] is False


# --- T27: Atomarität und A13-Regression ----------------------------------


def test_t27_400_faelle_schreiben_nichts(client, bundle):
    _eltern_aufgabe(bundle, task_status="abgeschlossen")
    vorher = _hash(bundle)
    anzahl = _anzahl_dateien(bundle)

    for daten in (
        {"parent": "aufgaben/gibtsnicht.md"},
        {"parent": "wellen/w1.md"},
        {"parent": 42},
        {"welle": "wellen/w1.md"},
        {"titel": ""},
        {"akzeptanz": []},
        {"prioritaet": "dringend"},
    ):
        antwort = _post(client, **daten)
        assert antwort.status_code == 400, daten

    assert _hash(bundle) == vorher
    assert _anzahl_dateien(bundle) == anzahl


def test_t27_ohne_parent_unveraendert(client, bundle):
    erster = _post(client, parent=None, titel="Kollision")
    zweiter = _post(client, parent=None, titel="Kollision")

    assert erster.status_code == 200
    assert zweiter.status_code == 200
    assert erster.get_json()["path"] == "aufgaben/kollision.md"
    assert zweiter.get_json()["path"] == "aufgaben/kollision-2.md"
    frontmatter, body = okf_bundle.lesen(zweiter.get_json()["path"])
    assert "parent" not in frontmatter
    assert _ueberschriften(body) == [
        "# Ziel",
        "# Akzeptanzkriterien",
        "# Testfälle (TDD)",
        "# Kontext",
        "# Betroffene Dateien",
        "# Ergebnisse",
    ]
