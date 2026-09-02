from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .chrome_cookie_bridge import ChromeCookieBridge, GEMINI_URL
from .chrome_profile import ChromeProfileStore
from .cookie_manager import CookieManager
from ..utils.logger import logger


class SystemChromeLauncher:
    """Capture cookies from a selected native Chrome profile on Gemini itself."""

    @staticmethod
    def get_system_chrome_path() -> str | None:
        possible_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]
        for path in possible_paths:
            if os.path.isfile(path):
                return path
        return None

    @staticmethod
    def _proxy_args(proxy_server: str | None) -> list[str]:
        return [f"--proxy-server={proxy_server}"] if proxy_server else []

    @classmethod
    def _launch_profile_picker(
        cls,
        chrome_path: str,
        user_data_dir: Path,
        proxy_server: str | None,
    ) -> subprocess.Popen[Any]:
        command = [
            chrome_path,
            f"--user-data-dir={user_data_dir}",
            "--show-profile-picker",
            "--no-first-run",
            "--no-default-browser-check",
            *cls._proxy_args(proxy_server),
        ]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    @classmethod
    def _launch_selected_profile(
        cls,
        chrome_path: str,
        user_data_dir: Path,
        profile_directory: str,
        proxy_server: str | None,
        *,
        headless: bool = True,
    ) -> subprocess.Popen[Any]:
        command = [
            chrome_path,
            f"--user-data-dir={user_data_dir}",
            f"--profile-directory={profile_directory}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            *cls._proxy_args(proxy_server),
        ]
        if headless:
            command.extend(["--headless=new", "--window-size=1280,900"])
        command.append(GEMINI_URL)
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
        """Stop only the headless Chrome process started by this refresh run."""

        try:
            import psutil
        except ImportError:  # pragma: no cover - optional platform dependency
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            return

        try:
            root = psutil.Process(process.pid)
            children = root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return

        for child in reversed(children):
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass
        try:
            root.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass

        gone, alive = psutil.wait_procs([*children, root], timeout=5)
        for child in alive:
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass
        try:
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass

    @classmethod
    def open_extension_setup(
        cls,
        *,
        user_data_dir: Path | None = None,
        profile_directory: str | None = None,
    ) -> bool:
        """Open the one-time unpacked-extension setup for a Chrome profile."""

        chrome_path = cls.get_system_chrome_path()
        if not chrome_path:
            logger.error("[CookieRefresh] System Chrome was not found.")
            return False

        store = ChromeProfileStore(user_data_dir)
        profiles = {profile.directory: profile for profile in store.profiles()}
        selected = profiles.get(profile_directory) if profile_directory else store.current_profile()
        if not selected:
            logger.error(
                "[CookieRefresh] Chrome profile was not found: %s",
                profile_directory or "last used profile",
            )
            return False

        extension_dir = ChromeCookieBridge().extension_dir.resolve()
        command = [
            chrome_path,
            f"--user-data-dir={store.user_data_dir}",
            f"--profile-directory={selected.directory}",
            "--no-first-run",
            "--no-default-browser-check",
            "chrome://extensions",
        ]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            subprocess.Popen(
                ["explorer.exe", str(extension_dir)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.error("[CookieRefresh] Failed to open extension setup: %s", exc)
            return False

        logger.info(
            "[CookieRefresh] Opened extension setup for %s (%s).",
            selected.name,
            selected.directory,
        )
        logger.info(
            "[CookieRefresh] Enable Developer mode, click Load unpacked, and select: %s",
            extension_dir,
        )
        logger.info(
            "[CookieRefresh] This one-time setup is required in each Chrome profile used for refresh."
        )
        return True

    @staticmethod
    def _system_chrome_running(chrome_path: str) -> bool:
        try:
            import psutil
        except ImportError:  # pragma: no cover - optional platform dependency
            return False

        expected = os.path.normcase(os.path.abspath(chrome_path))
        for process in psutil.process_iter(["exe"]):
            try:
                executable = process.info.get("exe")
                if executable and os.path.normcase(os.path.abspath(executable)) == expected:
                    return True
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
        return False

    @classmethod
    def _wait_for_chrome_exit(
        cls,
        chrome_path: str,
        timeout_seconds: float,
        poll_interval: float = 0.5,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not cls._system_chrome_running(chrome_path):
                return True
            time.sleep(poll_interval)
        return not cls._system_chrome_running(chrome_path)

    @classmethod
    async def launch_interactive_capture(
        cls,
        proxy_server: str | None = "http://127.0.0.1:7890",
        *,
        user_data_dir: Path | None = None,
        env_path: Path | None = None,
        timeout_seconds: float = 300,
        close_wait_seconds: float = 120,
        profile_directory: str | None = None,
        headless: bool = True,
    ) -> bool:
        """Select an existing profile, open Gemini, and persist its cookies."""

        chrome_path = cls.get_system_chrome_path()
        if not chrome_path:
            logger.error("[CookieRefresh] System Chrome was not found.")
            return False

        store = ChromeProfileStore(user_data_dir)
        if not store.user_data_dir.is_dir():
            logger.error("[CookieRefresh] Chrome User Data was not found: %s", store.user_data_dir)
            return False
        profiles = {profile.directory: profile for profile in store.profiles()}
        if not profiles:
            logger.error("[CookieRefresh] No Chrome profiles were found in %s", store.user_data_dir)
            return False

        if not profile_directory or profile_directory not in profiles:
            logger.error("[CookieRefresh] A valid Chrome profile must be selected before launch.")
            return False
        selected_profile = profiles[profile_directory]

        bridge = ChromeCookieBridge()
        extension_dir = bridge.extension_dir
        if not store.extension_installed(selected_profile, extension_dir):
            logger.error(
                "[CookieRefresh] %s (%s) 未安装 Cookie 桥接扩展。",
                selected_profile.name,
                selected_profile.directory,
            )
            logger.info(
                "[CookieRefresh] 扩展安装需要手动操作（Chrome 安全限制），运行以下命令获得详细指引："
            )
            logger.info(
                "  python scripts/fully_auto_install_extension.py --profile-directory \"%s\"",
                selected_profile.directory,
            )
            logger.info(
                "[CookieRefresh] 或参考文档：docs/EXTENSION_SETUP.md"
            )
            return False

        if cls._system_chrome_running(chrome_path):
            logger.info(
                "[CookieRefresh] Close all system Chrome windows first. "
                "The updater is waiting so the selected profile starts cleanly."
            )
            closed = await asyncio.to_thread(
                cls._wait_for_chrome_exit,
                chrome_path,
                close_wait_seconds,
            )
            if not closed:
                logger.error(
                    "[CookieRefresh] Chrome is still running after %.0f seconds; refresh cancelled.",
                    close_wait_seconds,
                )
                return False

        try:
            bridge.start()
        except (OSError, FileNotFoundError) as exc:
            logger.error("[CookieRefresh] Could not start the local cookie bridge: %s", exc)
            logger.error(
                "[CookieRefresh] Port %d must be free and the extension files must exist.",
                bridge.port,
            )
            return False

        browser_process: subprocess.Popen[Any] | None = None
        try:
            logger.info(
                "[CookieRefresh] Opening %s Chrome for %s (%s).",
                "headless" if headless else "visible",
                selected_profile.name,
                selected_profile.directory,
            )
            logger.info(
                "[CookieRefresh] Gemini page: %s",
                GEMINI_URL,
            )
            logger.info(
                "[CookieRefresh] Cookies are captured only after the Gemini editor confirms login."
            )
            try:
                browser_process = await asyncio.to_thread(
                    cls._launch_selected_profile,
                    chrome_path,
                    store.user_data_dir,
                    selected_profile.directory,
                    proxy_server,
                    headless=headless,
                )
            except OSError as exc:
                logger.error("[CookieRefresh] Failed to launch Chrome: %s", exc)
                return False

            capture = await asyncio.to_thread(bridge.wait, timeout_seconds)
            extension_seen = bridge.extension_seen
        finally:
            if browser_process:
                await asyncio.to_thread(cls._terminate_process_tree, browser_process)
            bridge.close()

        if not capture:
            if not extension_seen:
                logger.error(
                    "[CookieRefresh] The selected profile did not start the cookie refresh extension."
                )
                logger.error(
                    "[CookieRefresh] Install it once in that profile from chrome://extensions: %s",
                    bridge.extension_dir,
                )
            else:
                logger.error(
                    "[CookieRefresh] The extension connected, but no authenticated Gemini editor "
                    "was detected within %.0f seconds.",
                    timeout_seconds,
                )
            return False
        if not capture.url.startswith("https://gemini.google.com/"):
            logger.error("[CookieRefresh] Capture came from an unexpected page: %s", capture.url)
            return False
        if not capture.has_editor or capture.has_sign_in:
            logger.error("[CookieRefresh] Gemini page is not authenticated; cookies were not written.")
            return False

        cookies = CookieManager.normalize_cookies(capture.cookies)
        if not CookieManager.validate_google_session(cookies):
            logger.error("[CookieRefresh] Gemini loaded, but no valid Google auth cookie was returned.")
            return False

        raw_cookie_str = CookieManager.extract_cookie_string(cookies)
        if not raw_cookie_str:
            logger.error("[CookieRefresh] No Google cookies were extracted.")
            return False

        try:
            CookieManager.update_env_file(raw_cookie_str, env_path=env_path)
        except OSError as exc:
            logger.error("[CookieRefresh] Failed to update .env: %s", exc)
            return False

        logger.info(
            "[CookieRefresh] Updated %d Google cookies from %s after Gemini login validation.",
            len(cookies),
            selected_profile.name,
        )
        logger.info("[CookieRefresh] The headless Chrome process started for this run was closed.")
        return True
