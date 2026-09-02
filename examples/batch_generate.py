import asyncio
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from src import GeminiSession, Settings
from src.utils.logger import logger

tasks = [
    {
        "name": "vox_liang_wenfeng_portrait",
        "prompt": "Vox style documentary sticker cutout portrait of a visionary tech founder, halftone print texture, distinct white sticker keyline border, hot red accent, isolated pure white background."
    },
    {
        "name": "vox_nvidia_chip",
        "prompt": "Vox style documentary sticker cutout of a futuristic AI semiconductor microchip, halftone texture, thick white keyline border, isolated pure white background."
    }
]

async def main():
    print("=" * 60)
    print(f"🚀 Gemini Image Proxy - 批处理生图示例 v{__version__}")
    print("=" * 60)
    settings = Settings.load_from_files()

    async with GeminiSession(settings) as session:
        for idx, item in enumerate(tasks):
            logger.info(f"\n[{idx+1}/{len(tasks)}] 正在生成: {item['name']}...")
            paths = await session.generate_image(item["prompt"], output_name=item["name"])
            logger.info(f"-> 保存成果: {paths}")

if __name__ == "__main__":
    asyncio.run(main())
