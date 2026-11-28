"""TDD-Tests für das Freigabe-Fundament (A28, Paket 0).

``freigabe`` ist ein **Menschen-Recht**: Der Menschen-Kanal
(``POST /api/freigabe`` → :func:`freigabe.setzen` mit ``herkunft=MENSCH``)
schreibt das boolesche Frontmatter-Feld, der KI-Kanal (``meta.setzen``,
``POST /api/meta``) liefert 403 und schreibt nichts. Gelesen wird fail-closed
(``is True``). Alle Läufe arbeiten gegen das ``bundle``-Fixture (``tmp_path``).
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
PROJEKT = "projekt/phasen.md"

PROJEKT_INHALT = "---\ntype: Projekt\ntitle: \"Phasen\"\n---\n\n# Phasen\n\nText.\n"


@pytest.fixture()
def client(bundle):
    return server.create_app(bundle).test_client()


def _lies(bundle, pfad: str) -> str:
    with open(bundle / pfad, encoding="utf-8", newline="") as datei:
        return datei.read()


def _datei_hash(bundle, pfad: str) -> str:
    return hashlib.sha256(_lies(bundle, pfad).encode("utf-8")).hexdigest()


def _body_hash(bundle, pfad: str) -> str:
    body = okf_bundle.lesen(pfad)[1]
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _bestand(bundle) -> list[str]:
    return sorted(pfad.relative_to(bundle).as_posix() for pfad in bundle.rglob("*"))


def _aussen(bundle) -> list[str]:
    return sorted(pfad.name for pfad in bundle.parent.iterdir() if pfad.name != bundle.name)


def _mit_freigabe(bundle, pfad: str, wert: bool) -> Path:
    ziel = bundle / pfad
    text = ziel.read_text(encoding="utf-8")
    if "freigabe:" in text:
        zeilen = [
            f"freigabe: {'true' if wert else 'false'}" if zeile.startswith("freigabe:") else zeile
            for zeile in text.splitlines()
        ]
        ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    else:
        kopf, rest = text.split("\n---\n", 1)
        ziel.write_text(
            f"{kopf}\nfreigabe: {'true' if wert else 'false'}\n---\n{rest}", encoding="utf-8"
        )
    return ziel


def _schreibe_aufgabe_mit_freigabe(bundle, freigabe_zeile: str) -> Path:
    ziel = bundle / AUFGABE
    ziel.write_text(
        "---\n"
        "type: Task\n"
        'title: "A1: Mini-Aufgabe"\n'
        "task_status: offen\n"
        f"{freigabe_zeile}\n"
        "---\n\n"
        "# Ziel\n\nFixture.\n",
        encoding="utf-8",
    )
    return ziel


def _spy_set_meta(monkeypatch) -> list:
    aufrufe = []
    original = okf_bundle.set_meta

    def zaehlend(*args, **kwargs):
        aufrufe.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(okf_bundle, "set_meta", zaehlend)
    return aufrufe


# --- T8: fail-closed lesen ------------------------------------------------


@pytest.mark.parametrize(
    "frontmatter,erwartet",
    [
        ({}, False),
        ({"freigabe": True}, True),
        ({"freigabe": False}, False),
        ({"freigabe": "true"}, False),
        ({"freigabe": "ja"}, False),
        ({"freigabe": 1}, False),
        ({"freigabe": 0}, False),
        ({"freigabe": None}, False),
        ({"freigabe": ""}, False),
        ([], False),
        (None, False),
    ],
)
def test_t8_ist_freigegeben_fail_closed(frontmatter, erwartet):
    assert freigabe.ist_freigegeben(frontmatter) is erwartet


@pytest.mark.parametrize("rohwert", ['"true"', '"ja"', "1", "0"])
def test_t8_ungueltiger_rohwert_wird_gemeldet(client, bundle, rohwert):
    _schreibe_aufgabe_mit_freigabe(bundle, f"freigabe: {rohwert}")

    eintrag = {
        eintrag["path"]: eintrag for eintrag in client.get("/api/aufgaben").get_json()
    }[AUFGABE]
    detail = client.get(f"/api/file?path={AUFGABE}").get_json()

    assert eintrag["freigabe"] is False
    assert eintrag["freigabe_hinweis"].strip()
    assert "unerwarteten Wert" in eintrag["freigabe_hinweis"]
    assert str(bundle) not in eintrag["freigabe_hinweis"]
    assert detail["freigabe"] is False
    assert detail["freigabe_hinweis"] == eintrag["freigabe_hinweis"]


# --- T9/T10: Menschen-Kanal und KI-Verweigerung --------------------------


def test_t9_setzen_ueber_den_menschen_kanal(bundle, monkeypatch):
    aufrufe = _spy_set_meta(monkeypatch)
    body_vorher = _body_hash(bundle, AUFGABE)
    vorher = okf_bundle.lesen(AUFGABE)[0]

    frontmatter = freigabe.setzen(AUFGABE, True, herkunft=freigabe.MENSCH)

    assert frontmatter["freigabe"] is True
    assert len(aufrufe) == 1
    inhalt = _lies(bundle, AUFGABE)
    assert [zeile for zeile in inhalt.splitlines() if zeile.startswith("freigabe:")] == [
        "freigabe: true"
    ]
    assert _body_hash(bundle, AUFGABE) == body_vorher
    nachher = okf_bundle.lesen(AUFGABE)[0]
    for schluessel, wert in vorher.items():
        assert nachher[schluessel] == wert


@pytest.mark.parametrize("herkunft", [freigabe.KI, None, "", "mensch", "MENSCHLICH"])
@pytest.mark.parametrize("wert", [True, False])
def test_t10_ki_kanal_verweigert(bundle, monkeypatch, herkunft, wert):
    # Ausgangslage ist jeweils der Gegenwert: ein Schreibvorgang wäre byte-sichtbar.
    # Auch ``wert=False`` darf der KI-Weg nie schreiben (A28-AK-6, fail-closed).
    _mit_freigabe(bundle, AUFGABE, not wert)
    aufrufe = _spy_set_meta(monkeypatch)
    hash_vorher = _datei_hash(bundle, AUFGABE)

    with pytest.raises(meta.RechteFehler):
        freigabe.setzen(AUFGABE, wert, herkunft=herkunft)

    assert aufrufe == []
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


@pytest.mark.parametrize("wert", ["true", "ja", 1, 0, None, [], {}])
def test_t11_nur_echtes_bool(bundle, monkeypatch, wert):
    aufrufe = _spy_set_meta(monkeypatch)
    hash_vorher = _datei_hash(bundle, AUFGABE)

    with pytest.raises(okf_bundle.EingabeFehler):
        freigabe.setzen(AUFGABE, wert, herkunft=freigabe.MENSCH)

    assert aufrufe == []
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


# --- T12: Zielprüfung ----------------------------------------------------


def test_t12_aufgabe_und_welle_sind_zulaessig(bundle):
    assert freigabe.setzen(AUFGABE, True, herkunft=freigabe.MENSCH)["freigabe"] is True
    assert freigabe.setzen(WELLE, True, herkunft=freigabe.MENSCH)["freigabe"] is True


@pytest.mark.parametrize("pfad", ["index.md", "log.md", "features.md", "wellen/index.md"])
def test_t12_reservierte_ziele_sind_403(bundle, pfad):
    if not (bundle / pfad).exists():
        (bundle / pfad).parent.mkdir(parents=True, exist_ok=True)
        (bundle / pfad).write_text("---\ntype: Welle\ntitle: Index\n---\n", encoding="utf-8")
    hash_vorher = _datei_hash(bundle, pfad)

    with pytest.raises(meta.RechteFehler):
        freigabe.setzen(pfad, True, herkunft=freigabe.MENSCH)

    assert _datei_hash(bundle, pfad) == hash_vorher


def test_t12_fremde_datei_ist_eingabefehler(bundle):
    (bundle / PROJEKT).parent.mkdir(parents=True, exist_ok=True)
    (bundle / PROJEKT).write_text(PROJEKT_INHALT, encoding="utf-8")
    vorher = (bundle / PROJEKT).read_bytes()

    with pytest.raises(okf_bundle.EingabeFehler):
        freigabe.setzen(PROJEKT, True, herkunft=freigabe.MENSCH)

    assert (bundle / PROJEKT).read_bytes() == vorher


def test_t12_fehlende_datei_ist_404(bundle):
    with pytest.raises(FileNotFoundError):
        freigabe.setzen("aufgaben/gibtsnicht.md", True, herkunft=freigabe.MENSCH)

    assert not (bundle / "aufgaben/gibtsnicht.md").exists()


@pytest.mark.parametrize("pfad", ["../wellen/w1.md", "/etc/passwd", ""])
def test_t12_pfadfehler(bundle, pfad):
    bestand_vorher = _bestand(bundle)
    aussen_vorher = _aussen(bundle)

    with pytest.raises((okf_bundle.BundlePfadFehler, okf_bundle.EingabeFehler)):
        freigabe.setzen(pfad, True, herkunft=freigabe.MENSCH)

    assert _bestand(bundle) == bestand_vorher
    assert _aussen(bundle) == aussen_vorher


# --- T13/T14: Idempotenz und Entziehen ----------------------------------


@pytest.mark.parametrize("wert", [True, False])
def test_t13_unveraenderter_wert_ist_kein_schreibvorgang(bundle, monkeypatch, wert):
    _mit_freigabe(bundle, AUFGABE, wert)
    aufrufe = _spy_set_meta(monkeypatch)
    hash_vorher = _datei_hash(bundle, AUFGABE)
    mtime_vorher = (bundle / AUFGABE).stat().st_mtime_ns

    frontmatter = freigabe.setzen(AUFGABE, wert, herkunft=freigabe.MENSCH)

    assert frontmatter["freigabe"] is wert
    assert aufrufe == []
    assert _datei_hash(bundle, AUFGABE) == hash_vorher
    assert (bundle / AUFGABE).stat().st_mtime_ns == mtime_vorher


def test_t14_freigabe_entziehen(bundle):
    _mit_freigabe(bundle, AUFGABE, True)
    body_vorher = _body_hash(bundle, AUFGABE)

    frontmatter = freigabe.setzen(AUFGABE, False, herkunft=freigabe.MENSCH)

    assert frontmatter["freigabe"] is False
    inhalt = _lies(bundle, AUFGABE)
    assert inhalt.count("\nfreigabe:") == 1
    assert "freigabe: false" in inhalt
    assert _body_hash(bundle, AUFGABE) == body_vorher


# --- T15: meta-Guard ----------------------------------------------------


@pytest.mark.parametrize("wert", [True, False])
def test_t15_meta_modul_verweigert_freigabe(bundle, monkeypatch, wert):
    aufrufe = _spy_set_meta(monkeypatch)
    hash_vorher = _datei_hash(bundle, AUFGABE)

    with pytest.raises(meta.RechteFehler):
        meta.setzen(AUFGABE, freigabe=wert)

    assert aufrufe == []
    assert _datei_hash(bundle, AUFGABE) == hash_vorher


@pytest.mark.parametrize(
    "daten",
    [
        {"freigabe": True},
        {"freigabe": False},
        {"freigabe": "true"},
        {"freigabe": None},
        {"owner": "mensch", "freigabe": True},
    ],
)
def test_t15_api_meta_verweigert_freigabe(client, bundle, daten):
    hash_vorher = _datei_hash(bundle, AUFGABE)
    owner_vorher = okf_bundle.lesen(AUFGABE)[0].get("owner")

    antwort = client.post("/api/meta", json={"path": AUFGABE, **daten})

    assert antwort.status_code == 403
    assert antwort.mimetype == "application/json"
    assert antwort.get_json()["error"].strip()
    assert _datei_hash(bundle, AUFGABE) == hash_vorher
    assert okf_bundle.lesen(AUFGABE)[0].get("owner") == owner_vorher


# --- T16/T17: Endpunkt setzt und entzieht -------------------------------


def test_t16_endpunkt_setzt_die_freigabe(client, bundle):
    body_vorher = _body_hash(bundle, AUFGABE)

    antwort = client.post("/api/freigabe", json={"path": AUFGABE, "wert": True})

    assert antwort.status_code == 200
    assert antwort.mimetype == "application/json"
    daten = antwort.get_json()
    assert daten["path"] == AUFGABE
    assert daten["freigabe"] is True
    assert daten["frontmatter"]["freigabe"] is True
    assert "freigabe: true" in _lies(bundle, AUFGABE)
    assert _body_hash(bundle, AUFGABE) == body_vorher

    eintraege = {eintrag["path"]: eintrag for eintrag in client.get("/api/aufgaben").get_json()}
    assert eintraege[AUFGABE]["freigabe"] is True
    detail = client.get(f"/api/file?path={AUFGABE}").get_json()
    assert detail["freigabe"] is True

    welle_index = client.post("/api/freigabe", json={"path": WELLE, "wert": True})
    assert welle_index.status_code == 200
    assert client.get(f"/api/file?path={WELLE}").get_json()["freigabe"] is True


def test_t17_endpunkt_entzieht_die_freigabe(client, bundle):
    client.post("/api/freigabe", json={"path": AUFGABE, "wert": True})
    body_vorher = _body_hash(bundle, AUFGABE)

    antwort = client.post("/api/freigabe", json={"path": AUFGABE, "wert": False})

    assert antwort.status_code == 200
    assert antwort.get_json()["freigabe"] is False
    inhalt = _lies(bundle, AUFGABE)
    assert inhalt.count("\nfreigabe:") == 1
    assert "freigabe: false" in inhalt
    assert _body_hash(bundle, AUFGABE) == body_vorher


# --- T18: Endpunkt-Validierung -----------------------------------------


@pytest.mark.parametrize(
    "daten,code",
    [
        ({"path": AUFGABE}, 400),
        ({"path": AUFGABE, "wert": "true"}, 400),
        ({"path": AUFGABE, "wert": 1}, 400),
        ({"path": AUFGABE, "wert": None}, 400),
        ({"path": AUFGABE, "wert": []}, 400),
        ({"wert": True}, 400),
        ({"path": "", "wert": True}, 400),
        ({"path": 42, "wert": True}, 400),
        ({}, 400),
        ({"path": PROJEKT, "wert": True}, 400),
        ({"path": "aufgaben/gibtsnicht.md", "wert": True}, 404),
        ({"path": "features.md", "wert": True}, 403),
    ],
)
def test_t18_endpunkt_validierung(client, bundle, daten, code):
    (bundle / PROJEKT).parent.mkdir(parents=True, exist_ok=True)
    (bundle / PROJEKT).write_text(PROJEKT_INHALT, encoding="utf-8")
    hash_vorher = _datei_hash(bundle, AUFGABE)
    bestand_vorher = _bestand(bundle)

    antwort = client.post("/api/freigabe", json=daten)

    assert antwort.status_code == code
    assert antwort.mimetype == "application/json"
    fehler = antwort.get_json()["error"]
    assert fehler.strip()
    assert str(bundle) not in fehler
    assert "Errno" not in fehler
    assert _datei_hash(bundle, AUFGABE) == hash_vorher
    assert _bestand(bundle) == bestand_vorher


def test_t18_get_ist_405(client):
    antwort = client.get("/api/freigabe")

    assert antwort.status_code == 405
    assert antwort.mimetype == "application/json"


# --- T19: Atomarität ----------------------------------------------------


def test_t19_zwei_requests_ein_schluessel(client, bundle, monkeypatch):
    aufrufe = _spy_set_meta(monkeypatch)
    body_vorher = _body_hash(bundle, AUFGABE)

    erst = client.post("/api/freigabe", json={"path": AUFGABE, "wert": True})
    zweit = client.post("/api/freigabe", json={"path": AUFGABE, "wert": False})

    assert erst.status_code == 200
    assert zweit.status_code == 200
    assert len(aufrufe) == 2
    inhalt = _lies(bundle, AUFGABE)
    assert inhalt.count("\nfreigabe:") == 1
    assert "freigabe: false" in inhalt
    assert _body_hash(bundle, AUFGABE) == body_vorher


# --- T20/T21: Endpunkt-Inventar und Signale ---------------------------


def test_t20_endpunkt_inventar(client):
    regeln = {
        regel.rule
        for regel in client.application.url_map.iter_rules()
        if regel.rule.startswith("/api/")
    }

    assert regeln == {
        "/api/overview",
        "/api/file",
        "/api/aufgaben",
        "/api/wellen",
        "/api/nachtrag",
        "/api/task",
        "/api/welle",
        "/api/meta",
        "/api/freigabe",
    }


def test_t21_signale_ohne_neuen_endpunkt(client):
    # ``freigabe`` erscheint im Read-Modell, ohne dass es einen Schreib-Endpunkt
    # dafür in den Listen gibt: nur /api/freigabe ist neu.
    eintraege = client.get("/api/aufgaben").get_json()

    assert all("freigabe" in eintrag for eintrag in eintraege if eintrag["typ"] == "Task")
    assert client.get("/api/aufgaben/neu").status_code in (404, 405)


# --- T22: Neuanlage schreibt den Default ------------------------------


def test_t22_neue_welle_ist_nicht_freigegeben(bundle):
    import neu_welle

    pfad = neu_welle.anlegen(
        {"titel": "Welle X", "ziel": "Ziel.", "status": "Offen", "owner": "ai"}
    )

    frontmatter = okf_bundle.lesen(pfad)[0]
    assert frontmatter["freigabe"] is False
    assert freigabe.ist_freigegeben(frontmatter) is False
