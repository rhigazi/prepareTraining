#!/usr/bin/env python3
"""Desktop-Start des OKF Projekt-Managers (Aufgabe A21).

Startet die bestehende Flask-App im **eigenen Prozess** (``server.create_app``,
``make_server`` im Daemon-Thread) und lädt dieselbe SPA in einem
pywebview-Fenster von ``http://127.0.0.1:<port>``. Kein zweites Frontend, keine
``js_api``-Brücke, kein ``file://``.

Auf Modulebene werden nur Standardbibliothek und Konstanten importiert:
``pywebview`` ist eine **optionale** Abhängigkeit und wird erst zur Laufzeit
geladen. Fehlt sie, bricht der Start mit einer deutschen Meldung sauber ab —
der Server-/Browser-Betrieb ist davon unberührt.

Aufruf::

    python3 definitions/app/desktop.py
    bash start.sh --desktop        # gleicher Weg über das Startskript
"""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def _repo_root(app_dir: Path) -> Path:
    """Projektwurzel: ``definitions/app/`` (Dev) oder ``<projekt>/app/`` (verteilt)."""
    if app_dir.parent.name == "definitions":
        return app_dir.parents[1]
    return app_dir.parent


REPO_ROOT = _repo_root(APP_DIR)
BUNDLE_ROOT = REPO_ROOT / "wissen"

PORT_STANDARD = 5000
# Nur Loopback: eine Desktop-App braucht keine LAN-Freigabe.
HOST = "127.0.0.1"
TITEL = "OKF Projekt-Manager"
FENSTER_BREITE = 1200
FENSTER_HOEHE = 800


class DesktopFehler(ValueError):
    """Startfehler des Desktop-Modus; die Meldung geht verständlich nach stderr."""


def _webview_installiert() -> bool:
    """``True``, wenn das Paket ``pywebview`` importierbar wäre."""
    try:
        return importlib.util.find_spec("webview") is not None
    except (ImportError, ValueError):
        # Eintrag ohne Spec: das Paket ist vorhanden, aber nicht sauber ladbar.
        return "webview" in sys.modules


def _meldung_webview() -> str:
    """Deutsche Meldung: Paket fehlt oder ist installiert, aber nicht ladbar."""
    if _webview_installiert():
        return (
            "pywebview ist installiert, aber nicht ladbar — meist fehlt das "
            "Fenster-Backend (unter Linux z. B. GTK/WebKit). Hinweise im "
            "README-Abschnitt „Desktop-Modus (optional)“."
        )
    return (
        "pywebview fehlt. Der Desktop-Modus ist optional; Installation mit "
        "`python3 -m pip install pywebview` (unter Linux zusätzlich das "
        "Fenster-Backend, siehe README). Der Server-/Browser-Betrieb "
        "funktioniert ohne pywebview."
    )


def _lade_webview():
    """Importiert ``webview`` zur Laufzeit; ohne pywebview :class:`DesktopFehler`."""
    if not _webview_installiert():
        raise DesktopFehler(_meldung_webview())
    try:
        import webview
    except ImportError:
        raise DesktopFehler(_meldung_webview()) from None
    return webview


def _lade_server():
    """Importiert ``server`` (Flask) zur Laufzeit — Top-Level bleibt Standardbibliothek."""
    try:
        import server
    except ImportError:
        raise DesktopFehler(
            "Server-Modul nicht ladbar — bitte zuerst die Laufzeitpakete "
            "installieren (bash start.sh)."
        ) from None
    return server


def _bundle_root() -> Path:
    """Bundle-Wurzel: ``BUNDLE_ROOT`` aus der Umgebung hat Vorrang vor der Ableitung."""
    roh = os.environ.get("BUNDLE_ROOT", "").strip()
    if roh:
        return Path(roh).expanduser().resolve()
    return BUNDLE_ROOT


def _port_aus_umgebung() -> int:
    """``PORT`` über die bestehende Validierung aus ``server`` (eine Regelquelle)."""
    return _lade_server()._port_aus_umgebung()


def _port_belegt(port: int) -> bool:
    """Prüft vorab, ob der Loopback-Port belegt ist (fail-loud statt Traceback)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, port))
        except OSError:
            return True
    return False


def _starte_server(app, port: int):
    """Bindet synchron einen Loopback-Server und bedient ihn im Daemon-Thread.

    ``make_server`` bindet schon im Konstruktor — der Server ist damit bereit,
    bevor das Fenster seine URL lädt. ``shutdown()`` beendet ihn; der Thread
    schließt den Socket anschließend, damit der Port wieder frei ist.
    """
    from werkzeug.serving import make_server

    server = make_server(HOST, port, app, threaded=True)

    def bedienen() -> None:
        try:
            server.serve_forever()
        finally:
            server.server_close()

    threading.Thread(target=bedienen, name="okf-desktop-server", daemon=True).start()
    return server


def _starte_fenster(webview, url: str) -> None:
    """Öffnet das Fenster im Hauptthread; ``start`` blockiert bis zum Schließen."""
    webview.create_window(TITEL, url, width=FENSTER_BREITE, height=FENSTER_HOEHE)
    webview.start()


def _beende_server(handle) -> None:
    """Stoppt den Serverhandle; der Socket wird bestmöglich mitgeschlossen."""
    handle.shutdown()
    schliessen = getattr(handle, "server_close", None)
    if schliessen is not None:
        schliessen()


def main() -> int:
    """Startet Server und Fenster; Rückgabe ist der Exit-Code."""
    try:
        webview = _lade_webview()
    except DesktopFehler as fehler:
        print(f"Start abgebrochen: {fehler}", file=sys.stderr)
        return 1

    try:
        server = _lade_server()
    except DesktopFehler as fehler:
        print(f"Start abgebrochen: {fehler}", file=sys.stderr)
        return 1

    try:
        port = _port_aus_umgebung()
        app = server.create_app(_bundle_root())
    except server.StartFehler as fehler:
        print(f"Start abgebrochen: {fehler}", file=sys.stderr)
        return 1

    if _port_belegt(port):
        print(
            f"Start abgebrochen: Port {port} ist bereits belegt — bitte einen "
            f"freien Port wählen (PORT=<frei> bash start.sh --desktop).",
            file=sys.stderr,
        )
        return 1

    handle = _starte_server(app, port)
    url = f"http://{HOST}:{port}"
    print(f"{TITEL} startet im Desktop-Fenster: {url}", flush=True)
    try:
        _starte_fenster(webview, url)
    except KeyboardInterrupt:
        pass
    except Exception as fehler:
        print(f"Desktop-Fenster konnte nicht gestartet werden: {fehler}", file=sys.stderr)
        return 1
    finally:
        _beende_server(handle)

    print("Desktop-Fenster beendet.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
