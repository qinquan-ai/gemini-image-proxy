import os
import ipaddress
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

class BrowserSettings(BaseModel):
    proxy: Optional[str] = "http://127.0.0.1:7890"
    headless: bool = True
    typing_delay_ms: int = 5
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    viewport_width: int = 1280
    viewport_height: int = 900

class TaskSettings(BaseModel):
    timeout_seconds: int = 45
    min_image_dimension: int = 150
    new_chat_per_prompt: bool = True
    output_dir: Path = Path("./output")


class GatewaySettings(BaseModel):
    bind_host: str = "127.0.0.1"
    port: int = Field(default=4981, ge=1, le=65535)
    api_token: str = ""
    model: str = "gemini-web-image"
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:4981",
            "http://localhost:4981",
        ]
    )
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    eager_start: bool = True

    @property
    def is_loopback(self) -> bool:
        if self.bind_host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(self.bind_host).is_loopback
        except ValueError:
            return False

    def validate_remote_access(self) -> None:
        if not self.is_loopback and len(self.api_token) < 32:
            raise ValueError(
                "GATEWAY_API_TOKEN must contain at least 32 characters when "
                "GATEWAY_BIND_HOST is not a loopback address"
            )


class Settings(BaseModel):
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    task: TaskSettings = Field(default_factory=TaskSettings)
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    raw_cookies: str = ""

    @classmethod
    def load_from_files(cls, config_path: str = "config.yaml") -> "Settings":
        data: Dict[str, Any] = {}
        
        # 1. 尝试读取 YAML 配置文件
        yaml_file = Path(config_path)
        if yaml_file.exists():
            with open(yaml_file, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
                data.update(yaml_data)

        # 2. 从 .env 读取覆盖
        raw_cookies = os.getenv("GEMINI_RAW_COOKIES") or os.getenv(
            "GEMINI_RAW_COOKIE",
            "",
        )
        proxy_env = os.getenv("PROXY_SERVER")
        headless_env = os.getenv("HEADLESS")

        browser_dict = data.get("browser", {})
        if proxy_env:
            browser_dict["proxy"] = proxy_env
        if headless_env is not None:
            browser_dict["headless"] = headless_env.lower() == "true"
            
        data["browser"] = browser_dict
        data["raw_cookies"] = raw_cookies

        # 挂载视窗宽度
        if "viewport" in browser_dict:
            browser_dict["viewport_width"] = browser_dict["viewport"].get("width", 1280)
            browser_dict["viewport_height"] = browser_dict["viewport"].get("height", 900)

        task_dict = data.get("task", {})
        if "output_dir" in task_dict:
            task_dict["output_dir"] = Path(task_dict["output_dir"])
        data["task"] = task_dict

        gateway_dict = data.get("gateway", {})
        env_mapping = {
            "bind_host": os.getenv("GATEWAY_BIND_HOST"),
            "port": os.getenv("GATEWAY_PORT"),
            "api_token": os.getenv("GATEWAY_API_TOKEN")
            or os.getenv("PROXY_API_TOKEN"),
            "model": os.getenv("GATEWAY_MODEL"),
            "max_upload_bytes": os.getenv("GATEWAY_MAX_UPLOAD_BYTES"),
        }
        for field_name, value in env_mapping.items():
            if value is not None:
                gateway_dict[field_name] = value

        eager_start = os.getenv("GATEWAY_EAGER_START")
        if eager_start is not None:
            gateway_dict["eager_start"] = eager_start.lower() == "true"

        cors_origins = os.getenv("GATEWAY_CORS_ORIGINS")
        if cors_origins is not None:
            gateway_dict["cors_origins"] = [
                origin.strip()
                for origin in cors_origins.split(",")
                if origin.strip()
            ]
        elif isinstance(gateway_dict.get("cors_origins"), str):
            gateway_dict["cors_origins"] = [
                origin.strip()
                for origin in gateway_dict["cors_origins"].split(",")
                if origin.strip()
            ]
        data["gateway"] = gateway_dict

        return cls(**data)
