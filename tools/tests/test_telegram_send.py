"""Tests für das CLI-Werkzeug telegram_send.py (ohne echte API-Aufrufe)."""

import http.client
import io
import json
import socket
import sys
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import telegram_send  # noqa: E402

BOT_TOKEN = "123456:TEST-TOKEN-GEHEIM"
CHAT_ID = "987654321"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


class FakeResponse:
    """Minimaler Ersatz für die von urlopen gelieferte Antwort."""

    def __init__(self, payload, raw=None):
        self._raw = raw if raw is not None else json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """Wechselt in ein leeres Projektverzeichnis (config.json liegt im CWD)."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write_config(directory, **overrides):
    config = {"bot_token": BOT_TOKEN, "chat_id": CHAT_ID}
    config.update(overrides)
    (directory / "config.json").write_text(json.dumps(config), encoding="utf-8")


def make_http_error(code, payload):
    body = json.dumps(payload).encode("utf-8")
    return urllib.error.HTTPError(API_URL, code, "HTTP-Fehler", None, io.BytesIO(body))


def patch_urlopen(return_value=None, side_effect=None):
    return mock.patch.object(
        telegram_send.urllib.request,
        "urlopen",
        return_value=return_value,
        side_effect=side_effect,
    )


def test_sendet_nachricht_und_meldet_erfolg(project_dir, capsys):
    write_config(project_dir)

    with patch_urlopen(return_value=FakeResponse({"ok": True, "result": {}})):
        exit_code = telegram_send.main(["Hallo Welt"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "Nachricht gesendet."
    assert captured.err == ""


def test_erfolgsmeldung_enthaelt_keine_sensiblen_daten(project_dir, capsys):
    write_config(project_dir)

    with patch_urlopen(return_value=FakeResponse({"ok": True})):
        telegram_send.main(["Hallo Welt"])

    captured = capsys.readouterr()
    assert BOT_TOKEN not in captured.out + captured.err
    assert CHAT_ID not in captured.out + captured.err


def test_sendet_json_body_als_klartext_mit_timeout(project_dir):
    write_config(project_dir)

    with patch_urlopen(return_value=FakeResponse({"ok": True})) as urlopen:
        telegram_send.main(["Hallo <b>Welt</b>"])

    request = urlopen.call_args.args[0]
    assert request.full_url == API_URL
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "chat_id": CHAT_ID,
        "text": "Hallo <b>Welt</b>",
    }
    assert urlopen.call_args.kwargs["timeout"] == 10


def test_json_body_enthaelt_kein_parse_mode(project_dir):
    write_config(project_dir)

    with patch_urlopen(return_value=FakeResponse({"ok": True})) as urlopen:
        telegram_send.main(["Hallo *Welt*"])

    body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert "parse_mode" not in body
    assert body["text"] == "Hallo *Welt*"


def test_expliziter_timeout_wird_an_urlopen_uebergeben():
    with patch_urlopen(return_value=FakeResponse({"ok": True})) as urlopen:
        telegram_send.send_message(BOT_TOKEN, CHAT_ID, "Test", timeout=5)

    assert urlopen.call_args.kwargs["timeout"] == 5


def test_send_message_gibt_nichts_aus(capsys):
    with patch_urlopen(return_value=FakeResponse({"ok": True})):
        telegram_send.send_message(BOT_TOKEN, CHAT_ID, "Test")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_leere_nachricht_wird_abgelehnt(project_dir, capsys):
    write_config(project_dir)

    with patch_urlopen() as urlopen:
        exit_code = telegram_send.main(["   "])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "leer" in captured.err.lower()
    urlopen.assert_not_called()


def test_fehlendes_argument_wird_abgelehnt(project_dir, capsys):
    write_config(project_dir)

    with patch_urlopen() as urlopen:
        exit_code = telegram_send.main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err != ""
    urlopen.assert_not_called()


def test_zu_viele_argumente_werden_abgelehnt(project_dir, capsys):
    write_config(project_dir)

    with patch_urlopen() as urlopen:
        exit_code = telegram_send.main(["eins", "zwei"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err != ""
    urlopen.assert_not_called()


def test_fehlende_config_datei_meldet_fehler(project_dir, capsys):
    with patch_urlopen() as urlopen:
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "config.json" in captured.err
    urlopen.assert_not_called()


def test_ungueltiges_json_in_config_meldet_fehler(project_dir, capsys):
    (project_dir / "config.json").write_text("{kein json", encoding="utf-8")

    with patch_urlopen() as urlopen:
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "JSON" in captured.err
    urlopen.assert_not_called()


@pytest.mark.parametrize(
    "config",
    [
        {"chat_id": CHAT_ID},
        {"bot_token": BOT_TOKEN},
        {"bot_token": "", "chat_id": CHAT_ID},
        {"bot_token": BOT_TOKEN, "chat_id": ""},
        {"bot_token": None, "chat_id": CHAT_ID},
        ["bot_token", "chat_id"],
    ],
)
def test_fehlende_oder_ungueltige_schluessel_werden_erkannt(project_dir, capsys, config):
    (project_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")

    with patch_urlopen() as urlopen:
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err != ""
    urlopen.assert_not_called()


def test_api_fehler_ok_false_meldet_beschreibung(project_dir, capsys):
    write_config(project_dir)
    response = FakeResponse(
        {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
    )

    with patch_urlopen(return_value=response):
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Bad Request: chat not found" in captured.err
    assert BOT_TOKEN not in captured.err


def test_http_fehler_meldet_api_beschreibung(project_dir, capsys):
    write_config(project_dir)
    error = make_http_error(401, {"ok": False, "description": "Unauthorized"})

    with patch_urlopen(side_effect=error):
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Unauthorized" in captured.err
    assert BOT_TOKEN not in captured.err


def test_http_fehler_ohne_json_meldet_statuscode(project_dir, capsys):
    write_config(project_dir)
    error = urllib.error.HTTPError(API_URL, 502, "Bad Gateway", None, io.BytesIO(b"<html>"))

    with patch_urlopen(side_effect=error):
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "502" in captured.err
    assert BOT_TOKEN not in captured.err
    assert API_URL not in captured.err


def test_netzwerkfehler_meldet_verstaendlichen_fehler(project_dir, capsys):
    write_config(project_dir)
    error = urllib.error.URLError(ConnectionRefusedError("Verbindung abgelehnt"))

    with patch_urlopen(side_effect=error):
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Netzwerkfehler" in captured.err
    assert BOT_TOKEN not in captured.err


def test_zeitueberschreitung_meldet_verstaendlichen_fehler(project_dir, capsys):
    write_config(project_dir)

    with patch_urlopen(side_effect=TimeoutError("The read operation timed out")):
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Zeit" in captured.err


def test_ungueltige_api_antwort_meldet_fehler(project_dir, capsys):
    write_config(project_dir)

    with patch_urlopen(return_value=FakeResponse(None, raw=b"<html>kein json")):
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Antwort" in captured.err


def test_load_config_liest_token_und_chat_id(project_dir):
    write_config(project_dir)

    config = telegram_send.load_config()

    assert config == {"bot_token": BOT_TOKEN, "chat_id": CHAT_ID}


def test_load_config_akzeptiert_numerische_chat_id(project_dir):
    write_config(project_dir, chat_id=123456789)

    config = telegram_send.load_config()

    assert config["chat_id"] == "123456789"


def test_load_config_meldet_fehlende_datei(project_dir):
    with pytest.raises(telegram_send.ConfigError) as error:
        telegram_send.load_config()

    assert "config.json" in str(error.value)


def test_main_gibt_bei_hilfe_null_zurueck(capsys):
    exit_code = telegram_send.main(["--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "NACHRICHT" in captured.out
    assert "--config" in captured.out


def test_config_mit_steuerzeichen_im_token_wird_abgelehnt(project_dir, capsys):
    write_config(project_dir, bot_token="123456:TEST\nGEHEIM")

    with patch_urlopen() as urlopen:
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "bot_token" in captured.err
    assert "GEHEIM" not in captured.err
    assert API_URL not in captured.err
    assert "Traceback" not in captured.err
    urlopen.assert_not_called()


def test_config_fehler_leakt_keinen_token(project_dir, capsys):
    write_config(project_dir, chat_id="  ")

    with patch_urlopen() as urlopen:
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert BOT_TOKEN not in captured.err
    assert API_URL not in captured.err
    urlopen.assert_not_called()


def test_nicht_lesbare_config_meldet_fehler(project_dir, capsys, monkeypatch):
    write_config(project_dir)

    def read_text_mit_fehler(self, **kwargs):
        raise PermissionError("Zugriff verweigert")

    monkeypatch.setattr(Path, "read_text", read_text_mit_fehler)

    with patch_urlopen() as urlopen:
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "nicht lesbar" in captured.err
    assert BOT_TOKEN not in captured.err
    urlopen.assert_not_called()


def test_config_argument_erlaubt_anderen_pfad(project_dir, tmp_path_factory, capsys):
    anderes_verzeichnis = tmp_path_factory.mktemp("konfiguration")
    write_config(anderes_verzeichnis)
    config_path = anderes_verzeichnis / "config.json"

    with patch_urlopen(return_value=FakeResponse({"ok": True})) as urlopen:
        exit_code = telegram_send.main(["--config", str(config_path), "Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "Nachricht gesendet."
    assert not (project_dir / "config.json").exists()
    urlopen.assert_called_once()


def test_send_message_faengt_http_exception_ohne_url():
    error = http.client.InvalidURL(f"URL can't contain control characters: {API_URL}")

    with patch_urlopen(side_effect=error):
        with pytest.raises(telegram_send.SendError) as send_error:
            telegram_send.send_message(BOT_TOKEN, CHAT_ID, "Test")

    message = str(send_error.value)
    assert BOT_TOKEN not in message
    assert API_URL not in message


def test_http_exception_meldet_fehler_ohne_traceback(project_dir, capsys):
    write_config(project_dir)
    error = http.client.InvalidURL(f"URL kann nicht verarbeitet werden: {API_URL}")

    with patch_urlopen(side_effect=error):
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err != ""
    assert BOT_TOKEN not in captured.err
    assert API_URL not in captured.err
    assert "Traceback" not in captured.err


def test_unerwarteter_fehler_wird_generisch_gemeldet(project_dir, capsys):
    write_config(project_dir)
    error = RuntimeError(f"kaputt: {API_URL}")

    with patch_urlopen(side_effect=error):
        exit_code = telegram_send.main(["Hallo"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err != ""
    assert "kaputt" not in captured.err
    assert BOT_TOKEN not in captured.err
    assert API_URL not in captured.err
    assert "Traceback" not in captured.err


def test_netzwerkfehler_timeout_nutzt_uebergebenen_timeout():
    error = urllib.error.URLError(socket.timeout("The read operation timed out"))

    with patch_urlopen(side_effect=error):
        with pytest.raises(telegram_send.SendError) as send_error:
            telegram_send.send_message(BOT_TOKEN, CHAT_ID, "Test", timeout=3)

    assert "Zeitüberschreitung nach 3 Sekunden" in str(send_error.value)


def test_describe_network_error_nutzt_standard_timeout():
    message = telegram_send._describe_network_error(socket.timeout("zu langsam"))

    assert message == "Zeitüberschreitung nach 10 Sekunden."


class HttpErrorOhneBody:
    """HTTPError-Ersatz, dessen ``read`` einen AttributeError auslöst."""

    code = 500
    fp = None

    def read(self):
        raise AttributeError("'NoneType' object has no attribute 'read'")


def test_describe_http_error_ohne_body_meldet_statuscode():
    message = telegram_send._describe_http_error(HttpErrorOhneBody())

    assert message == "Telegram-API-Fehler: HTTP 500"
