import asyncio
from dataclasses import dataclass
from typing import Optional, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from ..config.settings import Settings
from .errors import BrowserUnavailableError, GeminiAuthenticationError
from ..utils.cookie_parser import parse_raw_cookies_to_playwright
from ..utils.logger import logger


@dataclass(frozen=True)
class GeminiLoginEvidence:
    authenticated: bool
    sign_in_visible: bool
    save_activity_sign_in_visible: bool
    account_control_count: int
    recent_chat_count: int


async def collect_gemini_login_evidence(page: Page) -> GeminiLoginEvidence:
    """Inspect stable visual login signals after Gemini finishes loading."""
    # 检测顶部登录按钮（英文和中文）
    sign_in_link = page.locator('#gb a[href*="ServiceLogin"], #gb a[aria-label="登录"], #gb a[aria-label="Sign in"]')
    sign_in_visible = await sign_in_link.count() > 0
    
    # 检测账户控件（已登录用户的头像/菜单）
    account_control = page.locator(
        '[aria-label*="Google Account"], '
        '[aria-label*="Google 帐号"], '
        '[aria-label*="Google 账号"], '
        '#gb img[src*="googleusercontent.com"]'  # 用户头像
    )
    
    # 检测游客提示
    save_activity_sign_in = page.get_by_text("Sign in to save activity", exact=False)
    save_activity_sign_in_zh = page.get_by_text("登录以保存活动", exact=False)
    
    # 历史对话
    recent_chats = page.locator('a[href^="/app/"]')
    
    account_control_count = await account_control.count()
    recent_chat_count = await recent_chats.count()
    save_activity_visible = (
        await save_activity_sign_in.count() > 0 
        or await save_activity_sign_in_zh.count() > 0
    )
    
    return GeminiLoginEvidence(
        authenticated=(
            not sign_in_visible
            and not save_activity_visible
            and account_control_count > 0
        ),
        sign_in_visible=sign_in_visible,
        save_activity_sign_in_visible=save_activity_visible,
        account_control_count=account_control_count,
        recent_chat_count=recent_chat_count,
    )


class BrowserManager:
    """
    浏览器生命周期管理者
    解耦管理 Playwright 启动、CDP 代理通道挂载、全量 Cookie 注入与探活
    """
    def __init__(self, settings: Settings):
        self.settings = settings
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    @property
    def is_ready(self) -> bool:
        return bool(
            self.playwright
            and self.browser
            and self.browser.is_connected()
            and self.context
        )

    async def start_browser(
        self, keep_browser_on_auth_failure: bool = False
    ) -> Tuple[BrowserContext, Page]:
        """初始化 Playwright 并建立具有身份凭证与代理通道的上下文"""
        if self.is_ready and self.context:
            pages = self.context.pages
            page = pages[0] if pages else await self.context.new_page()
            return self.context, page

        await self.close()
        try:
            self.playwright = await async_playwright().start()
            proxy_option = (
                {"server": self.settings.browser.proxy}
                if self.settings.browser.proxy
                else None
            )

            logger.info(
                "[BrowserManager] Starting Chromium (headless=%s, proxy=%s)",
                self.settings.browser.headless,
                self.settings.browser.proxy,
            )

            self.browser = await self.playwright.chromium.launch(
                headless=self.settings.browser.headless,
                proxy=proxy_option,
                args=["--disable-blink-features=AutomationControlled"],
            )

            headers = {}
            if self.settings.raw_cookies:
                headers["Cookie"] = self.settings.raw_cookies.strip()

            self.context = await self.browser.new_context(
                viewport={
                    "width": self.settings.browser.viewport_width,
                    "height": self.settings.browser.viewport_height,
                },
                extra_http_headers=headers,
                user_agent=self.settings.browser.user_agent,
            )

            cookie_objs = parse_raw_cookies_to_playwright(self.settings.raw_cookies)
            injected = 0
            for cookie in cookie_objs:
                try:
                    await self.context.add_cookies([cookie])
                    injected += 1
                except Exception as exc:
                    logger.debug("Cookie injection failed: %s", exc)
            logger.info(
                "[BrowserManager] Injected %s/%s cookies",
                injected,
                len(cookie_objs),
            )

            page = await self.context.new_page()
            await page.goto(
                "https://gemini.google.com/app",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await asyncio.sleep(2)

            try:
                await page.wait_for_selector("rich-textarea .ql-editor", timeout=25000)
            except Exception:
                logger.warning("Gemini editor probe failed; retrying after reload")
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_selector(
                        "rich-textarea .ql-editor",
                        timeout=20000,
                    )
                except Exception as exc:
                    raise GeminiAuthenticationError(
                        "Gemini session is not authenticated; refresh GEMINI_RAW_COOKIES"
                    ) from exc

            evidence = await collect_gemini_login_evidence(page)
            if not evidence.authenticated:
                raise GeminiAuthenticationError(
                    "Gemini session is not authenticated; refresh GEMINI_RAW_COOKIES"
                )

            logger.info(
                "[BrowserManager] Gemini session is authenticated "
                "(account_controls=%s, recent_chats=%s, save_activity_sign_in=%s)",
                evidence.account_control_count,
                evidence.recent_chat_count,
                evidence.save_activity_sign_in_visible,
            )
            return self.context, page
        except GeminiAuthenticationError:
            if not keep_browser_on_auth_failure:
                await self.close()
            raise
        except Exception as exc:
            await self.close()
            raise BrowserUnavailableError(
                "Chromium or the Gemini page could not be started"
            ) from exc

    async def close(self):
        """优雅关闭浏览器资源"""
        if self.context:
            try:
                await self.context.close()
            except Exception as exc:
                logger.warning("Browser context close failed: %s", exc)
            finally:
                self.context = None
        if self.browser:
            try:
                await self.browser.close()
            except Exception as exc:
                logger.warning("Chromium close failed: %s", exc)
            finally:
                self.browser = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception as exc:
                logger.warning("Playwright shutdown failed: %s", exc)
            finally:
                self.playwright = None
