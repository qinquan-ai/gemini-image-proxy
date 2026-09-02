from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..utils.logger import logger


COOKIE_KEY = "GEMINI_RAW_COOKIES"
AUTH_COOKIE_NAMES = {"__Secure-1PSID", "SID"}


def _cookie_value(cookie: Any, name: str, default: Any = None) -> Any:
    if isinstance(cookie, Mapping):
        return cookie.get(name, default)
    return getattr(cookie, name, default)


class CookieManager:
    """Read, validate, serialize, and persist the selected Chrome session."""

    @staticmethod
    def normalize_cookies(cookies: Iterable[Any]) -> list[dict[str, Any]]:
        """Convert browser-cookie3 or Playwright cookies to stable records.

        Only Google cookies are retained. Duplicate names are resolved in favor
        of the broadest Google domain so the resulting raw Cookie header remains
        compatible with the gateway's existing parser.
        """

        by_name: dict[str, dict[str, Any]] = {}
        for cookie in cookies:
            name = _cookie_value(cookie, "name")
            value = _cookie_value(cookie, "value")
            domain = _cookie_value(cookie, "domain", ".google.com") or ".google.com"
            path = _cookie_value(cookie, "path", "/") or "/"
            if not isinstance(name, str) or not name:
                continue
            if not isinstance(value, str) or not value:
                continue
            normalized_domain = str(domain).lstrip(".").lower()
            if normalized_domain != "google.com" and not normalized_domain.endswith(
                ".google.com"
            ):
                continue

            record = {
                "name": name,
                "value": value,
                "domain": str(domain),
                "path": str(path),
                "secure": bool(_cookie_value(cookie, "secure", False)),
                "httpOnly": bool(_cookie_value(cookie, "httpOnly", False)),
            }
            expires = _cookie_value(
                cookie,
                "expires",
                _cookie_value(cookie, "expirationDate"),
            )
            if isinstance(expires, (int, float)) and expires > 0:
                record["expires"] = int(expires)

            previous = by_name.get(name)
            if previous is None or len(record["domain"]) < len(previous["domain"]):
                by_name[name] = record

        return [by_name[name] for name in sorted(by_name)]

    @classmethod
    def extract_cookie_string(cls, cookies: Iterable[Any]) -> str | None:
        """Serialize normalized cookies to the raw header format used by `.env`."""

        records = cls.normalize_cookies(cookies)
        if not records:
            return None
        return "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in records)

    @classmethod
    def validate_google_session(cls, cookies: Iterable[Any]) -> bool:
        """Perform a structural check for a usable Google login session."""

        records = cls.normalize_cookies(cookies)
        return any(
            cookie["name"] in AUTH_COOKIE_NAMES and bool(cookie["value"])
            for cookie in records
        )

    @staticmethod
    def update_env_file(raw_cookie_str: str, env_path: Path | None = None) -> bool:
        """Atomically replace `GEMINI_RAW_COOKIES` while preserving other config."""

        raw_cookie_str = raw_cookie_str.strip()
        if not raw_cookie_str:
            raise ValueError("Cannot persist an empty Google cookie string.")

        env_path = env_path or Path(__file__).parent.parent.parent / ".env"
        env_path = Path(env_path)
        env_path.parent.mkdir(parents=True, exist_ok=True)
        if env_path.exists():
            with env_path.open("r", encoding="utf-8", newline="") as handle:
                existing = handle.read()
        else:
            existing = ""
        newline = "\r\n" if "\r\n" in existing else "\n"
        replacement = f"{COOKIE_KEY}={json.dumps(raw_cookie_str, ensure_ascii=False)}"
        pattern = re.compile(rf"(?m)^[ \t]*{re.escape(COOKIE_KEY)}[ \t]*=[^\r\n]*")

        if pattern.search(existing):
            updated = pattern.sub(replacement, existing, count=1)
        else:
            updated = existing
            if updated and not updated.endswith(("\n", "\r")):
                updated += newline
            updated += replacement + newline

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=env_path.parent,
                prefix=f".{env_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, env_path)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()

        logger.info("[CookieManager] Persisted the selected Google session to .env")
        return True
