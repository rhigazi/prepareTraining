#!/usr/bin/env bash
# Verifiziert ein Projekt-Setup auf Vollständigkeit und Funktion.
# Nach einem Container-Neustart ausführen: bash definitions/verify.sh
#
# Aufruf: ./verify.sh [ZIELPROJEKT]   (Default: aktuelles Verzeichnis)
# Exit 0 = Setup vollständig; Exit 1 = Befunde vorhanden.
set -uo pipefail

TARGET="${1:-$(pwd)}"
[ -e "$TARGET" ] || { echo "Ziel nicht gefunden: $TARGET" >&2; exit 1; }
TARGET="$(cd "$TARGET" && pwd)"

FAIL=0
ok()   { echo "  ✓ $1"; }
warn() { echo "  ! $1"; }
bad()  { echo "  ✗ $1"; FAIL=1; }

echo "→ Prüfe Setup in: $TARGET"

echo "1) Projektdateien"
for f in AGENTS.md opencode.jsonc \
         tools/telegram_send.py tools/tests/test_telegram_send.py; do
  [ -e "$TARGET/$f" ] && ok "$f" || bad "$f fehlt"
done

# OKF-Wissensgerüst: nur mit `setup.sh --wissen` verteilt. Fehlt es, ist die
# generische „fehlt"-Meldung wenig hilfreich — daher ein eigener Hinweis.
WISSEN_DATEIEN="wissen/index.md wissen/features.md wissen/log.md
wissen/entscheidungen/log.md wissen/aufgaben/index.md
wissen/projekt/phasen.md wissen/projekt/konzept.md
wissen/projekt/technische-spec.md"
WISSEN_GESAMT=0
WISSEN_FEHLT=0
WISSEN_FEHLT_LISTE=""
for f in $WISSEN_DATEIEN; do
  WISSEN_GESAMT=$((WISSEN_GESAMT + 1))
  if [ -e "$TARGET/$f" ]; then
    ok "$f"
  else
    WISSEN_FEHLT=$((WISSEN_FEHLT + 1))
    WISSEN_FEHLT_LISTE="$WISSEN_FEHLT_LISTE${WISSEN_FEHLT_LISTE:+, }$f"
  fi
done
if [ "$WISSEN_FEHLT" -eq "$WISSEN_GESAMT" ]; then
  # Gar kein Gerüst: setup.sh --wissen legt alles neu an, nichts geht verloren.
  bad "OKF-Wissensgerüst fehlt ($WISSEN_FEHLT von $WISSEN_GESAMT Pflichtdateien): $WISSEN_FEHLT_LISTE"
  echo "    → Lösung: setup.sh --wissen ausführen — legt das Gerüst unter $TARGET/wissen/ an (vorhandene Dateien bleiben unangetastet)."
elif [ "$WISSEN_FEHLT" -gt 0 ]; then
  # Teilgerüst: setup.sh --wissen hilft hier nicht (Abschnitt 5 wird bei
  # vorhandenem wissen/index.md übersprungen; fehlt index.md, kopiert `cp -r`
  # die Vorlage über die vorhandenen Wissensdateien).
  bad "OKF-Wissensgerüst unvollständig ($WISSEN_FEHLT von $WISSEN_GESAMT Pflichtdateien fehlen): $WISSEN_FEHLT_LISTE"
  echo "    → Teilgerüst: vorhandene Wissensdateien bleiben erhalten — ergänze die fehlenden Dateien einzeln aus definitions/wissen-vorlage/."
  echo "      setup.sh --wissen allein hilft hier nicht: bei vorhandenem wissen/index.md wird Abschnitt 5 übersprungen (fehlende Datei bleibt fehlend); fehlt index.md, überschreibt es die vorhandenen Wissensdateien."
fi

echo "2) Subagenten"
for a in planner coder reviewer tester documenter; do
  [ -e "$TARGET/.opencode/agents/$a.md" ] && ok ".opencode/agents/$a.md" || bad ".opencode/agents/$a.md fehlt"
done

echo "3) Werkzeuge & Laufzeit"
if command -v python3 >/dev/null 2>&1; then
  ok "python3 $(python3 --version 2>&1 | cut -d' ' -f2)"
else
  bad "python3 fehlt"
fi
if python3 -m pytest --version >/dev/null 2>&1; then
  ok "pytest $(python3 -m pytest --version 2>&1 | head -1 | awk '{print $2}')"
else
  bad "pytest fehlt (setup.sh ausführen oder: python3 -m pip install pytest)"
fi

echo "4) Unit-Tests"
if [ -d "$TARGET/tools/tests" ] && python3 -m pytest "$TARGET/tools/tests/" -q >/dev/null 2>&1; then
  ok "Test-Suite bestanden"
else
  bad "Test-Suite fehlgeschlagen oder nicht vorhanden"
fi

echo "5) CLI-Smoke"
python3 "$TARGET/tools/telegram_send.py" --help >/dev/null 2>&1 \
  && ok "--help → Exit 0" || bad "--help schlägt fehl"
if python3 "$TARGET/tools/telegram_send.py" >/dev/null 2>&1; then
  bad "ohne Argument sollte Exit != 0 sein"
else
  ok "ohne Argument → Exit 1"
fi

echo "6) Globale Umgebung (Hinweise)"
[ -e "$HOME/.agents/skills/okf-knowledge-base/SKILL.md" ] \
  && ok "Skill okf-knowledge-base" || warn "Skill okf-knowledge-base nicht installiert (setup.sh --global)"
[ -e "$HOME/.agents/skills/duckdb-docs/SKILL.md" ] \
  && ok "Skill duckdb-docs" || warn "Skill duckdb-docs nicht installiert (setup.sh --global)"
[ -e "$HOME/.config/opencode/agents/coder.md" ] \
  && ok "globale Subagenten" || warn "globale Subagenten nicht installiert (setup.sh --global)"
command -v moli >/dev/null 2>&1 && ok "moli Browser" || warn "moli nicht im PATH (optional, wird über setup.sh --global installiert)"

echo "7) App (app/ oder definitions/app/)"
FALLBACK=0
for f in server.py static/index.html tests; do
  if [ -e "$TARGET/app/$f" ]; then
    ok "app/$f"
  elif [ -e "$TARGET/definitions/app/$f" ]; then
    ok "definitions/app/$f"
    FALLBACK=1
  else
    bad "app/$f und definitions/app/$f fehlen"
  fi
done
[ "$FALLBACK" -eq 1 ] && warn "App unter definitions/app/ (Fallback) — verteilte Ziele führen sie unter app/"
if [ -d "$TARGET/app/tests" ]; then
  TESTS="$TARGET/app/tests"
elif [ -d "$TARGET/definitions/app/tests" ]; then
  TESTS="$TARGET/definitions/app/tests"
else
  TESTS=""
fi
if [ -z "$TESTS" ]; then
  bad "App-Test-Suite fehlgeschlagen oder nicht vorhanden"
elif python3 -m pytest "$TESTS/" -q >/dev/null 2>&1; then
  ok "App-Test-Suite bestanden"
else
  bad "App-Test-Suite fehlgeschlagen oder nicht vorhanden"
fi

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "✓ Setup vollständig und funktionsfähig."
else
  echo "✗ Setup unvollständig — siehe Befunde oben."
fi
exit "$FAIL"
