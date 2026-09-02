import os
import re
import uuid
from pathlib import Path
from typing import List, Tuple

from playwright.async_api import BrowserContext

from ..core.errors import ImageDownloadError
from ..core.models import GeneratedImage
from ..utils.logger import logger


IMAGE_FORMATS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

def sanitize_filename(name: str) -> str:
    """清理非法的本地文件名字符"""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.replace(" ", "_").strip("_")
    return name[:50] if name else "gemini_generated"

class ImageSaver:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _detect_format(content: bytes, content_type: str) -> Tuple[str, str]:
        mime_type = content_type.split(";", 1)[0].strip().lower()
        if mime_type not in IMAGE_FORMATS:
            if content.startswith(b"\x89PNG\r\n\x1a\n"):
                mime_type = "image/png"
            elif content.startswith(b"\xff\xd8\xff"):
                mime_type = "image/jpeg"
            elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
                mime_type = "image/webp"
            elif content.startswith((b"GIF87a", b"GIF89a")):
                mime_type = "image/gif"
            else:
                raise ImageDownloadError("Gemini returned an unsupported image format")
        return mime_type, IMAGE_FORMATS[mime_type]

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary_path.write_bytes(content)
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    async def download_images_from_urls(
        self,
        context: BrowserContext,
        urls: List[str],
        prefix: str = "gemini_gen",
    ) -> List[GeneratedImage]:
        """Download image bytes with the authenticated browser context."""
        generated_images: List[GeneratedImage] = []
        failures: List[str] = []
        base_name = sanitize_filename(prefix)

        for idx, url in enumerate(urls):
            img_page = await context.new_page()
            try:
                res = await img_page.goto(url, timeout=20000)
                if not res or not res.ok:
                    status = res.status if res else "no response"
                    raise ImageDownloadError(f"Image download returned {status}")

                image_bytes = await res.body()
                headers = await res.all_headers()
                mime_type, extension = self._detect_format(
                    image_bytes,
                    headers.get("content-type", ""),
                )
                file_path = self.output_dir / f"{base_name}_{idx + 1}{extension}"
                self._write_atomic(file_path, image_bytes)
                generated_images.append(
                    GeneratedImage(
                        content=image_bytes,
                        mime_type=mime_type,
                        source_url=url,
                        path=file_path,
                    )
                )
                logger.info(
                    "[ImageSaver] Saved generated image (%s/%s): %s",
                    idx + 1,
                    len(urls),
                    file_path,
                )
            except Exception as err:
                failures.append(str(err))
                logger.error("[ImageSaver] Image download failed (%s...): %s", url[:60], err)
            finally:
                await img_page.close()

        if not generated_images:
            detail = failures[-1] if failures else "no image URLs were returned"
            raise ImageDownloadError(f"No generated images could be downloaded: {detail}")
        return generated_images

    async def save_images_from_urls(
        self,
        context: BrowserContext,
        urls: List[str],
        prefix: str = "gemini_gen",
    ) -> List[Path]:
        """Backward-compatible path-only image saving API."""
        images = await self.download_images_from_urls(context, urls, prefix)
        return [image.path for image in images if image.path is not None]
