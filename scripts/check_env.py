import sys
import socket
from pathlib import Path

# 将项目根目录与 src 目录加入 Python 寻址路径
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from src import Settings
from src.utils.logger import logger

def check_socket_port(host: str, port: int) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((host, port))
        s.close()
        return True
    except:
        return False

def main():
    logger.info("🔍 [EnvCheck] 开始对 Gemini Crawl 运行环境进行自检...")
    
    settings = Settings.load_from_files()
    
    # 1. 检查 Cookies
    if not settings.raw_cookies:
        logger.error("❌ [.env 检查失败] 未找到 GEMINI_RAW_COOKIES，请检查 .env 配置")
    else:
        logger.info("✅ [.env 检查成功] 已检测到 GEMINI_RAW_COOKIES 标头字符串")

    # 2. 检查 Clash 代理端口
    proxy_url = settings.browser.proxy
    if proxy_url:
        host_port = proxy_url.replace("http://", "").replace("https://", "").split(":")
        if len(host_port) == 2:
            host, port = host_port[0], int(host_port[1])
            if check_socket_port(host, port):
                logger.info(f"✅ [代理检查成功] 本地代理 {host}:{port} 连通正常！")
            else:
                logger.warning(f"⚠️ [代理连接失败] 本地代理 {host}:{port} 端口未响应，请检查 Clash 服务是否已开启")

    # 3. 检查 Output 目录
    output_dir = settings.task.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"✅ [保存路径检查] 输出目录正常: {output_dir.resolve()}")

    logger.info("🎉 环境自检完成！可以通过 python main.py 直接运行生图任务。")

if __name__ == "__main__":
    main()
