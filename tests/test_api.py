import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import create_app
from src.config.settings import GatewaySettings, Settings
from src.core.models import GeneratedImage, GenerationResult


TOKEN = "internal-gateway-token-0123456789abcdef"
PNG_BYTES = b"\x89PNG\r\n\x1a\ninternal-test-image"


class FakeImageService:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def start(self):
        return None

    async def close(self):
        self.closed = True

    def status(self):
        return {
            "ready": True,
            "busy": False,
            "queued": 0,
            "active_request_id": None,
            "completed": len(self.calls),
            "failed": 0,
            "last_error": None,
            "uptime_seconds": 1.0,
        }

    async def generate(
        self,
        prompt,
        *,
        output_name=None,
        input_image=None,
        request_id=None,
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "output_name": output_name,
                "input_image": Path(input_image) if input_image else None,
                "input_exists": bool(input_image and Path(input_image).is_file()),
                "request_id": request_id,
            }
        )
        return GenerationResult(
            request_id=request_id,
            prompt=prompt,
            created=1770000000,
            duration_seconds=1.25,
            images=[
                GeneratedImage(
                    content=PNG_BYTES,
                    mime_type="image/png",
                    source_url="https://example.invalid/generated.png",
                )
            ],
            output_name=output_name,
        )


class UnexpectedFailureService(FakeImageService):
    async def generate(self, *args, **kwargs):
        raise RuntimeError("sensitive internal detail")


def make_settings(**gateway_overrides):
    values = {
        "api_token": TOKEN,
        "eager_start": False,
        "max_upload_bytes": 1024,
    }
    values.update(gateway_overrides)
    return Settings(gateway=GatewaySettings(**values))


def authorization_header():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_health_and_readiness_do_not_require_authentication():
    service = FakeImageService()
    with TestClient(create_app(make_settings(), service=service)) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}


def test_generation_requires_bearer_token():
    with TestClient(create_app(make_settings(), service=FakeImageService())) as client:
        response = client.post(
            "/v1/images/generations",
            json={"prompt": "test image"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_generation_returns_openai_compatible_base64_payload():
    service = FakeImageService()
    app = create_app(make_settings(), service=service)
    with TestClient(app) as client:
        response = client.post(
            "/v1/images/generations",
            headers={**authorization_header(), "X-Request-ID": "request-123"},
            json={
                "model": "gemini-web-image",
                "prompt": "test image",
                "n": 1,
                "size": "1024x1024",
                "response_format": "b64_json",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "request-123"
    payload = response.json()
    assert payload["created"] == 1770000000
    assert base64.b64decode(payload["data"][0]["b64_json"]) == PNG_BYTES
    assert service.calls[0]["request_id"] == "request-123"


def test_generation_rejects_unsupported_multiplicity():
    with TestClient(create_app(make_settings(), service=FakeImageService())) as client:
        response = client.post(
            "/v1/images/generations",
            headers=authorization_header(),
            json={"prompt": "test image", "n": 2},
        )
    assert response.status_code == 400
    assert response.json()["error"]["param"] == "n"


def test_edit_upload_is_available_during_generation_and_then_removed():
    service = FakeImageService()
    with TestClient(create_app(make_settings(), service=service)) as client:
        response = client.post(
            "/v1/images/edits",
            headers=authorization_header(),
            data={"prompt": "edit this image", "model": "gemini-web-image"},
            files={"image": ("reference.png", PNG_BYTES, "image/png")},
        )

    assert response.status_code == 200
    call = service.calls[0]
    assert call["input_exists"] is True
    assert call["input_image"].exists() is False


def test_edit_rejects_a_spoofed_image_content_type():
    with TestClient(create_app(make_settings(), service=FakeImageService())) as client:
        response = client.post(
            "/v1/images/edits",
            headers=authorization_header(),
            data={"prompt": "edit this image"},
            files={"image": ("not-an-image.png", b"plain text", "image/png")},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_image"


def test_unexpected_failures_use_a_redacted_openai_error_envelope():
    app = create_app(make_settings(), service=UnexpectedFailureService())
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/images/generations",
            headers=authorization_header(),
            json={"prompt": "test image"},
        )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "sensitive internal detail" not in response.text


def test_remote_binding_requires_a_strong_token():
    settings = make_settings(bind_host="0.0.0.0", api_token="short")
    with pytest.raises(ValueError, match="at least 32 characters"):
        create_app(settings, service=FakeImageService())
