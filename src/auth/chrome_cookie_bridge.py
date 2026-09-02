from __future__ import annotations

import hmac
import json
import queue
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


GEMINI_URL = "https://gemini.google.com/app"
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 4982
BRIDGE_CLIENT_HEADER = "gemini-cookie-refresh-extension-v1"
MAX_CAPTURE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class CookieCapture:
    cookies: list[dict[str, Any]]
    url: str
    has_editor: bool
    has_sign_in: bool


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class ChromeCookieBridge:
    """Receive one cookie capture from the extension in the selected profile."""

    def __init__(self, port: int = BRIDGE_PORT):
        if not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        self.port = port
        self._token = secrets.token_urlsafe(24)
        self._captures: queue.Queue[CookieCapture] = queue.Queue(maxsize=1)
        self._extension_seen = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def extension_dir(self) -> Path:
        return Path(__file__).with_name("chrome_extension")

    @property
    def status_url(self) -> str:
        return f"http://{BRIDGE_HOST}:{self.port}/status"

    @property
    def callback_url(self) -> str:
        return f"http://{BRIDGE_HOST}:{self.port}/capture"

    @property
    def extension_seen(self) -> bool:
        return self._extension_seen.is_set()

    def wait_for_extension(self, timeout_seconds: float) -> bool:
        return self._extension_seen.wait(timeout_seconds)

    def _handler_class(self):
        captures = self._captures
        expected_token = self._token
        expected_client = BRIDGE_CLIENT_HEADER
        extension_seen = self._extension_seen

        class CaptureHandler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _is_extension_request(self) -> bool:
                return hmac.compare_digest(
                    self.headers.get("X-Gemini-Cookie-Bridge", ""),
                    expected_client,
                )

            def _send_json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if urlsplit(self.path).path != "/status":
                    self.send_error(404)
                    return
                if not self._is_extension_request():
                    self.send_error(403)
                    return

                extension_seen.set()
                self._send_json(
                    200,
                    {
                        "active": True,
                        "token": expected_token,
                        "geminiUrl": GEMINI_URL,
                    },
                )

            def do_POST(self):
                if urlsplit(self.path).path != "/capture":
                    self.send_error(404)
                    return
                if not self._is_extension_request():
                    self.send_error(403)
                    return
                if not hmac.compare_digest(
                    self.headers.get("X-Gemini-Cookie-Bridge-Token", ""),
                    expected_token,
                ):
                    self.send_error(403)
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self.send_error(400)
                    return
                if length <= 0 or length > MAX_CAPTURE_BYTES:
                    self.send_error(413)
                    return

                try:
                    payload = json.loads(self.rfile.read(length))
                    cookies = payload.get("cookies")
                    page = payload.get("page") or {}
                    if not isinstance(cookies, list):
                        raise ValueError("cookies must be a list")
                    capture = CookieCapture(
                        cookies=[item for item in cookies if isinstance(item, dict)],
                        url=str(payload.get("url") or ""),
                        has_editor=bool(page.get("hasEditor")),
                        has_sign_in=bool(page.get("hasSignIn")),
                    )
                    if captures.empty():
                        captures.put_nowait(capture)
                except (json.JSONDecodeError, ValueError, TypeError, queue.Full):
                    self.send_error(400)
                    return

                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

        return CaptureHandler

    def start(self) -> None:
        if self._server:
            return
        if not (self.extension_dir / "manifest.json").is_file():
            raise FileNotFoundError(
                f"Cookie refresh extension is missing: {self.extension_dir}"
            )
        self._server = _ReusableThreadingHTTPServer(
            (BRIDGE_HOST, self.port),
            self._handler_class(),
        )
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def wait(self, timeout_seconds: float) -> CookieCapture | None:
        try:
            return self._captures.get(timeout=timeout_seconds)
        except queue.Empty:
            return None

    def close(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()
