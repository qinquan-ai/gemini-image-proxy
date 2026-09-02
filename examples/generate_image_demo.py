import asyncio
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from src import GeminiSession, Settings, __version__
from src.utils.logger import logger

async def main():
    print("=" * 60)
    print(f"🚀 Gemini Crawl SDK 生图示例 v{__version__}")
    print("=" * 60)

    settings = Settings.load_from_files()

    async with GeminiSession(settings) as session:
        # 生成图 1：Vox 贴纸
        prompt = "Vox style documentary sticker cutout of a futuristic DeepSeek AI whale mascot, halftone texture, thick white sticker keyline border, isolated pure white background."
        saved_files = await session.generate_image(prompt, output_name="vox_deepseek_whale_sdk")
        
        logger.info("\n完成！生成的落地文件列表:")
        for path in saved_files:
            logger.info(f"  - {path.resolve()}")

if __name__ == "__main__":
    asyncio.run(main())
