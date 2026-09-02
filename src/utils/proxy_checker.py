"""
代理地理位置检测工具
用于在 Gateway 启动时验证代理是否位于支持 Gemini 图像生成的地区
"""
import httpx
from typing import Optional, Dict, Any
from ..utils.logger import logger


class ProxyLocationChecker:
    """检查代理服务器的地理位置"""
    
    # 已验证支持图像生成的国家/地区（基于 2026 年数据）
    VERIFIED_SAFE_COUNTRIES = {"US", "CA", "AU", "SG", "IN", "KR", "BR", "MX"}
    
    # 完全被 Google 屏蔽的国家
    BLOCKED_COUNTRIES = {"CN", "RU", "IR", "KP"}  # 中国、俄罗斯、伊朗、朝鲜
    
    # 图像生成功能受限的国家/地区（隐私法规或区域限制）
    RESTRICTED_COUNTRIES = {"JP"}  # 日本（已知会降级为 Flash-Lite）
    
    # 欧盟国家代码（隐私法规可能限制图像生成）
    EU_COUNTRIES = {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", 
        "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", 
        "PL", "PT", "RO", "SK", "SI", "ES", "SE", "CH", "GB"  # 欧盟+英国+瑞士
    }
    
    @staticmethod
    async def check_proxy_location(proxy_url: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """
        检查代理的地理位置
        
        Returns:
            {
                "country": "美国",
                "countryCode": "US",
                "city": "洛杉矶",
                "region": "CA",
                "status": "success",
                "query": "142.249.39.246"
            }
        """
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout) as client:
                response = await client.get("http://ip-api.com/json/?lang=zh-CN")
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.warning(f"[ProxyChecker] 无法检测代理地理位置: {e}")
        return None
    
    @classmethod
    async def validate_proxy_for_gemini(cls, proxy_url: str) -> bool:
        """
        验证代理是否适合 Gemini 图像生成
        
        Returns:
            True: 代理位于安全地区
            False: 代理位于风险地区或检测失败
        """
        location = await cls.check_proxy_location(proxy_url)
        
        if not location or location.get("status") != "success":
            logger.warning("⚠️ [ProxyChecker] 无法验证代理地理位置，继续启动但可能存在风险")
            return True  # 检测失败时不阻塞启动
        
        country_code = location.get("countryCode", "")
        country_name = location.get("country", "未知")
        city = location.get("city", "")
        ip = location.get("query", "")
        
        logger.info(f"🌍 [ProxyChecker] 代理位置: {country_name} {city} (IP: {ip})")
        
        # 1. 完全被屏蔽的国家
        if country_code in cls.BLOCKED_COUNTRIES:
            logger.error(
                f"🚫 [ProxyChecker] 严重警告: 代理位于 {country_name}！\n"
                f"   该国家/地区被 Google 完全屏蔽，Gemini 无法访问。\n"
                f"   ⚠️ 必须切换到美国/加拿大/澳大利亚/新加坡等地区的代理"
            )
            return False
        
        # 2. 图像生成功能已知受限的国家
        if country_code in cls.RESTRICTED_COUNTRIES:
            logger.error(
                f"❌ [ProxyChecker] 警告: 代理位于 {country_name}！\n"
                f"   该地区已知图像生成功能受限（会降级为 Flash-Lite）。\n"
                f"   建议切换到美国/加拿大/澳大利亚等已验证地区"
            )
            return False
        
        # 3. 欧盟国家（可能因 GDPR 等隐私法规限制图像生成）
        if country_code in cls.EU_COUNTRIES:
            logger.warning(
                f"⚠️ [ProxyChecker] 注意: 代理位于欧盟/英国/瑞士 ({country_name})。\n"
                f"   该地区可能因隐私法规限制图像生成功能。\n"
                f"   如遇到问题，建议切换到美国/加拿大/澳大利亚"
            )
            return True  # 欧盟不强制阻止，仅警告
        
        # 4. 已验证安全的国家
        if country_code in cls.VERIFIED_SAFE_COUNTRIES:
            logger.info(f"✅ [ProxyChecker] 代理地区验证通过 ({country_name})")
            return True
        
        # 5. 其他未知国家
        logger.warning(
            f"⚠️ [ProxyChecker] 代理位于 {country_name}，"
            f"该地区未在已验证列表中。\n"
            f"   如图像生成失败，建议切换到美国/加拿大/澳大利亚"
        )
        return True  # 未知地区不阻塞启动，但发出警告
