"""
完全自动化 Chrome 扩展安装（尝试零人工干预）
使用 Playwright 自动化操作 Chrome 扩展管理页面
"""
import asyncio
import argparse
import sys
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from src.auth import ChromeProfileStore
from src.utils.logger import setup_logger

logger = setup_logger("FullyAutoInstall")

EXTENSION_DIR = root_dir / "src" / "auth" / "chrome_extension"
EXTENSION_NAME = "Gemini Cookie Refresh Bridge"


async def fully_automated_install(profile_directory: str, user_data_dir: Path = None):
    """完全自动化安装（尝试零人工）"""
    store = ChromeProfileStore(user_data_dir)
    selected = store.choose_interactively(
        requested_directory=profile_directory,
        extension_dir=EXTENSION_DIR,
    )
    
    if not selected:
        logger.error(f"找不到 Chrome 用户资料：{profile_directory}")
        return False
    
    logger.info(f"🎯 目标 Profile: {selected.name} ({selected.directory})")
    logger.info(f"📦 扩展路径: {EXTENSION_DIR.absolute()}")
    
    # 检查是否已安装
    if store.extension_installed(selected, EXTENSION_DIR):
        logger.info("✅ 扩展已安装，跳过")
        return True
    
    logger.info("\n🚀 尝试完全自动化安装...")
    
    # 方案1: 尝试通过命令行参数加载扩展
    logger.info("方案1: 使用 --load-extension 启动参数")
    try:
        async with async_playwright() as p:
            # 使用 --load-extension 直接加载
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir or store.user_data_dir),
                headless=False,
                args=[
                    f"--profile-directory={selected.directory}",
                    f"--load-extension={EXTENSION_DIR.absolute()}",
                    "--disable-extensions-except=" + str(EXTENSION_DIR.absolute()),
                ],
            )
            
            page = await context.new_page()
            await page.goto("chrome://extensions/")
            await asyncio.sleep(3)
            
            # 验证是否安装成功
            try:
                content = await page.content()
                if EXTENSION_NAME in content:
                    logger.info("✅ 方案1成功：扩展已通过启动参数加载")
                    await context.close()
                    return True
                else:
                    logger.warning("⚠️ 方案1失败：扩展未出现在列表中")
            except Exception as e:
                logger.warning(f"⚠️ 方案1失败: {e}")
            
            await context.close()
    except Exception as e:
        logger.warning(f"⚠️ 方案1异常: {e}")
    
    # 方案2: 尝试通过CDP命令安装
    logger.info("\n方案2: 使用 Chrome DevTools Protocol")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            
            # 使用CDP命令
            cdp = await page.context.new_cdp_session(page)
            
            # 尝试通过CDP加载扩展（需要特殊权限）
            try:
                result = await cdp.send("Extensions.loadUnpacked", {
                    "path": str(EXTENSION_DIR.absolute())
                })
                logger.info(f"✅ 方案2成功: CDP返回 {result}")
                await browser.close()
                return True
            except Exception as e:
                logger.warning(f"⚠️ 方案2失败: {e}")
            
            await browser.close()
    except Exception as e:
        logger.warning(f"⚠️ 方案2异常: {e}")
    
    # 方案3: 回退到半自动模式（显示详细指引）
    logger.info("\n方案3: 半自动模式（需要用户确认）")
    logger.info("=" * 60)
    logger.info("⚠️ 完全自动化失败，Chrome 安全限制阻止了无人值守安装")
    logger.info("=" * 60)
    logger.info("\n📋 请按照以下步骤手动完成（仅需1次）：")
    logger.info("\n1️⃣ 打开 Chrome 扩展管理页面（已自动打开）")
    logger.info("2️⃣ 启用「开发者模式」（右上角开关）")
    logger.info("3️⃣ 点击「加载未打包的扩展程序」按钮")
    logger.info("4️⃣ 在文件选择器中复制粘贴以下路径：")
    logger.info(f"\n   {EXTENSION_DIR.absolute()}")
    logger.info("\n5️⃣ 点击「选择文件夹」")
    logger.info("\n✨ 完成后，扩展将永久生效（无需重复安装）")
    logger.info("=" * 60)
    
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir or store.user_data_dir),
            headless=False,
            args=[f"--profile-directory={selected.directory}"],
        )
        
        page = await context.new_page()
        await page.goto("chrome://extensions/")
        
        # 等待用户完成安装
        logger.info("\n⏳ 等待安装完成（最多60秒）...")
        for i in range(60):
            await asyncio.sleep(1)
            try:
                content = await page.content()
                if EXTENSION_NAME in content:
                    logger.info("✅ 检测到扩展安装成功！")
                    await asyncio.sleep(2)
                    await context.close()
                    return True
            except Exception:
                pass
        
        logger.warning("⏱️ 超时：未检测到扩展安装")
        await context.close()
        return False


async def main():
    parser = argparse.ArgumentParser(description="完全自动化 Chrome 扩展安装")
    parser.add_argument(
        "--profile-directory",
        required=True,
        help="Chrome Profile 目录（例如：Profile 1）"
    )
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        default=None,
        help="Chrome User Data 目录"
    )
    args = parser.parse_args()
    
    success = await fully_automated_install(
        profile_directory=args.profile_directory,
        user_data_dir=args.user_data_dir,
    )
    
    if success:
        logger.info("\n✅ 安装完成！现在可以运行：")
        logger.info(f'   python scripts/update_cookies.py --profile-directory "{args.profile_directory}"')
    else:
        logger.error("\n❌ 安装失败")
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
