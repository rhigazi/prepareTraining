import { getJson, istDateiAntwort, zeigeFehler } from "./api.js";

const CONTAINER_ID = "liste-features";
const FEATURES_PFAD = "features.md";
const FEATURES_ROUTE = "#/features";
const AUFGABEN_ENDPUNKT = "/api/aufgaben";
const DETAIL_VORSCHLAG = "#/detail/";

const LEER_FEATURES = "Keine Features.";
const LADE_FEHLER = "Feature-Liste konnte nicht geladen werden.";
const LADE_AUFGABEN_FEHLER = "Aufgaben konnten nicht geladen werden.";
const FORMAT_PRAEFIX = "Feature-Liste hat ein unerwartetes Format";
const FORMAT_FEHLER = `${FORMAT_PRAEFIX}.`;
const FORMAT_AUFGABEN_FEHLER = "Aufgaben haben ein unerwartetes Format.";
const ABSCHNITT_FEHLER = `${FORMAT_PRAEFIX}: Feature-Abschnitt fehlt.`;
const ZEILEN_FEHLER = `${FORMAT_PRAEFIX}: Feature-Zeile hat einen Link nicht am Zeilenanfang.`;

const STATUS_WORTE = ["offen", "in Umsetzung", "umgesetzt", "pausiert"];
const PRIORITAET_WORTE = ["hoch", "mittel", "niedrig"];
const FEATURE_ABSCHNITTE = ["Offene Features", "Umgesetzte Features"];
const OHNE_STATUS = "ohne Status";
const TITEL_OHNE_LINK = "Ohne Titel";
const KEINE_ANGABE = "—";
const LEER_AUFGABEN = "Keine Aufgaben zugeordnet.";
const LEER_GRUPPE = "Keine Aufgaben.";
const GRUPPEN_ANZEIGE = [
  { schluessel: "offen", titel: "Offen" },
  { schluessel: "inBearbeitung", titel: "In Bearbeitung" },
  { schluessel: "erledigt", titel: "Erledigt" },
];

const ZIEL_ENDE = /\.md$/i;
const UEBERSCHRIFT = /^(#{1,6})\s+(.*)$/;
const BULLET = /^([ \t]*)[*+-]\s+(.*)$/;
const FEATURE_ZEILE = /^\[([^\]]+)\]\(([^)]+)\)/;

function dekodiereZiel(ziel) {
  const text = ziel.trim();
  let dekodiert;
  try {
    dekodiert = decodeURIComponent(text);
  } catch {
    dekodiert = text;
  }
  // Absolute Ziele (`/aufgaben/…`) gelten relativ zum Bundle-Wurzelverzeichnis.
  return dekodiert.replace(/^\//, "");
}

function linkZiele(text) {
  const ziele = [];
  for (const treffer of text.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)) {
    const ziel = dekodiereZiel(treffer[1]);
    if (ZIEL_ENDE.test(ziel)) ziele.push(ziel);
  }
  return ziele;
}

function fettSegmente(text) {
  const segmente = [];
  for (const treffer of text.matchAll(/\*\*([^*]+)\*\*/g)) {
    const segment = treffer[1].trim();
    if (segment) segmente.push(segment);
  }
  return segmente;
}

function prioritaetAusSegment(segment) {
  const bereinigt = segment.replace(/^Priorität\s+/, "").trim();
  return PRIORITAET_WORTE.includes(bereinigt) ? bereinigt : null;
}

function statusAusSegment(segment) {
  for (const wort of STATUS_WORTE) {
    if (segment === wort) return { status: wort, hinweis: null };
    if (!segment.startsWith(wort)) continue;
    const rest = segment.slice(wort.length);
    if (!/^[\s—–\-:]/.test(rest)) continue;
    const hinweis = rest.replace(/^[\s—–\-:]+/, "").trim();
    return { status: wort, hinweis: hinweis || null };
  }
  return null;
}

/** Liest Status und Priorität aus den `**…**`-Segmenten einer Feature-Zeile. */
function auswertungAusZeile(zeile) {
  let status = null;
  let hinweis = null;
  let prioritaet = null;
  let unbekannt = null;

  for (const segment of fettSegmente(zeile)) {
    const gelesen = prioritaetAusSegment(segment);
    if (gelesen) {
      prioritaet ??= gelesen;
      continue;
    }
    if (status !== null) continue;
    const erkannt = statusAusSegment(segment);
    if (erkannt) {
      status = erkannt.status;
      hinweis = erkannt.hinweis;
    } else {
      unbekannt ??= segment;
    }
  }

  if (status === null) {
    status = "offen";
    hinweis = unbekannt ?? OHNE_STATUS;
  }
  return { status, hinweis, prioritaet };
}

function aufgabenAusZeile(text, bisher) {
  const aufgaben = [...bisher];
  for (const ziel of linkZiele(text)) {
    if (!ziel.startsWith("aufgaben/")) continue;
    if (!aufgaben.includes(ziel)) aufgaben.push(ziel);
  }
  return aufgaben;
}

function slugAusPfad(pfad) {
  const name = pfad.split("/").pop() ?? "";
  return name.replace(/\.md$/i, "");
}

/**
 * Parst die Feature-Abschnitte (`# Offene Features`/`# Umgesetzte Features`)
 * in `[{titel, pfad, slug, status, hinweis, prioritaet, aufgaben}]`.
 *
 * Nur Top-Level-Bullets mit Markdown-Link auf `.md` sind Feature-Einträge;
 * eingerückte Unterpunkte liefern die zugehörigen Aufgaben-Links. Fehlt jeder
 * Feature-Abschnitt, ist das ein Formatfehler (fail-loud statt „keine Features").
 */
export function parseFeatures(markdown) {
  if (typeof markdown !== "string" || !markdown.trim()) return [];

  const features = [];
  let imAbschnitt = false;
  let abschnittGefunden = false;
  let aktuell = null;

  for (const zeile of markdown.split(/\r?\n/)) {
    const ueberschrift = UEBERSCHRIFT.exec(zeile.trim());
    if (ueberschrift && ueberschrift[1].length === 1) {
      imAbschnitt = FEATURE_ABSCHNITTE.includes(ueberschrift[2].trim());
      if (imAbschnitt) abschnittGefunden = true;
      aktuell = null;
      continue;
    }
    if (!imAbschnitt) continue;

    const bullet = BULLET.exec(zeile);
    if (!bullet) continue;

    if (bullet[1].length > 0) {
      if (aktuell) aktuell.aufgaben = aufgabenAusZeile(bullet[2], aktuell.aufgaben);
      continue;
    }

    const treffer = FEATURE_ZEILE.exec(bullet[2]);
    // Fail-loud: Ein Top-Level-Bullet mit `.md`-Link, dessen Link nicht am
    // Zeilenanfang steht, ist eine kaputte Feature-Zeile statt eines Texts.
    if (!treffer) {
      if (linkZiele(bullet[2]).length > 0) throw new Error(ZEILEN_FEHLER);
      aktuell = null;
      continue;
    }

    const pfad = dekodiereZiel(treffer[2]);
    // Ein Aufgaben-Link ist kein Feature, auch wenn er auf oberster Ebene steht.
    if (!ZIEL_ENDE.test(pfad) || pfad.startsWith("aufgaben/")) {
      aktuell = null;
      continue;
    }

    const { status, hinweis, prioritaet } = auswertungAusZeile(bullet[2]);
    aktuell = {
      titel: treffer[1].trim() || TITEL_OHNE_LINK,
      pfad,
      slug: slugAusPfad(pfad),
      status,
      hinweis,
      prioritaet,
      aufgaben: [],
    };
    features.push(aktuell);
  }

  if (!abschnittGefunden) {
    throw new Error(ABSCHNITT_FEHLER);
  }
  return features;
}

/** Anzeigegruppen der Aufgaben; die sechs UI-Status werden auf drei reduziert. */
const GRUPPE_JE_STATUS = {
  Klarung: "offen",
  Offen: "offen",
  "In Arbeit": "inBearbeitung",
  Testing: "inBearbeitung",
  Dokumentation: "inBearbeitung",
  Geschlossen: "erledigt",
};

/**
 * Gruppiert Aufgaben in `{offen, inBearbeitung, erledigt}`; die Reihenfolge
 * der Eingabe bleibt je Gruppe erhalten. Unbekannte Status landen sichtbar in
 * „offen" (Hinweis statt Verwerfen), damit ein Ausreißer die Ansicht nicht kippt.
 */
export function gruppeAufgaben(aufgaben) {
  const gruppen = { offen: [], inBearbeitung: [], erledigt: [] };
  if (!Array.isArray(aufgaben)) return gruppen;

  for (const aufgabe of aufgaben) {
    const status = aufgabe?.status;
    const bekannt = typeof status === "string" && Object.hasOwn(GRUPPE_JE_STATUS, status);
    const eintrag = { ...aufgabe };
    if (!bekannt && !eintrag.hinweis) {
      eintrag.hinweis = typeof status === "string" && status ? status : OHNE_STATUS;
    }
    const schluessel = bekannt ? GRUPPE_JE_STATUS[status] : "offen";
    gruppen[schluessel].push(eintrag);
  }
  return gruppen;
}

/** Zähler je Anzeigegruppe; Summe entspricht der Anzahl der Aufgaben. */
export function zaehleGruppen(gruppen) {
  return {
    offen: gruppen?.offen?.length ?? 0,
    inBearbeitung: gruppen?.inBearbeitung?.length ?? 0,
    erledigt: gruppen?.erledigt?.length ?? 0,
  };
}

/**
 * Verbindet die Aufgaben-Links eines Features mit der API-Liste (`path`).
 * Fehlende Einträge werden als Warnung gemeldet statt still verworfen.
 */
export function verbindeAufgaben(feature, aufgaben) {
  const index = new Map();
  if (Array.isArray(aufgaben)) {
    for (const aufgabe of aufgaben) {
      if (aufgabe && typeof aufgabe.path === "string") index.set(aufgabe.path, aufgabe);
    }
  }

  const gefunden = [];
  const warnungen = [];
  const pfade = Array.isArray(feature?.aufgaben) ? feature.aufgaben : [];

  for (const pfad of pfade) {
    const aufgabe = index.get(pfad);
    if (!aufgabe) {
      warnungen.push({ pfad, grund: "nicht gefunden" });
      continue;
    }
    gefunden.push({
      path: pfad,
      titel: typeof aufgabe.titel === "string" && aufgabe.titel.trim() ? aufgabe.titel : pfad,
      status: typeof aufgabe.status === "string" ? aufgabe.status : "",
      hinweis: typeof aufgabe.hinweis === "string" && aufgabe.hinweis ? aufgabe.hinweis : null,
    });
  }

  return { aufgaben: gefunden, warnungen };
}

/** API-Aufgaben, deren Pfad in keinem Feature verlinkt ist (Sammelhinweis). */
export function ohneZuordnung(features, aufgaben) {
  if (!Array.isArray(aufgaben)) return [];

  const zugeordnet = new Set();
  for (const feature of Array.isArray(features) ? features : []) {
    for (const pfad of Array.isArray(feature?.aufgaben) ? feature.aufgaben : []) {
      zugeordnet.add(pfad);
    }
  }
  return aufgaben.filter(
    (aufgabe) => aufgabe && typeof aufgabe.path === "string" && !zugeordnet.has(aufgabe.path),
  );
}

function dateiAnfrage(pfad) {
  return `/api/file?path=${encodeURIComponent(pfad)}`;
}

function erstelleHinweis(text, klasse = "leer") {
  const hinweis = document.createElement("p");
  hinweis.classList.add(klasse);
  hinweis.textContent = text;
  return hinweis;
}

function meldeFehlendenContainer(id) {
  zeigeFehler(`Ansicht nicht verfügbar: Container #${id} fehlt in index.html.`);
}

function erstelleFeatureListe(features, aufgaben) {
  const liste = document.createElement("ul");
  liste.classList.add("liste");
  for (const feature of features) {
    const punkt = document.createElement("li");
    const link = document.createElement("a");
    link.href = `${FEATURES_ROUTE}/${encodeURIComponent(feature.slug)}`;
    link.textContent = feature.titel;

    const { aufgaben: gefunden } = verbindeAufgaben(feature, aufgaben);
    const zaehler = zaehleGruppen(gruppeAufgaben(gefunden));

    const meta = document.createElement("p");
    meta.classList.add("feature-meta");
    meta.append(erstelleStatusMarke(feature.status, feature.hinweis));
    if (feature.prioritaet) {
      meta.append(document.createTextNode(` · Priorität ${feature.prioritaet}`));
    }
    meta.append(
      document.createTextNode(
        ` · ${zaehler.offen} offen · ${zaehler.inBearbeitung} in Bearbeitung · ${zaehler.erledigt} erledigt`,
      ),
    );

    punkt.append(link, meta);
    liste.append(punkt);
  }
  return liste;
}

/** Statusmarke; Feature-Status wortgleich, Aufgabenstatus aus der API. */
function erstelleStatusMarke(status, hinweis) {
  const marke = document.createElement("span");
  marke.classList.add("status");
  if (status === "umgesetzt" || status === "Geschlossen") marke.classList.add("status--geschlossen");
  if (status === "offen" || status === "Klarung") marke.classList.add("status--klarung");
  marke.append(document.createTextNode(status || KEINE_ANGABE));

  if (hinweis) {
    const zusatz = document.createElement("span");
    zusatz.textContent = ` — ${hinweis}`;
    marke.append(zusatz);
  }
  return marke;
}

function erstelleAufgabenListe(aufgaben) {
  const liste = document.createElement("ul");
  liste.classList.add("liste");
  for (const aufgabe of aufgaben) {
    const punkt = document.createElement("li");
    const link = document.createElement("a");
    link.href = `${DETAIL_VORSCHLAG}${encodeURIComponent(aufgabe.path)}`;
    link.textContent = aufgabe.titel;
    punkt.append(link, erstelleStatusMarke(aufgabe.status, aufgabe.hinweis));
    liste.append(punkt);
  }
  return liste;
}

function erstelleGruppe(schluessel, titel, aufgaben) {
  const gruppe = document.createElement("section");
  gruppe.classList.add("feature-gruppe");
  gruppe.dataset.gruppe = schluessel;
  gruppe.id = `feature-gruppe-${schluessel}`;

  const ueberschrift = document.createElement("h4");
  ueberschrift.classList.add("uebersicht-titel");
  ueberschrift.textContent = `${titel} (${aufgaben.length})`;

  gruppe.append(
    ueberschrift,
    aufgaben.length === 0 ? erstelleHinweis(LEER_GRUPPE) : erstelleAufgabenListe(aufgaben),
  );
  return gruppe;
}

function erstelleSammelhinweis(features, aufgaben) {
  const rest = ohneZuordnung(features, aufgaben);
  if (rest.length === 0) return null;
  const wort = rest.length === 1 ? "Aufgabe" : "Aufgaben";
  return erstelleHinweis(`${rest.length} ${wort} ohne Feature-Zuordnung`, "hinweis");
}

function erstelleFeatureDetail(feature, aufgaben) {
  const bereich = document.createDocumentFragment();

  const titel = document.createElement("h3");
  titel.classList.add("uebersicht-titel");
  titel.textContent = feature.titel;

  const kopf = document.createElement("p");
  kopf.append(erstelleStatusMarke(feature.status, feature.hinweis));
  if (feature.prioritaet) {
    kopf.append(document.createTextNode(` · Priorität ${feature.prioritaet}`));
  }

  const { aufgaben: gefunden, warnungen } = verbindeAufgaben(feature, aufgaben);
  bereich.append(titel, kopf);
  for (const warnung of warnungen) {
    bereich.append(
      erstelleHinweis(`In features.md verlinkt, aber nicht gefunden: ${warnung.pfad}`, "hinweis"),
    );
  }

  if (gefunden.length === 0) {
    bereich.append(erstelleHinweis(LEER_AUFGABEN));
  } else {
    const gruppen = gruppeAufgaben(gefunden);
    for (const { schluessel, titel: gruppenTitel } of GRUPPEN_ANZEIGE) {
      bereich.append(erstelleGruppe(schluessel, gruppenTitel, gruppen[schluessel]));
    }
  }

  const zurueck = document.createElement("a");
  zurueck.classList.add("knopf");
  zurueck.href = FEATURES_ROUTE;
  zurueck.textContent = "← Zurück zur Feature-Liste";

  bereich.append(zurueck);
  return bereich;
}

/**
 * Ansichts-Loader „Feature List": ohne Unterpunkt die Liste aller Features,
 * mit Unterpunkt (Slug) das Feature-Detail mit seinen Aufgaben.
 */
export async function ladeFeaturesAnsicht({ unterpunkt } = {}) {
  const ziel = document.getElementById(CONTAINER_ID);
  if (!ziel) {
    meldeFehlendenContainer(CONTAINER_ID);
    return { ok: true };
  }

  const daten = await getJson(dateiAnfrage(FEATURES_PFAD));
  if (daten === null) {
    ziel.replaceChildren(erstelleHinweis(LADE_FEHLER));
    return { ok: false };
  }
  if (!istDateiAntwort(daten)) {
    ziel.replaceChildren(erstelleHinweis(FORMAT_FEHLER));
    zeigeFehler(FORMAT_FEHLER);
    return { ok: false };
  }

  let features;
  try {
    features = parseFeatures(daten.markdown);
  } catch (fehler) {
    const meldung =
      typeof fehler?.message === "string" && fehler.message.startsWith(FORMAT_PRAEFIX)
        ? fehler.message
        : ABSCHNITT_FEHLER;
    ziel.replaceChildren(erstelleHinweis(meldung));
    zeigeFehler(meldung);
    return { ok: false };
  }

  const name = typeof unterpunkt === "string" ? unterpunkt.trim() : "";
  const feature = name ? features.find((eintrag) => eintrag.slug === name) ?? null : null;
  if (name && !feature) {
    const meldung = `Unbekanntes Feature: ${name}`;
    zeigeFehler(meldung);
    ziel.replaceChildren(erstelleHinweis(meldung));
    return { ok: false };
  }

  const aufgaben = await getJson(AUFGABEN_ENDPUNKT);
  if (aufgaben === null) {
    ziel.replaceChildren(erstelleHinweis(LADE_AUFGABEN_FEHLER));
    return { ok: false };
  }
  if (!Array.isArray(aufgaben)) {
    ziel.replaceChildren(erstelleHinweis(FORMAT_AUFGABEN_FEHLER));
    zeigeFehler(FORMAT_AUFGABEN_FEHLER);
    return { ok: false };
  }

  if (feature) {
    ziel.replaceChildren(erstelleFeatureDetail(feature, aufgaben));
    return { ok: true };
  }
  if (features.length === 0) {
    ziel.replaceChildren(erstelleHinweis(LEER_FEATURES));
    return { ok: true };
  }

  const bereich = document.createDocumentFragment();
  bereich.append(erstelleFeatureListe(features, aufgaben));
  const sammelhinweis = erstelleSammelhinweis(features, aufgaben);
  if (sammelhinweis) bereich.append(sammelhinweis);
  ziel.replaceChildren(bereich);
  return { ok: true };
}
