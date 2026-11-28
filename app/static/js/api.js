const FEHLER_BEREICH_ID = "fehler";
const MELDUNG_BEREICH_ID = "meldung";
const ZEITUEBERSCHREITUNG_MS = 10000;

function bereich(id) {
  return document.getElementById(id);
}

export function zeigeFehler(text) {
  const ziel = bereich(FEHLER_BEREICH_ID);
  if (!ziel) return;
  ziel.textContent = text;
  ziel.hidden = false;
}

export function loescheFehler() {
  const ziel = bereich(FEHLER_BEREICH_ID);
  if (!ziel) return;
  ziel.textContent = "";
  ziel.hidden = true;
}

export function zeigeMeldung(text) {
  const ziel = bereich(MELDUNG_BEREICH_ID);
  if (!ziel) return;
  ziel.textContent = text;
  ziel.hidden = false;
}

export function loescheMeldung() {
  const ziel = bereich(MELDUNG_BEREICH_ID);
  if (!ziel) return;
  ziel.textContent = "";
  ziel.hidden = true;
}

/**
 * Prüft eine `/api/file`-Antwort: Objekt, kein Array und `markdown` als String.
 * Ein Prädikat für alle Ansichten (A14-5); die Meldungen bleiben je Ansicht eigen.
 */
export function istDateiAntwort(daten) {
  return (
    daten !== null &&
    typeof daten === "object" &&
    !Array.isArray(daten) &&
    typeof daten.markdown === "string"
  );
}

/**
 * Liest den Antwort-Body. `204` und leere Bodies liefern `null` ohne Fehler;
 * nicht parsebares JSON wird als Lesefehler gekennzeichnet.
 */
async function leseAntwort(antwort) {
  if (antwort.status === 204) return { gelesen: true, daten: null };

  const typ = antwort.headers.get("content-type") || "";
  if (!typ.includes("application/json")) return { gelesen: true, daten: null };

  const text = await antwort.text();
  if (!text.trim()) return { gelesen: true, daten: null };

  try {
    return { gelesen: true, daten: JSON.parse(text) };
  } catch {
    return { gelesen: false, daten: null };
  }
}

/**
 * Führt einen Request aus und meldet Fehler einheitlich im Fehlerbereich.
 * Gibt bei jedem Fehler `null` zurück, damit Aufrufer ohne try/catch auskommen.
 */
async function anfrage(pfad, optionen = {}) {
  let antwort;
  try {
    antwort = await fetch(pfad, {
      ...optionen,
      signal: optionen.signal ?? AbortSignal.timeout(ZEITUEBERSCHREITUNG_MS),
    });
  } catch (fehler) {
    if (fehler?.name === "TimeoutError") {
      zeigeFehler(
        `Zeitüberschreitung: Der Server hat nicht innerhalb von ${
          ZEITUEBERSCHREITUNG_MS / 1000
        } Sekunden geantwortet.`,
      );
    } else {
      zeigeFehler(`Netzwerkfehler: Server nicht erreichbar (${fehler?.message ?? "unbekannter Fehler"}).`);
    }
    return null;
  }

  const { gelesen, daten } = await leseAntwort(antwort);

  if (!antwort.ok) {
    const meldung =
      daten && typeof daten.error === "string" && daten.error
        ? daten.error
        : `Serverfehler (HTTP ${antwort.status}).`;
    zeigeFehler(meldung);
    return null;
  }

  if (!gelesen) {
    zeigeFehler("Antwort des Servers konnte nicht gelesen werden.");
    return null;
  }

  return daten;
}

export async function getJson(pfad) {
  return anfrage(pfad, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
}

export async function postJson(pfad, daten = {}) {
  return anfrage(pfad, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(daten),
  });
}
