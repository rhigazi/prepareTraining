import { getJson, istDateiAntwort, zeigeFehler } from "./api.js";
import {
  erstelleAnkerVergabe,
  parseMarkdown,
  rendereMarkdown,
  springeZuAnker,
  trenneAnker,
} from "./detail.js";

const CONTAINER_ENTSCHEIDUNGEN_ID = "liste-entscheidungen";
const CONTAINER_PROJEKT_ID = "liste-projekt";

const ENTSCHEIDUNGEN_PFAD = "entscheidungen/log.md";
const DETAIL_VORSCHLAG = "#/detail/";
const PROJEKT_VORSCHLAG = "#/projekt/";
const PROJEKT_ROUTE = "#/projekt";

const LEER_ENTSCHEIDUNGEN = "Keine Einträge.";
const LEER_UNTERPUNKT = "Keine Inhalte.";
const LADE_FEHLER = "Datei konnte nicht geladen werden.";
const FORMAT_FEHLER = "Datei hat ein unerwartetes Format.";
const ZURUECK = "← Zurück zum Projekt";

// Einträge des Entscheidungslogs: `## YYYY-MM-DD: Titel`; Trennzeichen tolerant.
// Der Renderer liefert die Überschrift ohne `##`; der Anker entsteht daraus.
const EINTRAG = /^(\d{4}-\d{2}-\d{2})\s*(?:[:\-–—]\s*)?(.+)$/;

/**
 * Parst die Einträge des Entscheidungslogs in `[{datum, titel, anker}]`; die
 * Reihenfolge entspricht der Datei. Unpassende Zeilen bleiben unberücksichtigt.
 * Die Anker-Vergabe läuft über alle Überschriften — genau wie im Renderer,
 * damit die Verweise auf die tatsächlichen IDs zeigen (A38).
 */
export function parseEntscheidungen(markdown) {
  const ankerFuer = erstelleAnkerVergabe();
  const eintraege = [];

  for (const block of parseMarkdown(markdown)) {
    if (block.art !== "ueberschrift") continue;
    const anker = ankerFuer(block.text);
    if (block.ebene !== 2) continue;

    const treffer = EINTRAG.exec(block.text);
    if (!treffer) continue;
    const titel = treffer[2].trim();
    if (!titel) continue;
    eintraege.push({ datum: treffer[1], titel, anker });
  }
  return eintraege;
}

// Die fünf Projekt-Unterpunkte der Navigation; Pfade relativ zum Bundle-Root.
export const PROJEKT_PUNKTE = [
  { unterpunkt: "konzept", titel: "Konzept", pfad: "projekt/konzept.md" },
  { unterpunkt: "technische-spec", titel: "Technische Spec", pfad: "projekt/technische-spec.md" },
  { unterpunkt: "user-stories", titel: "User Stories", pfad: "projekt/user-stories/index.md" },
  { unterpunkt: "phasen", titel: "Phasen", pfad: "projekt/phasen.md" },
  { unterpunkt: "log", titel: "Log", pfad: "log.md" },
];

/** Liefert den Projekt-Unterpunkt zum Routen-Segment; unbekannt ist `null`. */
export function projektPunkt(unterpunkt) {
  return PROJEKT_PUNKTE.find((punkt) => punkt.unterpunkt === unterpunkt) ?? null;
}

function dateiAnfrage(pfad) {
  return `/api/file?path=${encodeURIComponent(pfad)}`;
}

function erstelleHinweis(text) {
  const hinweis = document.createElement("p");
  hinweis.classList.add("leer");
  hinweis.textContent = text;
  return hinweis;
}

/** Meldet einen fehlenden Container (index.html), statt still zurückzukehren. */
function meldeFehlendenContainer(id) {
  zeigeFehler(`Ansicht nicht verfügbar: Container #${id} fehlt in index.html.`);
}

/** Lädt eine Datei über `GET /api/file`; Fehler zeigt bereits api.js an. */
async function ladeDatei(pfad, ziel) {
  const daten = await getJson(dateiAnfrage(pfad));
  if (daten === null) {
    ziel.replaceChildren(erstelleHinweis(LADE_FEHLER));
    return null;
  }
  if (!istDateiAntwort(daten)) {
    ziel.replaceChildren(erstelleHinweis(FORMAT_FEHLER));
    zeigeFehler(FORMAT_FEHLER);
    return null;
  }
  return daten;
}

// --- Entscheidungen --------------------------------------------------------

/** Liste aus Datum und Titel je Eintrag; Klick öffnet das Detail der Log-Datei. */
function erstelleEntscheidungsListe(eintraege) {
  const liste = document.createElement("ul");
  liste.classList.add("liste");
  for (const eintrag of eintraege) {
    const punkt = document.createElement("li");
    const link = document.createElement("a");
    link.href = `${DETAIL_VORSCHLAG}${encodeURIComponent(ENTSCHEIDUNGEN_PFAD)}#${eintrag.anker}`;
    link.textContent = `${eintrag.datum}: ${eintrag.titel}`;
    punkt.append(link);
    liste.append(punkt);
  }
  return liste;
}

/** Ansichts-Loader „Entscheidungen": Einträge aus `entscheidungen/log.md`. */
export async function ladeEntscheidungenAnsicht() {
  const ziel = document.getElementById(CONTAINER_ENTSCHEIDUNGEN_ID);
  if (!ziel) {
    meldeFehlendenContainer(CONTAINER_ENTSCHEIDUNGEN_ID);
    return;
  }

  const daten = await ladeDatei(ENTSCHEIDUNGEN_PFAD, ziel);
  if (daten === null) return;

  const eintraege = parseEntscheidungen(daten.markdown);
  if (eintraege.length === 0) {
    ziel.replaceChildren(erstelleHinweis(LEER_ENTSCHEIDUNGEN));
    return;
  }
  ziel.replaceChildren(erstelleEntscheidungsListe(eintraege));
}

// --- Projekt ---------------------------------------------------------------

function erstelleProjektListe() {
  const liste = document.createElement("ul");
  liste.classList.add("liste");
  for (const punkt of PROJEKT_PUNKTE) {
    const eintrag = document.createElement("li");
    const link = document.createElement("a");
    link.href = `${PROJEKT_VORSCHLAG}${encodeURIComponent(punkt.unterpunkt)}`;
    link.textContent = punkt.titel;
    eintrag.append(link);
    liste.append(eintrag);
  }
  return liste;
}

/** Detail eines Unterpunkts: Titel, gerendeter Inhalt und Rückweg zur Liste. */
function erstelleProjektDetail(punkt, markdown) {
  const bereich = document.createDocumentFragment();

  const titel = document.createElement("h3");
  titel.classList.add("uebersicht-titel");
  titel.textContent = punkt.titel;

  const inhalt = document.createElement("div");
  inhalt.classList.add("detail-inhalt");
  // Befund 8: leere Datei zeigt einen Hinweis statt leerer Fläche.
  const markdownText = typeof markdown === "string" ? markdown.trim() : "";
  inhalt.append(markdownText ? rendereMarkdown(markdown) : erstelleHinweis(LEER_UNTERPUNKT));

  const zurueck = document.createElement("a");
  zurueck.classList.add("knopf");
  zurueck.href = PROJEKT_ROUTE;
  zurueck.textContent = ZURUECK;

  bereich.append(titel, inhalt, zurueck);
  return bereich;
}

/**
 * Ansichts-Loader „Projekt": ohne Unterpunkt die fünf Punkte, mit Unterpunkt
 * dessen Datei als Detail mit gerendertem Inhalt.
 */
export async function ladeProjektAnsicht({ unterpunkt } = {}) {
  const ziel = document.getElementById(CONTAINER_PROJEKT_ID);
  if (!ziel) {
    meldeFehlendenContainer(CONTAINER_PROJEKT_ID);
    return;
  }

  // A38: `unterpunkt#anker` (z. B. `log#2026-11-16`) springt zum Eintrag.
  const { pfad: name, anker } = trenneAnker(unterpunkt);
  if (!name) {
    ziel.replaceChildren(erstelleProjektListe());
    return;
  }

  const punkt = projektPunkt(name);
  if (!punkt) {
    zeigeFehler(`Unbekannter Unterpunkt: ${name}`);
    ziel.replaceChildren(erstelleHinweis(`Unbekannter Unterpunkt: ${name}`));
    return;
  }

  const daten = await ladeDatei(punkt.pfad, ziel);
  if (daten === null) return;

  ziel.replaceChildren(erstelleProjektDetail(punkt, daten.markdown));
  springeZuAnker(anker);
}
