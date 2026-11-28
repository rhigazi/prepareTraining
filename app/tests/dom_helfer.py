"""Gemeinsamer Mini-DOM-Harness für die UI-Tests (Node, keine Abhängigkeit).

Der Harness enthält nur den generischen Teil: Node-Runner, Mini-DOM und die
Auswerte-Helfer für ``liste.js``/``detail.js``. Seiten- und Fetch-Gerüste
bleiben in den jeweiligen Testdateien.

Dies ist die **konsolidierte Quelle** (extrahiert aus ``test_welle_zuordnung.py``,
vierte Kopie; [A14-6]). Alle UI-Testdateien nutzen ausschließlich diesen Harness
und legen keine weitere Kopie an; seiten- und fetch-spezifische Gerüste bleiben
in den jeweiligen Testdateien.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = APP_DIR / "static"
LISTE_JS = STATIC_DIR / "js" / "liste.js"
DETAIL_JS = STATIC_DIR / "js" / "detail.js"

NODE = shutil.which("node")

ohne_node = pytest.mark.skipif(NODE is None, reason="node nicht verfügbar")


def lies(pfad: Path) -> str:
    """Liest eine Datei als Text; fehlende Dateien sind ein Testfehler."""
    assert pfad.is_file(), f"{pfad} fehlt"
    return pfad.read_text(encoding="utf-8")


def node_ausfuehren(skript: str) -> dict:
    """Führt ein Node-Skript aus und liest das JSON-Ergebnis aus stdout."""
    assert NODE is not None
    ergebnis = subprocess.run(
        [NODE, "--input-type=module", "-e", skript],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    return json.loads(ergebnis.stdout)


def js_liste(ausdruck: str, daten=None):
    """Wertet einen Ausdruck im Kontext von ``liste.js`` über Node aus."""
    skript = (
        f"import * as liste from {json.dumps(LISTE_JS.as_uri())};\n"
        f"const daten = {json.dumps(daten, ensure_ascii=False)};\n"
        f"console.log(JSON.stringify({ausdruck}));"
    )
    return node_ausfuehren(skript)


def js_detail(ausdruck: str, daten=None):
    """Wertet einen Ausdruck im Kontext von ``detail.js`` über Node aus."""
    skript = (
        f"import * as detail from {json.dumps(DETAIL_JS.as_uri())};\n"
        f"const daten = {json.dumps(daten, ensure_ascii=False)};\n"
        f"console.log(JSON.stringify({ausdruck}));"
    )
    return node_ausfuehren(skript)


MINI_DOM = r"""
const REGISTRIERT = new Map();
const ALLE = [];

class Knoten {
  constructor(marke, art) {
    this.marke = marke;
    this.art = art;
    this.kinder = [];
    this.attribute = {};
    this.dataset = {};
    this.hoerer = {};
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.type = "";
    this.scope = "";
    this.href = "";
    this.htmlFor = "";
    this.title = "";
    this._text = "";
    this._eltern = null;
    this._imDokument = false;
    const knoten = this;
    this.classList = {
      add: (...namen) => {
        const vorhanden = new Set(knoten.klassen());
        for (const name of namen) vorhanden.add(name);
        knoten.attribute.class = [...vorhanden].join(" ");
      },
      remove: (...namen) => {
        const weg = new Set(namen);
        knoten.attribute.class = knoten.klassen().filter((name) => !weg.has(name)).join(" ");
      },
      contains: (name) => knoten.klassen().includes(name),
      toggle: (name, an) => {
        const soll = an === undefined ? !knoten.classList.contains(name) : Boolean(an);
        if (soll) {
          knoten.classList.add(name);
        } else {
          knoten.attribute.class = knoten.klassen().filter((wert) => wert !== name).join(" ");
        }
      },
    };
    ALLE.push(this);
  }

  klassen() {
    return (this.attribute.class || "").split(/\s+/).filter(Boolean);
  }

  get className() {
    return this.attribute.class || "";
  }

  set className(wert) {
    this.attribute.class = String(wert);
  }

  get textContent() {
    if (this.kinder.length === 0) return this._text;
    return this.kinder.map((kind) => kind.textContent).join("");
  }

  set textContent(wert) {
    this._text = String(wert);
    this.kinder = [];
  }

  get id() {
    return this.attribute.id || "";
  }

  set id(wert) {
    this.attribute.id = wert;
    REGISTRIERT.set(wert, this);
  }

  get parentElement() {
    return this._eltern;
  }

  get options() {
    return this.kinder.filter((kind) => kind.marke === "option");
  }

  get isConnected() {
    let knoten = this;
    while (knoten._eltern) knoten = knoten._eltern;
    return knoten._imDokument === true;
  }

  setAttribute(name, wert) {
    this.attribute[name] = wert;
  }

  getAttribute(name) {
    return this.attribute[name] ?? null;
  }

  removeAttribute(name) {
    delete this.attribute[name];
  }

  addEventListener(art, hoerer) {
    if (!this.hoerer[art]) this.hoerer[art] = [];
    this.hoerer[art].push(hoerer);
  }

  /** Löst ``art`` wie im Browser aus; ``target``/``type``/``preventDefault`` sind gesetzt. */
  async ausloesen(art, ereignis = {}) {
    const ausgeloest = { target: this, type: art, preventDefault() {}, ...ereignis };
    const rueckgaben = (this.hoerer[art] || []).map((hoerer) => hoerer(ausgeloest));
    await Promise.all(rueckgaben);
  }

  append(...kinder) {
    for (const kind of kinder) {
      if (kind.art === "fragment") {
        for (const teil of kind.kinder) this.append(teil);
      } else {
        kind._eltern = this;
        this.kinder.push(kind);
      }
    }
  }

  insertBefore(neu, bezug) {
    neu._eltern = this;
    const index = this.kinder.indexOf(bezug);
    if (index === -1) this.kinder.push(neu);
    else this.kinder.splice(index, 0, neu);
    return neu;
  }

  replaceChildren(...kinder) {
    this.kinder = [];
    this._text = "";
    this.append(...kinder);
  }

  remove() {
    if (!this._eltern) return;
    this._eltern.kinder = this._eltern.kinder.filter((kind) => kind !== this);
    this._eltern = null;
  }

  createTHead() {
    const kopf = document.createElement("thead");
    this.append(kopf);
    return kopf;
  }

  createTBody() {
    const koerper = document.createElement("tbody");
    this.append(koerper);
    return koerper;
  }

  insertRow() {
    const zeile = document.createElement("tr");
    this.append(zeile);
    return zeile;
  }

  focus() {
    globalThis.document.activeElement = this;
  }

  alleKnoten() {
    const liste = [this];
    for (const kind of this.kinder) liste.push(...kind.alleKnoten());
    return liste;
  }
}

globalThis.document = {
  createElement: (marke) => new Knoten(marke, "element"),
  createTextNode: (text) => {
    const knoten = new Knoten("#text", "text");
    knoten._text = String(text);
    return knoten;
  },
  createDocumentFragment: () => new Knoten("#fragment", "fragment"),
  getElementById: (id) => REGISTRIERT.get(id) || null,
  querySelectorAll: (auswahl) => {
    const name = auswahl.replace(/^\./, "");
    return ALLE.filter((knoten) => knoten.classList.contains(name));
  },
  addEventListener: () => {},
  readyState: "complete",
  activeElement: null,
};

const sammle = (el) => [el, ...(el?.kinder ?? []).flatMap(sammle)];
const bei = (id) => document.getElementById(id);
const ausloesen = async (knoten, art) => knoten.ausloesen(art);
const optionen = (el) => (el ? el.kinder.filter((kind) => kind.marke === "option") : []);
const optionstexte = (el) => optionen(el).map((kind) => kind.textContent);
const optionenwerte = (el) => optionen(el).map((kind) => kind.value);
const marken = (el) => sammle(el).map((knoten) => knoten.marke);
const pfade = (id) =>
  sammle(bei(id))
    .filter((knoten) => knoten.marke === "tr" && knoten.dataset.path)
    .map((knoten) => knoten.dataset.path);
const kopfzeilen = (id) =>
  sammle(bei(id))
    .filter((knoten) => knoten.marke === "th")
    .map((knoten) => knoten.textContent);
const anzahl = (id, element_id) => sammle(bei(id)).filter((knoten) => knoten.id === element_id).length;
const sichtbar = (id) => document.getElementById(id)?.hidden === false;
const links = (id) =>
  sammle(bei(id))
    .filter((knoten) => knoten.marke === "a")
    .map((knoten) => ({ text: knoten.textContent, href: knoten.href }));
const knotenMitKlasse = (id, klasse) =>
  sammle(bei(id)).filter((knoten) => knoten.classList.contains(klasse));
"""
