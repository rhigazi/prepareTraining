/**
 * Unter-Aufgaben im Aufgaben-Detail (A34): Anzeige der Kinder und Anlegen eines
 * Kindes über das bestehende `POST /api/task` (Feld `parent`).
 *
 * Aufbau und Bedienung folgen den A27-Mustern (`erstelleTabelle`,
 * Inline-Formular mit `try/finally`); die Validierung kommt aus `formulare.js`
 * (eine Regelquelle). Ausschließlich `textContent`/`createElement`/`classList`.
 */

import {
  loescheFehler,
  loescheMeldung,
  postJson,
  zeigeFehler,
  zeigeMeldung,
} from "./api.js";
import { erstelleTabelle } from "./liste.js";
import {
  PRIORITAETEN,
  leseAngelegtenPfad,
  teileAkzeptanz,
  validiereAufgabe,
} from "./formulare.js";

const ABSCHNITT_KLASSE = "detail-abschnitt";
const ABSCHNITT_UEBERSCHRIFT_KLASSE = "uebersicht-titel";

const ANLEGEN_ID = "unteraufgabe-anlegen";
const KNOPF_ID = "detail-unteraufgabe-anlegen";
const SPEICHERN_ID = "unteraufgabe-speichern";
const ABBRECHEN_ID = "unteraufgabe-abbrechen";
const FELD_PREFIX = "unteraufgabe-";
const FEHLER_PREFIX = "unteraufgabe-fehler-";

const KNOPF_TEXT = "Unter-Aufgabe anlegen";
const SPEICHERN_TEXT = "Speichern";
const ABBRECHEN_TEXT = "Abbrechen";
const VORGABE_PRIORITAET = "mittel";
const ERFOLG = "Unter-Aufgabe angelegt.";
const FORMAT_FEHLER = "Antwort hat ein unerwartetes Format.";
export const UNTERAUFGABEN_LADE_FEHLER = "Unter-Aufgaben konnten nicht geladen werden.";
export const UNTERAUFGABEN_FORMAT_FEHLER = "Unter-Aufgaben haben ein unerwartetes Format.";

const FELDER = [
  { name: "titel", beschriftung: "Titel", art: "text" },
  { name: "ziel", beschriftung: "Ziel", art: "textarea", zeilen: 3 },
  {
    name: "akzeptanz",
    beschriftung: "Akzeptanzkriterien (eine pro Zeile)",
    art: "textarea",
    zeilen: 4,
  },
  { name: "prioritaet", beschriftung: "Priorität", art: "auswahl", optionen: PRIORITAETEN },
];

// Pfad- und Titel-Kennung tragen die Unter-Nummer (`a34.001-…` bzw. `A34.001: …`).
const NUMER_PFAD = /\/a\d+\.(\d{3})(?:-|\.md$|$)/;
const NUMER_TITEL = /^A\d+\.(\d{3})(?::|$)/;

function text(wert) {
  return typeof wert === "string" ? wert.trim() : "";
}

/** Kinder eines Eltern-Pfades; alles außer einem Array ergibt `[]`. */
export function unteraufgabenVon(eintraege, elternPfad) {
  const pfad = text(elternPfad);
  if (!pfad || !Array.isArray(eintraege)) return [];

  return eintraege.filter((eintrag) => text(eintrag?.parent) === pfad);
}

/** Unter-Nummer einer Aufgabe aus Pfad oder Titel; `null`, wenn nicht erkennbar. */
function unterNummer(eintrag) {
  const pfad = text(eintrag?.path);
  const ausPfad = NUMER_PFAD.exec(pfad);
  if (ausPfad) return Number(ausPfad[1]);

  const ausTitel = NUMER_TITEL.exec(text(eintrag?.titel));
  return ausTitel ? Number(ausTitel[1]) : null;
}

/** Sortiert stabil nach Unter-Nummer, dann `path`; ohne Nummer ans Ende. */
export function sortiereUnteraufgaben(eintraege) {
  if (!Array.isArray(eintraege)) return [];

  return [...eintraege].sort((links, rechts) => {
    const nummerLinks = unterNummer(links);
    const nummerRechts = unterNummer(rechts);
    if (nummerLinks !== nummerRechts) {
      if (nummerLinks === null) return 1;
      if (nummerRechts === null) return -1;
      return nummerLinks - nummerRechts;
    }
    return text(links?.path).localeCompare(text(rechts?.path));
  });
}

function erstelleHinweis(inhalt) {
  const hinweis = document.createElement("p");
  hinweis.className = "leer";
  hinweis.textContent = inhalt;
  return hinweis;
}

/**
 * Abschnitt „Unter-Aufgaben (n)" für ein Eltern-Detail; `null` ohne Kinder.
 * Ladefehler und unerwartete Antworten bleiben sichtbar (fail-loud) — nur eine
 * erfolgreich geladene leere Liste bedeutet „keine Kinder".
 */
export function erstelleUnteraufgabenSicht(pfad, aufgaben) {
  const eintraege = Array.isArray(aufgaben?.eintraege) ? aufgaben.eintraege : null;
  const fehler = text(aufgaben?.fehler);
  const treffer =
    eintraege === null ? [] : sortiereUnteraufgaben(unteraufgabenVon(eintraege, pfad));

  if (eintraege !== null && !fehler && treffer.length === 0) return null;

  const bereich = document.createElement("section");
  bereich.classList.add(ABSCHNITT_KLASSE);
  bereich.classList.add("uebersicht-block");

  const titel = document.createElement("h3");
  titel.className = ABSCHNITT_UEBERSCHRIFT_KLASSE;
  const gescheitert = Boolean(fehler) || eintraege === null;
  titel.textContent = gescheitert ? "Unter-Aufgaben" : `Unter-Aufgaben (${treffer.length})`;
  bereich.append(titel);

  if (gescheitert) {
    bereich.append(erstelleHinweis(fehler || UNTERAUFGABEN_LADE_FEHLER));
    return bereich;
  }

  bereich.append(erstelleTabelle(treffer));
  return bereich;
}

function erstelleEingabe(feld) {
  if (feld.art === "textarea") {
    const eingabe = document.createElement("textarea");
    eingabe.rows = feld.zeilen ?? 3;
    return eingabe;
  }
  if (feld.art === "auswahl") {
    const auswahl = document.createElement("select");
    for (const wert of feld.optionen ?? []) {
      const option = document.createElement("option");
      option.value = wert;
      option.textContent = wert;
      auswahl.append(option);
    }
    return auswahl;
  }

  const eingabe = document.createElement("input");
  eingabe.type = "text";
  return eingabe;
}

function erstelleFeldfehler(name) {
  const fehler = document.createElement("p");
  fehler.id = `${FEHLER_PREFIX}${name}`;
  fehler.className = "feldfehler";
  fehler.setAttribute("role", "alert");
  fehler.hidden = true;
  return fehler;
}

function leseWerte(eingaben) {
  const werte = {};
  for (const [name, eingabe] of Object.entries(eingaben)) werte[name] = eingabe.value;
  return werte;
}

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

function leereEingaben(eingaben) {
  for (const [name, eingabe] of Object.entries(eingaben)) {
    eingabe.value = name === "prioritaet" ? VORGABE_PRIORITAET : "";
  }
}

/** Payload für `POST /api/task`: `parent` zuletzt, kein `welle`, kein `user_story`. */
export function erstellePayload(werte, pfad) {
  return {
    titel: text(werte?.titel),
    ziel: text(werte?.ziel),
    akzeptanz: teileAkzeptanz(werte?.akzeptanz),
    prioritaet: text(werte?.prioritaet),
    parent: text(pfad),
  };
}

/**
 * Anlege-Bereich (standardmäßig versteckt) und der Knopf für `.detail-aktionen`.
 * `beiErfolg` lädt das Detail neu; das Kind erscheint dann im Abschnitt.
 */
export function erstelleAnlegeSicht(pfad, beiErfolg) {
  const bereich = document.createElement("div");
  bereich.id = ANLEGEN_ID;
  bereich.hidden = true;

  const formular = document.createElement("form");
  formular.className = "formular";
  formular.setAttribute("aria-label", KNOPF_TEXT);

  const eingaben = {};
  const fehlerElemente = {};
  for (const feld of FELDER) {
    const eingabe = erstelleEingabe(feld);
    eingabe.id = `${FELD_PREFIX}${feld.name}`;
    eingabe.name = feld.name;
    eingaben[feld.name] = eingabe;

    const feldBereich = document.createElement("div");
    feldBereich.className = "formular-feld";
    const beschriftung = document.createElement("label");
    beschriftung.htmlFor = eingabe.id;
    beschriftung.textContent = feld.beschriftung;
    feldBereich.append(beschriftung, eingabe);

    const fehler = erstelleFeldfehler(feld.name);
    fehlerElemente[feld.name] = fehler;
    formular.append(feldBereich, fehler);
  }
  eingaben.prioritaet.value = VORGABE_PRIORITAET;

  const speichern = document.createElement("button");
  // `type="button"` plus eigener Klick-Handler: das Detail enthält bereits das
  // Nachtragsformular, und vorhandene Prüfungen identifizieren „den" Submit-Knopf
  // über `type === "submit"` (A12-2). Enter im Formular löst weiterhin `submit` aus.
  speichern.type = "button";
  speichern.id = SPEICHERN_ID;
  speichern.className = "knopf knopf--primaer";
  speichern.textContent = SPEICHERN_TEXT;

  const abbrechen = document.createElement("button");
  abbrechen.type = "button";
  abbrechen.id = ABBRECHEN_ID;
  abbrechen.className = "knopf";
  abbrechen.textContent = ABBRECHEN_TEXT;

  formular.append(speichern, abbrechen);
  bereich.append(formular);

  const knopf = document.createElement("button");
  knopf.type = "button";
  knopf.id = KNOPF_ID;
  knopf.className = "knopf";
  knopf.textContent = KNOPF_TEXT;
  knopf.addEventListener("click", () => {
    bereich.hidden = false;
    eingaben.titel.focus();
  });

  abbrechen.addEventListener("click", () => {
    bereich.hidden = true;
  });

  let laeuft = false;
  async function speichere() {
    // Doppelklickschutz: genau eine Datei je Auslöser (A12-2/A13-Muster).
    if (laeuft) return;

    const werte = leseWerte(eingaben);
    const { ok, fehler } = validiereAufgabe(werte);
    zeigeFeldfehler(fehlerElemente, fehler);
    if (!ok) {
      fokusAufErstenFehler(eingaben, fehler);
      return;
    }

    loescheFehler();
    loescheMeldung();
    laeuft = true;
    speichern.disabled = true;
    knopf.disabled = true;
    try {
      const antwort = await postJson("/api/task", erstellePayload(werte, pfad));
      if (antwort === null) return; // Fehler zeigt bereits api.js
      if (leseAngelegtenPfad(antwort) === null) {
        zeigeFehler(FORMAT_FEHLER); // fail-loud bei unerwarteter Antwort
        return;
      }

      zeigeMeldung(ERFOLG);
      leereEingaben(eingaben);
      zeigeFeldfehler(fehlerElemente, {});
      bereich.hidden = true;
      await beiErfolg();
    } finally {
      laeuft = false;
      speichern.disabled = false;
      knopf.disabled = false;
    }
  }

  speichern.addEventListener("click", speichere);
  formular.addEventListener("submit", (ereignis) => {
    ereignis.preventDefault();
    return speichere();
  });

  return { bereich, knopf };
}
