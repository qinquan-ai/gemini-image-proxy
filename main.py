import argparse
import asyncio
import sys
from pathlib import Path

root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from src import GeminiSession, Settings, __version__
from src.core.errors import ImageGatewayError
from src.utils.logger import logger

async def run_cli():
    parser = argparse.ArgumentParser(description=f"Gemini Crawl CLI v{__version__}")
    parser.add_argument("-p", "--prompt", type=str, help="单个生图 Prompt 提示词")
    parser.add_argument("-o", "--output", type=str, default=None, help="输出文件名")
    parser.add_argument("-i", "--image", type=str, default=None, help="参考原图路径 (用于【图生图】)")
    parser.add_argument("-f", "--file", type=str, default=None, help="批处理任务 JSON 文件路径 (例如 tasks.json)")
    parser.add_argument("--config", type=str, default="config.yaml", help="配置文件路径")
    parser.add_argument("--new-chat", action="store_true", default=None, help="每次生图强行开启新对话")
    parser.add_argument("--keep-chat", action="store_true", default=None, help="在同一个对话窗口中连续生图")
    parser.add_argument("--list-chats", action="store_true", help="获取并列出所有历史 Chat ID 列表")
    parser.add_argument("--chat-id", type=str, default=None, help="指定特定的 Chat ID 进行追加生图")

    args = parser.parse_args()

    print("=" * 60)
    print(f"🚀 Gemini Image Proxy Framework v{__version__}")
    print("=" * 60)

    settings = Settings.load_from_files(args.config)

    # 1. 列表模式：直接列出所有历史 Chat ID
    if args.list_chats:
        async with GeminiSession(settings) as session:
            await session.list_chats()
        return

    # 确定 new_chat 标志
    override_new_chat = None
    if args.keep_chat:
        override_new_chat = False
    elif args.new_chat:
        override_new_chat = True

    # 批处理模式
    if args.file:
        task_file = Path(args.file)
        if not task_file.exists():
            logger.error(f"❌ 任务文件不存在: {task_file}")
            return
            
        import json
        try:
            tasks = json.loads(task_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"❌ 解析任务文件失败: {e}")
            return

        logger.info(f"📋 检测到批处理文件，共 {len(tasks)} 个生图任务。在同一个浏览器会话中连续生成 (KeepChat={args.keep_chat})...")
        
        async with GeminiSession(settings) as session:
            for idx, t in enumerate(tasks):
                p_text = t.get("prompt")
                o_name = t.get("name") or f"batch_{idx+1}"
                img_path = t.get("image") or t.get("input_image")
                if p_text:
                    logger.info(f"\n[{idx+1}/{len(tasks)}] 正在生成: {o_name}...")
                    paths = await session.generate_image(
                        p_text, 
                        output_name=o_name, 
                        new_chat=override_new_chat,
                        input_image=img_path
                    )
                    logger.info(f"  ✅ 落地保存: {paths}")
            
            # 打印插件追踪对比报告
            session.tracker.print_summary()
        return

    # 单任务模式
    prompt = args.prompt or "Vox style documentary sticker cutout of a golden trophy award, halftone print texture, thick white sticker keyline border, isolated pure white background."
    
    async with GeminiSession(settings) as session:
        saved_files = await session.generate_image(
            prompt, 
            output_name=args.output, 
            new_chat=override_new_chat,
            chat_id=args.chat_id,
            input_image=args.image
        )
        
        logger.info("\n生成落盘结果:")
        for path in saved_files:
            logger.info(f"  - {path.resolve()}")
            
        session.tracker.print_summary()

if __name__ == "__main__":
    try:
        asyncio.run(run_cli())
    except ImageGatewayError as exc:
        logger.error("Generation failed [%s]: %s", exc.code, exc.message)
        raise SystemExit(1) from exc
