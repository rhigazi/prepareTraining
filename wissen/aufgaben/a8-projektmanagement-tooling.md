---
type: Task
title: "A8: Projektmanagement-/OKF-Tooling"
description: Webapp zur Aufgaben-/Wellen-/Freigabe-Verwaltung, Telegram-Benachrichtigung, Projekt-Setup; Wissensdatenbank.
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: hoch
assigned_to: mensch
feature: /features/f8-projektmanagement-tooling.md
---

# Ziel

Projektsteuerung und Wissensdatenbank (OKF) für die Mensch-KI-Zusammenarbeit.

# Akzeptanzkriterien

- Webapp (OKF-Bundle, Aufgaben/Welle/Freigabe, Status) in `app/*.py`.
- Telegram-Benachrichtigung (`tools/telegram_send.py`) und Projektanlage (`tools/neues_projekt.py`).
- Setup/Verify (`definitions/*`) und Wissensdatenbank (`wissen/*`).
- Tests in `app/tests/` grün, `verify.sh` Exit 0.

# Betroffene Dateien

- `app/*`, `tools/*`, `definitions/*`, `wissen/*`

# Ergebnisse

- 2026-11-28: Umgesetzt; App-Suite grün, verify.sh Exit 0, in prepareTraining-Repo gepusht.
