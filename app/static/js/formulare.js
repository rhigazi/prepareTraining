import {
  getJson,
  loescheFehler,
  loescheMeldung,
  postJson,
  zeigeFehler,
  zeigeMeldung,
} from "./api.js";
import { ladeAufgaben, ladeWellen } from "./liste.js";

const CONTAINER_AUFGABE_ID = "formular-aufgabe";
const CONTAINER_WELLE_ID = "formular-welle";

const KEINE_ANGABE = "—";
const FORMAT_FEHLER = "Antwort hat ein unerwartetes Format.";
const AUFGABE_ERFOLG = "Aufgabe angelegt.";
const WELLE_ERFOLG = "Welle angelegt.";
const KURZKONTEXT_BESCHRIFTUNG = "Kurzkontext für die KI-Übergabe";

// Whitelists der Anlege-API (A4/A5); Spiegel der Formular-Auswahlen.
export const PRIORITAETEN = ["hoch", "mittel", "niedrig"];
export const WELLEN_STATUS_WERTE = [
  "Klarung",
  "Offen",
  "In Arbeit",
  "Testing",
  "Dokumentation",
  "Geschlossen",
];
export const OWNER_WERTE = ["mensch", "ai"];

const FELD_FEHLER = {
  titel: "Bitte einen Titel eingeben.",
  ziel: "Bitte ein Ziel eingeben.",
  akzeptanz: "Bitte mindestens ein Akzeptanzkriterium eingeben.",
  prioritaet: "Bitte eine Priorität wählen.",
  prioritaetUngueltig: "Unzulässige Priorität.",
  status: "Bitte einen Status wählen.",
  statusUngueltig: "Unzulässiger Status.",
  owner: "Bitte einen owner wählen.",
  ownerUngueltig: "Unzulässiger owner.",
};

// --- Reine Logik (Validierung, Payload, Kurzkontext) -----------------------

function text(wert) {
  return typeof wert === "string" ? wert.trim() : "";
}

/** Zerlegt das mehrzeilige Akzeptanzfeld in je ein Kriterium pro Zeile. */
export function teileAkzeptanz(wert) {
  if (typeof wert !== "string") return [];
  return wert
    .split(/\r?\n/)
    .map((zeile) => zeile.trim())
    .filter((zeile) => zeile.length > 0);
}

/** Prüft die Pflichtfelder des Formulars „Aufgabe"; Fehlertexte je Feld. */
export function validiereAufgabe({ titel, ziel, akzeptanz, prioritaet } = {}) {
  const fehler = {};
  if (!text(titel)) fehler.titel = FELD_FEHLER.titel;
  if (!text(ziel)) fehler.ziel = FELD_FEHLER.ziel;
  if (teileAkzeptanz(akzeptanz).length === 0) fehler.akzeptanz = FELD_FEHLER.akzeptanz;
  const prioritaetWert = text(prioritaet);
  if (!prioritaetWert) fehler.prioritaet = FELD_FEHLER.prioritaet;
  else if (!PRIORITAETEN.includes(prioritaetWert)) fehler.prioritaet = FELD_FEHLER.prioritaetUngueltig;
  return { ok: Object.keys(fehler).length === 0, fehler };
}

/**
 * Payload für `POST /api/task`. Ohne Pfadfeld: Slug/Kollision entstehen
 * serverseitig (R2). Optionale Felder (R10) werden nur gesendet, wenn sie
 * einen Wert haben — `null` bzw. weggelassen heißt „nicht gesetzt".
 */
export function erstelleAufgabePayload({ titel, ziel, akzeptanz, prioritaet, welle, user_story } = {}) {
  const daten = {
    titel: text(titel),
    ziel: text(ziel),
    akzeptanz: teileAkzeptanz(akzeptanz),
    prioritaet: text(prioritaet),
  };
  const wellePfad = text(welle);
  if (wellePfad) daten.welle = wellePfad;
  const story = text(user_story);
  if (story) daten.user_story = story;
  return daten;
}

/** Prüft die Pflichtfelder des Formulars „Welle"; Fehlertexte je Feld. */
export function validiereWelle({ titel, ziel, status, owner } = {}) {
  const fehler = {};
  if (!text(titel)) fehler.titel = FELD_FEHLER.titel;
  if (!text(ziel)) fehler.ziel = FELD_FEHLER.ziel;
  const statusWert = text(status);
  if (!statusWert) fehler.status = FELD_FEHLER.status;
  else if (!WELLEN_STATUS_WERTE.includes(statusWert)) fehler.status = FELD_FEHLER.statusUngueltig;
  const ownerWert = text(owner);
  if (!ownerWert) fehler.owner = FELD_FEHLER.owner;
  else if (!OWNER_WERTE.includes(ownerWert)) fehler.owner = FELD_FEHLER.ownerUngueltig;
  return { ok: Object.keys(fehler).length === 0, fehler };
}

/** Payload für `POST /api/welle`; ebenfalls ohne Pfadfeld (R2). */
export function erstelleWellePayload({ titel, ziel, status, owner } = {}) {
  return {
    titel: text(titel),
    ziel: text(ziel),
    status: text(status),
    owner: text(owner),
  };
}

/** Kopierbarer Kurzkontext für die KI-Übergabe (US-3: Titel, Pfad, Ziel). */
export function erstelleKurzkontext({ titel, pfad, ziel } = {}) {
  return `Titel: ${text(titel)}\nPfad: ${text(pfad)}\nZiel: ${text(ziel)}`;
}

/**
 * Liest den Pfad aus einer Anlege-Antwort. Alles ohne String-`path` ist eine
 * unerwartete Antwort und liefert `null` (fail-loud im Aufrufer).
 */
export function leseAngelegtenPfad(antwort) {
  if (antwort === null || typeof antwort !== "object" || Array.isArray(antwort)) return null;
  const pfad = antwort.path;
  return typeof pfad === "string" && pfad.trim() ? pfad.trim() : null;
}

// --- Formularaufbau --------------------------------------------------------

const FELDER_AUFGABE = [
  { id: "aufgabe-titel", name: "titel", beschriftung: "Titel", art: "text", fehlerId: "aufgabe-fehler-titel" },
  { id: "aufgabe-ziel", name: "ziel", beschriftung: "Ziel", art: "textarea", zeilen: 3, fehlerId: "aufgabe-fehler-ziel" },
  {
    id: "aufgabe-akzeptanz",
    name: "akzeptanz",
    beschriftung: "Akzeptanzkriterien (eine pro Zeile)",
    art: "textarea",
    zeilen: 4,
    fehlerId: "aufgabe-fehler-akzeptanz",
  },
  {
    id: "aufgabe-prioritaet",
    name: "prioritaet",
    beschriftung: "Priorität",
    art: "auswahl",
    optionen: PRIORITAETEN,
    fehlerId: "aufgabe-fehler-prioritaet",
  },
  { id: "aufgabe-welle", name: "welle", beschriftung: "Welle (optional)", art: "auswahl", optionen: [] },
  { id: "aufgabe-user-story", name: "user_story", beschriftung: "User Story (optional)", art: "text" },
];

const FELDER_WELLE = [
  { id: "welle-titel", name: "titel", beschriftung: "Titel", art: "text", fehlerId: "welle-fehler-titel" },
  {
    id: "welle-ziel",
    name: "ziel",
    beschriftung: "Ziel/Beschreibung",
    art: "textarea",
    zeilen: 3,
    fehlerId: "welle-fehler-ziel",
  },
  {
    id: "welle-status",
    name: "status",
    beschriftung: "Status",
    art: "auswahl",
    optionen: WELLEN_STATUS_WERTE,
    fehlerId: "welle-fehler-status",
  },
  {
    id: "welle-owner",
    name: "owner",
    beschriftung: "owner",
    art: "auswahl",
    optionen: OWNER_WERTE,
    fehlerId: "welle-fehler-owner",
  },
];

const FORMULAR_AUFGABE = {
  formular: "aufgabe-formular",
  beschriftung: "Neue Aufgabe anlegen",
  knopf: "aufgabe-anlegen",
  knopfText: "Aufgabe anlegen",
  erfolg: "aufgabe-erfolg",
  kurzkontext: "aufgabe-kurzkontext",
  endpunkt: "/api/task",
  erfolgsmeldung: AUFGABE_ERFOLG,
  felder: FELDER_AUFGABE,
  validieren: validiereAufgabe,
  erstellePayload: erstelleAufgabePayload,
  nachErfolg: ladeAufgaben,
};

const FORMULAR_WELLE = {
  formular: "welle-formular",
  beschriftung: "Neue Welle anlegen",
  knopf: "welle-anlegen",
  knopfText: "Welle anlegen",
  erfolg: "welle-erfolg",
  kurzkontext: "welle-kurzkontext",
  endpunkt: "/api/welle",
  erfolgsmeldung: WELLE_ERFOLG,
  felder: FELDER_WELLE,
  validieren: validiereWelle,
  erstellePayload: erstelleWellePayload,
  nachErfolg: ladeWellen,
};

function fuelleAuswahl(auswahl, optionen) {
  auswahl.replaceChildren();
  for (const [wert, beschriftung] of optionen) {
    const option = document.createElement("option");
    option.value = wert;
    option.textContent = beschriftung;
    auswahl.append(option);
  }
}

function erstelleEingabe(feld) {
  if (feld.art === "textarea") {
    const eingabe = document.createElement("textarea");
    eingabe.rows = feld.zeilen ?? 3;
    return eingabe;
  }
  if (feld.art === "auswahl") {
    const auswahl = document.createElement("select");
    const optionen = [["", KEINE_ANGABE]];
    for (const wert of feld.optionen ?? []) optionen.push([wert, wert]);
    fuelleAuswahl(auswahl, optionen);
    return auswahl;
  }
  const eingabe = document.createElement("input");
  eingabe.type = "text";
  return eingabe;
}

function erstelleEingabeFeld(feld, eingabe) {
  const feldBereich = document.createElement("div");
  feldBereich.className = "formular-feld";
  const beschriftung = document.createElement("label");
  beschriftung.htmlFor = feld.id;
  beschriftung.textContent = feld.beschriftung;
  feldBereich.append(beschriftung, eingabe);
  return feldBereich;
}

function erstelleFeldfehler(id) {
  const fehler = document.createElement("p");
  fehler.id = id;
  fehler.className = "feldfehler";
  fehler.setAttribute("role", "alert");
  fehler.hidden = true;
  return fehler;
}

function erstelleDetailLink(pfad) {
  const link = document.createElement("a");
  link.href = `#/detail/${encodeURIComponent(pfad)}`;
  link.textContent = pfad;
  return link;
}

function anhaengenFeld(angaben, name, inhalt) {
  const bezeichnung = document.createElement("dt");
  bezeichnung.textContent = name;
  const wert = document.createElement("dd");
  if (typeof inhalt === "string") {
    wert.textContent = inhalt;
  } else {
    wert.append(inhalt);
  }
  angaben.append(bezeichnung, wert);
}

function leseWerte(eingaben) {
  const werte = {};
  for (const [name, eingabe] of Object.entries(eingaben)) werte[name] = eingabe.value;
  return werte;
}

/** Zeigt Inline-Fehler je Feld; ohne Fehlermeldung ist das Feld wieder sauber. */
function zeigeFeldfehler(fehlerElemente, fehler) {
  for (const [name, element] of Object.entries(fehlerElemente)) {
    const meldung = fehler[name];
    element.textContent = meldung ?? "";
    element.hidden = !meldung;
  }
}

function fokusAufErstenFehler(eingaben, fehler) {
  for (const name of Object.keys(fehler)) {
    const eingabe = eingaben[name];
    if (!eingabe) continue;
    eingabe.focus();
    return;
  }
}

/** Erfolgsanzeige mit kopierbarem Kurzkontext; Verweise auf Pfad und Welle. */
function zeigeErfolgsanzeige(erfolg, konfiguration, werte, pfad) {
  const hinweis = document.createElement("p");
  hinweis.textContent = konfiguration.erfolgsmeldung;

  const angaben = document.createElement("dl");
  anhaengenFeld(angaben, "Pfad", erstelleDetailLink(pfad));
  if (werte.welle) anhaengenFeld(angaben, "Welle", erstelleDetailLink(werte.welle));

  const beschriftung = document.createElement("label");
  beschriftung.htmlFor = konfiguration.kurzkontext;
  beschriftung.textContent = KURZKONTEXT_BESCHRIFTUNG;

  const kontext = document.createElement("textarea");
  kontext.id = konfiguration.kurzkontext;
  kontext.className = "kurzkontext";
  kontext.readOnly = true;
  kontext.rows = 4;
  kontext.value = erstelleKurzkontext({ titel: werte.titel, pfad, ziel: werte.ziel });

  erfolg.replaceChildren(hinweis, angaben, beschriftung, kontext);
  erfolg.hidden = false;
}

/** Nach Erfolg leeren sich die Textfelder; Auswahlen bleiben für Folgeanlagen. */
function setzeZurueck(eingaben) {
  for (const eingabe of Object.values(eingaben)) {
    if (eingabe.tagName === "SELECT") continue;
    eingabe.value = "";
  }
}

/**
 * Verdrahtet Absenden und Anlegen: Inline-Validierung, Doppelklickschutz
 * (höchstens ein Request), Erfolgsanzeige und Neuladen der zugehörigen Liste.
 */
function verdrahteAnlegen(konfiguration, { formular, knopf, erfolg, eingaben, fehlerElemente }) {
  let laeuft = false;

  formular.addEventListener("submit", async (ereignis) => {
    ereignis.preventDefault();
    // Doppelklickschutz: höchstens ein Request, also höchstens eine Datei (T7).
    if (laeuft) return;

    const werte = leseWerte(eingaben);
    const { ok, fehler } = konfiguration.validieren(werte);
    zeigeFeldfehler(fehlerElemente, fehler);
    if (!ok) {
      fokusAufErstenFehler(eingaben, fehler);
      return; // bei Fehlern entsteht kein Eintrag (T2/T6)
    }

    loescheFehler();
    loescheMeldung();
    erfolg.hidden = true;
    laeuft = true;
    knopf.disabled = true;
    try {
      const antwort = await postJson(konfiguration.endpunkt, konfiguration.erstellePayload(werte));
      if (antwort === null) return; // Fehler zeigt bereits api.js
      const pfad = leseAngelegtenPfad(antwort);
      if (pfad === null) {
        zeigeFehler(FORMAT_FEHLER); // fail-loud bei unerwarteter Antwort
        return;
      }
      zeigeErfolgsanzeige(erfolg, konfiguration, werte, pfad);
      zeigeMeldung(konfiguration.erfolgsmeldung);
      setzeZurueck(eingaben);
      await konfiguration.nachErfolg();
    } finally {
      laeuft = false;
      knopf.disabled = false;
    }
  });
}

function zeichneFormular(ziel, konfiguration) {
  const ueberschrift = document.createElement("h3");
  ueberschrift.className = "formular-ueberschrift";
  ueberschrift.textContent = konfiguration.beschriftung;

  const formular = document.createElement("form");
  formular.id = konfiguration.formular;
  formular.className = "formular";
  formular.setAttribute("aria-label", konfiguration.beschriftung);

  const eingaben = {};
  const fehlerElemente = {};
  for (const feld of konfiguration.felder) {
    const eingabe = erstelleEingabe(feld);
    eingabe.id = feld.id;
    eingabe.name = feld.name;
    eingaben[feld.name] = eingabe;
    formular.append(erstelleEingabeFeld(feld, eingabe));
    if (feld.fehlerId) {
      const fehler = erstelleFeldfehler(feld.fehlerId);
      fehlerElemente[feld.name] = fehler;
      formular.append(fehler);
    }
  }

  const knopf = document.createElement("button");
  knopf.type = "submit";
  knopf.id = konfiguration.knopf;
  knopf.className = "knopf knopf--primaer";
  knopf.textContent = konfiguration.knopfText;
  formular.append(knopf);

  const erfolg = document.createElement("div");
  erfolg.id = konfiguration.erfolg;
  erfolg.className = "formular-erfolg";
  erfolg.setAttribute("role", "status");
  erfolg.hidden = true;

  verdrahteAnlegen(konfiguration, { formular, knopf, erfolg, eingaben, fehlerElemente });
  ziel.replaceChildren(ueberschrift, formular, erfolg);
}

// --- Verdrahtung und Ansichts-Loader --------------------------------------

/** Zeichnet beide Formulare in ihre Container aus index.html (A10). */
export function initialisiereFormulare() {
  const aufgabe = document.getElementById(CONTAINER_AUFGABE_ID);
  if (aufgabe) zeichneFormular(aufgabe, FORMULAR_AUFGABE);
  const welle = document.getElementById(CONTAINER_WELLE_ID);
  if (welle) zeichneFormular(welle, FORMULAR_WELLE);
}

/** Befüllt die Wellen-Auswahl des Aufgabe-Formulars aus `GET /api/wellen`. */
async function ladeWellenAuswahl() {
  const feld = FORMULAR_AUFGABE.felder.find((eintrag) => eintrag.name === "welle");
  const auswahl = feld ? document.getElementById(feld.id) : null;
  if (!auswahl) return;

  const daten = await getJson("/api/wellen");
  if (daten === null) return; // Fehler zeigt bereits api.js
  if (!Array.isArray(daten)) {
    zeigeFehler(FORMAT_FEHLER); // fail-loud statt leere Auswahl
    return;
  }

  const vorher = auswahl.value;
  const optionen = [["", KEINE_ANGABE]];
  for (const eintrag of daten) {
    const pfad = text(eintrag?.path);
    if (!pfad) continue;
    const titel = text(eintrag?.titel);
    // A13-Klein 1: Pfad im Label, damit Titel-Duplikate unterscheidbar bleiben.
    optionen.push([pfad, titel ? `${titel} (${pfad})` : pfad]);
  }
  fuelleAuswahl(auswahl, optionen);
  auswahl.value = optionen.some(([wert]) => wert === vorher) ? vorher : "";
}

/** Ansichts-Loader „Aufgaben": Liste (A11) plus Wellen-Auswahl des Formulars. */
export function ladeAufgabenAnsicht() {
  return Promise.all([ladeAufgaben(), ladeWellenAuswahl()]);
}

/** Ansichts-Loader „Wellen": Liste (A11); das Formular bleibt gezeichnet. */
export function ladeWellenAnsicht() {
  return ladeWellen();
}
