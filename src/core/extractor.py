import asyncio
from pathlib import Path
from typing import List
from playwright.async_api import Page
from ..utils.logger import logger

class ElementExtractor:
    """
    DOM 元素提取与交互仿真器
    解决 TrustedTypes 限制打字输入，精准识别筛选高精 Imagen 3 渲染图
    """
    @staticmethod
    async def type_prompt_safely(page: Page, prompt: str, delay_ms: int = 5):
        """绕过 TrustedTypes 防火墙，模拟真实键盘打字输入 Prompt"""
        editor = await page.wait_for_selector("rich-textarea .ql-editor", timeout=10000)
        await editor.focus()
        await page.keyboard.type(f"Generate an image: {prompt}", delay=delay_ms)
        await asyncio.sleep(1)

    @staticmethod
    async def upload_image(page: Page, image_path: str):
        """上传参考图片实现真正【图生图】功能 (双轨: 剪贴板 DataTransfer 注入 + 唤醒挂载)"""
        file_path = Path(image_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Input image file not found: {file_path}")

        import base64
        with open(file_path, "rb") as f:
            base64_data = base64.b64encode(f.read()).decode("utf-8")

        ext = file_path.suffix.lower()
        mime_type = "image/png" if ext == ".png" else "image/jpeg"

        logger.info(f"📋 [ElementExtractor] 正在通过剪贴板 DataTransfer 注入原图: {file_path.name}...")

        # 1. 第一轨：尝试通过剪贴板 Paste 事件直接将二进制 File 注入 rich-textarea
        await page.evaluate(f"""async () => {{
            const response = await fetch('data:{mime_type};base64,{base64_data}');
            const blob = await response.blob();
            const file = new File([blob], "{file_path.name}", {{ type: "{mime_type}" }});
            
            const dt = new DataTransfer();
            dt.items.add(file);
            
            const editor = document.querySelector('rich-textarea .ql-editor') || document.querySelector('rich-textarea');
            if (editor) {{
                editor.focus();
                const pasteEvent = new ClipboardEvent('paste', {{
                    bubbles: true,
                    cancelable: true,
                    clipboardData: dt
                }});
                editor.dispatchEvent(pasteEvent);
            }}
        }}""")

        # 2. 第二轨：同步触发DOM内部隐藏 file input 的 set_input_files 作为辅助备选
        file_abs_path = str(file_path.resolve())
        file_inputs = await page.query_selector_all('input[type="file"]')
        for inp in file_inputs:
            try:
                await inp.set_input_files(file_abs_path)
            except Exception:
                pass

        await asyncio.sleep(2)

    @staticmethod
    async def send_message(page: Page):
        """点击发送按钮或触发 Enter 回车"""
        send_btn = await page.query_selector('button[aria-label="Send message"], button[aria-label="发送消息"]')
        if send_btn:
            await send_btn.click()
        else:
            await page.keyboard.press("Enter")

    @staticmethod
    async def open_new_chat(page: Page):
        """如果当前对话已有历史消息，点击开启新对话隔绝上下文"""
        messages = await page.query_selector_all('div[id^="model-response-message-content"]')
        if len(messages) > 0:
            new_chat_btn = await page.query_selector('button[aria-label="New chat"], button[aria-label="发起新聊天"], a[href="/app"]')
            if not new_chat_btn:
                raise RuntimeError("Gemini new-chat control was not found")
            await new_chat_btn.click()
            await asyncio.sleep(2)
            await page.wait_for_selector("rich-textarea .ql-editor", timeout=10000)

    @staticmethod
    async def list_history_chats(page: Page) -> List[dict]:
        """扫描侧边栏 Recents 列表，提取所有历史 Chat ID 与标题"""
        history = []
        try:
            # 显式等待侧边栏历史列表加载
            await page.wait_for_selector('a[href*="/app/"]', timeout=8000)
        except Exception:
            pass

        # 匹配所有侧边栏对话链接
        chat_links = await page.query_selector_all('a[href*="/app/"]')
        for link in chat_links:
            href = await link.get_attribute("href")
            title = (await link.inner_text()).strip()
            if href and "/app/" in href:
                chat_id = href.split("/app/")[-1].strip()
                # 过滤纯 /app 根路径
                if chat_id and chat_id != "app" and "?" not in chat_id:
                    # 避免重复记录
                    if not any(item["chat_id"] == chat_id for item in history):
                        history.append({
                            "chat_id": chat_id,
                            "title": title.replace("\n", " ") or "未命名对话",
                            "url": f"https://gemini.google.com/app/{chat_id}"
                        })
        return history

    @staticmethod
    async def switch_to_chat(page: Page, chat_id: str):
        """跳转并切换到指定的历史 Chat ID 页面"""
        target_url = f"https://gemini.google.com/app/{chat_id}"
        current_url = page.url
        if chat_id not in current_url:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
        try:
            await page.wait_for_selector("rich-textarea .ql-editor", timeout=15000)
        except Exception:
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_selector("rich-textarea .ql-editor", timeout=15000)

    @staticmethod
    async def extract_generated_image_urls(page: Page, min_dimension: int = 150) -> List[str]:
        """
        全页智能扫描并根据尺寸/控件特征过滤出真实的 Imagen 3 生成图 URL
        """
        imgs = await page.query_selector_all('img')
        return await ElementExtractor._extract_large_image_urls(imgs, min_dimension)

    @staticmethod
    async def extract_latest_response_image_urls(
        page: Page,
        min_dimension: int = 150,
    ) -> List[str]:
        """Extract generated images only from the latest model response."""
        model_responses = await page.query_selector_all(
            'div[id^="model-response-message-content"], '
            'div[class*="response-container"]'
        )
        if not model_responses:
            return []
        imgs = await model_responses[-1].query_selector_all("img")
        return await ElementExtractor._extract_large_image_urls(imgs, min_dimension)

    @staticmethod
    async def extract_latest_response_text(page: Page) -> str:
        """Return response text, with a visible-page fallback for Gemini DOM changes."""
        model_responses = await page.query_selector_all(
            'div[id^="model-response-message-content"], '
            'div[class*="response-container"], '
            '[data-message-author-role="model"], '
            '[data-message-author-role="assistant"]'
        )
        if model_responses:
            try:
                response_text = (await model_responses[-1].inner_text()).strip()
                if response_text:
                    return response_text
            except Exception:
                pass

        # Gemini periodically changes response container names. The visible text
        # tail still contains the most recent answer while avoiding a full DOM dump.
        try:
            visible_text = await page.locator("body").inner_text(timeout=1000)
            return visible_text[-6000:].strip()
        except Exception:
            return ""

    @staticmethod
    async def _extract_large_image_urls(imgs, min_dimension: int) -> List[str]:
        image_urls = []

        for img in imgs:
            src = await img.get_attribute("src")
            box = await img.bounding_box()

            if src and box:
                # 校验图片尺寸大图特征 (大于 150px 见方)，排除图标与头像
                if box["width"] >= min_dimension and box["height"] >= min_dimension:
                    if "default-user" not in src and "photo.jpg" not in src and "s64-c" not in src:
                        if src not in image_urls:
                            image_urls.append(src)

        return image_urls
