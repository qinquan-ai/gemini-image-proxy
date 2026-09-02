import asyncio
from typing import Dict, Any, Optional
from playwright.async_api import Page
from ..utils.logger import logger

class ImageInspectorPlugin:
    """
    轻量级、插拔式的 Gemini 对话图像双重防护与诊断探针插件
    具备：
    1. 【发送前防护 Barrier】: 确认参考原图已成功挂载至输入框缩略图区才允许点击发送，防止误发降级为纯文生图。
    2. 【发送后检验 Inspector】: 检测最新对话气泡内是否有原图缩略图，断言判定【真·图生图】模式。
    """
    def __init__(self):
        self.last_inspection: Dict[str, Any] = {}

    async def wait_for_pre_send_attachment(self, page: Page, timeout_sec: float = 10.0) -> bool:
        """
        【发送前防护门】拦截器
        在调用 send_message 之前，强行拦截校验输入框上方是否有已挂载的图片缩略图
        """
        logger.info("🛡️ [ImageInspector 防护门] 正在校验发送前的输入框原图缩略图挂载状态...")
        start_time = asyncio.get_event_loop().time()
        
        preview_selectors = [
            'file-preview-item',
            'div[class*="preview"]',
            'uploader-file-item',
            'rich-textarea img',
            'div.file-preview',
            'thumbnail-preview',
            'img[src^="data:image"]',
            'img[src^="blob:"]'
        ]

        while (asyncio.get_event_loop().time() - start_time) < timeout_sec:
            for sel in preview_selectors:
                elem = await page.query_selector(sel)
                if elem:
                    box = await elem.bounding_box()
                    if box and box["width"] > 20 and box["height"] > 20:
                        logger.info("✅ [ImageInspector 防护门] 拦截校验通过！确认参考原图已在输入框内渲染好缩略图，放行发送！")
                        return True
            await asyncio.sleep(0.5)

        logger.warning("⚠️ [ImageInspector 防护门] 警告: 未能在超时时间内显式拦截到输入框原图缩略图！")
        return False

    async def inspect_latest_turn(self, page: Page) -> Dict[str, Any]:
        """【发送后检验】诊断最新一轮对话中的图片构成结构"""
        inspection = {
            "has_user_uploaded_image": False,
            "user_image_src": None,
            "generated_image_count": 0,
            "generated_image_urls": [],
            "mode": "文生图 (Text-to-Image)"
        }

        try:
            # 1. 检查最新一个用户消息气泡中是否有上传的参考图缩略图
            user_queries = await page.query_selector_all('user-query, div[class*="user-query"], div.query-content, message-content[class*="user"], conversation-container .user-query')
            if user_queries:
                latest_user_query = user_queries[-1]
                # 兼容 Gemini 多种前端已发送附件/缩略图 DOM 封装 (gds-file-item, div.thumbnail, mat-icon, img)
                uploaded_attachment = await latest_user_query.query_selector(
                    'img, div[class*="image-preview"] img, file-preview img, thumbnail img, gds-file-item, div[class*="attachment"], div[class*="thumbnail"], div[class*="file-item"]'
                )
                if uploaded_attachment:
                    src = await uploaded_attachment.get_attribute("src") or await uploaded_attachment.get_attribute("data-src") or "Attached Image"
                    inspection["has_user_uploaded_image"] = True
                    inspection["user_image_src"] = src[:60] + "..." if len(src) > 60 else src
                    inspection["mode"] = "🔥 【真·图生图 (Image-to-Image)】"

            # 2. 检查模型生成的图片数量与 URL
            model_responses = await page.query_selector_all('div[id^="model-response-message-content"], div[class*="response-container"]')
            if model_responses:
                latest_response = model_responses[-1]
                imgs = await latest_response.query_selector_all('img')
                for img in imgs:
                    box = await img.bounding_box()
                    src = await img.get_attribute("src")
                    if src and box and box["width"] > 150 and box["height"] > 150:
                        if "default-user" not in src:
                            inspection["generated_image_urls"].append(src)

                inspection["generated_image_count"] = len(inspection["generated_image_urls"])

            self.last_inspection = inspection

            # 控制台输出精准诊断结果
            logger.info("\n" + "=" * 65)
            logger.info("📸 [ImageInspector 调试插件报告]")
            logger.info("=" * 65)
            logger.info(f"  └─ 当前交互模式: {inspection['mode']}")
            if inspection["has_user_uploaded_image"]:
                logger.info(f"  └─ 用户参考原图: ✅ 已检测到上传缩略图！({inspection['user_image_src']})")
            else:
                logger.info("  └─ 用户参考原图: ❌ 未检测到上传缩略图 (纯文本 Prompt 模式)")
            logger.info(f"  └─ 模型生成图像: ✅ 捕获到 {inspection['generated_image_count']} 张高精生成图")
            logger.info("=" * 65 + "\n")

            return inspection

        except Exception as e:
            logger.warning(f"⚠️ [ImageInspector] 诊断执行失败: {e}")
            return inspection
