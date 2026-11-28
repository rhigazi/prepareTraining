"""TDD-Tests für die Wellen-Freigabe (A29, Paket 1: Read-Modell + Gate).

Eine Welle ist standardmäßig **nicht freigegeben** (fail-closed). Für eine
Aufgabe gilt die wirksame Freigabe als UND aus eigener Freigabe und – falls eine
Welle zugeordnet ist – deren Freigabe. Der Freigabe-Pfad (``POST /api/freigabe``)
schreibt in die Wellen-Datei ausschließlich das Feld ``freigabe`` (Menschen-Kanal
aus A28); der A11/A27-Schreibpfad (``POST /api/meta``) darf weiterhin
``owner``/``status``/``welle`` schreiben.

Alle Läufe arbeiten gegen das ``bundle``-Fixture (``tmp_path``).
"""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import freigabe
import meta
import okf_bundle
import server

AUFGABE = "aufgaben/a1.md"
WELLE = "wellen/w1.md"
WELLE_2 = "wellen/w2.md"
PROJEKT = "projekt/phasen.md"

PROJEKT_INHALT = "---\ntype: Projekt\ntitle: \"Phasen\"\n---\n\n# Phasen\n\nText.\n"


@pytest.fixture()
def client(bundle):
    return server.create_app(bundle).test_client()


def _schreibe(bundle, pfad: str, text: str) -> Path:
    ziel = bundle / pfad
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    return ziel


def _welle(bundle, pfad: str = WELLE, freigabe_zeile: str | None = None) -> Path:
    zeilen = [
        "---",
        "type: Welle",
        'title: "Welle 1: Fixture"',
        "description: Fixture-Welle.",
        "status: Offen",
        "owner: ai",
    ]
    if freigabe_zeile is not None:
        zeilen.append(f"freigabe: {freigabe_zeile}")
    zeilen += ["---", "", "# Ziel", "", "Fixture-Ziel der Welle.", "", "# Aufgaben", ""]
    return _schreibe(bundle, pfad, "\n".join(zeilen))


def _aufgabe(bundle, welle: str | None = None, freigabe_zeile: str | None = None) -> Path:
    zeilen = [
        "---",
        "type: Task",
        'title: "A1: Mini-Aufgabe"',
        "task_status: in Umsetzung",
        "owner: ai",
    ]
    if welle is not None:
        zeilen.append(f"welle: {welle}")
    if freigabe_zeile is not None:
        zeilen.append(f"freigabe: {freigabe_zeile}")
    zeilen += ["---", "", "# Ziel", "", "Fixture-Ziel.", ""]
    return _schreibe(bundle, AUFGABE, "\n".join(zeilen))


def _lies(bundle, pfad: str) -> str:
    with open(bundle / pfad, encoding="utf-8", newline="") as datei:
        return datei.read()


def _hash(bundle, pfad: str) -> str:
    return hashlib.sha256(_lies(bundle, pfad).encode("utf-8")).hexdigest()


def _body_hash(bundle, pfad: str) -> str:
    return hashlib.sha256(okf_bundle.lesen(pfad)[1].encode("utf-8")).hexdigest()


def _aussen(bundle) -> list[str]:
    return sorted(pfad.name for pfad in bundle.parent.iterdir() if pfad.name != bundle.name)


def _eintraege(client, endpunkt: str = "/api/wellen") -> dict:
    return {eintrag["path"]: eintrag for eintrag in client.get(endpunkt).get_json()}


def _detail(client, pfad: str = AUFGABE) -> dict:
    return client.get(f"/api/file?path={pfad}").get_json()


# --- A. Read-Modell (AK-1, AK-2) ----------------------------------------


def test_t1_default_ist_nicht_freigegeben(client, bundle):
    wellen = _eintraege(client)
    uebersicht = _eintraege(client, "/api/overview")

    assert wellen[WELLE]["typ"] == "Welle"
    assert wellen[WELLE]["freigabe"] is False
    assert "freigabe_hinweis" not in wellen[WELLE]
    assert uebersicht[WELLE]["freigabe"] is False
    assert uebersicht[AUFGABE]["freigabe"] is False


def test_t2_freigegeben_und_explizit_false(client, bundle):
    _welle(bundle, WELLE, "true")
    _welle(bundle, WELLE_2, "false")

    wellen = _eintraege(client)
    uebersicht = _eintraege(client, "/api/overview")

    assert wellen[WELLE]["freigabe"] is True
    assert uebersicht[WELLE]["freigabe"] is True
    assert "freigabe_hinweis" not in wellen[WELLE]
    assert wellen[WELLE_2]["freigabe"] is False
    assert "freigabe_hinweis" not in wellen[WELLE_2]


@pytest.mark.parametrize("rohwert", ['"ja"', '"true"', "1", "0", "null"])
def test_t3_ungueltiger_wert_ist_fail_closed(client, bundle, rohwert):
    _welle(bundle, WELLE, rohwert)

    wellen = _eintraege(client)
    eintrag = wellen[WELLE]

    assert eintrag["freigabe"] is False
    assert eintrag["freigabe_hinweis"].strip()
    assert "unerwarteten Wert" in eintrag["freigabe_hinweis"]
    assert str(bundle) not in eintrag["freigabe_hinweis"]
    # Kein stilles Weglassen, Stammfelder unverändert.
    assert eintrag["typ"] == "Welle"
    assert eintrag["titel"] == "Welle 1: Fixture"
    assert eintrag["status"] == "Offen"
    assert eintrag["owner"] == "ai"


# --- B. Endpunkt/Rechte für Wellen (AK-7, AK-8) -------------------------


def test_t4_wellen_freigabe_setzen(client, bundle, monkeypatch):
    aufrufe = []
    original = okf_bundle.set_meta

    def zaehlend(*args, **kwargs):
        aufrufe.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(okf_bundle, "set_meta", zaehlend)
    body_vorher = _body_hash(bundle, WELLE)
    aufgaben_vorher = _eintraege(client, "/api/aufgaben")

    antwort = client.post("/api/freigabe", json={"path": WELLE, "wert": True})

    assert antwort.status_code == 200
    daten = antwort.get_json()
    assert daten["path"] == WELLE
    assert daten["freigabe"] is True
    assert daten["frontmatter"]["freigabe"] is True
    assert len(aufrufe) == 1
    inhalt = _lies(bundle, WELLE)
    assert [zeile for zeile in inhalt.splitlines() if zeile.startswith("freigabe:")] == [
        "freigabe: true"
    ]
    assert _body_hash(bundle, WELLE) == body_vorher
    # Join-Beleg: die Lese-API spiegelt den Zustand sofort.
    assert _eintraege(client)[WELLE]["freigabe"] is True
    assert _eintraege(client, "/api/aufgaben") == aufgaben_vorher


def test_t5_entziehen_und_konsistenz(client, bundle):
    _welle(bundle, WELLE, "true")
    aufgaben_teil = _lies(bundle, WELLE).split("# Aufgaben")[1]
    body_vorher = _body_hash(bundle, WELLE)
    vorher = okf_bundle.lesen(WELLE)[0]

    antwort = client.post("/api/freigabe", json={"path": WELLE, "wert": False})

    assert antwort.status_code == 200
    assert antwort.get_json()["freigabe"] is False
    inhalt = _lies(bundle, WELLE)
    assert inhalt.count("\nfreigabe:") == 1
    assert "freigabe: false" in inhalt
    assert inhalt.split("# Aufgaben")[1] == aufgaben_teil
    assert _body_hash(bundle, WELLE) == body_vorher
    nachher = okf_bundle.lesen(WELLE)[0]
    for schluessel in ("type", "title", "description", "status", "owner"):
        assert nachher[schluessel] == vorher[schluessel]


def test_t6_ki_kanal_verweigert_wellen(client, bundle, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(okf_bundle, "set_meta", lambda *a, **k: aufrufe.append((a, k)))
    hash_vorher = _hash(bundle, WELLE)

    api = client.post("/api/meta", json={"path": WELLE, "freigabe": True})
    with pytest.raises(meta.RechteFehler):
        meta.setzen(WELLE, freigabe=True)
    with pytest.raises(meta.RechteFehler):
        freigabe.setzen(WELLE, True, herkunft=freigabe.KI)

    assert api.status_code == 403
    assert api.get_json()["error"].strip()
    assert aufrufe == []
    assert _hash(bundle, WELLE) == hash_vorher


def test_t7_ziel_und_eingabefehler(client, bundle):
    (bundle / PROJEKT).parent.mkdir(parents=True, exist_ok=True)
    (bundle / PROJEKT).write_text(PROJEKT_INHALT, encoding="utf-8")
    if not (bundle / "wellen/index.md").exists():
        _welle(bundle, "wellen/index.md")
    aussen_vorher = _aussen(bundle)
    hash_vorher = _hash(bundle, WELLE)

    faelle = [
        ({"path": "wellen/index.md", "wert": True}, 403),
        ({"path": "wellen/gibtsnicht.md", "wert": True}, 404),
        ({"path": "wellen/../aufgaben/a1.md", "wert": True}, 400),
        ({"path": "/etc/passwd", "wert": True}, 400),
        ({"path": "", "wert": True}, 400),
        ({"path": WELLE}, 400),
        ({"path": WELLE, "wert": "true"}, 400),
        ({"path": WELLE, "wert": 1}, 400),
        ({"path": WELLE, "wert": None}, 400),
        ({"path": PROJEKT, "wert": True}, 400),
    ]
    for daten, code in faelle:
        antwort = client.post("/api/freigabe", json=daten)
        assert antwort.status_code == code, daten
        fehler = antwort.get_json()["error"]
        assert fehler.strip()
        assert str(bundle) not in fehler
        assert "Errno" not in fehler

    assert _aussen(bundle) == aussen_vorher
    assert _hash(bundle, WELLE) == hash_vorher


# --- C. Wirksame Freigabe im Detail (AK-3) -----------------------------


@pytest.mark.parametrize(
    "wellen_freigabe,erwartet",
    [(True, True), (False, False), (None, False)],
)
def test_t8_welle_freigabe_im_detail(client, bundle, wellen_freigabe, erwartet):
    _aufgabe(bundle, WELLE, "true")
    _welle(bundle, WELLE, None if wellen_freigabe is None else str(wellen_freigabe).lower())

    daten = _detail(client)

    assert daten["welle_freigabe"] is erwartet
    assert daten["wirksam_freigegeben"] is erwartet


def test_t8_ohne_welle_ist_welle_freigabe_null(client, bundle):
    _aufgabe(bundle, freigabe_zeile="true")

    daten = _detail(client)

    assert "welle_freigabe" in daten
    assert daten["welle_freigabe"] is None
    assert daten["wirksam_freigegeben"] is True


@pytest.mark.parametrize(
    "aufgabe_freigabe,wellen_freigabe,erwartet",
    [
        ("true", "true", True),
        ("true", "false", False),
        ("false", "true", False),
        ("false", "false", False),
    ],
)
def test_t9_und_matrix(client, bundle, aufgabe_freigabe, wellen_freigabe, erwartet):
    _aufgabe(bundle, WELLE, aufgabe_freigabe)
    _welle(bundle, WELLE, wellen_freigabe)

    daten = _detail(client)

    assert daten["welle_freigabe"] is (wellen_freigabe == "true")
    assert daten["wirksam_freigegeben"] is erwartet


@pytest.mark.parametrize(
    "aufgabe_freigabe,erwartet", [("true", True), ("false", False), (None, False)]
)
def test_t9_ohne_welle_gilt_nur_die_aufgaben_freigabe(client, bundle, aufgabe_freigabe, erwartet):
    _aufgabe(bundle, None, aufgabe_freigabe)

    daten = _detail(client)

    assert daten["welle_freigabe"] is None
    assert daten["wirksam_freigegeben"] is erwartet


def test_t9_verschwundene_welle_ist_gesperrt(client, bundle):
    _aufgabe(bundle, "wellen/geloescht.md", "true")

    daten = _detail(client)

    assert daten["welle_freigabe"] is None
    assert daten["wirksam_freigegeben"] is False


def test_t10_abgrenzung_nicht_tasks(client, bundle):
    _welle(bundle, WELLE, "true")
    (bundle / PROJEKT).parent.mkdir(parents=True, exist_ok=True)
    (bundle / PROJEKT).write_text(PROJEKT_INHALT, encoding="utf-8")

    for pfad in (WELLE, PROJEKT):
        daten = _detail(client, pfad)
        for feld in ("welle_freigabe", "wirksam_freigegeben", "neu", "kennung", "naechste_kennung"):
            assert feld not in daten, (pfad, feld)
        assert {"frontmatter", "markdown", "nachtraege"} <= set(daten)


def test_t10_welle_zeigt_auf_aufgabe_ist_gesperrt(client, bundle):
    # ``welle`` zeigt auf eine Aufgabe, nicht auf eine Welle → fail-closed.
    _aufgabe(bundle, AUFGABE, "true")

    daten = _detail(client)

    assert daten["welle_freigabe"] is None
    assert daten["wirksam_freigegeben"] is False


# --- D. A27-Konsistenz und Neuanlage (AK-7) ----------------------------


def test_t11_wellen_datei_nur_freigabe_geaendert(client, bundle):
    _welle(bundle, WELLE, "false")
    aufgaben_vorher = _eintraege(client, "/api/aufgaben")
    wellen_vorher = client.get("/api/wellen").get_json()
    body_vorher = _body_hash(bundle, WELLE)
    kopf_vorher = _lies(bundle, WELLE).split("\n---\n")[0].splitlines()

    client.post("/api/freigabe", json={"path": WELLE, "wert": True})

    inhalt = _lies(bundle, WELLE)
    kopf_nachher = inhalt.split("\n---\n")[0].splitlines()
    assert _body_hash(bundle, WELLE) == body_vorher
    assert [zeile for zeile in kopf_nachher if not zeile.startswith("freigabe:")] == [
        zeile for zeile in kopf_vorher if not zeile.startswith("freigabe:")
    ]
    assert _eintraege(client, "/api/aufgaben") == aufgaben_vorher
    # Wellenliste: Reihenfolge und Bestandsfelder unverändert, nur freigabe neu.
    wellen_nachher = client.get("/api/wellen").get_json()
    assert [eintrag["path"] for eintrag in wellen_nachher] == [
        eintrag["path"] for eintrag in wellen_vorher
    ]
    for vorher, nachher in zip(wellen_vorher, wellen_nachher, strict=True):
        # ``zuletzt_geaendert`` ändert sich durch den Schreibvorgang; alle anderen
        # Bestandsfelder bleiben gleich.
        for feld in ("path", "typ", "titel", "status", "owner"):
            assert nachher[feld] == vorher[feld]
        assert nachher["freigabe"] is True


def test_t12_neue_welle_ist_nicht_freigegeben(bundle):
    import neu_welle

    pfad = neu_welle.anlegen(
        {"titel": "Welle A29", "ziel": "Ziel.", "status": "Offen", "owner": "ai"}
    )

    frontmatter = okf_bundle.lesen(pfad)[0]
    assert frontmatter["freigabe"] is False
    assert freigabe.ist_freigegeben(frontmatter) is False
