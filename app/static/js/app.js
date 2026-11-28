import { loescheFehler, loescheMeldung, zeigeFehler } from "./api.js";
import { ladeDetail } from "./detail.js";
import { ladeFeaturesAnsicht } from "./features.js";
import { initialisiereFormulare, ladeAufgabenAnsicht, ladeWellenAnsicht } from "./formulare.js";
import { ladeUebersicht } from "./liste.js";
import { ladeEntscheidungenAnsicht, ladeProjektAnsicht } from "./projekt.js";

const STANDARD_ANSICHT = "uebersicht";

// Ordnet jeder Hash-Route die passende Ansichtssektion aus index.html zu.
const ANSICHTEN = {
  uebersicht: "ansicht-uebersicht",
  wellen: "ansicht-wellen",
  aufgaben: "ansicht-aufgaben",
  features: "ansicht-features",
  entscheidungen: "ansicht-entscheidungen",
  projekt: "ansicht-projekt",
  detail: "ansicht-detail",
};

const ladeFunktionen = new Map();

/**
 * Registriert eine Lade-Funktion für eine Ansicht. Spätere Module (A11–A14)
 * hängen sich hier ein, ohne den Router selbst zu verändern.
 *
 * Muss eine Funktionsdeklaration bleiben: die Folgemodule importieren dieses
 * Modul, während es sie importiert (zyklischer Import) — die Hoisting-
 * Eigenschaft der Deklaration verhindert Zugriffe auf `undefined`.
 */
export function registriereAnsicht(basis, ladeFunktion) {
  if (!istAnsicht(basis)) {
    console.warn(`Unbekannte Ansicht registriert: ${basis}`);
    zeigeFehler(`Unbekannte Ansicht registriert: ${basis}`);
    return;
  }
  ladeFunktionen.set(basis, ladeFunktion);
}

function istAnsicht(name) {
  return Object.hasOwn(ANSICHTEN, name);
}

function dekodiere(wert) {
  try {
    return decodeURIComponent(wert);
  } catch {
    return wert;
  }
}

function leseRoute() {
  const roh = window.location.hash.replace(/^#\/?/, "");
  const [basis, ...rest] = roh.split("/");
  return {
    basis: dekodiere(basis || ""),
    unterpunkt: rest.map(dekodiere).join("/"),
  };
}

function zeigeAnsicht(basis) {
  document.querySelectorAll(".ansicht-bereich").forEach((sektion) => {
    sektion.hidden = sektion.dataset.ansicht !== basis;
  });
}

function markiereNavigation(basis, unterpunkt) {
  document.querySelectorAll(".navigation-link").forEach((link) => {
    const linkUnterpunkt = link.dataset.unterpunkt || "";
    // `projekt` hat Unterpunkt-Links; alle anderen Ansichten (auch `features`)
    // haben genau einen Menüpunkt, der auf allen Routen der Ansicht aktiv bleibt.
    const aktiv =
      link.dataset.ansicht === basis &&
      (basis === "projekt" ? linkUnterpunkt === unterpunkt : linkUnterpunkt === "");

    link.classList.toggle("aktiv", aktiv);
    if (aktiv) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
}

export function navigiere() {
  const { basis: rohBasis, unterpunkt } = leseRoute();
  const basis = istAnsicht(rohBasis) ? rohBasis : STANDARD_ANSICHT;

  zeigeAnsicht(basis);
  markiereNavigation(basis, basis === rohBasis ? unterpunkt : "");
  loescheFehler();
  loescheMeldung();

  if (rohBasis && basis !== rohBasis) {
    zeigeFehler(`Unbekannte Ansicht: ${rohBasis}`);
  }

  const lade = ladeFunktionen.get(basis);
  if (!lade) return;

  try {
    const ergebnis = lade({ basis, unterpunkt });
    if (ergebnis && typeof ergebnis.catch === "function") {
      ergebnis.catch((fehler) => {
        zeigeFehler(`Ansicht konnte nicht geladen werden: ${fehler?.message ?? "unbekannter Fehler"}`);
      });
    }
  } catch (fehler) {
    zeigeFehler(`Ansicht konnte nicht geladen werden: ${fehler?.message ?? "unbekannter Fehler"}`);
  }
}

// Listenansicht (A11): Übersicht, Wellen und Aufgaben teilen sich liste.js.
// Formulare (A13): Wellen-/Aufgabenansicht laden zusätzlich ihren Formularzustand.
registriereAnsicht("uebersicht", ladeUebersicht);
registriereAnsicht("wellen", ladeWellenAnsicht);
registriereAnsicht("aufgaben", ladeAufgabenAnsicht);

// Feature-List (A23): Liste aller Features und je Feature die zugehörigen Aufgaben.
registriereAnsicht("features", ladeFeaturesAnsicht);

// Detailansicht (A12): Klick auf eine Listenzeile öffnet den Punkt.
registriereAnsicht("detail", ladeDetail);

// Projekt-Ansicht (A14): Entscheidungslog und die fünf Projekt-Unterpunkte.
registriereAnsicht("entscheidungen", ladeEntscheidungenAnsicht);
registriereAnsicht("projekt", ladeProjektAnsicht);

function oeffneDetail(event) {
  const zeile = event.target.closest?.("tr[data-path]");
  if (!zeile) return;

  window.location.hash = `#/detail/${encodeURIComponent(zeile.dataset.path)}`;
}

function starte() {
  document.addEventListener("click", oeffneDetail);
  window.addEventListener("hashchange", navigiere);
  initialisiereFormulare();
  navigiere();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", starte);
} else {
  starte();
}
