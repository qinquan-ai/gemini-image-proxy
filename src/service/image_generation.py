import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Union

from ..config.settings import Settings
from ..core.gemini_session import GeminiSession
from ..core.models import GenerationResult


class ImageGenerationService:
    """Owns queueing, lifecycle, and status around one Gemini browser session."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        session: Optional[GeminiSession] = None,
    ):
        self.settings = settings or Settings.load_from_files()
        self.session = session or GeminiSession(self.settings)
        self._queue_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._queued = 0
        self._active_request_id: Optional[str] = None
        self._started_at = time.time()
        self._completed = 0
        self._failed = 0
        self._last_error: Optional[Dict[str, Any]] = None

    async def start(self) -> None:
        try:
            await self.session.start()
            self._last_error = None
        except Exception as exc:
            self._last_error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "at": int(time.time()),
            }
            raise

    async def close(self) -> None:
        await self.session.close()

    async def generate(
        self,
        prompt: str,
        *,
        output_name: Optional[str] = None,
        input_image: Optional[Union[str, Path]] = None,
        request_id: Optional[str] = None,
    ) -> GenerationResult:
        effective_request_id = request_id or uuid.uuid4().hex
        async with self._state_lock:
            self._queued += 1

        try:
            async with self._queue_lock:
                async with self._state_lock:
                    self._queued -= 1
                    self._active_request_id = effective_request_id
                try:
                    result = await self.session.generate(
                        prompt=prompt,
                        output_name=output_name,
                        input_image=input_image,
                        request_id=effective_request_id,
                    )
                except Exception as exc:
                    async with self._state_lock:
                        self._failed += 1
                        self._last_error = {
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "at": int(time.time()),
                            "request_id": effective_request_id,
                        }
                    raise
                else:
                    async with self._state_lock:
                        self._completed += 1
                        self._last_error = None
                    return result
                finally:
                    async with self._state_lock:
                        self._active_request_id = None
        except asyncio.CancelledError:
            async with self._state_lock:
                if self._active_request_id != effective_request_id:
                    self._queued = max(0, self._queued - 1)
            raise

    def status(self) -> Dict[str, Any]:
        return {
            "ready": bool(getattr(self.session, "is_ready", False)),
            "busy": self._active_request_id is not None,
            "queued": self._queued,
            "active_request_id": self._active_request_id,
            "completed": self._completed,
            "failed": self._failed,
            "last_error": self._last_error,
            "uptime_seconds": round(time.time() - self._started_at, 3),
        }
