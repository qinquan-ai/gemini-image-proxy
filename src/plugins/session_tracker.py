import urllib.parse
from typing import Dict, List, Optional
from playwright.async_api import Page
from ..utils.logger import logger

class SessionTrackerPlugin:
    """
    轻量级、插拔式的 Chat Session ID 追踪与对比调试插件
    解析 Gemini 前端真实路由 URL (https://gemini.google.com/app/<chat_id>) 提取真实 Session ID
    """
    def __init__(self):
        self.records: List[Dict[str, str]] = []

    async def capture(self, page: Page, task_name: str) -> Optional[str]:
        """抓取当前页面所在的真实 Gemini Chat ID"""
        try:
            current_url = page.url
            parsed = urllib.parse.urlparse(current_url)
            path_parts = [p for p in parsed.path.split('/') if p]
            
            # 提取 /app/<chat_id> 中的 chat_id
            chat_id = "NEW_UNSAVED_CHAT"
            if len(path_parts) >= 2 and path_parts[0] == "app":
                chat_id = path_parts[1]
                
            # 尝试抓取侧边栏高亮条目的 Chat 标题
            active_title = "未知"
            title_el = await page.query_selector('div[class*="selected"] .conversation-title, div[aria-selected="true"]')
            if title_el:
                active_title = (await title_el.inner_text()).strip()

            record = {
                "task_name": task_name,
                "chat_id": chat_id,
                "url": current_url,
                "active_title": active_title
            }
            self.records.append(record)

            logger.info(f"🕵️ [SessionTracker] 任务 '{task_name}' 真实 Chat ID: {chat_id}")
            return chat_id
        except Exception as e:
            logger.warning(f"⚠️ [SessionTracker] 抓取 Chat ID 失败: {e}")
            return None

    def print_summary(self):
        """对比并打印多个任务间的 Chat Session ID 对比报告"""
        logger.info("\n" + "=" * 65)
        logger.info("📊 [SessionTracker 插件调试报告]")
        logger.info("=" * 65)

        if not self.records:
            logger.warning("未检测到任何记录。")
            return

        chat_ids = set()
        for idx, rec in enumerate(self.records):
            chat_ids.add(rec['chat_id'])
            logger.info(f"  任务 {idx+1} [{rec['task_name']}]:")
            logger.info(f"    ├─ Chat ID:  {rec['chat_id']}")
            logger.info(f"    └─ 完整 URL: {rec['url']}")

        logger.info("-" * 65)
        if len(chat_ids) == 1:
            logger.info(f"✅ 【判定成功】 所有任务均在同一个 Chat 窗口内完成！(ID: {list(chat_ids)[0]})")
        else:
            logger.info(f"⚠️ 【判定偏离】 检测到 {len(chat_ids)} 个不同的 Chat ID (产生了新记录条目): {list(chat_ids)}")
        logger.info("=" * 65 + "\n")

    def reset(self):
        """重置记录器"""
        self.records.clear()
