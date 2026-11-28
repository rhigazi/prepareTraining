"""TDD-Tests für den Arbeitsstatus aus ``aktuell`` (A30, Paket 1: Modul + Read-Modell).

Die Ableitung ist reine Logik ohne I/O (:mod:`arbeitsstand`), die Auslieferung
läuft über die Lese-API. Alle API-Läufe arbeiten gegen das ``bundle``-Fixture
(``tmp_path``-Kopie von ``fixtures/bundle_min``); zusätzliche Dateien entstehen
im Test — nie im echten ``wissen/``.
"""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arbeitsstand
import okf_bundle
import server

AUFGABE = "aufgaben/a1.md"
ARBEIT = "aufgaben/a30-arbeit.md"
OHNE = "aufgaben/a30-ohne.md"
WELLE = "wellen/w-aktuell.md"
PROJEKT = "projekt/phase.md"

AKTUELL = "coder: Umsetzung Paket 2"
FELDER = ("arbeitsrolle", "arbeitsrolle_label", "arbeitsstatus")


@pytest.fixture()
def client(bundle):
    return server.create_app(bundle).test_client()


def _schreibe(bundle, pfad: str, text: str) -> Path:
    ziel = bundle / pfad
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    return ziel


def _aufgabe(bundle, pfad: str, aktuell: str | None = AKTUELL, task_status: str = "in Umsetzung"):
    zeilen = [
        "---",
        "type: Task",
        'title: "A30: Arbeitsstatus"',
        f"task_status: {task_status}",
        "owner: ai",
    ]
    if aktuell is not None:
        zeilen.append(f"aktuell: {aktuell!r}")
    zeilen += ["---", "", "# Ziel", "", "Fixture-Ziel.", ""]
    return _schreibe(bundle, pfad, "\n".join(zeilen))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- A. Modul (AK-1, AK-2) ------------------------------------------------


def test_t1_standardfall():
    ergebnis = arbeitsstand.ermittle({"type": "Task", "aktuell": "coder: Umsetzung Paket 2"})

    assert ergebnis == {
        "arbeitsrolle": "coder",
        "arbeitsrolle_label": "Coder",
        "arbeitsstatus": "Umsetzung Paket 2",
    }


@pytest.mark.parametrize(
    "rolle,erwartete_rolle,label",
    [
        ("Planer", "planner", "Planer"),
        ("Coder", "coder", "Coder"),
        ("Tester", "tester", "Tester"),
        ("Review", "reviewer", "Review"),
        ("Reviewer", "reviewer", "Review"),
        ("Documenter", "documenter", "Documenter"),
        ("Doku", "documenter", "Documenter"),
        ("PM", "pm", "PM"),
        ("Projektmanager", "pm", "PM"),
        ("Projektleitung", "pm", "PM"),
    ],
)
def test_t2_rollen_und_aliase(rolle, erwartete_rolle, label):
    ergebnis = arbeitsstand.ermittle({"type": "Task", "aktuell": f"{rolle}: Text"})

    assert ergebnis["arbeitsrolle"] == erwartete_rolle
    assert ergebnis["arbeitsrolle_label"] == label
    assert ergebnis["arbeitsstatus"] == "Text"


@pytest.mark.parametrize("aktuell", ["Umsetzung Paket 2", "Coder"])
def test_t3_ohne_doppelpunkt_ist_nur_text(aktuell):
    ergebnis = arbeitsstand.ermittle({"type": "Task", "aktuell": aktuell})

    assert ergebnis == {"arbeitsstatus": aktuell}


@pytest.mark.parametrize(
    "aktuell,label",
    [("Architekt: Konzept", "Architekt"), ("  Architekt : Konzept ", "Architekt")],
)
def test_t4_unbekannte_rolle_bleibt_originaltext(aktuell, label):
    ergebnis = arbeitsstand.ermittle({"type": "Task", "aktuell": aktuell})

    assert "arbeitsrolle" not in ergebnis
    assert ergebnis["arbeitsrolle_label"] == label
    assert ergebnis["arbeitsstatus"] == "Konzept"


@pytest.mark.parametrize(
    "frontmatter",
    [
        {},
        {"aktuell": ""},
        {"aktuell": "   "},
        {"aktuell": None},
        {"aktuell": 42},
        {"aktuell": True},
        {"aktuell": []},
        {"aktuell": {}},
        None,
        [],
        # A30-R1: MIT gültigem Typ laufen diese Fälle nicht mehr am Typ-Gate
        # vorbei, sondern bis in ``_text`` (Mutante ``str(wert)`` stirbt hier).
        {"type": "Task", "aktuell": 42},
        {"type": "Task", "aktuell": True},
        {"type": "Task", "aktuell": []},
        {"type": "Task", "aktuell": {}},
    ],
)
def test_t5_leer_und_falscher_typ_ohne_anzeige(frontmatter):
    assert arbeitsstand.ermittle(frontmatter) == {}


def test_t6_nur_rolle_und_leere_rolle():
    nur_rolle = arbeitsstand.ermittle({"type": "Task", "aktuell": "Coder:"})
    assert nur_rolle == {"arbeitsrolle": "coder", "arbeitsrolle_label": "Coder"}

    leere_rolle = arbeitsstand.ermittle({"type": "Task", "aktuell": ": Text"})
    assert leere_rolle == {"arbeitsstatus": "Text"}

    assert arbeitsstand.ermittle({"type": "Task", "aktuell": ":"}) == {}


def test_t7_leerraum_wird_normalisiert():
    ergebnis = arbeitsstand.ermittle(
        {"type": "Task", "aktuell": "  Coder :  Umsetzung\nPaket   2 "}
    )

    assert ergebnis["arbeitsrolle"] == "coder"
    assert ergebnis["arbeitsrolle_label"] == "Coder"
    assert ergebnis["arbeitsstatus"] == "Umsetzung Paket 2"

    ohne_text = arbeitsstand.ermittle({"type": "Task", "aktuell": "coder:   "})
    assert ohne_text == {"arbeitsrolle": "coder", "arbeitsrolle_label": "Coder"}


def test_t8_nur_der_erste_doppelpunkt_trennt():
    ergebnis = arbeitsstand.ermittle({"type": "Task", "aktuell": "coder: Fix: Randfall"})

    assert ergebnis["arbeitsrolle"] == "coder"
    assert ergebnis["arbeitsstatus"] == "Fix: Randfall"


def test_t9_nach_abschluss_keine_felder():
    assert (
        arbeitsstand.ermittle(
            {"type": "Task", "task_status": "abgeschlossen", "aktuell": "coder: Rest"}
        )
        == {}
    )
    assert (
        arbeitsstand.ermittle({"type": "Task", "status": "Geschlossen", "aktuell": "coder: Rest"})
        == {}
    )

    aktiv = arbeitsstand.ermittle(
        {"type": "Task", "task_status": "in Umsetzung", "aktuell": "coder: Rest"}
    )
    assert aktiv["arbeitsstatus"] == "Rest"


def test_t9b_nur_tasks_erhalten_felder():
    for typ in ("Welle", "Projekt", "User Story", "unbekannt", None):
        assert (
            arbeitsstand.ermittle({"type": typ, "aktuell": "coder: Umsetzung Paket 2"}) == {}
        ), typ

    assert arbeitsstand.ermittle({"aktuell": "coder: Umsetzung Paket 2"}) == {}


# --- B. Read-Modell (AK-3, AK-7) -----------------------------------------


def _bestand_anlegen(bundle) -> None:
    _aufgabe(bundle, ARBEIT)
    _aufgabe(bundle, OHNE, aktuell=None, task_status="offen")
    _schreibe(
        bundle,
        WELLE,
        "---\ntype: Welle\ntitle: \"Welle mit aktuell\"\nstatus: Offen\nowner: ai\n"
        f"aktuell: {AKTUELL!r}\n---\n\n# Ziel\n\nWelle.\n",
    )
    _schreibe(
        bundle,
        PROJEKT,
        "---\ntype: Projekt\ntitle: \"Phase\"\n"
        f"aktuell: {AKTUELL!r}\n---\n\n# Phase\n\nText.\n",
    )


def test_t10_api_aufgaben_liefert_arbeitsstatus(client, bundle):
    _bestand_anlegen(bundle)

    antwort = client.get("/api/aufgaben")

    assert antwort.status_code == 200
    eintraege = {eintrag["path"]: eintrag for eintrag in antwort.get_json()}
    assert eintraege[ARBEIT]["arbeitsrolle"] == "coder"
    assert eintraege[ARBEIT]["arbeitsrolle_label"] == "Coder"
    assert eintraege[ARBEIT]["arbeitsstatus"] == "Umsetzung Paket 2"
    assert eintraege[OHNE].keys().isdisjoint(FELDER)
    # Bestehende Felder bleiben unverändert.
    assert eintraege[ARBEIT]["typ"] == "Task"
    assert eintraege[ARBEIT]["status"] == "In Arbeit"
    assert eintraege[ARBEIT]["owner"] == "ai"


def test_t11_api_overview_nur_tasks(client, bundle):
    _bestand_anlegen(bundle)

    antwort = client.get("/api/overview")

    assert antwort.status_code == 200
    daten = antwort.get_json()
    assert isinstance(daten, list)
    eintraege = {eintrag["path"]: eintrag for eintrag in daten}

    mit_feldern = {
        pfad for pfad, eintrag in eintraege.items() if not eintrag.keys().isdisjoint(FELDER)
    }
    assert mit_feldern == {ARBEIT}
    assert eintraege[WELLE].keys().isdisjoint(FELDER)
    assert eintraege[PROJEKT].keys().isdisjoint(FELDER)


def test_t12_api_file_liefert_felder_top_level(client, bundle):
    _bestand_anlegen(bundle)
    markdown_vorher = okf_bundle.lesen(ARBEIT)[1]

    antwort = client.get(f"/api/file?path={ARBEIT}")

    assert antwort.status_code == 200
    daten = antwort.get_json()
    # A33-K2: exakte Schlüsselmenge statt „enthalten / enthalten nicht". Der
    # Vertrag von ``/api/file`` für ``type: Task`` umfasst A8 (Basis), A28
    # (``neu``/``kennung``/``naechste_kennung``/``freigabe``), A29
    # (``welle_freigabe``/``wirksam_freigegeben``), A30 (Arbeitsstatus),
    # A35 (``ui_status``/``hinweis``/``owner_default`` — Status-Mapping
    # server-seitig) und A36 (``schreibgeschuetzt`` — Schreib-UI-Grenze).
    # ``freigabe_hinweis`` fehlt hier, weil der Rohwert fehlt/gültig ist —
    # den Ungültig-Fall prüft ``test_freigabe.py``.
    assert set(daten) == {
        "frontmatter",
        "markdown",
        "nachtraege",
        "arbeitsrolle",
        "arbeitsrolle_label",
        "arbeitsstatus",
        "neu",
        "kennung",
        "naechste_kennung",
        "freigabe",
        "welle_freigabe",
        "wirksam_freigegeben",
        "ui_status",
        "hinweis",
        "schreibgeschuetzt",
        "owner_default",
    }
    assert daten["arbeitsrolle"] == "coder"
    assert daten["arbeitsrolle_label"] == "Coder"
    assert daten["arbeitsstatus"] == "Umsetzung Paket 2"
    assert daten["ui_status"] == "In Arbeit"
    assert daten["hinweis"] is None
    assert daten["owner_default"] == "ai"
    # Das Roh-Feld bleibt unverändert erhalten.
    assert daten["frontmatter"]["aktuell"] == AKTUELL
    assert daten["markdown"] == markdown_vorher
    assert daten["nachtraege"] == []


@pytest.mark.parametrize("pfad", [OHNE, WELLE, PROJEKT])
def test_t12_api_file_ohne_arbeitsstatus(client, bundle, pfad):
    _bestand_anlegen(bundle)

    daten = client.get(f"/api/file?path={pfad}").get_json()

    # A28 ergänzt ``freigabe``/``neu``; die A30-Arbeitsstatus-Felder fehlen weiterhin.
    assert set(daten).isdisjoint(FELDER)
    assert {"frontmatter", "markdown", "nachtraege"} <= set(daten)


def test_t13_keine_schreibpfade_und_keine_doppelpflege(client, bundle):
    ziel = _aufgabe(bundle, ARBEIT)
    aktuell_zeile = [
        zeile
        for zeile in ziel.read_text(encoding="utf-8").splitlines()
        if zeile.startswith("aktuell:")
    ]
    assert len(aktuell_zeile) == 1
    vorher = client.get(f"/api/file?path={ARBEIT}").get_json()

    nachtrag = client.post("/api/nachtrag", json={"path": ARBEIT, "text": "Bitte prüfen."})
    meta = client.post("/api/meta", json={"path": ARBEIT, "owner": "mensch", "welle": None})
    unbekannt = client.post("/api/meta", json={"path": ARBEIT, "arbeitsstatus": "x"})

    assert nachtrag.status_code == 200
    assert meta.status_code == 200
    assert unbekannt.status_code == 400

    inhalt = ziel.read_text(encoding="utf-8")
    assert [zeile for zeile in inhalt.splitlines() if zeile.startswith("aktuell:")] == aktuell_zeile
    assert "arbeitsstatus:" not in inhalt
    assert "arbeitsrolle" not in inhalt

    nachher = client.get(f"/api/file?path={ARBEIT}").get_json()
    for feld in FELDER:
        assert nachher[feld] == vorher[feld]
    assert nachher["frontmatter"]["aktuell"] == AKTUELL


def test_t13_ableitung_ist_idempotent(bundle):
    _aufgabe(bundle, ARBEIT)
    vorher = _hash(okf_bundle.lesen(ARBEIT)[1])

    arbeitsstand.ermittle(okf_bundle.lesen(ARBEIT)[0])
    arbeitsstand.ermittle(okf_bundle.lesen(ARBEIT)[0])

    assert _hash(okf_bundle.lesen(ARBEIT)[1]) == vorher
    assert okf_bundle.lesen(ARBEIT)[0]["aktuell"] == AKTUELL
