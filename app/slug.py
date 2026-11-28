"""Gemeinsame Slug-Regel (R2) für Aufgaben- und Wellen-Dateinamen.

Ein Slug ist ASCII, kleingeschrieben, enthält nur ``a-z``/``0-9`` mit ``-``
als Trenner und höchstens 60 Zeichen. Umlaute und Klein-``ß`` werden
umgeschrieben; Groß-``ẞ`` fällt unter die Exoten-Regel (``-``, am Rand
entfernt).
Akzente werden per NFKD entfernt; alle übrigen Zeichen trennen. Bleibt kein
verwendbares Zeichen übrig, ist das Ergebnis leer — die Aufrufer entscheiden
über Fehler bzw. Fallback.
"""

from __future__ import annotations

import re
import unicodedata

MAX_SLUG_LAENGE = 60

_UMLAUTE = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
    }
)
_NICHT_SLUG = re.compile(r"[^a-z0-9]+")


def slug_aus_titel(titel: str) -> str:
    """ASCII-Slug aus dem Titel: Umlaute → ASCII, Sonderzeichen → ``-``, max. 60."""
    text = str(titel).translate(_UMLAUTE).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(zeichen for zeichen in text if not unicodedata.combining(zeichen))

    slug = _NICHT_SLUG.sub("-", text).strip("-")
    if len(slug) > MAX_SLUG_LAENGE:
        slug = slug[:MAX_SLUG_LAENGE].rstrip("-")
    return slug
