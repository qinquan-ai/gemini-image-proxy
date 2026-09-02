import asyncio
import sys
from pathlib import Path

# 将项目根目录与 src 目录加入 Python 寻址路径
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from src import GeminiSession, Settings, __version__
from src.utils.logger import logger

async def main():
    print("=" * 60)
    print(f"🚀 Gemini Image Proxy - 【图生图】Image-to-Image 示例 v{__version__}")
    print("=" * 60)

    settings = Settings.load_from_files()

    # 参考原图路径
    input_img = root_dir / "output" / "vox_trophy_award_1.png"
    if not input_img.exists():
        logger.error(f"❌ 参考原图不存在，请先运行常规生图任务生成 {input_img}")
        return

    logger.info(f"🖼️ 使用参考原图进行图生图风格转换: {input_img}")

    prompt = "Transform this trophy into a futuristic cyberpunk glowing neon sticker with cyan and magenta accents, halftone texture, white keyline border."

    async with GeminiSession(settings) as session:
        saved_files = await session.generate_image(
            prompt=prompt,
            output_name="cyberpunk_neon_trophy",
            input_image=input_img
        )
        
        logger.info("\n🎉 图生图落地保存结果:")
        for path in saved_files:
            logger.info(f"  - {path.resolve()}")

if __name__ == "__main__":
    asyncio.run(main())
