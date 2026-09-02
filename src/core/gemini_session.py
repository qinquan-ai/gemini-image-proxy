import asyncio
import time
import uuid
from pathlib import Path
from typing import List, Optional, Tuple, Union

from .browser import BrowserManager
from .errors import (
    BrowserUnavailableError,
    GenerationTimeoutError,
    GenerationRejectedError,
    ImageGatewayError,
    InputAttachmentError,
    InvalidGenerationRequest,
)
from .extractor import ElementExtractor
from .models import GenerationResult
from ..config.settings import Settings
from ..plugins.image_inspector import ImageInspectorPlugin
from ..plugins.session_tracker import SessionTrackerPlugin
from ..storage.image_saver import ImageSaver
from ..utils.logger import logger


class GeminiSession:
    """Single-browser Gemini Web adapter with serialized operations."""

    ALLOWED_INPUT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
    GENERATION_REJECTION_MARKERS = (
        "can't create it right now",
        "cannot create it right now",
        "image creation isn't available",
        "image creation is not available",
        "image generation isn't available",
        "image generation is not available",
        "image creation is unavailable",
        "image generation is unavailable",
        "image creation may not be available",
        "image generation may not be available",
        "signed out",
        "not available in your location",
    )

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings.load_from_files()
        self.browser_mgr = BrowserManager(self.settings)
        self.saver = ImageSaver(self.settings.task.output_dir)
        self.tracker = SessionTrackerPlugin()
        self.inspector = ImageInspectorPlugin()
        self.context = None
        self.page = None
        self._start_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()

    @property
    def is_ready(self) -> bool:
        return bool(
            self.browser_mgr.is_ready
            and self.context
            and self.page
            and not self.page.is_closed()
        )

    @property
    def is_busy(self) -> bool:
        return self._operation_lock.locked()

    async def start(self) -> None:
        if self.is_ready:
            return
        async with self._start_lock:
            if self.is_ready:
                return
            self.context, self.page = await self.browser_mgr.start_browser()

    async def _reset_browser(self) -> None:
        await self.browser_mgr.close()
        self.context = None
        self.page = None

    def _validate_request(
        self,
        prompt: str,
        input_image: Optional[Union[str, Path]],
    ) -> Tuple[str, Optional[Path]]:
        normalized_prompt = prompt.strip() if isinstance(prompt, str) else ""
        if not normalized_prompt:
            raise InvalidGenerationRequest("Prompt must not be empty", param="prompt")

        if not input_image:
            return normalized_prompt, None

        image_path = Path(input_image)
        if not image_path.is_file():
            raise InvalidGenerationRequest(
                "Input image does not exist or is not a file",
                param="image",
            )
        if image_path.suffix.lower() not in self.ALLOWED_INPUT_SUFFIXES:
            raise InvalidGenerationRequest(
                "Input image must be PNG, JPEG, or WebP",
                param="image",
            )
        if image_path.stat().st_size > self.settings.gateway.max_upload_bytes:
            raise InvalidGenerationRequest(
                "Input image exceeds the configured upload limit",
                param="image",
            )
        return normalized_prompt, image_path

    @classmethod
    def _is_generation_rejection(cls, response_text: str) -> bool:
        normalized = response_text.lower()
        return any(marker in normalized for marker in cls.GENERATION_REJECTION_MARKERS)

    @classmethod
    def _is_new_generation_rejection(
        cls,
        response_text: str,
        baseline_text: str,
    ) -> bool:
        """Ignore matching rejection text that was already present before send."""
        current = response_text.lower()
        baseline = baseline_text.lower()
        return any(
            current.count(marker) > baseline.count(marker)
            for marker in cls.GENERATION_REJECTION_MARKERS
        )

    async def list_chats(self) -> List[dict]:
        async with self._operation_lock:
            await self.start()
            chats = await ElementExtractor.list_history_chats(self.page)
            logger.info("[GeminiSession] Found %s historical chats", len(chats))
            return chats

    async def generate(
        self,
        prompt: str,
        output_name: Optional[str] = None,
        output_dir: Optional[Union[str, Path]] = None,
        new_chat: Optional[bool] = None,
        chat_id: Optional[str] = None,
        input_image: Optional[Union[str, Path]] = None,
        request_id: Optional[str] = None,
    ) -> GenerationResult:
        normalized_prompt, input_path = self._validate_request(prompt, input_image)
        effective_request_id = request_id or uuid.uuid4().hex

        async with self._operation_lock:
            started_at = time.time()
            try:
                return await self._generate_locked(
                    prompt=normalized_prompt,
                    output_name=output_name,
                    output_dir=output_dir,
                    new_chat=new_chat,
                    chat_id=chat_id,
                    input_image=input_path,
                    request_id=effective_request_id,
                    started_at=started_at,
                )
            except (GenerationTimeoutError, InputAttachmentError, BrowserUnavailableError):
                await self._reset_browser()
                raise
            except ImageGatewayError:
                raise
            except Exception as exc:
                logger.exception(
                    "[GeminiSession] Unexpected failure for request %s",
                    effective_request_id,
                )
                await self._reset_browser()
                raise BrowserUnavailableError(
                    "Gemini browser interaction failed unexpectedly"
                ) from exc

    async def _generate_locked(
        self,
        *,
        prompt: str,
        output_name: Optional[str],
        output_dir: Optional[Union[str, Path]],
        new_chat: Optional[bool],
        chat_id: Optional[str],
        input_image: Optional[Path],
        request_id: str,
        started_at: float,
    ) -> GenerationResult:
        await self.start()
        saver = ImageSaver(output_dir) if output_dir else self.saver

        if chat_id:
            await ElementExtractor.switch_to_chat(self.page, chat_id)
        else:
            should_open_new = (
                new_chat
                if new_chat is not None
                else self.settings.task.new_chat_per_prompt
            )
            if should_open_new:
                await ElementExtractor.open_new_chat(self.page)

        await ElementExtractor.type_prompt_safely(
            self.page,
            prompt,
            delay_ms=self.settings.browser.typing_delay_ms,
        )

        if input_image:
            attached = False
            for timeout_seconds in (6.0, 4.0):
                await ElementExtractor.upload_image(self.page, str(input_image))
                attached = await self.inspector.wait_for_pre_send_attachment(
                    self.page,
                    timeout_sec=timeout_seconds,
                )
                if attached:
                    break
            if not attached:
                raise InputAttachmentError(
                    "Gemini did not acknowledge the uploaded reference image",
                    param="image",
                )

        # Use the latest-response scanner for attribution, but keep the older
        # whole-page scanner as a fallback because Gemini may render images in
        # a container that is not yet matched by the response selector.
        baseline_urls = set(
            await ElementExtractor.extract_generated_image_urls(
                self.page,
                min_dimension=self.settings.task.min_image_dimension,
            )
        )
        baseline_urls.update(
            await ElementExtractor.extract_latest_response_image_urls(
                self.page,
                min_dimension=self.settings.task.min_image_dimension,
            )
        )
        baseline_response_text = await ElementExtractor.extract_latest_response_text(
            self.page
        )
        await ElementExtractor.send_message(self.page)
        logger.info("[GeminiSession] Request %s submitted", request_id)

        image_urls: List[str] = []
        rejection_detected = False
        deadline = time.monotonic() + self.settings.task.timeout_seconds
        while time.monotonic() < deadline:
            all_page_urls = await ElementExtractor.extract_generated_image_urls(
                self.page,
                min_dimension=self.settings.task.min_image_dimension,
            )
            latest_urls = await ElementExtractor.extract_latest_response_image_urls(
                self.page,
                min_dimension=self.settings.task.min_image_dimension,
            )
            image_urls = [url for url in all_page_urls if url not in baseline_urls]
            for url in latest_urls:
                if url not in baseline_urls and url not in image_urls:
                    image_urls.append(url)
            if image_urls:
                await asyncio.sleep(1)
                settled_page_urls = await ElementExtractor.extract_generated_image_urls(
                    self.page,
                    min_dimension=self.settings.task.min_image_dimension,
                )
                settled_urls = await ElementExtractor.extract_latest_response_image_urls(
                    self.page,
                    min_dimension=self.settings.task.min_image_dimension,
                )
                image_urls = [
                    url for url in settled_page_urls if url not in baseline_urls
                ]
                for url in settled_urls:
                    if url not in baseline_urls and url not in image_urls:
                        image_urls.append(url)
                break

            response_text = await ElementExtractor.extract_latest_response_text(self.page)
            if self._is_new_generation_rejection(
                response_text,
                baseline_response_text,
            ):
                logger.warning(
                    "[GeminiSession] Gemini declined image generation for request %s",
                    request_id,
                )
                rejection_detected = True
                break
            await asyncio.sleep(2)

        captured_chat_id = await self.tracker.capture(
            self.page,
            output_name or request_id,
        )
        await self.inspector.inspect_latest_turn(self.page)

        if rejection_detected:
            raise GenerationRejectedError(
                "Gemini declined image creation; check account, model, and location availability"
            )

        if not image_urls:
            debug_image = saver.output_dir / f"debug_failed_{request_id}.png"
            await self.page.screenshot(path=str(debug_image))
            raise GenerationTimeoutError(
                "Gemini did not produce a detectable image before the timeout"
            )

        prefix = output_name or f"request_{request_id}"
        images = await saver.download_images_from_urls(
            self.context,
            image_urls,
            prefix=prefix,
        )
        return GenerationResult(
            request_id=request_id,
            prompt=prompt,
            created=int(started_at),
            duration_seconds=round(time.time() - started_at, 3),
            images=images,
            output_name=output_name,
            chat_id=captured_chat_id,
        )

    async def generate_image(
        self,
        prompt: str,
        output_name: Optional[str] = None,
        output_dir: Optional[Union[str, Path]] = None,
        new_chat: Optional[bool] = None,
        chat_id: Optional[str] = None,
        input_image: Optional[Union[str, Path]] = None,
    ) -> List[Path]:
        """Backward-compatible path-only generation API."""
        result = await self.generate(
            prompt=prompt,
            output_name=output_name,
            output_dir=output_dir,
            new_chat=new_chat,
            chat_id=chat_id,
            input_image=input_image,
        )
        return result.paths

    async def close(self) -> None:
        await self._reset_browser()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
