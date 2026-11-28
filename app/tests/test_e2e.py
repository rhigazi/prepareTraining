"""E2E-Regressionstest (A22): T1/T2/T7-Kette des A17-Abnahmelaufs.

Fährt die reale Flask-App (``server.create_app``) über die JSON-API gegen ein
frisches Test-Bundle unter ``/tmp/opencode`` — nie gegen das echte ``wissen/``.
Die Kette entspricht dem dokumentierten A17-Abnahmelauf:

* **T1** Overview → Nachtrag → Aufgabe anlegen → Welle anlegen → Meta
  (``owner``, Status ``Klarung``, Wellen-Zuordnung) → Freigabe/Gate → lesen und
  über alle Schritte konsistent verifizieren.
* **T2** Frontmatter-Invarianten: ``type``/``title`` unverändert, genau ein
  Nachtrag-Marker, append-only.
* **T7** Test-Bundle zurücksetzen und erneut fahren → identisches Protokoll.
* **T3/Isolation** SHA-256 über das echte ``wissen/`` vor/nach dem Lauf identisch.

Die historischen Ad-hoc-Skripte ``/tmp/opencode/a17_*.py`` sind nicht mehr
vorhanden; die Kette folgt der Aufgaben-/Log-Dokumentation zu A17.
"""

import hashlib
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import okf_bundle
import server

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BUNDLE_VORLAGE = FIXTURES / "bundle_min"
E2E_BASIS = Path("/tmp/opencode")
WISSEN = Path(__file__).resolve().parents[3] / "wissen"

AUFGABE_FIXTURE = "aufgaben/a1.md"
WELLE_FIXTURE = "wellen/w1.md"
NEUE_AUFGABE = "aufgaben/a99-e2e-aufgabe.md"
NEUE_WELLE = "wellen/welle-9-e2e-welle.md"

MARKER = re.compile(
    r"^> \*\*Nachtrag \(Mensch, (?P<datum>\d{4}-\d{2}-\d{2})\):\*\* .+$"
)
DATUM_PLATZHALTER = "<datum>"


# --- Fixtures & Helfer ----------------------------------------------------


@pytest.fixture()
def e2e_bundles(monkeypatch):
    """Fabrik für frische Test-Bundles unter ``/tmp/opencode`` (R9/A17-Muster).

    Jeder Aufruf legt eine eigene Kopie von ``fixtures/bundle_min`` an; die
    Verzeichnisse werden nach dem Test entfernt. Das echte ``wissen/`` wird
    nie als Bundle-Wurzel gesetzt. ``BUNDLE_ROOT`` wird nach dem Test
    zurückgesetzt (die App-Factory setzt es global).
    """
    monkeypatch.setattr(okf_bundle, "BUNDLE_ROOT", okf_bundle.BUNDLE_ROOT)
    basen: list[Path] = []

    def neu() -> Path:
        E2E_BASIS.mkdir(parents=True, exist_ok=True)
        basis = Path(tempfile.mkdtemp(prefix="a22-e2e-", dir=str(E2E_BASIS)))
        ziel = basis / "bundle"
        shutil.copytree(BUNDLE_VORLAGE, ziel)
        basen.append(basis)
        return ziel

    yield neu
    for basis in basen:
        shutil.rmtree(basis, ignore_errors=True)


@pytest.fixture()
def e2e_bundle(e2e_bundles):
    """Ein frisches Test-Bundle für einen Testlauf."""
    return e2e_bundles()


def _client(bundle: Path):
    return server.create_app(bundle).test_client()


def _zuruecksetzen(bundle: Path) -> None:
    """Setzt das Test-Bundle auf den Fixture-Stand zurück (T7)."""
    shutil.rmtree(bundle)
    shutil.copytree(BUNDLE_VORLAGE, bundle)


def _lies(bundle: Path, pfad: str) -> str:
    with open(bundle / pfad, encoding="utf-8", newline="") as datei:
        return datei.read()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _marker_zeilen(text: str) -> list[str]:
    return [zeile for zeile in text.splitlines() if MARKER.match(zeile)]


def _utc_heute() -> str:
    """Heutiges Datum in UTC — so stempelt ``nachtrag`` neue Marker."""
    return datetime.now(timezone.utc).date().isoformat()


def _marker_datum(zeile: str) -> str:
    treffer = MARKER.match(zeile)
    assert treffer is not None, f"keine Nachtrags-Markerzeile: {zeile!r}"
    return treffer.group("datum")


def _marker_pruefen(text: str, erwarteter_text: str, datum_fenster: set[str]) -> str:
    """Prüft genau einen Nachtrags-Marker samt Datum aus dem Lauf-Fenster.

    ``datum_fenster`` enthält das UTC-Datum vor und nach dem POST. Läuft ein
    Test über 00:00 UTC, akzeptiert die Prüfung beide Tage (K5).
    """
    marker = _marker_zeilen(text)
    assert len(marker) == 1, f"genau ein Marker erwartet: {marker!r}"
    datum = _marker_datum(marker[0])
    assert datum in datum_fenster, (
        f"Datum {datum} außerhalb des Lauf-Fensters {datum_fenster}"
    )
    assert marker == [f"> **Nachtrag (Mensch, {datum}):** {erwarteter_text}"]
    return datum


def _ohne_datum(text: str) -> str:
    """Ersetzt konkrete Nachtragsdaten durch einen Platzhalter (T7).

    Ein Lauf über 00:00 UTC unterscheidet sich nur im Tagesstempel. Für den
    reproduzierbaren Protokollvergleich wird deshalb ausschließlich das Datum
    normalisiert; alle übrigen Bytes bleiben im Hash enthalten.
    """
    for zeile in _marker_zeilen(text):
        text = text.replace(_marker_datum(zeile), DATUM_PLATZHALTER)
    return text


def _marker_ohne_datum(marker: list[str]) -> list[str]:
    return [_ohne_datum(zeile) for zeile in marker]


def _nachtraege_ohne_datum(eintraege: list[dict]) -> list[dict]:
    return [{**eintrag, "datum": DATUM_PLATZHALTER} for eintrag in eintraege]


def _eintrag(uebersicht: list[dict], pfad: str) -> dict:
    treffer = [eintrag for eintrag in uebersicht if eintrag["path"] == pfad]
    assert len(treffer) == 1, f"{pfad} muss genau einmal in der Übersicht stehen"
    return treffer[0]


def _ohne_zeit(uebersicht: list[dict]) -> list[dict]:
    """Übersicht ohne mtime und in Pfadreihenfolge — für reproduzierbare Vergleiche."""
    bereinigt = [
        {feld: wert for feld, wert in eintrag.items() if feld != "zuletzt_geaendert"}
        for eintrag in uebersicht
    ]
    return sorted(bereinigt, key=lambda eintrag: eintrag["path"])


def _datei_hash(bundle: Path, pfad: str) -> str:
    return _sha256(_lies(bundle, pfad))


def _datei_hash_ohne_datum(bundle: Path, pfad: str) -> str:
    """Datei-Hash für das Protokoll; nur der Tagesstempel wird neutralisiert (T7)."""
    return _sha256(_ohne_datum(_lies(bundle, pfad)))


def _baum_hash(wurzel: Path) -> str:
    """SHA-256 über alle Dateien inklusive relativem Pfad (Reihenfolge stabil)."""
    digest = hashlib.sha256()
    for pfad in sorted(p for p in wurzel.rglob("*") if p.is_file()):
        digest.update(pfad.relative_to(wurzel).as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(pfad.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def _baum_dateien(wurzel: Path) -> list[str]:
    return sorted(p.relative_to(wurzel).as_posix() for p in wurzel.rglob("*") if p.is_file())


# --- T1: durchgängige API-E2E-Kette ---------------------------------------


def _fahre_kette(client, bundle: Path) -> list[dict]:
    """Fährt die A17-Kette und liefert ein reproduzierbares Protokoll (T1/T7).

    Alle Schritte laufen über die echte Flask-App und prüfen den Zustand nach
    dem Schreiben jeweils über einen frischen Lese-Request. Rückgabe sind nur
    deterministische Werte (ohne mtime), damit T7 zwei Läufe vergleichen kann.
    """
    protokoll: list[dict] = []

    def merke(schritt: str, wert: object) -> None:
        protokoll.append({"schritt": schritt, "wert": wert})

    # 1. Ausgangslage: sauberes Fixture-Bundle (zugleich Reset-Beleg für T7).
    antwort = client.get("/api/overview")
    assert antwort.status_code == 200
    assert antwort.mimetype == "application/json"
    uebersicht = antwort.get_json()
    merke("overview_start", _ohne_zeit(uebersicht))
    assert {eintrag["path"] for eintrag in uebersicht} == {AUFGABE_FIXTURE, WELLE_FIXTURE}

    start_eintrag = _eintrag(uebersicht, AUFGABE_FIXTURE)
    assert start_eintrag["typ"] == "Task"
    assert start_eintrag["titel"] == "A1: Mini-Aufgabe"
    assert start_eintrag["status"] == "Offen"
    assert start_eintrag["owner"] == "ai"
    assert start_eintrag["freigabe"] is False
    assert _marker_zeilen(_lies(bundle, AUFGABE_FIXTURE)) == []

    antwort = client.get("/api/file", query_string={"path": AUFGABE_FIXTURE})
    assert antwort.status_code == 200
    detail_start = antwort.get_json()
    frontmatter_start = detail_start["frontmatter"]
    inhalt_start = _lies(bundle, AUFGABE_FIXTURE)
    assert frontmatter_start["type"] == "Task"
    assert frontmatter_start["title"] == "A1: Mini-Aufgabe"
    assert detail_start["nachtraege"] == []

    # 2. T1: Nachtrag anfügen — append-only, genau ein Marker.
    datum_vorher = _utc_heute()
    antwort = client.post(
        "/api/nachtrag",
        json={"path": AUFGABE_FIXTURE, "text": "E2E: Bitte präzisieren."},
    )
    assert antwort.status_code == 200
    assert antwort.mimetype == "application/json"
    daten = antwort.get_json()
    assert daten["path"] == AUFGABE_FIXTURE
    assert daten["frontmatter"] == frontmatter_start
    inhalt_nachtrag = _lies(bundle, AUFGABE_FIXTURE)
    datum_nachher = _utc_heute()
    assert inhalt_nachtrag.startswith(inhalt_start)
    datum_marker = _marker_pruefen(
        inhalt_nachtrag,
        "E2E: Bitte präzisieren.",
        {datum_vorher, datum_nachher},
    )
    assert daten["nachtraege"] == [
        {"autor": "Mensch", "datum": datum_marker, "text": "E2E: Bitte präzisieren."}
    ]
    merke(
        "nachtrag_a1",
        {
            "frontmatter": daten["frontmatter"],
            "nachtraege": _nachtraege_ohne_datum(daten["nachtraege"]),
            "marker": _marker_ohne_datum(_marker_zeilen(inhalt_nachtrag)),
            "sha256": _sha256(_ohne_datum(inhalt_nachtrag)),
        },
    )

    # 3. T1/T2: Lesen bestätigt den geschriebenen Zustand.
    antwort = client.get("/api/file", query_string={"path": AUFGABE_FIXTURE})
    assert antwort.status_code == 200
    detail = antwort.get_json()
    assert detail["frontmatter"] == frontmatter_start
    assert detail["frontmatter"]["type"] == "Task"
    assert detail["frontmatter"]["title"] == "A1: Mini-Aufgabe"
    assert len(_marker_zeilen(detail["markdown"])) == 1
    assert detail["nachtraege"] == daten["nachtraege"]
    eintrag = _eintrag(client.get("/api/overview").get_json(), AUFGABE_FIXTURE)
    assert eintrag["status"] == "Offen"
    assert eintrag["owner"] == "ai"

    # 4. T1: Aufgabe anlegen.
    antwort = client.post(
        "/api/task",
        json={
            "titel": "A99: E2E-Aufgabe",
            "ziel": "Durchgängige E2E-Kette der A22-Regression.",
            "akzeptanz": [
                "Kette läuft gegen das Test-Bundle.",
                "Frontmatter bleibt intakt.",
            ],
            "prioritaet": "hoch",
        },
    )
    assert antwort.status_code == 200
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["path"] == NEUE_AUFGABE

    aufgabe_detail = client.get(
        "/api/file", query_string={"path": NEUE_AUFGABE}
    ).get_json()
    aufgabe_frontmatter = aufgabe_detail["frontmatter"]
    assert aufgabe_frontmatter["type"] == "Task"
    assert aufgabe_frontmatter["title"] == "A99: E2E-Aufgabe"
    assert aufgabe_frontmatter["task_status"] == "offen"
    assert aufgabe_frontmatter["owner"] == "ai"
    assert aufgabe_frontmatter["freigabe"] is False
    for abschnitt in (
        "# Ziel",
        "# Akzeptanzkriterien",
        "# Testfälle (TDD)",
        "# Kontext",
        "# Betroffene Dateien",
        "# Ergebnisse",
    ):
        assert abschnitt in aufgabe_detail["markdown"]
    assert aufgabe_detail["nachtraege"] == []

    aufgabe_eintrag = _eintrag(client.get("/api/overview").get_json(), NEUE_AUFGABE)
    assert aufgabe_eintrag["typ"] == "Task"
    assert aufgabe_eintrag["status"] == "Offen"
    assert aufgabe_eintrag["owner"] == "ai"
    assert aufgabe_eintrag["freigabe"] is False
    merke(
        "aufgabe_neu",
        {
            "path": NEUE_AUFGABE,
            "frontmatter": aufgabe_frontmatter,
            "eintrag": {k: v for k, v in aufgabe_eintrag.items() if k != "zuletzt_geaendert"},
        },
    )

    # 5. T1: Welle anlegen.
    antwort = client.post(
        "/api/welle",
        json={
            "titel": "Welle 9: E2E-Welle",
            "ziel": "E2E-Welle für die A22-Regression.",
            "status": "Offen",
            "owner": "ai",
        },
    )
    assert antwort.status_code == 200
    assert antwort.get_json()["path"] == NEUE_WELLE

    wellen_detail = client.get("/api/file", query_string={"path": NEUE_WELLE}).get_json()
    wellen_frontmatter = wellen_detail["frontmatter"]
    assert wellen_frontmatter["type"] == "Welle"
    assert wellen_frontmatter["title"] == "Welle 9: E2E-Welle"
    assert wellen_frontmatter["status"] == "Offen"
    assert wellen_frontmatter["owner"] == "ai"
    assert wellen_frontmatter["freigabe"] is False

    wellen_eintrag = _eintrag(client.get("/api/overview").get_json(), NEUE_WELLE)
    assert wellen_eintrag["typ"] == "Welle"
    assert wellen_eintrag["status"] == "Offen"
    assert wellen_eintrag["owner"] == "ai"
    assert wellen_eintrag["freigabe"] is False
    merke(
        "welle_neu",
        {
            "path": NEUE_WELLE,
            "frontmatter": wellen_frontmatter,
            "eintrag": {k: v for k, v in wellen_eintrag.items() if k != "zuletzt_geaendert"},
        },
    )

    # 6. T1: owner auf „mensch" umschalten (explizites Feld hat Vorrang).
    antwort = client.post("/api/meta", json={"path": NEUE_AUFGABE, "owner": "mensch"})
    assert antwort.status_code == 200
    assert antwort.get_json()["frontmatter"]["owner"] == "mensch"
    eintrag = _eintrag(client.get("/api/overview").get_json(), NEUE_AUFGABE)
    assert eintrag["owner"] == "mensch"
    assert eintrag["status"] == "Offen"
    merke("meta_owner", {"frontmatter": antwort.get_json()["frontmatter"], "eintrag": {
        k: v for k, v in eintrag.items() if k != "zuletzt_geaendert"
    }})

    # 7. T1: Status „Klarung" setzen (schreibt task_status `in Klärung`).
    antwort = client.post("/api/meta", json={"path": NEUE_AUFGABE, "status": "Klarung"})
    assert antwort.status_code == 200
    status_frontmatter = antwort.get_json()["frontmatter"]
    assert status_frontmatter["task_status"] == "in Klärung"
    assert status_frontmatter["owner"] == "mensch"
    eintrag = _eintrag(client.get("/api/overview").get_json(), NEUE_AUFGABE)
    assert eintrag["status"] == "Klarung"
    assert eintrag["owner"] == "mensch"
    merke("meta_status", {"frontmatter": status_frontmatter, "eintrag": {
        k: v for k, v in eintrag.items() if k != "zuletzt_geaendert"
    }})

    # 8. T1: Aufgabe der Welle zuordnen — Gate bleibt zunächst geschlossen.
    antwort = client.post(
        "/api/meta", json={"path": NEUE_AUFGABE, "welle": NEUE_WELLE}
    )
    assert antwort.status_code == 200
    assert antwort.get_json()["frontmatter"]["welle"] == NEUE_WELLE
    eintrag = _eintrag(client.get("/api/overview").get_json(), NEUE_AUFGABE)
    assert eintrag["welle"] == NEUE_WELLE
    detail = client.get("/api/file", query_string={"path": NEUE_AUFGABE}).get_json()
    assert detail["welle_freigabe"] is False
    assert detail["wirksam_freigegeben"] is False
    merke(
        "meta_welle",
        {
            "frontmatter": antwort.get_json()["frontmatter"],
            "eintrag": {k: v for k, v in eintrag.items() if k != "zuletzt_geaendert"},
            "welle_freigabe": detail["welle_freigabe"],
            "wirksam_freigegeben": detail["wirksam_freigegeben"],
        },
    )

    # 9. T1: Welle freigeben — Aufgabe selbst ist noch nicht freigegeben (UND-Gate).
    antwort = client.post("/api/freigabe", json={"path": NEUE_WELLE, "wert": True})
    assert antwort.status_code == 200
    assert antwort.get_json()["freigabe"] is True
    detail = client.get("/api/file", query_string={"path": NEUE_AUFGABE}).get_json()
    assert detail["welle_freigabe"] is True
    assert detail["wirksam_freigegeben"] is False
    merke(
        "freigabe_welle",
        {
            "freigabe": antwort.get_json()["freigabe"],
            "welle_freigabe": detail["welle_freigabe"],
            "wirksam_freigegeben": detail["wirksam_freigegeben"],
        },
    )

    # 10. T1: Aufgabe freigeben — erst jetzt ist das UND-Gate offen.
    antwort = client.post("/api/freigabe", json={"path": NEUE_AUFGABE, "wert": True})
    assert antwort.status_code == 200
    assert antwort.get_json()["freigabe"] is True
    detail = client.get("/api/file", query_string={"path": NEUE_AUFGABE}).get_json()
    assert detail["welle_freigabe"] is True
    assert detail["wirksam_freigegeben"] is True
    eintrag = _eintrag(client.get("/api/overview").get_json(), NEUE_AUFGABE)
    assert eintrag["freigabe"] is True
    merke(
        "freigabe_aufgabe",
        {
            "freigabe": antwort.get_json()["freigabe"],
            "welle_freigabe": detail["welle_freigabe"],
            "wirksam_freigegeben": detail["wirksam_freigegeben"],
            "eintrag": {k: v for k, v in eintrag.items() if k != "zuletzt_geaendert"},
        },
    )

    # 11. T1: Freigabe bleibt Menschen-Recht — KI-Pfad liefert 403, kein Schreibvorgang.
    hash_vorher = _datei_hash(bundle, NEUE_AUFGABE)
    antwort = client.post("/api/meta", json={"path": NEUE_AUFGABE, "freigabe": False})
    assert antwort.status_code == 403
    assert antwort.get_json()["error"]
    # K2: byte-identisch, nicht nur semantisch unverändert.
    assert _datei_hash(bundle, NEUE_AUFGABE) == hash_vorher
    detail = client.get("/api/file", query_string={"path": NEUE_AUFGABE}).get_json()
    assert detail["frontmatter"]["freigabe"] is True

    # 12. T2: Nachtrag auf der neuen Aufgabe — Frontmatter unverändert, genau 1 Marker.
    datum_vorher = _utc_heute()
    antwort = client.post(
        "/api/nachtrag",
        json={"path": NEUE_AUFGABE, "text": "E2E: Nachfrage zur Aufgabe."},
    )
    assert antwort.status_code == 200
    nachtrag_frontmatter = antwort.get_json()["frontmatter"]
    assert nachtrag_frontmatter["type"] == "Task"
    assert nachtrag_frontmatter["title"] == "A99: E2E-Aufgabe"
    assert nachtrag_frontmatter["freigabe"] is True
    inhalt_aufgabe = _lies(bundle, NEUE_AUFGABE)
    datum_nachher = _utc_heute()
    _marker_pruefen(
        inhalt_aufgabe,
        "E2E: Nachfrage zur Aufgabe.",
        {datum_vorher, datum_nachher},
    )
    merke(
        "nachtrag_aufgabe",
        {
            "frontmatter": nachtrag_frontmatter,
            "marker": _marker_ohne_datum(_marker_zeilen(inhalt_aufgabe)),
            "sha256": _sha256(_ohne_datum(inhalt_aufgabe)),
        },
    )

    # 13. T1: beide Listen-Endpunkte führen die neuen Punkte.
    assert NEUE_AUFGABE in [e["path"] for e in client.get("/api/aufgaben").get_json()]
    assert NEUE_WELLE in [e["path"] for e in client.get("/api/wellen").get_json()]

    # 14. Endzustand der Übersicht: alle vier Punkte, konsistente Werte.
    uebersicht_ende = client.get("/api/overview").get_json()
    assert {eintrag["path"] for eintrag in uebersicht_ende} == {
        AUFGABE_FIXTURE,
        WELLE_FIXTURE,
        NEUE_AUFGABE,
        NEUE_WELLE,
    }
    assert _eintrag(uebersicht_ende, NEUE_AUFGABE)["status"] == "Klarung"
    assert _eintrag(uebersicht_ende, NEUE_AUFGABE)["owner"] == "mensch"
    assert _eintrag(uebersicht_ende, NEUE_WELLE)["freigabe"] is True
    merke("overview_ende", _ohne_zeit(uebersicht_ende))
    merke(
        "dateien",
        {
            pfad: _datei_hash_ohne_datum(bundle, pfad)
            for pfad in (AUFGABE_FIXTURE, NEUE_AUFGABE, NEUE_WELLE)
        },
    )
    return protokoll


def test_t1_api_e2e_kette(e2e_bundle):
    """T1: Overview → Nachtrag → Aufgabe → Welle → Meta/Status → Lesen, konsistent."""
    assert e2e_bundle.is_relative_to(E2E_BASIS)
    protokoll = _fahre_kette(_client(e2e_bundle), e2e_bundle)

    # K1: Statt der tautologischen Schrittnamen-Liste prüft der Abschluss die
    # Anzahl (Klammer) und ausgewählte fachliche Werte aus dem Protokoll.
    assert len(protokoll) == 12
    nach_schritt = {eintrag["schritt"]: eintrag["wert"] for eintrag in protokoll}
    assert len(nach_schritt) == len(protokoll), "Schrittnamen müssen eindeutig sein"

    assert nach_schritt["nachtrag_a1"]["marker"] == [
        f"> **Nachtrag (Mensch, {DATUM_PLATZHALTER}):** E2E: Bitte präzisieren."
    ]
    assert nach_schritt["aufgabe_neu"]["frontmatter"]["task_status"] == "offen"
    assert nach_schritt["aufgabe_neu"]["frontmatter"]["owner"] == "ai"
    assert nach_schritt["meta_status"]["eintrag"]["status"] == "Klarung"
    assert nach_schritt["meta_status"]["frontmatter"]["task_status"] == "in Klärung"
    assert nach_schritt["freigabe_welle"]["wirksam_freigegeben"] is False
    assert nach_schritt["freigabe_aufgabe"]["wirksam_freigegeben"] is True
    assert {eintrag["path"] for eintrag in nach_schritt["overview_ende"]} == {
        AUFGABE_FIXTURE,
        WELLE_FIXTURE,
        NEUE_AUFGABE,
        NEUE_WELLE,
    }

    dateien = nach_schritt["dateien"]
    assert set(dateien) == {AUFGABE_FIXTURE, NEUE_AUFGABE, NEUE_WELLE}
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in dateien.values())
    assert len(set(dateien.values())) == len(dateien)


def test_t2_frontmatter_invarianten(e2e_bundle):
    """T2: `type`/`title` unverändert, genau ein Marker, append-only."""
    client = _client(e2e_bundle)

    vorher = client.get("/api/file", query_string={"path": AUFGABE_FIXTURE}).get_json()
    inhalt_vorher = _lies(e2e_bundle, AUFGABE_FIXTURE)
    datum_vorher = _utc_heute()
    antwort = client.post(
        "/api/nachtrag",
        json={"path": AUFGABE_FIXTURE, "text": "T2: Nachtrag eins."},
    )
    assert antwort.status_code == 200
    nachher = client.get("/api/file", query_string={"path": AUFGABE_FIXTURE}).get_json()
    inhalt_nachher = _lies(e2e_bundle, AUFGABE_FIXTURE)
    datum_nachher = _utc_heute()

    assert nachher["frontmatter"] == vorher["frontmatter"]
    assert nachher["frontmatter"]["type"] == "Task"
    assert nachher["frontmatter"]["title"] == "A1: Mini-Aufgabe"
    assert inhalt_nachher.startswith(inhalt_vorher)
    _marker_pruefen(
        inhalt_nachher,
        "T2: Nachtrag eins.",
        {datum_vorher, datum_nachher},
    )
    assert len(nachher["nachtraege"]) == 1

    pfad = client.post(
        "/api/task",
        json={
            "titel": "A99: E2E-Aufgabe",
            "ziel": "T2-Prüfung an einer neu angelegten Aufgabe.",
            "akzeptanz": ["Frontmatter bleibt intakt."],
            "prioritaet": "mittel",
        },
    ).get_json()["path"]
    aufgabe_vorher = client.get("/api/file", query_string={"path": pfad}).get_json()
    aufgabe_inhalt_vorher = _lies(e2e_bundle, pfad)
    datum_vorher = _utc_heute()
    client.post("/api/nachtrag", json={"path": pfad, "text": "T2: Nachtrag zwei."})
    aufgabe_nachher = client.get("/api/file", query_string={"path": pfad}).get_json()
    aufgabe_inhalt_nachher = _lies(e2e_bundle, pfad)
    datum_nachher = _utc_heute()

    assert aufgabe_nachher["frontmatter"] == aufgabe_vorher["frontmatter"]
    assert aufgabe_nachher["frontmatter"]["type"] == "Task"
    assert aufgabe_nachher["frontmatter"]["title"] == "A99: E2E-Aufgabe"
    assert aufgabe_inhalt_nachher.startswith(aufgabe_inhalt_vorher)
    _marker_pruefen(
        aufgabe_inhalt_nachher,
        "T2: Nachtrag zwei.",
        {datum_vorher, datum_nachher},
    )


def test_t7_reset_reproduzierbar(e2e_bundle):
    """T7: Bundle zurücksetzen und erneut fahren → identisches Protokoll."""
    erstes = _fahre_kette(_client(e2e_bundle), e2e_bundle)

    _zuruecksetzen(e2e_bundle)

    # Der Reset stellt den Fixture-Stand wirklich wieder her.
    assert not (e2e_bundle / NEUE_AUFGABE).exists()
    assert not (e2e_bundle / NEUE_WELLE).exists()
    assert _marker_zeilen(_lies(e2e_bundle, AUFGABE_FIXTURE)) == []

    zweites = _fahre_kette(_client(e2e_bundle), e2e_bundle)
    assert zweites == erstes


# --- T3/Isolation: echtes Bundle bleibt unberührt -------------------------


def test_t3_echtes_wissen_bleibt_unberuehrt(e2e_bundle):
    """Hash-Nachweis wie A17: `/content/pmTool/wissen` vor/nach dem Lauf identisch."""
    if not WISSEN.is_dir():
        pytest.skip(
            "Isolationsprobe A22/T3 übersprungen: Entwicklungs-Bundle "
            f"{WISSEN} fehlt. Die Probe läuft nur in einem vollständigen "
            "Repo-Checkout mit wissen/; in Installationen ohne Projektwissen "
            "gibt es kein echtes Bundle zu schützen."
        )

    assert e2e_bundle.resolve() != WISSEN.resolve()
    assert WISSEN.resolve() not in e2e_bundle.resolve().parents

    dateien_vorher = _baum_dateien(WISSEN)
    hash_vorher = _baum_hash(WISSEN)
    assert dateien_vorher, "wissen/ darf nicht leer sein"

    _fahre_kette(_client(e2e_bundle), e2e_bundle)

    assert _baum_dateien(WISSEN) == dateien_vorher
    assert _baum_hash(WISSEN) == hash_vorher
