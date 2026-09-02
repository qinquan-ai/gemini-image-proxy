from typing import Dict, Any, Tuple
from playwright.async_api import Page
from ..utils.logger import logger

class AuthInspectorPlugin:
    """
    🔐 身份认证与登录界面调试插件 (Inspector)
    Diagnose Playwright-controlled pages without hiding blank or unknown states.
    """
    def __init__(self, name: str = "AuthPageInspector"):
        self.name = name

    async def inspect_auth_page(self, page: Page) -> Tuple[str, Dict[str, Any]]:
        """
        探查当前页面状态，返回 (status, details)
        """
        try:
            url = page.url
            title = await page.title()
        except Exception as exc:
            return "PAGE_UNAVAILABLE", {"url": "", "title": str(exc)}
        details = {
            "url": url,
            "title": title,
            "has_editor": False,
            "has_login_btn": False,
            "is_picker": False
        }

        if url == "about:blank":
            return "BLANK_PAGE", details

        # Native Chrome profile-picker pages are not normally exposed to Playwright.
        if "profile-picker" in url or "chrome://" in url:
            details["is_picker"] = True
            logger.info(f"✅ [{self.name}] 成功定位至 Chrome 原生用户选择卡片界面")
            return "PROFILE_PICKER", details

        # 2. 检查 Gemini 界面状态
        if "gemini.google.com" in url:
            has_editor = await page.query_selector("rich-textarea .ql-editor")
            details["has_editor"] = bool(has_editor)

            login_btn = await page.query_selector('a[aria-label*="Sign in"], a[aria-label*="登录"], button:has-text("Sign in"), button:has-text("登录")')
            details["has_login_btn"] = bool(login_btn)

            if has_editor and not login_btn:
                logger.info(f"🎉 [{self.name}] 成功定位至 Gemini 账号已登录主界面！")
                return "GEMINI_LOGGED_IN", details
            elif login_btn:
                logger.info(f"ℹ️ [{self.name}] 页面已调起，当前处于登录选择界面，请在浏览器中完成登录")
                return "GEMINI_LOGGED_OUT", details

        return "UNKNOWN", details

    def print_inspection_report(self, status: str, details: Dict[str, Any]):
        """在控制台打印高可读性的无报错探针报告"""
        logger.info("=" * 65)
        logger.info(f"📸 [{self.name} 页面探针报告]")
        logger.info("=" * 65)
        logger.info(f"  └─ 当前目标 URL : {details.get('url')}")
        logger.info(f"  └─ 页面窗口 Title: {details.get('title') or 'Gemini Web Application'}")
        logger.info(f"  └─ 页面判定状态 : {status}")
        if status == "GEMINI_LOGGED_IN":
            logger.info("  └─ 登录校验结果 : ✅ 100% 有效登录状态")
        elif status in {"BLANK_PAGE", "PAGE_UNAVAILABLE", "UNKNOWN"}:
            logger.info("  └─ 登录校验结果 : ❌ 页面状态未通过，停止自动提取")
        else:
            logger.info("  └─ 登录校验结果 : ℹ️ 界面已就绪，等待交互操作中")
        logger.info("=" * 65)
