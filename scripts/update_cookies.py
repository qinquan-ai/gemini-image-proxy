import asyncio
import argparse
import sys
from pathlib import Path

# 将项目根目录与 src 目录加入 Python 寻址路径
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from src.auth import ChromeCookieBridge, ChromeProfileStore, SystemChromeLauncher
from src.config.settings import Settings

async def main():
    parser = argparse.ArgumentParser(description="Refresh Gemini cookies from a selected local Chrome profile.")
    parser.add_argument("--proxy", default=None, help="Chrome/validation proxy URL; defaults to config.yaml or 127.0.0.1:7890")
    parser.add_argument("--user-data-dir", type=Path, default=None, help="Chrome User Data directory")
    parser.add_argument("--env-file", type=Path, default=None, help=".env file to update")
    parser.add_argument("--timeout", type=float, default=300, help="Seconds to wait for an authenticated Gemini page")
    parser.add_argument("--close-wait", type=float, default=120, help="Seconds to wait for existing Chrome windows to close")
    parser.add_argument(
        "--setup-extension",
        action="store_true",
        help="Select a Chrome profile and open its one-time extension setup",
    )
    parser.add_argument(
        "--profile-directory",
        default=None,
        help="Skip the menu and use this Chrome profile directory (for example: Profile 4)",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Show the selected Chrome profile for troubleshooting; default is headless",
    )
    args = parser.parse_args()

    store = ChromeProfileStore(args.user_data_dir)
    extension_dir = ChromeCookieBridge().extension_dir
    selected = store.choose_interactively(
        requested_directory=args.profile_directory,
        extension_dir=extension_dir,
    )
    if not selected:
        if args.profile_directory:
            print(f"找不到 Chrome 用户资料：{args.profile_directory}")
        raise SystemExit(1)

    if args.setup_extension:
        success = SystemChromeLauncher.open_extension_setup(
            user_data_dir=args.user_data_dir,
            profile_directory=selected.directory,
        )
        if not success:
            raise SystemExit(1)
        return

    settings = Settings.load_from_files()
    proxy = args.proxy if args.proxy is not None else (settings.browser.proxy or "http://127.0.0.1:7890")
    success = await SystemChromeLauncher.launch_interactive_capture(
        proxy_server=proxy,
        user_data_dir=args.user_data_dir,
        env_path=args.env_file,
        timeout_seconds=args.timeout,
        close_wait_seconds=args.close_wait,
        profile_directory=selected.directory,
        headless=not args.visible,
    )
    if not success:
        raise SystemExit(1)

if __name__ == "__main__":
    asyncio.run(main())
