import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from src.auth.chrome_cookie_bridge import BRIDGE_CLIENT_HEADER, ChromeCookieBridge
from src.auth.chrome_profile import ChromeProfileStore
from src.auth.cookie_manager import CookieManager
from src.auth.profile_launcher import SystemChromeLauncher


def test_cookie_normalization_filters_google_and_prefers_broad_domain():
    cookies = [
        {"name": "SID", "value": "host", "domain": "accounts.google.com"},
        {"name": "SID", "value": "broad", "domain": ".google.com"},
        {"name": "__Secure-1PSID", "value": "psid", "domain": ".google.com"},
        {"name": "not_google", "value": "ignored", "domain": ".example.com"},
        {"name": "lookalike", "value": "ignored", "domain": ".evilgoogle.com"},
    ]

    records = CookieManager.normalize_cookies(cookies)

    assert [record["name"] for record in records] == ["SID", "__Secure-1PSID"]
    assert records[0]["value"] == "broad"
    assert CookieManager.validate_google_session(records)


def test_cookie_validation_rejects_empty_auth_values():
    assert not CookieManager.validate_google_session(
        [{"name": "__Secure-1PSID", "value": "", "domain": ".google.com"}]
    )


def test_update_env_file_preserves_other_values_and_quotes_cookie_header(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GATEWAY_PORT=4981\nGEMINI_RAW_COOKIES=\"old\"\n",
        encoding="utf-8",
    )

    CookieManager.update_env_file(
        "SID=new; __Secure-1PSID=token with spaces",
        env_path=env_path,
    )

    content = env_path.read_text(encoding="utf-8")
    assert "GATEWAY_PORT=4981" in content
    assert 'GEMINI_RAW_COOKIES="SID=new; __Secure-1PSID=token with spaces"' in content
    assert content.count("GEMINI_RAW_COOKIES=") == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_update_env_file_preserves_crlf_without_doubling_line_endings(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"A=1\r\nGEMINI_RAW_COOKIES=old\r\n")

    CookieManager.update_env_file("SID=new", env_path=env_path)

    content = env_path.read_bytes()
    assert b"\r\r\n" not in content
    assert b"A=1\r\n" in content


def test_profile_store_returns_last_used_profile(tmp_path: Path):
    (tmp_path / "Default").mkdir()
    (tmp_path / "Profile 1").mkdir()
    (tmp_path / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    (tmp_path / "Profile 1" / "Preferences").write_text("{}", encoding="utf-8")
    (tmp_path / "Local State").write_text(
        json.dumps(
            {
                "profile": {
                    "last_used": "Profile 1",
                    "last_active_profiles": ["Profile 1"],
                    "info_cache": {
                        "Default": {"name": "First", "user_name": "first@example.com"},
                        "Profile 1": {"name": "Second", "user_name": "second@example.com"},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    store = ChromeProfileStore(tmp_path)
    selected = store.current_profile()

    assert selected is not None
    assert selected.directory == "Profile 1"
    assert selected.name == "Second"


def test_profile_store_detects_bridge_extension_and_cli_selection(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    extension_dir = tmp_path / "bridge"
    extension_dir.mkdir()
    for directory in ("Default", "Profile 1"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "Preferences").write_text("{}", encoding="utf-8")
    (tmp_path / "Profile 1" / "Secure Preferences").write_text(
        json.dumps(
            {
                "extensions": {
                    "settings": {
                        "extension-id": {"path": str(extension_dir)},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "Local State").write_text(
        json.dumps(
            {
                "profile": {
                    "last_used": "Default",
                    "info_cache": {
                        "Default": {"name": "First", "user_name": "first@example.com"},
                        "Profile 1": {"name": "Second", "user_name": "second@example.com"},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    store = ChromeProfileStore(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    selected = store.choose_interactively(extension_dir=extension_dir)
    output = capsys.readouterr().out

    assert selected is not None
    assert selected.directory == "Profile 1"
    assert store.extension_installed(selected, extension_dir)
    assert "[1] First" in output
    assert "[2] Second" in output
    assert "桥接扩展已安装" in output


def test_cookie_bridge_receives_only_authenticated_gemini_capture():
    payload = {
        "cookies": [
            {"name": "__Secure-1PSID", "value": "secret", "domain": ".google.com"}
        ],
        "url": "https://gemini.google.com/app",
        "page": {"hasEditor": True, "hasSignIn": False},
    }

    with ChromeCookieBridge(port=0) as bridge:
        background = (bridge.extension_dir / "background.js").read_text(encoding="utf-8")
        assert "https://gemini.google.com/app" in background
        status_request = urllib.request.Request(
            bridge.status_url,
            headers={"X-Gemini-Cookie-Bridge": BRIDGE_CLIENT_HEADER},
        )
        with urllib.request.urlopen(status_request, timeout=2) as response:
            status = json.load(response)
        assert status["active"] is True
        assert status["token"]
        assert bridge.extension_seen

        request = urllib.request.Request(
            bridge.callback_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Gemini-Cookie-Bridge": BRIDGE_CLIENT_HEADER,
                "X-Gemini-Cookie-Bridge-Token": status["token"],
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 204
        capture = bridge.wait(timeout_seconds=1)

    assert capture is not None
    assert capture.url == "https://gemini.google.com/app"
    assert capture.has_editor
    assert not capture.has_sign_in
    assert capture.cookies[0]["name"] == "__Secure-1PSID"


def test_cookie_bridge_rejects_requests_without_extension_header():
    with ChromeCookieBridge(port=0) as bridge:
        request = urllib.request.Request(bridge.status_url)
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("bridge accepted a request without the extension header")


def test_profile_picker_does_not_force_the_last_active_profile(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    SystemChromeLauncher._launch_profile_picker(
        "chrome.exe",
        tmp_path,
        "http://127.0.0.1:7890",
    )

    command = captured["command"]
    assert "--show-profile-picker" in command
    assert "https://gemini.google.com/app" not in command
    assert not any(argument.startswith("--profile-directory=") for argument in command)


def test_selected_profile_launches_headless_gemini_without_picker(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    SystemChromeLauncher._launch_selected_profile(
        "chrome.exe",
        tmp_path,
        "Profile 4",
        "http://127.0.0.1:7890",
        headless=True,
    )

    command = captured["command"]
    assert "--headless=new" in command
    assert "--profile-directory=Profile 4" in command
    assert "https://gemini.google.com/app" in command
    assert "--show-profile-picker" not in command
