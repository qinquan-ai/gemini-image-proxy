from typing import List, Dict, Any

def parse_raw_cookies_to_playwright(raw_cookie_str: str) -> List[Dict[str, Any]]:
    """
    将原生 Cookie 标头长字符串转换为 Playwright 所需的标准 Cookie 对象列表
    """
    cookies = []
    if not raw_cookie_str:
        return cookies

    for item in raw_cookie_str.strip().split(";"):
        if "=" in item:
            parts = item.strip().split("=", 1)
            k = parts[0].strip()
            v = parts[1].strip()
            if not k or not v:
                continue

            domain = ".google.com"
            ck_obj = {
                "name": k,
                "value": v,
                "domain": domain,
                "path": "/",
                "sameSite": "None" if "3P" in k else "Lax",
                "secure": True if k.startswith("__Secure-") else False
            }
            cookies.append(ck_obj)

    return cookies

def parse_raw_cookies_to_dict(raw_cookie_str: str) -> Dict[str, str]:
    """
    将原生 Cookie 标头长字符串转换为 Key-Value 字典
    """
    cookies_dict = {}
    if not raw_cookie_str:
        return cookies_dict

    for item in raw_cookie_str.strip().split(";"):
        if "=" in item:
            parts = item.strip().split("=", 1)
            k = parts[0].strip()
            v = parts[1].strip()
            if k and v:
                cookies_dict[k] = v
    return cookies_dict
