#!/usr/bin/env python3
"""Sendet eine Klartextnachricht über die Telegram Bot API.

Konfiguration: config.json im aktuellen Verzeichnis (oder per ``--config``
angegebener Pfad) mit den Schlüsseln ``bot_token`` und ``chat_id``.

Aufruf:
    python3 telegram_send.py "NACHRICHT"
    python3 telegram_send.py --config pfad/zur/config.json "NACHRICHT"

Exit-Codes: 0 bei Erfolg, 1 bei jedem Fehler (Meldung auf stderr).
"""

import argparse
import http.client
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_FILE = "config.json"
API_URL_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT_SECONDS = 10
SUCCESS_MESSAGE = "Nachricht gesendet."
UNEXPECTED_ERROR_MESSAGE = "Unerwarteter Fehler beim Senden der Nachricht."
REQUIRED_KEYS = ("bot_token", "chat_id")
BOT_TOKEN_PATTERN = re.compile(r"[0-9]+:[A-Za-z0-9_-]+")


class TelegramError(Exception):
    """Basisfehler des Werkzeugs; die Meldung ist für die CLI-Ausgabe gedacht."""


class ConfigError(TelegramError):
    """Die Konfiguration fehlt oder ist ungültig."""


class SendError(TelegramError):
    """Das Senden ist fehlgeschlagen (API- oder Netzwerkfehler)."""


def load_config(path=CONFIG_FILE):
    """Liest und validiert die Konfiguration aus ``path``."""
    config_path = Path(path)
    try:
        raw_config = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigError(
            f"Konfigurationsdatei '{path}' nicht gefunden. "
            "Bitte mit den Schlüsseln 'bot_token' und 'chat_id' anlegen."
        ) from error
    except OSError as error:
        raise ConfigError(f"Konfigurationsdatei '{path}' ist nicht lesbar.") from error

    try:
        config = json.loads(raw_config)
    except json.JSONDecodeError as error:
        raise ConfigError(f"Konfigurationsdatei '{path}' enthält kein gültiges JSON.") from error

    if not isinstance(config, dict):
        raise ConfigError(f"Konfigurationsdatei '{path}' muss ein JSON-Objekt enthalten.")

    values = {}
    for key in REQUIRED_KEYS:
        value = config.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"Schlüssel '{key}' fehlt oder ist leer in '{path}'.")
        values[key] = value.strip()

    if not BOT_TOKEN_PATTERN.fullmatch(values["bot_token"]):
        raise ConfigError(
            f"Schlüssel 'bot_token' hat in '{path}' kein gültiges Format "
            "(erwartet: Ziffern, Doppelpunkt, Token ohne Sonderzeichen)."
        )
    return values


def send_message(bot_token, chat_id, text, timeout=TIMEOUT_SECONDS):
    """Sendet ``text`` als Klartextnachricht an den Chat ``chat_id``."""
    request = urllib.request.Request(
        API_URL_TEMPLATE.format(token=bot_token),
        data=json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_response = response.read()
    except urllib.error.HTTPError as error:
        raise SendError(_describe_http_error(error)) from error
    except urllib.error.URLError as error:
        raise SendError(_describe_network_error(error.reason, timeout)) from error
    except TimeoutError as error:
        raise SendError(f"Zeitüberschreitung nach {timeout} Sekunden.") from error
    except OSError as error:
        raise SendError(f"Netzwerkfehler: {error}") from error
    except http.client.HTTPException as error:
        raise SendError(
            "Ungültige Anfrage an die Telegram-API. Bitte das Tokenformat prüfen."
        ) from error

    payload = _parse_response(raw_response)
    if payload.get("ok") is not True:
        description = payload.get("description")
        if isinstance(description, str) and description:
            raise SendError(f"Telegram-API-Fehler: {description}")
        raise SendError("Telegram-API-Fehler: Die Nachricht wurde nicht angenommen.")


def _parse_response(raw_response):
    try:
        payload = json.loads(raw_response.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise SendError("Ungültige Antwort der Telegram-API erhalten.") from error
    if not isinstance(payload, dict):
        raise SendError("Ungültige Antwort der Telegram-API erhalten.")
    return payload


def _describe_http_error(error):
    """Baut eine Meldung ohne URL, damit der Token nicht in Ausgaben landet."""
    try:
        raw_body = error.read() if getattr(error, "fp", None) is not None else b""
        payload = json.loads(raw_body.decode("utf-8"))
    except (AttributeError, ValueError, OSError, UnicodeDecodeError):
        payload = {}

    description = payload.get("description") if isinstance(payload, dict) else None
    if isinstance(description, str) and description:
        return f"Telegram-API-Fehler: {description}"
    return f"Telegram-API-Fehler: HTTP {error.code}"


def _describe_network_error(reason, timeout=TIMEOUT_SECONDS):
    if isinstance(reason, TimeoutError):
        return f"Zeitüberschreitung nach {timeout} Sekunden."
    return f"Netzwerkfehler: {reason}"


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Sendet eine Klartextnachricht über die Telegram Bot API.",
    )
    parser.add_argument("message", metavar="NACHRICHT", help="zu sendender Nachrichtentext")
    parser.add_argument(
        "--config",
        metavar="PFAD",
        default=CONFIG_FILE,
        help=f"Pfad zur Konfigurationsdatei (Standard: {CONFIG_FILE})",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_signal:
        # argparse beendet sich bei Argumentfehlern mit 2 und bei --help mit 0.
        return 0 if exit_signal.code == 0 else 1

    if not args.message.strip():
        print("Fehler: Die Nachricht darf nicht leer sein.", file=sys.stderr)
        return 1

    try:
        config = load_config(args.config)
        send_message(config["bot_token"], config["chat_id"], args.message)
    except TelegramError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    except Exception:
        # Kein Traceback nach außen, damit weder Token noch URL sichtbar werden.
        print(f"Fehler: {UNEXPECTED_ERROR_MESSAGE}", file=sys.stderr)
        return 1

    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
