---
type: Feature
title: Projektmanagement-/OKF-Tooling
description: Webapp zur Aufgaben-/Wellen-/Freigabe-Verwaltung, Telegram-Benachrichtigung, Projekt-Setup; Wissensdatenbank.
status: umgesetzt
priority: hoch
---

# Ziel

Projektsteuerung und Wissensdatenbank (OKF) für die Mensch-KI-Zusammenarbeit.

# Umfang

- `app/*.py` (server, meta, freigabe, status, overview, arbeitsstand, …): Projektmanagement-Webapp (OKF-Bundle, Aufgaben/Welle/Freigabe, Status).
- `tools/telegram_send.py`, `tools/neues_projekt.py`: Benachrichtigung und Projektanlage.
- `definitions/*`, `wissen/*`: Setup/Verify, Regeln, Wissensdatenbank.

# Aufgaben

- [A8: Projektmanagement-/OKF-Tooling](/aufgaben/a8-projektmanagement-tooling.md)

# Stand

Umgesetzt (umfangreiche Tests in `app/tests/`, verify.sh Exit 0).
