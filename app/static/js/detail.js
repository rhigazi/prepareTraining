import {
  getJson,
  istDateiAntwort,
  loescheFehler,
  loescheMeldung,
  postJson,
  zeigeFehler,
  zeigeMeldung,
} from "./api.js";
import { erstelleTabelle, formatiereArbeitsstand } from "./liste.js";
import {
  UNTERAUFGABEN_FORMAT_FEHLER,
  UNTERAUFGABEN_LADE_FEHLER,
  erstelleAnlegeSicht,
  erstelleUnteraufgabenSicht,
} from "./unteraufgaben.js";

const CONTAINER_ID = "detail";
const OWNER_AUSWAHL_ID = "detail-owner";
const OWNER_HINWEIS_ID = "detail-owner-hinweis";
const WELLE_AUSWAHL_ID = "detail-welle";
const WELLE_HINWEIS_ID = "detail-welle-hinweis";
const FORMULAR_ID = "nachtrag-formular";
const TEXT_ID = "nachtrag-text";
const FEHLER_ID = "nachtrag-fehler";

const KEINE_ANGABE = "—";
const LEER_KEINE_AUSWAHL = "Keine Datei ausgewählt.";
const LADE_FEHLER = "Datei konnte nicht geladen werden.";
const FORMAT_FEHLER = "Datei hat ein unerwartetes Format.";
const FELD_LEER = "Bitte einen Nachtrag eingeben.";
const NACHRAG_ERFOLG = "Nachtrag gespeichert.";
const OWNER_ERFOLG = "owner gespeichert.";
const STATUS_ERFOLG = "Status gespeichert.";
const OWNER_UNBEKANNT = "unbekannt";
const ZURUECK_ZIEL = "#/uebersicht";

// Wellen-Zuordnung (A27): Feld nur an Aufgaben, Optionen aus `GET /api/wellen`.
const WELLE_KEINE = "keine";
const WELLE_UNBEKANNT = "unbekannt";
const WELLE_ERFOLG = "Welle gespeichert.";
const WELLE_ENTFERNT = "Welle entfernt.";
const WELLEN_LADE_FEHLER = "Wellen konnten nicht geladen werden.";
const WELLEN_FORMAT_FEHLER = "Wellen haben ein unerwartetes Format.";
const AUFGABEN_LADE_FEHLER = "Aufgaben konnten nicht geladen werden.";
const AUFGABEN_FORMAT_FEHLER = "Aufgaben haben ein unerwartetes Format.";
const KEINE_AUFGABEN = "Keine Aufgaben dieser Welle.";
const ABSCHNITT_KLASSE = "detail-abschnitt";
const GESCHLOSSEN = "Geschlossen";

// A28: Kennungs-Hinweis und Freigabe (Menschen-Kanal `POST /api/freigabe`).
const NEU_HINWEIS_ID = "detail-neu-hinweis";
const FREIGABE_ID = "detail-freigabe";
const FREIGABE_STATUS_ID = "detail-freigabe-status";
const NEU_HINWEIS =
  "Neue Aufgabe ohne Kennung — die Kennung wird beim Annehmen als `A<N>: ` " +
  "im Titel ergänzt.";
const FREIGABE_TEXT = "Freigegeben";
const NICHT_FREIGEGEBEN_TEXT = "Nicht freigegeben";
const FREIGABE_ERFOLG = "Aufgabe freigegeben.";
const FREIGABE_ENTZOGEN = "Freigabe entzogen.";

// A29: Wellen-Freigabe (zweite Stufe) und Sperrhinweis im Aufgaben-Detail.
const WELLE_FREIGABE_ID = "detail-welle-freigabe";
const WELLE_FREIGABE_STATUS_ID = "detail-welle-freigabe-status";
const FREIGABE_HINWEIS_ID = "detail-freigabe-hinweis";
const SPERRE_HINWEIS_ID = "detail-sperre-hinweis";
const WELLE_FREIGABE_ERFOLG = "Welle freigegeben.";
const WELLE_FREIGEGEBEN = "freigegeben";
const WELLE_NICHT_FREIGEGEBEN = "nicht freigegeben (Standard)";
const AUFGABEN_ORDNER = "aufgaben/";
const WELLEN_ORDNER = "wellen/";

// A36: Schreib-UI-Grenze — nur der Server entscheidet über `schreibgeschuetzt`.
// Listen haben keine Schreibaktionen; Symlink-Kanten sind dort unkritisch.
const SCHREIBGESCHUETZT_HINWEIS_ID = "detail-schreibgeschuetzt-hinweis";
const SCHREIBGESCHUETZT_HINWEIS =
  "Schreibgeschützt — diese Datei pflegen Projektmanager und documenter (KI).";

// R1: Nur diese beiden Status sind über die UI setzbar; Pipeline-Status nicht.
export const STATUS_KNOEPFE = ["Klarung", "Geschlossen"];
const OWNER_WERTE = ["mensch", "ai"];

// Blockmarker des Minimal-Renderers; `ZAUN` umschließt Codeblöcke.
const ZAUN = "```";
const UEBERSCHRIFT = /^(#{1,6})\s+(.*)$/;
const ZITAT = /^>\s?(.*)$/;
const UNGEORDNET = /^[-*+]\s+(.*)$/;
const GEORDNET = /^\d+[.)]\s+(.*)$/;

// A38: Anker je Überschrift; nur `[a-z0-9-]`, damit IDs und Links sicher sind.
const ANKER_MAX = 80;
const ANKER_FALLBACK = "abschnitt";
const ANKER_KLASSE = "anker-ziel";

function feld(frontmatter, name) {
  if (!frontmatter || typeof frontmatter !== "object") return null;

  const wert = frontmatter[name];
  if (wert === null || wert === undefined) return null;

  const text = String(wert).trim();
  return text || null;
}

/**
 * Zerlegt Markdown in Blocktokens (Überschrift, Absatz, Liste, Code, Zitat).
 * Absichtlich minimal: keine Inline-Auszeichnung, damit das Rendern ohne
 * HTML-Interpretation auskommt (R6).
 */
export function parseMarkdown(markdown) {
  if (typeof markdown !== "string" || !markdown.trim()) return [];

  const zeilen = markdown.split(/\r?\n/);
  const bloecke = [];
  let index = 0;

  while (index < zeilen.length) {
    const geprueft = zeilen[index].trim();
    if (!geprueft) {
      index += 1;
      continue;
    }

    if (geprueft.startsWith(ZAUN)) {
      const code = [];
      index += 1;
      while (index < zeilen.length && !zeilen[index].trim().startsWith(ZAUN)) {
        code.push(zeilen[index]);
        index += 1;
      }
      index += 1;
      bloecke.push({ art: "code", text: code.join("\n") });
      continue;
    }

    const ueberschrift = UEBERSCHRIFT.exec(geprueft);
    if (ueberschrift) {
      bloecke.push({
        art: "ueberschrift",
        ebene: ueberschrift[1].length,
        text: ueberschrift[2].trim(),
      });
      index += 1;
      continue;
    }

    if (ZITAT.test(geprueft)) {
      const zitat = [];
      while (index < zeilen.length) {
        const treffer = ZITAT.exec(zeilen[index].trim());
        if (!treffer) break;
        zitat.push(treffer[1]);
        index += 1;
      }
      bloecke.push({ art: "zitat", text: zitat.join("\n").trimEnd() });
      continue;
    }

    const liste = leseListe(zeilen, index);
    if (liste) {
      bloecke.push(liste.block);
      index = liste.ende;
      continue;
    }

    const absatz = [];
    while (index < zeilen.length && zeilen[index].trim() && !istBlockstart(zeilen[index])) {
      absatz.push(zeilen[index].trim());
      index += 1;
    }
    bloecke.push({ art: "absatz", text: absatz.join(" ") });
  }

  return bloecke;
}

function istBlockstart(zeile) {
  const text = zeile.trim();
  return (
    text.startsWith(ZAUN) ||
    UEBERSCHRIFT.test(text) ||
    ZITAT.test(text) ||
    UNGEORDNET.test(text) ||
    GEORDNET.test(text)
  );
}

function leseListe(zeilen, start) {
  const geprueft = zeilen[start].trim();
  const geordnet = GEORDNET.test(geprueft);
  const muster = geordnet ? GEORDNET : UNGEORDNET;
  if (!muster.test(geprueft)) return null;

  const eintraege = [];
  let index = start;
  while (index < zeilen.length) {
    const treffer = muster.exec(zeilen[index].trim());
    if (!treffer) break;
    eintraege.push(treffer[1].trim());
    index += 1;
  }

  return { block: { art: "liste", geordnet, eintraege }, ende: index };
}

/**
 * Stabiler Anker aus einem Überschriftentext (A38): Umlaute werden
 * umschrieben, alles andere zu `-` zusammengezogen. Das Ergebnis besteht nur
 * aus `[a-z0-9-]` — dadurch ist es als ``id`` und im Link sicher.
 */
export function erstelleAnker(text) {
  const roh = typeof text === "string" ? text : "";
  const ersetzt = roh
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  // Kürzen ohne hängenden Bindestrich; leerer Text bleibt verlinkbar.
  const gekuerzt = ersetzt.slice(0, ANKER_MAX).replace(/-+$/g, "");
  return gekuerzt || ANKER_FALLBACK;
}

/**
 * Vergabe für ein Dokument: gleiche Titel bekommen `-2`, `-3`, … — damit
 * Renderer und Verweise dieselben Anker liefern (A38).
 */
export function erstelleAnkerVergabe() {
  const zaehler = new Map();
  return (text) => {
    const basis = erstelleAnker(text);
    const nummer = (zaehler.get(basis) ?? 0) + 1;
    zaehler.set(basis, nummer);
    return nummer === 1 ? basis : `${basis}-${nummer}`;
  };
}

/** Baut aus Markdown ein DOM-Fragment; alle Texte laufen über `textContent`. */
export function rendereMarkdown(markdown) {
  const fragment = document.createDocumentFragment();
  const anker = erstelleAnkerVergabe();
  for (const block of parseMarkdown(markdown)) {
    const id = block.art === "ueberschrift" ? anker(block.text) : null;
    fragment.append(erstelleBlock(block, id));
  }
  return fragment;
}

/**
 * Sucht die Anker-ID ausschließlich unterhalb von ``bereich`` (A38-K2). Ein
 * Slug wie „detail" oder „fehler" kann mit einer festen Seiten-ID kollidieren;
 * ``getElementById`` würde dann das Seitengerüst statt der Überschrift treffen.
 */
function findeAnker(bereich, id) {
  // Attribut-Selektor statt `#id`: Anker dürfen mit einer Ziffer beginnen.
  if (typeof bereich.querySelectorAll === "function" && /^[a-z0-9-]+$/.test(id)) {
    const treffer = bereich.querySelectorAll(`[id="${id}"]`);
    if (treffer.length > 0) return treffer[0];
  }

  // Rückfall ohne Element-Selektoren (Mini-DOM der Tests): global suchen, aber
  // nur ein Ziel innerhalb des Bereichs akzeptieren.
  const element = document.getElementById(id);
  return element && istImBereich(element, bereich) ? element : null;
}

/** Liegt ``element`` im Teilbaum von ``bereich`` (inklusive ``bereich``)? */
function istImBereich(element, bereich) {
  for (let knoten = element; knoten; knoten = knoten.parentElement) {
    if (knoten === bereich) return true;
  }
  return false;
}

/** Springt zu einem Anker und hebt das Ziel leicht hervor (A38). */
export function springeZuAnker(anker, bereich = null) {
  const ziel = typeof anker === "string" ? anker.trim() : "";
  if (!ziel) return null;

  const element = bereich ? findeAnker(bereich, ziel) : document.getElementById(ziel);
  if (!element) return null;

  // Klasse plus Fokus: die Klasse markiert das Ziel, der Fokusring macht es
  // sichtbar (kein style.css-Eingriff in A38).
  element.classList.add(ANKER_KLASSE);
  element.setAttribute("tabindex", "-1");
  if (typeof element.scrollIntoView === "function") {
    element.scrollIntoView({ block: "start" });
  }
  if (typeof element.focus === "function") element.focus();
  return element;
}

/** Trennt `pfad#anker`; ohne `#` bleibt der Anker leer. */
export function trenneAnker(text) {
  const roh = typeof text === "string" ? text.trim() : "";
  const index = roh.indexOf("#");
  if (index === -1) return { pfad: roh, anker: "" };
  return { pfad: roh.slice(0, index).trim(), anker: roh.slice(index + 1).trim() };
}

function erstelleBlock(block, anker = null) {
  switch (block.art) {
    case "ueberschrift": {
      const ebene = Math.min(Math.max(block.ebene, 1), 6);
      const element = document.createElement(`h${ebene}`);
      element.textContent = block.text;
      if (anker) element.id = anker;
      return element;
    }
    case "liste": {
      const liste = document.createElement(block.geordnet ? "ol" : "ul");
      for (const eintrag of block.eintraege) {
        const punkt = document.createElement("li");
        punkt.textContent = eintrag;
        liste.append(punkt);
      }
      return liste;
    }
    case "code": {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = block.text;
      pre.append(code);
      return pre;
    }
    case "zitat": {
      const zitat = document.createElement("blockquote");
      zitat.textContent = block.text;
      return zitat;
    }
    default: {
      const absatz = document.createElement("p");
      absatz.textContent = block.text;
      return absatz;
    }
  }
}

/** Getrimmter String aus der Server-Antwort; sonst ``null``. */
function serverText(daten, name) {
  const wert = daten?.[name];
  if (typeof wert !== "string") return null;
  const text = wert.trim();
  return text || null;
}

/**
 * UI-Status und Hinweis aus der Server-Ableitung (``status.ui_status``, A35).
 * Ohne Server-Feld gilt „Offen" — es gibt keinen JS-Spiegel der Mapping-Tabelle.
 */
export function ermittleStatus(daten) {
  return {
    status: serverText(daten, "ui_status") ?? "Offen",
    hinweis: serverText(daten, "hinweis"),
  };
}

/** Anzeige-owner aus der Server-Ableitung (R3); Altantworten nutzen das Rohfeld. */
export function ermittleOwner(daten) {
  return serverText(daten, "owner_default") ?? feld(daten?.frontmatter, "owner");
}

/**
 * Payload für `POST /api/meta`: Nicht gesetzte Felder werden weggelassen, weil
 * die API strikt prüft und leere Strings mit 403 abweist. `welle: null` wird
 * mitgeschickt — das ist die Anweisung „Zuordnung entfernen".
 */
export function erstelleMetaPayload(pfad, { owner, status, welle } = {}) {
  const daten = { path: pfad };
  const ownerText = typeof owner === "string" ? owner.trim() : "";
  const statusText = typeof status === "string" ? status.trim() : "";

  if (ownerText) daten.owner = ownerText;
  if (statusText) daten.status = statusText;
  if (welle === null) {
    daten.welle = null;
  } else {
    const welleText = typeof welle === "string" ? welle.trim() : "";
    if (welleText) daten.welle = welleText;
  }
  return daten;
}

/** Payload für `POST /api/nachtrag`; leerer Text ergibt `null` (kein Eintrag). */
export function erstelleNachtragPayload(pfad, text) {
  const inhalt = typeof text === "string" ? text.trim() : "";
  if (!inhalt) return null;
  return { path: pfad, text: inhalt };
}

function erstelleHinweis(text) {
  const hinweis = document.createElement("p");
  hinweis.className = "leer";
  hinweis.textContent = text;
  return hinweis;
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

function erstelleStatusAnzeige(status, hinweis) {
  const anzeige = document.createDocumentFragment();

  const marke = document.createElement("span");
  marke.className = "status";
  if (status === "Klarung") marke.classList.add("status--klarung");
  if (status === "Geschlossen") marke.classList.add("status--geschlossen");
  marke.textContent = status;
  anzeige.append(marke);

  if (hinweis) {
    const zusatz = document.createElement("span");
    zusatz.textContent = ` (${hinweis})`;
    anzeige.append(zusatz);
  }
  return anzeige;
}

/** Lese-Anzeige des owner ohne Bedienung (schreibgeschützte Dateien, A36). */
function erstelleOwnerAnzeige(owner) {
  const anzeige = document.createElement("span");
  anzeige.textContent = owner ?? KEINE_ANGABE;
  return anzeige;
}

function erstelleOwnerAuswahl(pfad, owner) {
  const auswahl = document.createElement("select");
  auswahl.id = OWNER_AUSWAHL_ID;
  auswahl.setAttribute("aria-label", "owner");

  const ohne = document.createElement("option");
  ohne.value = "";
  ohne.textContent = KEINE_ANGABE;
  auswahl.append(ohne);

  for (const wert of OWNER_WERTE) {
    const option = document.createElement("option");
    option.value = wert;
    option.textContent = wert;
    auswahl.append(option);
  }

  // A12-3: unbekannte Werte nicht still verschlucken — eigener Eintrag plus Hinweis.
  const bekannt = OWNER_WERTE.includes(owner);
  const unbekannt = Boolean(owner) && !bekannt;
  if (unbekannt) {
    const option = document.createElement("option");
    option.value = owner;
    option.textContent = `${owner} (${OWNER_UNBEKANNT})`;
    auswahl.append(option);
  }

  auswahl.value = owner ?? "";
  const anzeigewert = auswahl.value;

  auswahl.addEventListener("change", async () => {
    const wert = auswahl.value;
    if (!OWNER_WERTE.includes(wert)) {
      auswahl.value = anzeigewert;
      return;
    }
    if (!(await speichereMeta(pfad, { owner: wert }, OWNER_ERFOLG))) {
      auswahl.value = anzeigewert;
    }
  });

  if (!unbekannt) return auswahl;

  const hinweis = document.createElement("span");
  hinweis.id = OWNER_HINWEIS_ID;
  hinweis.classList.add("hinweis");
  hinweis.textContent = `owner „${owner}" ist ${OWNER_UNBEKANNT}; bitte mensch oder ai wählen.`;

  const bereich = document.createDocumentFragment();
  bereich.append(auswahl, hinweis);
  return bereich;
}

function erstelleWellenOption(wert, beschriftung) {
  const option = document.createElement("option");
  option.value = wert;
  option.textContent = beschriftung;
  return option;
}

/** Ist die Datei eine Aufgabe? `type: Task` oder Altbestand unter `aufgaben/`. */
function istAufgabe(pfad, frontmatter) {
  if (pfad.startsWith(AUFGABEN_ORDNER)) return true;
  return feld(frontmatter, "type") === "Task";
}

/**
 * Wellen-Auswahl im Frontmatter-Kopf; speichert beim Wechsel sofort
 * (`POST /api/meta`), sperrt das Feld während des Requests und rollt bei einem
 * Fehler auf den vorherigen Wert zurück.
 */
function erstelleWellenAuswahl(pfad, welle, wellen) {
  const eintraege = Array.isArray(wellen?.eintraege) ? wellen.eintraege : null;
  const fehler = wellen?.fehler ?? null;

  const auswahl = document.createElement("select");
  auswahl.id = WELLE_AUSWAHL_ID;
  auswahl.setAttribute("aria-label", "Welle");
  auswahl.append(erstelleWellenOption("", WELLE_KEINE));

  const bekannt = new Set();
  for (const eintrag of eintraege ?? []) {
    const wellenPfad = typeof eintrag?.path === "string" ? eintrag.path.trim() : "";
    if (!wellenPfad) continue;
    const titel = typeof eintrag?.titel === "string" ? eintrag.titel.trim() : "";
    // Pfad im Label, damit Titel-Duplikate unterscheidbar bleiben (A13).
    const beschriftung = titel ? `${titel} (${wellenPfad})` : wellenPfad;
    auswahl.append(erstelleWellenOption(wellenPfad, beschriftung));
    bekannt.add(wellenPfad);
  }

  // A12-3-Muster: unbekannte Werte nicht still verschlucken.
  const unbekannt = Boolean(welle) && !bekannt.has(welle);
  if (unbekannt) {
    auswahl.append(erstelleWellenOption(welle, `${welle} (${WELLE_UNBEKANNT})`));
  }

  auswahl.value = welle ?? "";
  const anzeigewert = auswahl.value;
  // Ohne Wellenliste (Fehler/Format) bleibt das Feld gesperrt: kein Blindschreiben.
  const gesperrt = eintraege === null || fehler !== null;
  auswahl.disabled = gesperrt;

  auswahl.addEventListener("change", async () => {
    if (auswahl.disabled) return;
    const entfernen = auswahl.value === "";
    auswahl.disabled = true;
    try {
      const erfolg = await speichereMeta(
        pfad,
        { welle: entfernen ? null : auswahl.value },
        entfernen ? WELLE_ENTFERNT : WELLE_ERFOLG,
      );
      if (!erfolg) auswahl.value = anzeigewert;
    } finally {
      if (!gesperrt) auswahl.disabled = false;
    }
  });

  const hinweise = [];
  if (unbekannt) {
    hinweise.push(
      `Welle „${welle}" ist ${WELLE_UNBEKANNT}; bitte eine Welle wählen oder „${WELLE_KEINE}" setzen.`,
    );
  }
  if (fehler) hinweise.push(fehler);
  if (hinweise.length === 0) return auswahl;

  const hinweis = document.createElement("span");
  hinweis.id = WELLE_HINWEIS_ID;
  hinweis.classList.add("hinweis");
  hinweis.textContent = hinweise.join(" ");

  const bereich = document.createDocumentFragment();
  bereich.append(auswahl, hinweis);
  return bereich;
}

/**
 * Lesbare Wellen-Angabe für gesperrte Aufgaben (A36-K4): gleiches Format wie
 * die Auswahl (`Titel (Pfad)`), damit nur die Bedienung entfällt, nicht die
 * Information. Fehlt der Titel (Liste nicht ladbar, unbekannter Pfad), bleibt
 * der Dateistamm — wie der Fallback in A33-B4, nie der rohe Pfad.
 */
function formatiereWellenAnzeige(welle, wellen) {
  if (!welle) return KEINE_ANGABE;

  const eintraege = Array.isArray(wellen?.eintraege) ? wellen.eintraege : [];
  const treffer = eintraege.find((eintrag) => eintrag?.path === welle);
  const titel = typeof treffer?.titel === "string" ? treffer.titel.trim() : "";
  return titel ? `${titel} (${welle})` : dateistamm(welle);
}

/** Dateiname ohne Ordner und `.md`; bleibt bei ungewöhnlichen Pfaden stabil. */
function dateistamm(pfad) {
  const name = pfad.slice(pfad.lastIndexOf("/") + 1).replace(/\.md$/i, "");
  return name || pfad;
}

function erstelleStatusKnopf(status, aktiv) {
  const knopf = document.createElement("button");
  knopf.type = "button";
  knopf.className = "knopf";
  knopf.dataset.status = status;
  knopf.textContent = status;
  knopf.setAttribute("aria-pressed", aktiv ? "true" : "false");
  if (aktiv) knopf.classList.add("knopf--primaer");
  return knopf;
}

function erstelleAktionen(pfad, status, anlegeKnopf = null, gesperrt = false) {
  const aktionen = document.createElement("div");
  aktionen.className = "detail-aktionen";

  const statusKnoepfe = [];
  if (!gesperrt) {
    for (const wert of STATUS_KNOEPFE) {
      const knopf = erstelleStatusKnopf(wert, wert === status);
      knopf.addEventListener("click", async () => {
        // Parallelklicks sperren: genau eine Schreibaktion je Auslöser (A12-2).
        if (statusKnoepfe.some((kandidat) => kandidat.disabled)) return;
        for (const kandidat of statusKnoepfe) kandidat.disabled = true;
        try {
          await speichereMeta(pfad, { status: wert }, STATUS_ERFOLG);
        } finally {
          for (const kandidat of statusKnoepfe) kandidat.disabled = false;
        }
      });
      statusKnoepfe.push(knopf);
      aktionen.append(knopf);
    }
  }

  if (anlegeKnopf) aktionen.append(anlegeKnopf);

  const zurueck = document.createElement("a");
  zurueck.className = "knopf";
  zurueck.href = ZURUECK_ZIEL;
  zurueck.textContent = "← Zurück zur Übersicht";
  aktionen.append(zurueck);

  return aktionen;
}

/** Fail-closed: nur ein echtes ``freigabe: true`` gilt als freigegeben. */
function istFreigegeben(daten) {
  return daten?.freigabe === true;
}

/**
 * A36: Nur ein echtes ``schreibgeschuetzt: true`` sperrt die Schreib-UI.
 * Die reservierte Namensliste kennt die UI nicht — sie folgt dem Server.
 */
export function istSchreibgeschuetzt(daten) {
  return daten?.schreibgeschuetzt === true;
}

/** Hinweis für Aufgaben ohne Kennung, inkl. nächster freier Kennung (wenn geliefert). */
function erstelleNeuHinweis(daten) {
  const hinweis = document.createElement("p");
  hinweis.id = NEU_HINWEIS_ID;
  hinweis.classList.add("hinweis");

  const kennung = typeof daten?.naechste_kennung === "string" ? daten.naechste_kennung.trim() : "";
  hinweis.textContent = kennung
    ? `${NEU_HINWEIS} Nächste freie Kennung: ${kennung}.`
    : NEU_HINWEIS;
  return hinweis;
}

/** Zustand + Knopf der Freigabe; schreibt über den Menschen-Kanal der App. */
function erstelleFreigabeAnzeige(pfad, daten, gesperrt = false) {
  const freigegeben = istFreigegeben(daten);

  const bereich = document.createDocumentFragment();
  const anzeige = document.createElement("span");
  anzeige.id = FREIGABE_STATUS_ID;
  anzeige.textContent = freigegeben ? FREIGABE_TEXT : NICHT_FREIGEGEBEN_TEXT;
  bereich.append(anzeige);
  // A36: Schreibgeschützte Datei zeigt den Zustand, aber keine Bedienung.
  if (gesperrt) return bereich;

  const knopf = document.createElement("button");
  knopf.type = "button";
  knopf.id = FREIGABE_ID;
  knopf.className = "knopf";
  knopf.textContent = freigegeben ? "Freigabe entziehen" : "Freigeben";
  knopf.addEventListener("click", async () => {
    // Doppelklickschutz: genau eine Schreibaktion je Auslöser (A27-Muster).
    if (knopf.disabled) return;
    knopf.disabled = true;
    try {
      await schreibeFreigabe(pfad, !freigegeben);
    } finally {
      knopf.disabled = false;
    }
  });

  // Abstand zwischen Zustand und Knopf als Textknoten (kein style.css-Eingriff).
  bereich.append(document.createTextNode(" "), knopf);
  return bereich;
}

/** Setzt/entzieht die Freigabe; Fehler zeigt `api.js`, die Ansicht bleibt stehen. */
async function schreibeFreigabe(pfad, wert) {
  loescheFehler();
  loescheMeldung();

  const ergebnis = await postJson("/api/freigabe", { path: pfad, wert });
  if (ergebnis === null) return false;

  zeigeMeldung(wert ? FREIGABE_ERFOLG : FREIGABE_ENTZOGEN);
  await ladeDetail({ unterpunkt: pfad });
  return true;
}

/** Status-Hinweis zu einem ungültigen ``freigabe``-Rohwert (falls geliefert). */
function erstelleFreigabeHinweis(daten) {
  const meldung =
    typeof daten?.freigabe_hinweis === "string" ? daten.freigabe_hinweis.trim() : "";
  if (!meldung) return null;

  const hinweis = document.createElement("span");
  hinweis.id = FREIGABE_HINWEIS_ID;
  hinweis.classList.add("hinweis");
  hinweis.textContent = meldung;
  return hinweis;
}

/**
 * Wellen-Freigabe im Wellen-Detail: Anzeige „Freigabe …" plus ein Knopf über
 * den Menschen-Kanal (``POST /api/freigabe``), Muster wie der Aufgaben-Knopf.
 */
function erstelleWellenFreigabeAnzeige(pfad, daten, gesperrt = false) {
  const freigegeben = istFreigegeben(daten);

  const bereich = document.createDocumentFragment();
  const anzeige = document.createElement("span");
  anzeige.id = WELLE_FREIGABE_STATUS_ID;
  anzeige.textContent = freigegeben ? WELLE_FREIGEGEBEN : WELLE_NICHT_FREIGEGEBEN;
  // A36: Nur lesend — Zustand bleibt, Knopf entfällt.
  if (gesperrt) {
    bereich.append(anzeige);
    const hinweis = erstelleFreigabeHinweis(daten);
    if (hinweis) bereich.append(hinweis);
    return bereich;
  }

  const knopf = document.createElement("button");
  knopf.type = "button";
  knopf.id = WELLE_FREIGABE_ID;
  knopf.className = "knopf";
  knopf.textContent = freigegeben ? "Freigabe entziehen" : "Welle freigeben";
  knopf.addEventListener("click", async () => {
    if (knopf.disabled) return;
    knopf.disabled = true;
    try {
      await schreibeWellenFreigabe(pfad, !freigegeben);
    } finally {
      knopf.disabled = false;
    }
  });

  // Abstände als Textknoten (A28-K3-Rest): kein leeres span-Element.
  bereich.append(
    document.createTextNode(" "),
    anzeige,
    document.createTextNode(" "),
    knopf,
  );

  const hinweis = erstelleFreigabeHinweis(daten);
  if (hinweis) bereich.append(hinweis);
  return bereich;
}

/** Setzt/entzieht die Wellen-Freigabe; Fehler zeigt `api.js`, die Ansicht bleibt. */
async function schreibeWellenFreigabe(pfad, wert) {
  loescheFehler();
  loescheMeldung();

  const ergebnis = await postJson("/api/freigabe", { path: pfad, wert });
  if (ergebnis === null) return false;

  zeigeMeldung(wert ? WELLE_FREIGABE_ERFOLG : FREIGABE_ENTZOGEN);
  await ladeDetail({ unterpunkt: pfad });
  return true;
}

/**
 * Sperrhinweis (A29): sagt, welches Gate fehlt — Aufgabe, Welle oder beides.
 * Erscheint nur, wenn der Server ``wirksam_freigegeben === false`` meldet.
 */
function erstelleSperrHinweis(daten) {
  const hinweis = document.createElement("p");
  hinweis.id = SPERRE_HINWEIS_ID;
  hinweis.classList.add("hinweis");
  hinweis.setAttribute("role", "status");

  const welle = daten?.welle_freigabe;
  const hatWelle =
    typeof daten?.frontmatter?.welle === "string" && daten.frontmatter.welle.trim() !== "";
  const aufgabe = daten?.freigabe === true;
  let grund = "Aufgabe nicht freigegeben.";
  // Wellen-Grund auch bei `null` (fehlende/defekte Wellenreferenz, A29-T1/K1):
  // Hat die Aufgabe eine Welle, ist ein fehlendes Wellen-Gate ein Wellen-Grund —
  // auch ohne Aufgaben-Freigabe. Ohne Wellen-Referenz bleibt die Aufgabe der Grund.
  const welleGesperrt = welle === false || (welle == null && hatWelle);
  if (welleGesperrt) {
    grund = aufgabe
      ? "Welle nicht freigegeben."
      : "Aufgabe und Welle nicht freigegeben.";
  }
  hinweis.textContent = `Umsetzung gesperrt: ${grund}`;
  return hinweis;
}

/** Hinweis auf einer schreibgeschützten Datei (A36): warum fehlen die Aktionen. */
function erstelleSchreibgeschuetztHinweis() {
  const hinweis = document.createElement("p");
  hinweis.id = SCHREIBGESCHUETZT_HINWEIS_ID;
  hinweis.classList.add("hinweis");
  hinweis.setAttribute("role", "status");
  hinweis.textContent = SCHREIBGESCHUETZT_HINWEIS;
  return hinweis;
}

function erstelleKopf(pfad, daten, wellen, anlegeKnopf = null) {
  const frontmatter =
    daten.frontmatter && typeof daten.frontmatter === "object" ? daten.frontmatter : {};
  const { status, hinweis } = ermittleStatus(daten);
  const gesperrt = istSchreibgeschuetzt(daten);

  const kopf = document.createElement("div");
  kopf.className = "detail-kopf";

  const titel = document.createElement("h2");
  titel.className = "ansicht-titel";
  titel.textContent = feld(frontmatter, "title") || pfad;
  kopf.append(titel);

  const angaben = document.createElement("dl");
  anhaengenFeld(angaben, "Typ", feld(frontmatter, "type") || KEINE_ANGABE);
  anhaengenFeld(angaben, "Status", erstelleStatusAnzeige(status, hinweis));
  // Arbeitsstatus (A30): abgeleitet aus `aktuell`, nur wenn vorhanden.
  const arbeitsstand = formatiereArbeitsstand(daten);
  if (arbeitsstand) anhaengenFeld(angaben, "Arbeitsstatus", arbeitsstand);
  const owner = ermittleOwner(daten);
  anhaengenFeld(
    angaben,
    "owner",
    gesperrt ? erstelleOwnerAnzeige(owner) : erstelleOwnerAuswahl(pfad, owner),
  );
  if (istAufgabe(pfad, frontmatter)) {
    const welle = feld(frontmatter, "welle");
    anhaengenFeld(
      angaben,
      "Welle",
      gesperrt
        ? formatiereWellenAnzeige(welle, wellen)
        : erstelleWellenAuswahl(pfad, welle, wellen),
    );
    anhaengenFeld(angaben, "Freigabe", erstelleFreigabeAnzeige(pfad, daten, gesperrt));
  } else if (pfad.startsWith(WELLEN_ORDNER)) {
    anhaengenFeld(
      angaben,
      "Freigabe",
      erstelleWellenFreigabeAnzeige(pfad, daten, gesperrt),
    );
  }
  kopf.append(angaben);
  if (gesperrt) kopf.append(erstelleSchreibgeschuetztHinweis());
  if (istAufgabe(pfad, frontmatter) && daten?.neu === true) {
    kopf.append(erstelleNeuHinweis(daten));
  }
  if (istAufgabe(pfad, frontmatter) && daten?.wirksam_freigegeben === false) {
    kopf.append(erstelleSperrHinweis(daten));
  }
  kopf.append(erstelleAktionen(pfad, status, anlegeKnopf, gesperrt));

  return kopf;
}

/**
 * Wellen-Sicht (AK-10/AK-11): Aufgaben werden ausschließlich aus dem
 * `welle`-Feld abgeleitet (`GET /api/aufgaben`); die Wellen-Datei bleibt
 * unangetastet.
 */
function erstelleAufgabenSicht(pfad, aufgaben) {
  if (!pfad.startsWith(WELLEN_ORDNER)) return null;

  const eintraege = Array.isArray(aufgaben?.eintraege) ? aufgaben.eintraege : [];
  const fehler = aufgaben?.fehler ?? null;
  const treffer = eintraege.filter(
    (eintrag) => typeof eintrag?.welle === "string" && eintrag.welle.trim() === pfad,
  );

  const bereich = document.createElement("section");
  bereich.classList.add(ABSCHNITT_KLASSE);
  bereich.classList.add("uebersicht-block");

  const titel = document.createElement("h3");
  titel.className = "uebersicht-titel";
  titel.textContent = `Aufgaben dieser Welle (${treffer.length})`;
  bereich.append(titel);

  if (fehler) {
    bereich.append(erstelleHinweis(fehler));
    return bereich;
  }
  if (treffer.length === 0) {
    bereich.append(erstelleHinweis(KEINE_AUFGABEN));
    return bereich;
  }
  bereich.append(erstelleTabelle(treffer));
  return bereich;
}

function erstelleInhalt(markdown) {
  const inhalt = document.createElement("div");
  inhalt.className = "detail-inhalt";
  inhalt.append(rendereMarkdown(markdown));
  return inhalt;
}

function erstelleNachtragFormular(pfad) {
  const formular = document.createElement("form");
  formular.id = FORMULAR_ID;
  formular.className = "formular";
  formular.setAttribute("aria-label", "Nachtrag einfügen");

  const feldBereich = document.createElement("div");
  feldBereich.className = "formular-feld";

  const beschriftung = document.createElement("label");
  beschriftung.htmlFor = TEXT_ID;
  beschriftung.textContent = "Nachtrag einfügen";

  const eingabe = document.createElement("textarea");
  eingabe.id = TEXT_ID;
  eingabe.name = "text";
  eingabe.className = "kurzkontext";
  eingabe.rows = 4;

  feldBereich.append(beschriftung, eingabe);

  const fehler = document.createElement("p");
  fehler.id = FEHLER_ID;
  fehler.className = "feldfehler";
  fehler.setAttribute("role", "alert");
  fehler.hidden = true;

  const knopf = document.createElement("button");
  knopf.type = "submit";
  knopf.className = "knopf knopf--primaer";
  knopf.textContent = "Nachtrag speichern";

  formular.append(feldBereich, fehler, knopf);

  formular.addEventListener("submit", async (ereignis) => {
    ereignis.preventDefault();
    // Doppeltes Absenden sperren: genau ein Eintrag je Klick (A12-2).
    if (knopf.disabled) return;

    const daten = erstelleNachtragPayload(pfad, eingabe.value);
    if (daten === null) {
      fehler.textContent = FELD_LEER;
      fehler.hidden = false;
      eingabe.focus();
      return;
    }

    fehler.textContent = "";
    fehler.hidden = true;
    loescheFehler();
    loescheMeldung();

    knopf.disabled = true;
    try {
      const ergebnis = await postJson("/api/nachtrag", daten);
      if (ergebnis === null) return;

      zeigeMeldung(NACHRAG_ERFOLG);
      await ladeDetail({ unterpunkt: pfad });
    } finally {
      knopf.disabled = false;
    }
  });

  return formular;
}

/** Schreibt `owner`/`status`; Fehler zeigt bereits `api.js`, die Ansicht bleibt stehen. */
async function speichereMeta(pfad, aenderung, erfolgsmeldung) {
  loescheFehler();
  loescheMeldung();

  const ergebnis = await postJson("/api/meta", erstelleMetaPayload(pfad, aenderung));
  if (ergebnis === null) return false;

  zeigeMeldung(erfolgsmeldung);
  await ladeDetail({ unterpunkt: pfad });
  return true;
}

function zeichne(ziel, pfad, daten, zusatz) {
  const frontmatter =
    daten.frontmatter && typeof daten.frontmatter === "object" ? daten.frontmatter : {};
  const aufgabe = istAufgabe(pfad, frontmatter);
  const gesperrt = istSchreibgeschuetzt(daten);
  // Unter-Aufgaben (Tiefe 1) bekommen weder Anlegen-Knopf noch Abschnitt.
  const istUnteraufgabe = Boolean(feld(frontmatter, "parent"));
  const anlege =
    aufgabe && !istUnteraufgabe && !gesperrt && ermittleStatus(daten).status !== GESCHLOSSEN
      ? erstelleAnlegeSicht(pfad, () => ladeDetail({ unterpunkt: pfad }))
      : null;

  const teile = [erstelleKopf(pfad, daten, zusatz.wellen, anlege?.knopf ?? null)];
  if (anlege) teile.push(anlege.bereich);
  teile.push(erstelleInhalt(daten.markdown));

  if (aufgabe && !istUnteraufgabe) {
    const unteraufgabenSicht = erstelleUnteraufgabenSicht(pfad, zusatz.aufgaben);
    if (unteraufgabenSicht) teile.push(unteraufgabenSicht);
  }

  const aufgabenSicht = erstelleAufgabenSicht(pfad, zusatz.aufgaben);
  if (aufgabenSicht) teile.push(aufgabenSicht);

  // A36: Schreibgeschützte Dateien bekommen kein Nachtragsformular.
  if (!gesperrt) teile.push(erstelleNachtragFormular(pfad));
  ziel.replaceChildren(...teile);
}

/** Wellenliste für die Detail-Auswahl; Fehler werden fail-loud gemeldet. */
async function ladeWellenListe(noetig) {
  if (!noetig) return { eintraege: null, fehler: null };

  const antwort = await getJson("/api/wellen");
  if (antwort === null) {
    // 200 mit leerem Body zeigt api.js nicht an — hier sichtbar machen.
    zeigeFehler(WELLEN_LADE_FEHLER);
    return { eintraege: null, fehler: WELLEN_LADE_FEHLER };
  }
  if (!Array.isArray(antwort)) {
    zeigeFehler(WELLEN_FORMAT_FEHLER);
    return { eintraege: null, fehler: WELLEN_FORMAT_FEHLER };
  }
  return { eintraege: antwort, fehler: null };
}

/** Aufgabenliste für die Wellen-Sicht; Fehler erscheinen im Abschnitt. */
async function ladeAufgabenListe(
  noetig,
  ladeFehler = AUFGABEN_LADE_FEHLER,
  formatFehler = AUFGABEN_FORMAT_FEHLER,
) {
  if (!noetig) return { eintraege: null, fehler: null };

  const antwort = await getJson("/api/aufgaben");
  if (antwort === null) return { eintraege: null, fehler: ladeFehler };
  if (!Array.isArray(antwort)) return { eintraege: null, fehler: formatFehler };
  return { eintraege: antwort, fehler: null };
}

/** Lädt eine Datei aus `GET /api/file` und zeichnet die Detailansicht. */
export async function ladeDetail({ unterpunkt } = {}) {
  const ziel = document.getElementById(CONTAINER_ID);
  if (!ziel) return;

  // A38: Der Router reicht `pfad#anker` als Unterpunkt durch (Vertrag
  // unverändert); die Detailansicht trennt beides und scrollt danach.
  const { pfad, anker } = trenneAnker(unterpunkt);
  if (!pfad) {
    ziel.replaceChildren(erstelleHinweis(LEER_KEINE_AUSWAHL));
    return;
  }

  const daten = await getJson(`/api/file?path=${encodeURIComponent(pfad)}`);
  if (daten === null) {
    ziel.replaceChildren(erstelleHinweis(LADE_FEHLER));
    return;
  }

  if (!istDateiAntwort(daten)) {
    ziel.replaceChildren(erstelleHinweis(FORMAT_FEHLER));
    zeigeFehler(FORMAT_FEHLER);
    return;
  }

  const frontmatter =
    daten.frontmatter && typeof daten.frontmatter === "object" ? daten.frontmatter : {};
  const aufgabe = istAufgabe(pfad, frontmatter);
  const gesperrt = istSchreibgeschuetzt(daten);
  // A36: Schreibgeschützte Dateien brauchen keine Auswahl; eine gesperrte
  // Aufgabe mit Welle braucht aber die Liste für das Label `Titel (Pfad)`
  // (A36-K4) — sonst bleibt nur der rohe Pfad.
  const wellen = await ladeWellenListe(
    aufgabe && (!gesperrt || Boolean(feld(frontmatter, "welle"))),
  );
  // A34: Unter-Aufgaben kommen aus `GET /api/aufgaben`; Aufgaben brauchen die
  // Liste auch dann, wenn sie als Unter-Aufgabe keinen Abschnitt zeigen (T43).
  const wellenSicht = pfad.startsWith(WELLEN_ORDNER);
  const aufgaben = await ladeAufgabenListe(
    wellenSicht || aufgabe,
    wellenSicht ? AUFGABEN_LADE_FEHLER : UNTERAUFGABEN_LADE_FEHLER,
    wellenSicht ? AUFGABEN_FORMAT_FEHLER : UNTERAUFGABEN_FORMAT_FEHLER,
  );

  zeichne(ziel, pfad, daten, { wellen, aufgaben });
  // A38-K2: nur innerhalb der Detailansicht suchen, nicht global.
  springeZuAnker(anker, ziel);
}
