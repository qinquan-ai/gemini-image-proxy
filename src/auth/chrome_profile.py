from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChromeProfile:
    directory: str
    name: str
    email: str = ""


class ChromeProfileStore:
    """Inspect Chrome's local profile metadata without controlling its UI."""

    def __init__(self, user_data_dir: Path | None = None):
        self.user_data_dir = Path(user_data_dir or self.default_user_data_dir())

    @staticmethod
    def default_user_data_dir() -> Path:
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Google" / "Chrome" / "User Data"
        return Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"

    @property
    def local_state_path(self) -> Path:
        return self.user_data_dir / "Local State"

    def _read_local_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.local_state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def profiles(self) -> list[ChromeProfile]:
        state = self._read_local_state()
        info_cache = state.get("profile", {}).get("info_cache", {})
        result: list[ChromeProfile] = []

        if isinstance(info_cache, dict):
            for directory, info in info_cache.items():
                if not isinstance(directory, str) or not isinstance(info, dict):
                    continue
                result.append(
                    ChromeProfile(
                        directory=directory,
                        name=str(info.get("name") or directory),
                        email=str(info.get("user_name") or info.get("gaia_name") or ""),
                    )
                )

        if result:
            return result

        for directory in sorted(self.user_data_dir.glob("Profile *")):
            if directory.is_dir():
                result.append(ChromeProfile(directory.name, directory.name))
        default = self.user_data_dir / "Default"
        if default.is_dir():
            result.insert(0, ChromeProfile("Default", "Default"))
        return result

    def current_profile(self) -> ChromeProfile | None:
        state = self._read_local_state()
        profile_state = state.get("profile", {})
        profiles = {profile.directory: profile for profile in self.profiles()}
        last_used = profile_state.get("last_used")
        if last_used in profiles:
            return profiles[last_used]
        active = profile_state.get("last_active_profiles", [])
        if isinstance(active, list):
            for directory in active:
                if directory in profiles:
                    return profiles[directory]
        return None

    @staticmethod
    def _normal_path(path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    def extension_installed(self, profile: ChromeProfile, extension_dir: Path) -> bool:
        """Check Chrome's extension metadata without reading any cookie data."""

        expected = self._normal_path(extension_dir)
        profile_dir = self.user_data_dir / profile.directory
        for filename in ("Secure Preferences", "Preferences"):
            try:
                state = json.loads((profile_dir / filename).read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                continue
            settings = state.get("extensions", {}).get("settings", {})
            if not isinstance(settings, dict):
                continue
            for item in settings.values():
                if isinstance(item, dict) and item.get("path"):
                    if self._normal_path(item["path"]) == expected:
                        return True
        return False

    def choose_interactively(
        self,
        *,
        requested_directory: str | None = None,
        extension_dir: Path | None = None,
    ) -> ChromeProfile | None:
        """List profiles and return the profile selected by its displayed number."""

        profiles = self.profiles()
        if not profiles:
            return None

        by_directory = {profile.directory: profile for profile in profiles}
        if requested_directory:
            return by_directory.get(requested_directory)

        current = self.current_profile()
        print("\n可用的 Chrome 用户资料：", file=sys.stdout)
        for index, profile in enumerate(profiles, start=1):
            marker = " * 当前最后使用" if current and profile.directory == current.directory else ""
            account = f"，{profile.email}" if profile.email else ""
            has_extension = extension_dir and self.extension_installed(profile, extension_dir)
            # 只在未安装扩展时显示警告标记，减少视觉噪音
            extension_warning = " [需要安装扩展]" if extension_dir and not has_extension else ""
            print(
                f"  [{index}] {profile.name}{account} ({profile.directory}){extension_warning}{marker}",
                file=sys.stdout,
            )

        while True:
            try:
                answer = input("请选择用户序号（输入 q 取消）: ").strip()
            except (EOFError, KeyboardInterrupt):
                print(file=sys.stdout)
                return None
            if answer.lower() in {"q", "quit", "exit"}:
                return None
            try:
                index = int(answer)
            except ValueError:
                print("请输入列表中的数字。", file=sys.stdout)
                continue
            if 1 <= index <= len(profiles):
                return profiles[index - 1]
            print(f"请输入 1 到 {len(profiles)} 之间的数字。", file=sys.stdout)
