import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from src import Settings
from src.core.browser import BrowserManager, collect_gemini_login_evidence
from src.core.errors import GeminiAuthenticationError

EVIDENCE_DIR = root_dir / "output" / "playwright"
RESULT_PATH = EVIDENCE_DIR / "login-check-result.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open Gemini visibly, capture a login-state screenshot, and validate Cookie login."
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep the visible browser open until Enter is pressed after the check.",
    )
    return parser.parse_args()


def save_result(status: str, screenshot_path: Path, evidence: dict) -> None:
    RESULT_PATH.write_text(
        json.dumps(
            {
                "status": status,
                "screenshot": str(screenshot_path),
                "evidence": evidence,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def main() -> int:
    args = parse_args()
    settings = Settings.load_from_files()
    settings.browser.headless = False
    browser = BrowserManager(settings)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        try:
            _, page = await browser.start_browser(keep_browser_on_auth_failure=True)
        except GeminiAuthenticationError:
            screenshot_path = EVIDENCE_DIR / "login-failed.png"
            page = browser.context.pages[0] if browser.context and browser.context.pages else None
            if page:
                evidence = asdict(await collect_gemini_login_evidence(page))
                await page.screenshot(path=str(screenshot_path), full_page=True)
            else:
                evidence = {"page_available": False}
            save_result("FAILED", screenshot_path, evidence)
            print("LOGIN_STATUS=FAILED")
            print(f"SCREENSHOT={screenshot_path}")
            print(f"RESULT={RESULT_PATH}")
            print("REASON=Google login evidence is absent or a guest sign-in prompt is visible.")
            if args.keep_open and page:
                await asyncio.to_thread(input, "Inspect the browser, then press Enter to close it... ")
            return 1

        evidence = asdict(await collect_gemini_login_evidence(page))
        screenshot_path = EVIDENCE_DIR / "login-authenticated.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)
        save_result("AUTHENTICATED", screenshot_path, evidence)
        print("LOGIN_STATUS=AUTHENTICATED")
        print(f"SCREENSHOT={screenshot_path}")
        print(f"RESULT={RESULT_PATH}")
        print(f"ACCOUNT_CONTROL_COUNT={evidence['account_control_count']}")
        print(f"SAVE_ACTIVITY_SIGN_IN_VISIBLE={evidence['save_activity_sign_in_visible']}")
        print(f"RECENT_CHAT_COUNT={evidence['recent_chat_count']}")
        if args.keep_open:
            await asyncio.to_thread(input, "Inspect the browser, then press Enter to close it... ")
        return 0
    finally:
        await browser.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
