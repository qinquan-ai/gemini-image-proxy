import asyncio
import time

from src.config.settings import Settings
from src.core.errors import GenerationTimeoutError
from src.core.models import GeneratedImage, GenerationResult
from src.core.gemini_session import GeminiSession
from src.service.image_generation import ImageGenerationService


class RecordingSession:
    def __init__(self, fail=False):
        self.is_ready = True
        self.fail = fail
        self.active = 0
        self.max_active = 0
        self.prompts = []

    async def start(self):
        return None

    async def close(self):
        return None

    async def generate(self, prompt, **kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.prompts.append(prompt)
        try:
            await asyncio.sleep(0.01)
            if self.fail:
                raise GenerationTimeoutError("timed out")
            return GenerationResult(
                request_id=kwargs["request_id"],
                prompt=prompt,
                created=int(time.time()),
                duration_seconds=0.01,
                images=[
                    GeneratedImage(
                        content=b"image",
                        mime_type="image/png",
                        source_url="https://example.invalid/image.png",
                    )
                ],
            )
        finally:
            self.active -= 1


def test_service_serializes_concurrent_requests():
    async def scenario():
        session = RecordingSession()
        service = ImageGenerationService(Settings(), session=session)
        results = await asyncio.gather(
            service.generate("first", request_id="first"),
            service.generate("second", request_id="second"),
            service.generate("third", request_id="third"),
        )
        return session, service, results

    session, service, results = asyncio.run(scenario())
    assert session.max_active == 1
    assert [result.request_id for result in results] == ["first", "second", "third"]
    assert service.status()["completed"] == 3
    assert service.status()["queued"] == 0
    assert service.status()["busy"] is False


def test_service_records_failures_without_leaving_an_active_request():
    async def scenario():
        service = ImageGenerationService(Settings(), session=RecordingSession(fail=True))
        try:
            await service.generate("failure", request_id="failed-request")
        except GenerationTimeoutError:
            pass
        return service.status()

    status = asyncio.run(scenario())
    assert status["failed"] == 1
    assert status["active_request_id"] is None
    assert status["last_error"]["request_id"] == "failed-request"


def test_generation_rejection_markers_are_detected_before_timeout():
    assert GeminiSession._is_generation_rejection(
        "I can't create it right now. Image creation isn't available in your location."
    )
    assert not GeminiSession._is_generation_rejection(
        "Here is the image you requested."
    )


def test_rejection_detection_ignores_a_historical_response():
    refusal = "Image creation may not be available in your location yet."
    assert not GeminiSession._is_new_generation_rejection(refusal, refusal)
    assert GeminiSession._is_new_generation_rejection(
        f"Earlier message. {refusal}",
        "Earlier message.",
    )
