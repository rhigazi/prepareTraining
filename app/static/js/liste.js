import { getJson } from "./api.js";

const SPALTEN = ["Titel", "Status", "owner", "zuletzt geändert"];
// A31: eigene Wellen-Spalte für Übersicht und Aufgabenliste (nach dem Titel).
const WELLE_SPALTE = "Welle";
// Top 5 zuletzt geänderte Punkte gemäß US-1-AC4.
const ZULETZT_ANZAHL = 5;
const KEINE_ANGABE = "—";
// A28: Marke für Aufgaben ohne gültige Kennung (``neu`` aus der Lese-API).
const MARKE_NEU = "neu";
// A29: Freigabe-Status der Wellen in der Titel-Zelle (nur Wellen-Ansicht, keine neue Spalte).
const MARKE_FREIGEGEBEN = "freigegeben";
const MARKE_NICHT_FREIGEGEBEN = "nicht freigegeben";
const LEER_TABELLE = "Keine Einträge.";
const LEER_TREFFER = "Keine Treffer.";
const LEER_KLARUNG = "Keine offenen Rückfragen.";
const LADE_FEHLER = "Einträge konnten nicht geladen werden.";
const FORMAT_FEHLER = "Einträge haben ein unerwartetes Format.";

// Wellen-Filter: „Alle" (leer) plus die Wellen des geladenen Bestands.
const WELLE_OHNE = "ohne";
const WELLE_ALLE_TEXT = "Alle";
const WELLE_OHNE_TEXT = "ohne Welle";
const WELLEN_ORDNER = "wellen/";

// Übersicht, Wellen und Aufgaben teilen sich dieselbe Listendarstellung.
const ANSICHTEN = {
  uebersicht: {
    pfad: "/api/overview",
    tabelle: "tabelle",
    formular: "filter",
    status: "filter-status",
    owner: "filter-owner",
    welle: "filter-welle",
    welleSpalte: true,
    freigabeMarke: false,
    suche: "suche-uebersicht",
    zuruecksetzen: "filter-zuruecksetzen",
  },
  wellen: {
    pfad: "/api/wellen",
    tabelle: "tabelle-wellen",
    formular: "filter-wellen",
    status: "filter-wellen-status",
    owner: "filter-wellen-owner",
    welle: null,
    welleSpalte: false,
    freigabeMarke: true,
    suche: "suche-wellen",
    zuruecksetzen: "filter-wellen-zuruecksetzen",
  },
  aufgaben: {
    pfad: "/api/aufgaben",
    tabelle: "tabelle-aufgaben",
    formular: "filter-aufgaben",
    status: "filter-aufgaben-status",
    owner: "filter-aufgaben-owner",
    welle: "filter-welle-aufgaben",
    welleSpalte: true,
    freigabeMarke: false,
    suche: "suche-aufgaben",
    zuruecksetzen: "filter-aufgaben-zuruecksetzen",
  },
};

const datenProAnsicht = new Map();
const initialisierteFilter = new Set();
// Für den Wellen-Filter ermittelte Wellen je Ansicht (A31-H1: unabhängig vom
// Filterformular gefüllt, damit die Spalte „Welle" auch ohne Formular Titel zeigt).
const wellenProAnsicht = new Map();

// Wellen-Metadaten aus bereits geladenen Daten (kein zusätzlicher Request):
// die Übersicht enthält alle Wellen, die Aufgabenliste referenziert sie.
let bekannteWellen = [];
// Pfad → Wellen-Titel für die Spalte „Welle" (aus denselben Daten gefüllt).
const wellenTitel = new Map();
// Vollständiger Wellen-Bestand bereits geladen (Übersicht/Wellenliste oder
// Nachladen per `/api/wellen`, A27-F1).
let wellenBestandVollstaendig = false;
let wellenNachtragAktiv = false;

// Durchsuchbare Felder aus `/api/overview`; „zuletzt geändert" gehört bewusst
// nicht dazu (Datumsrecherche ist nicht Teil der Anforderung).
const SUCHFELDER = ["titel", "path", "typ", "status", "owner", "hinweis", "welle"];

/**
 * Normalisiert Text für den Vergleich: Kleinschreibung, `ß`→`ss` und
 * NFD-Faltung, damit „prufung" auch „Prüfung" und „strasse" auch „Straße" trifft.
 */
function normalisiere(wert) {
  return String(wert ?? "")
    .toLowerCase()
    .replace(/ß/g, "ss")
    .normalize("NFD")
    .replace(/\p{M}/gu, "");
}

/** Zerlegt die Sucheingabe in getrimmte Begriffe; Leerraum trennt (UND). */
function suchbegriffe(suche) {
  return normalisiere(suche).split(/\s+/).filter(Boolean);
}

/**
 * Prüft, ob ein Eintrag alle Suchbegriffe enthält. Verglichen wird literarisch
 * über `includes` — kein `RegExp`, damit Sonderzeichen nicht crashen.
 */
function passtZurSuche(eintrag, begriffe) {
  if (begriffe.length === 0) return true;

  const text = normalisiere(SUCHFELDER.map((feld) => eintrag?.[feld]).join("\n"));
  return begriffe.every((begriff) => text.includes(begriff));
}

/**
 * Filtert Einträge nach UI-Status, owner, Suchbegriffen und Welle; leere Werte
 * bedeuten „alle". `owner: "ohne"` trifft Einträge ohne Zuständigkeit,
 * `welle: "ohne"` Einträge ohne Wellen-Zuordnung.
 */
export function filtereEintraege(
  eintraege,
  { status = "", owner = "", suche = "", welle = "" } = {},
) {
  if (!Array.isArray(eintraege)) return [];

  const begriffe = suchbegriffe(suche);

  return eintraege.filter((eintrag) => {
    if (!passtZurSuche(eintrag, begriffe)) return false;
    if (status && eintrag?.status !== status) return false;
    if (!passtZurWelle(eintrag, welle)) return false;
    if (!owner) return true;
    if (owner === "ohne") return !eintrag?.owner;
    return eintrag?.owner === owner;
  });
}

/** Wellen-Filter: exakte Pfadgleichheit; „ohne" trifft Einträge ohne ``welle``. */
function passtZurWelle(eintrag, welle) {
  if (!welle) return true;
  if (welle === WELLE_OHNE) return !eintrag?.welle;
  return eintrag?.welle === welle;
}

/**
 * Entscheidet, was die Tabelle zeigt: Fehlerzustand hat Vorrang vor Filter- und
 * Leerzustand. Eine Antwort, die kein Array ist, wird als Formatfehler gemeldet
 * statt als leere Liste getarnt.
 */
export function waehleAnzeige(
  daten,
  { status = "", owner = "", suche = "", welle = "" } = {},
) {
  if (daten === null) return { art: "fehler", text: LADE_FEHLER, eintraege: [] };
  if (!Array.isArray(daten)) return { art: "fehler", text: FORMAT_FEHLER, eintraege: [] };

  const eintraege = filtereEintraege(daten, { status, owner, suche, welle });
  if (eintraege.length === 0) {
    // „Keine Treffer." nur bei gesetztem Suchbegriff und vorhandenen Daten;
    // sonst bleibt es beim A11-Leerzustand „Keine Einträge.".
    const ohneTreffer = daten.length > 0 && suchbegriffe(suche).length > 0;
    return { art: "leer", text: ohneTreffer ? LEER_TREFFER : LEER_TABELLE, eintraege };
  }

  return { art: "tabelle", text: "", eintraege };
}

/** Formatiert einen ISO-Zeitstempel lokal; fehlende/ungültige Werte als „—". */
export function formatiereZeitstempel(wert) {
  if (!wert) return KEINE_ANGABE;

  const datum = new Date(wert);
  if (Number.isNaN(datum.getTime())) return KEINE_ANGABE;

  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(datum);
}

/**
 * Formatiert den abgeleiteten Arbeitsstatus als „<Label>: <Text>".
 * Fehlt eines der Teile, steht nur das andere; ohne Angabe bleibt es leer
 * (dann entsteht keine Zeile). Unbekannte Rollen kommen unverändert an.
 */
export function formatiereArbeitsstand(quelle) {
  if (quelle === null || typeof quelle !== "object" || Array.isArray(quelle)) return "";

  const label = textWert(quelle.arbeitsrolle_label) || textWert(quelle.arbeitsrolle);
  const inhalt = textWert(quelle.arbeitsstatus);
  if (label && inhalt) return `${label}: ${inhalt}`;
  return label || inhalt;
}

function textWert(wert) {
  return typeof wert === "string" ? wert.trim() : "";
}

/** Sortiert absteigend nach „zuletzt geändert", Tie-Breaker `path`. */
export function sortiereNachAenderung(eintraege) {
  if (!Array.isArray(eintraege)) return [];

  return [...eintraege].sort((links, rechts) => {
    const zeitLinks = zeitwert(links);
    const zeitRechts = zeitwert(rechts);
    if (zeitLinks !== zeitRechts) return zeitRechts - zeitLinks;
    return String(links?.path ?? "").localeCompare(String(rechts?.path ?? ""));
  });
}

function zeitwert(eintrag) {
  const datum = new Date(eintrag?.zuletzt_geaendert ?? "");
  return Number.isNaN(datum.getTime()) ? 0 : datum.getTime();
}

function erstelleZelle(text, tag = "td") {
  const zelle = document.createElement(tag);
  zelle.textContent = text;
  return zelle;
}

function erstelleStatusZelle(eintrag) {
  const zelle = document.createElement("td");
  const status = eintrag?.status;
  if (!status) {
    zelle.textContent = KEINE_ANGABE;
    return zelle;
  }

  const marke = document.createElement("span");
  marke.classList.add("status");
  if (status === "Klarung") marke.classList.add("status--klarung");
  if (status === "Geschlossen") marke.classList.add("status--geschlossen");
  marke.textContent = status;
  zelle.append(marke);

  if (eintrag?.hinweis) {
    zelle.append(document.createTextNode(` (${eintrag.hinweis})`));
  }

  // Arbeitsstatus (A30): nur Aufgaben, nur bei ableitbarer Angabe.
  const arbeitsstand = eintrag?.typ === "Task" ? formatiereArbeitsstand(eintrag) : "";
  if (arbeitsstand) {
    const zeile = document.createElement("div");
    zeile.classList.add("arbeitsstand");
    zeile.textContent = arbeitsstand;
    zelle.append(zeile);
  }
  return zelle;
}

function erstelleOwnerZelle(eintrag) {
  const zelle = document.createElement("td");
  const owner = eintrag?.owner;
  if (!owner) {
    zelle.textContent = KEINE_ANGABE;
    return zelle;
  }

  const marke = document.createElement("span");
  marke.classList.add("owner");
  marke.textContent = owner;
  zelle.append(marke);
  return zelle;
}

function erstelleZeitZelle(eintrag) {
  const zelle = erstelleZelle(formatiereZeitstempel(eintrag?.zuletzt_geaendert));
  if (eintrag?.zuletzt_geaendert) zelle.title = eintrag.zuletzt_geaendert;
  return zelle;
}

/** Spaltenköpfe je Ansicht; ohne Wellen-Spalte bleibt es bei den vier A11-Spalten. */
function spaltenFuer(mitWelle) {
  if (!mitWelle) return SPALTEN;
  return [SPALTEN[0], WELLE_SPALTE, ...SPALTEN.slice(1)];
}

/**
 * Zelle „Welle": sichtbarer Wellen-Titel, Tooltip = Pfad; ohne Zuordnung „—";
 * ist kein Titel bekannt (dangling, Deep-Link), steht der Pfad als Fallback.
 */
function erstelleWelleZelle(eintrag) {
  const zelle = document.createElement("td");
  const pfad = typeof eintrag?.welle === "string" ? eintrag.welle.trim() : "";
  if (!pfad) {
    zelle.textContent = KEINE_ANGABE;
    return zelle;
  }

  zelle.textContent = wellenTitel.get(pfad) || pfad;
  zelle.title = pfad;
  return zelle;
}

/** Marke in der Titel-Zelle (bestehende Status-Pille, keine neue Spalte). */
function erstelleMarke(text) {
  const marke = document.createElement("span");
  marke.classList.add("status");
  marke.textContent = text;
  return marke;
}

/**
 * Titel-Zelle mit optionalen Marken: „neu" für Aufgaben ohne Kennung (A28),
 * „freigegeben"/„nicht freigegeben" für Wellen (A29, nur Wellen-Ansicht).
 */
function erstelleTitelZelle(eintrag, { mitFreigabeMarke = false } = {}) {
  const titel = eintrag?.titel || KEINE_ANGABE;
  const marken = [];
  if (eintrag?.neu === true) marken.push(MARKE_NEU);
  if (mitFreigabeMarke && eintrag?.typ === "Welle") {
    marken.push(eintrag?.freigabe === true ? MARKE_FREIGEGEBEN : MARKE_NICHT_FREIGEGEBEN);
  }
  if (marken.length === 0) return erstelleZelle(titel);

  const zelle = document.createElement("td");
  zelle.append(document.createTextNode(titel));
  for (const text of marken) {
    zelle.append(document.createTextNode(" "), erstelleMarke(text));
  }
  return zelle;
}

/** Baut die Tabelle aus API-Einträgen; `mitWelle` ergänzt die Spalte „Welle". */
export function erstelleTabelle(
  eintraege,
  { mitWelle = false, mitFreigabeMarke = false } = {},
) {
  const tabelle = document.createElement("table");
  tabelle.classList.add("tabelle");

  const kopf = tabelle.createTHead().insertRow();
  for (const spalte of spaltenFuer(mitWelle)) {
    const zelle = erstelleZelle(spalte, "th");
    zelle.scope = "col";
    kopf.append(zelle);
  }

  const koerper = tabelle.createTBody();
  for (const eintrag of eintraege) {
    const zeile = koerper.insertRow();
    if (eintrag?.path) zeile.dataset.path = eintrag.path;
    if (eintrag?.status === "Klarung") zeile.classList.add("klarung");
    zeile.append(erstelleTitelZelle(eintrag, { mitFreigabeMarke }));
    if (mitWelle) zeile.append(erstelleWelleZelle(eintrag));
    zeile.append(
      erstelleStatusZelle(eintrag),
      erstelleOwnerZelle(eintrag),
      erstelleZeitZelle(eintrag),
    );
  }
  return tabelle;
}

function erstelleHinweis(text) {
  const hinweis = document.createElement("p");
  hinweis.classList.add("leer");
  hinweis.textContent = text;
  return hinweis;
}

function zeichneTabelle(bereich, eintraege, mitWelle) {
  if (!bereich) return;

  // Kein eigener Leerzustand: den trägt bereits die Haupttabelle, sonst
  // erscheint „Keine Einträge." doppelt auf der Übersicht (A25-Befund 2).
  bereich.replaceChildren();
  if (eintraege.length === 0) return;
  bereich.append(erstelleTabelle(eintraege, { mitWelle }));
}

function zeichneRueckfragen(bereich, eintraege) {
  if (!bereich) return;

  bereich.replaceChildren();
  if (eintraege.length === 0) {
    bereich.append(erstelleHinweis(LEER_KLARUNG));
    return;
  }

  const liste = document.createElement("ul");
  liste.classList.add("liste");
  for (const eintrag of eintraege) {
    const punkt = document.createElement("li");
    const titel = eintrag?.titel || KEINE_ANGABE;
    if (eintrag?.path) {
      const link = document.createElement("a");
      link.href = `#/detail/${encodeURIComponent(eintrag.path)}`;
      link.textContent = titel;
      punkt.append(link);
    } else {
      punkt.textContent = titel;
    }
    liste.append(punkt);
  }
  bereich.append(liste);
}

function zeichneUebersichtZusatz(daten) {
  const anzeige = waehleAnzeige(daten);
  if (anzeige.art === "fehler") {
    for (const id of ["uebersicht-zuletzt", "uebersicht-klarung"]) {
      const bereich = document.getElementById(id);
      if (bereich) bereich.replaceChildren(erstelleHinweis(anzeige.text));
    }
    return;
  }

  zeichneTabelle(
    document.getElementById("uebersicht-zuletzt"),
    sortiereNachAenderung(anzeige.eintraege).slice(0, ZULETZT_ANZAHL),
    ANSICHTEN.uebersicht.welleSpalte,
  );
  zeichneRueckfragen(
    document.getElementById("uebersicht-klarung"),
    anzeige.eintraege.filter((eintrag) => eintrag?.status === "Klarung"),
  );
}

/**
 * Hängt das Suchfeld dynamisch vor die Tabelle. Es liegt außerhalb des
 * Filterformulars (kein Submit-/Reload-Pfad) und wird nur einmal montiert.
 */
function montiereSuche(basis) {
  const konfiguration = ANSICHTEN[basis];
  const tabelle = document.getElementById(konfiguration.tabelle);
  if (!tabelle?.parentElement) return null;

  const vorhanden = document.getElementById(konfiguration.suche);
  // Ein verwaistes Feld (Container neu aufgebaut) wird ersetzt (A25-Befund 1).
  if (vorhanden && vorhanden.isConnected !== false) return vorhanden;

  const bereich = document.createElement("div");
  bereich.classList.add("filter");
  const reihe = document.createElement("div");
  reihe.classList.add("filter-feld");
  const beschriftung = document.createElement("label");
  beschriftung.htmlFor = konfiguration.suche;
  beschriftung.textContent = "Suche";
  const eingabe = document.createElement("input");
  eingabe.type = "search";
  eingabe.id = konfiguration.suche;
  eingabe.value = "";

  reihe.append(beschriftung, eingabe);
  bereich.append(reihe);
  tabelle.parentElement.insertBefore(bereich, tabelle);

  eingabe.addEventListener("input", () => wendeFilterAn(basis));
  return eingabe;
}

/** Wellen-Einträge aus dem geladenen Bestand (Präfix `wellen/`, wie `/api/wellen`). */
function wellenAusBestand(daten) {
  if (!Array.isArray(daten)) return [];
  return daten.filter(
    (eintrag) => typeof eintrag?.path === "string" && eintrag.path.startsWith(WELLEN_ORDNER),
  );
}

/** In Aufgaben referenzierte Wellen-Pfade (ohne Titel — Anzeige dann als Pfad). */
function wellenAusVerweisen(daten) {
  if (!Array.isArray(daten)) return [];
  const gefunden = [];
  for (const eintrag of daten) {
    const pfad = typeof eintrag?.welle === "string" ? eintrag.welle.trim() : "";
    if (!pfad) continue;
    if (!gefunden.some((kandidat) => kandidat.path === pfad)) gefunden.push({ path: pfad });
  }
  return gefunden;
}

function fuehreWellenZusammen(...quellen) {
  const ergebnis = [];
  for (const quelle of quellen) {
    for (const eintrag of quelle) {
      const pfad = typeof eintrag?.path === "string" ? eintrag.path.trim() : "";
      if (!pfad) continue;
      const index = ergebnis.findIndex((kandidat) => kandidat.path === pfad);
      if (index === -1) ergebnis.push({ ...eintrag, path: pfad });
      else if (!ergebnis[index].titel && eintrag?.titel) ergebnis[index] = { ...eintrag, path: pfad };
    }
  }
  return ergebnis;
}

/**
 * Wellen für eine Ansicht: die Übersicht liefert alle Wellen, die Aufgabenliste
 * ergänzt den bekannten Bestand um die in den Aufgaben referenzierten Pfade.
 * Auch die Wellenliste liefert den vollständigen Bestand und erneuert den Cache
 * (A27-K2) — so erscheinen in der Sitzung neu angelegte Wellen im Filter.
 * Die Titel landen in ``wellenTitel`` — Grundlage der Spalte „Welle".
 */
function ermittleWellen(basis, daten) {
  const ausBestand = wellenAusBestand(daten);
  if (basis === "uebersicht" || basis === "wellen") {
    bekannteWellen = ausBestand;
    wellenBestandVollstaendig = true;
    merkeWellenTitel(basis, ausBestand);
    return ausBestand;
  }
  const wellen = fuehreWellenZusammen(bekannteWellen, ausBestand, wellenAusVerweisen(daten));
  merkeWellenTitel(basis, wellen);
  return wellen;
}

/**
 * Pfad → Titel für die Spalte „Welle". Die Übersicht ist die vollständige
 * Quelle und baut die Map neu auf; andere Ansichten ergänzen sie nur.
 */
// Cache-Verhalten nach Wellen-Loeschen (A31-H2): ``wellenTitel`` wird nur bei
// einem frischen Uebersichts-Laden geleert und neu aufgebaut; eine in der Sitzung
// geloeschte Welle bleibt bis zum naechsten Uebersichts-Reload als Stale-Titel in
// der Map. Die Spalte zeigt dann den (veralteten) Titel statt des Pfad-Fallbacks.
// Bewusste Grenze: kein explizites Entfernen aus ``wellenTitel`` bei Loeschung
// (kein Extra-Request, A25-Request-Budget bleibt unveraendert); der Titel
// aktualisiert sich beim naechsten ``ladeUebersicht()``.
function merkeWellenTitel(basis, wellen) {
  if (basis === "uebersicht") wellenTitel.clear();
  for (const eintrag of wellen) {
    const pfad = typeof eintrag?.path === "string" ? eintrag.path.trim() : "";
    const titel = typeof eintrag?.titel === "string" ? eintrag.titel.trim() : "";
    if (pfad && titel) wellenTitel.set(pfad, titel);
  }
}

function erstelleOption(wert, beschriftung) {
  const option = document.createElement("option");
  option.value = wert;
  option.textContent = beschriftung;
  return option;
}

function fuelleWellenAuswahl(auswahl, wellen) {
  const optionen = [erstelleOption("", WELLE_ALLE_TEXT), erstelleOption(WELLE_OHNE, WELLE_OHNE_TEXT)];
  for (const eintrag of wellen) {
    const titel = typeof eintrag?.titel === "string" ? eintrag.titel.trim() : "";
    // Pfad im Label, damit Titel-Duplikate unterscheidbar bleiben (A13).
    optionen.push(erstelleOption(eintrag.path, titel ? `${titel} (${eintrag.path})` : eintrag.path));
  }
  auswahl.replaceChildren(...optionen);
}

/**
 * Hängt den Wellen-Filter je Ansicht idempotent in das bestehende Filterformular
 * ein (vor „Filter zurücksetzen"); `index.html` bleibt ohne Markup. Die Optionen
 * stammen aus den bereits geladenen Listen (``wellenProAnsicht``) — kein
 * zusätzlicher Request beim Anzeigen.
 */
function montiereWellenFilter(basis, daten) {
  const konfiguration = ANSICHTEN[basis];
  const feldId = konfiguration.welle;
  if (!feldId) return null;

  const formular = document.getElementById(konfiguration.formular);
  const zuruecksetzen = document.getElementById(konfiguration.zuruecksetzen);
  if (!formular || !zuruecksetzen) return null;

  let auswahl = document.getElementById(feldId);
  if (auswahl && auswahl.isConnected === false) auswahl = null;
  if (!auswahl) {
    const reihe = document.createElement("div");
    reihe.classList.add("filter-feld");
    const beschriftung = document.createElement("label");
    beschriftung.htmlFor = feldId;
    beschriftung.textContent = "Welle";
    auswahl = document.createElement("select");
    auswahl.id = feldId;
    auswahl.setAttribute("aria-label", "Welle");
    reihe.append(beschriftung, auswahl);
    formular.insertBefore(reihe, zuruecksetzen);
    auswahl.addEventListener("change", () => wendeFilterAn(basis));
    // A27-F1: Beim Deep-Link (z. B. `#/aufgaben` als erster Aufruf) fehlen Wellen
    // ohne Aufgaben. Der vollständige Bestand wird erst bei der ersten Interaktion
    // nachgeladen — beim reinen Anzeigen bleibt das Request-Budget unverändert.
    for (const art of ["focus", "pointerdown"]) {
      auswahl.addEventListener(art, () => ergaenzeWellenBestand(basis));
    }
  }

  const vorher = auswahl.value;
  if (Array.isArray(daten)) {
    fuelleWellenAuswahl(auswahl, wellenProAnsicht.get(basis) ?? []);
    auswahl.disabled = false;
  } else {
    // Fail-loud: ohne Daten wird nicht still weggefiltert, nur „Alle" bleibt.
    auswahl.replaceChildren(erstelleOption("", WELLE_ALLE_TEXT));
    auswahl.disabled = true;
  }
  auswahl.value = optionenEnthaelt(auswahl, vorher) ? vorher : "";
  return auswahl;
}

/**
 * Lädt den vollständigen Wellen-Bestand nach (A27-F1) und ergänzt Filter und
 * Spalte „Welle" der aktuellen Ansicht. Läuft höchstens einmal je Sitzung.
 */
async function ergaenzeWellenBestand(basis) {
  if (wellenBestandVollstaendig || wellenNachtragAktiv) return;
  wellenNachtragAktiv = true;
  try {
    const daten = await getJson(ANSICHTEN.wellen.pfad);
    // Fehler meldet api.js bereits; die Auswahl bleibt dann unverändert.
    if (!Array.isArray(daten)) return;

    bekannteWellen = wellenAusBestand(daten);
    wellenBestandVollstaendig = true;
    const eigene = datenProAnsicht.get(basis);
    wellenProAnsicht.set(basis, ermittleWellen(basis, Array.isArray(eigene) ? eigene : []));
    montiereWellenFilter(basis, eigene ?? null);
    wendeFilterAn(basis);
  } finally {
    wellenNachtragAktiv = false;
  }
}

function optionenEnthaelt(auswahl, wert) {
  if (!wert) return true;
  return Array.from(auswahl.options ?? []).some((option) => option.value === wert);
}

function wendeFilterAn(basis) {
  if (!datenProAnsicht.has(basis)) return;

  const konfiguration = ANSICHTEN[basis];
  const daten = datenProAnsicht.get(basis);
  const status = document.getElementById(konfiguration.status)?.value ?? "";
  const owner = document.getElementById(konfiguration.owner)?.value ?? "";
  const suche = document.getElementById(konfiguration.suche)?.value ?? "";
  const welle = konfiguration.welle
    ? document.getElementById(konfiguration.welle)?.value ?? ""
    : "";
  const anzeige = waehleAnzeige(daten, { status, owner, suche, welle });

  const bereich = document.getElementById(konfiguration.tabelle);
  if (!bereich) return;

  bereich.replaceChildren();
  if (anzeige.art === "tabelle") {
    bereich.append(
      erstelleTabelle(anzeige.eintraege, {
        mitWelle: konfiguration.welleSpalte,
        mitFreigabeMarke: konfiguration.freigabeMarke,
      }),
    );
  } else {
    bereich.append(erstelleHinweis(anzeige.text));
  }
}

function initialisiereFilter(basis) {
  if (initialisierteFilter.has(basis)) return;

  const konfiguration = ANSICHTEN[basis];
  const formular = document.getElementById(konfiguration.formular);
  const status = document.getElementById(konfiguration.status);
  const owner = document.getElementById(konfiguration.owner);
  const zuruecksetzen = document.getElementById(konfiguration.zuruecksetzen);
  if (!formular || !status || !owner || !zuruecksetzen) return;

  const neuZeichnen = () => wendeFilterAn(basis);
  status.addEventListener("change", neuZeichnen);
  owner.addEventListener("change", neuZeichnen);
  zuruecksetzen.addEventListener("click", () => {
    status.value = "";
    owner.value = "";
    const welle = konfiguration.welle ? document.getElementById(konfiguration.welle) : null;
    if (welle) welle.value = "";
    const suche = document.getElementById(konfiguration.suche);
    if (suche) suche.value = "";
    neuZeichnen();
  });

  initialisierteFilter.add(basis);
}

async function ladeListe(basis) {
  const konfiguration = ANSICHTEN[basis];
  initialisiereFilter(basis);
  montiereSuche(basis);

  const daten = await getJson(konfiguration.pfad);
  // Rohe Antwort pro Ansicht merken: Fehler-/Formatzustand bleibt so auch bei
  // Filteränderungen erhalten, bis neu geladen wird.
  datenProAnsicht.set(basis, daten ?? null);
  // A31-H1: Den Titel-Cache unabhängig vom Filterformular füllen — sonst zeigt die
  // Spalte „Welle" Pfade, wenn das Formular fehlt. Bei Fehlern bleibt der Cache.
  wellenProAnsicht.set(basis, Array.isArray(daten) ? ermittleWellen(basis, daten) : []);
  montiereWellenFilter(basis, daten ?? null);
  wendeFilterAn(basis);

  if (basis === "uebersicht") zeichneUebersichtZusatz(daten ?? null);
}

export function ladeUebersicht() {
  return ladeListe("uebersicht");
}

export function ladeWellen() {
  return ladeListe("wellen");
}

export function ladeAufgaben() {
  return ladeListe("aufgaben");
}
