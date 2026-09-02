import hmac
import logging
import re
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..__version__ import __version__
from ..config.settings import Settings
from ..core.errors import (
    BrowserUnavailableError,
    GenerationTimeoutError,
    GenerationRejectedError,
    GeminiAuthenticationError,
    ImageDownloadError,
    ImageGatewayError,
    InputAttachmentError,
    InvalidGenerationRequest,
)
from ..core.models import GenerationResult
from ..service.image_generation import ImageGenerationService


logger = logging.getLogger("gemini-image-gateway")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
UPLOAD_MIME_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class APIRequestError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        code: str = "invalid_request",
        param: Optional[str] = None,
        error_type: str = "invalid_request_error",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code
        self.param = param
        self.error_type = error_type


class ImageGenerationRequest(BaseModel):
    model: Optional[str] = None
    prompt: str = Field(min_length=1, max_length=20000)
    n: int = Field(default=1, ge=1)
    size: Optional[str] = None
    quality: Optional[str] = None
    style: Optional[str] = None
    response_format: str = "b64_json"
    user: Optional[str] = None


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", uuid.uuid4().hex)


def _error_response(
    *,
    status_code: int,
    message: str,
    error_type: str,
    code: str,
    param: Optional[str],
    request_id: str,
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": param,
                "code": code,
            }
        },
    )
    response.headers["x-request-id"] = request_id
    return response


def _domain_error_status(exc: ImageGatewayError) -> int:
    if isinstance(exc, InvalidGenerationRequest):
        return 400
    if isinstance(exc, GenerationTimeoutError):
        return 504
    if isinstance(exc, GenerationRejectedError):
        return 422
    if isinstance(exc, (GeminiAuthenticationError, BrowserUnavailableError)):
        return 503
    if isinstance(exc, (InputAttachmentError, ImageDownloadError)):
        return 502
    return 500


def _validate_generation_options(
    settings: Settings,
    *,
    model: Optional[str],
    n: int,
    size: Optional[str],
    quality: Optional[str],
    style: Optional[str],
    response_format: str,
) -> str:
    effective_model = model or settings.gateway.model
    if effective_model != settings.gateway.model:
        raise APIRequestError(
            400,
            f"Unsupported model: {effective_model}",
            code="model_not_found",
            param="model",
        )
    if n != 1:
        raise APIRequestError(
            400,
            "This gateway currently supports n=1 only",
            code="unsupported_parameter",
            param="n",
        )
    if response_format != "b64_json":
        raise APIRequestError(
            400,
            "This gateway currently supports response_format=b64_json only",
            code="unsupported_parameter",
            param="response_format",
        )
    if size not in (None, "auto", "1024x1024"):
        raise APIRequestError(
            400,
            "Supported size hints are auto and 1024x1024",
            code="unsupported_parameter",
            param="size",
        )
    if quality not in (None, "auto"):
        raise APIRequestError(
            400,
            "Quality selection is not supported by the Gemini Web backend",
            code="unsupported_parameter",
            param="quality",
        )
    if style not in (None, "auto"):
        raise APIRequestError(
            400,
            "Style selection is not supported by the Gemini Web backend",
            code="unsupported_parameter",
            param="style",
        )
    return effective_model


def _generation_payload(result: GenerationResult, n: int = 1) -> Dict[str, Any]:
    if not result.images:
        raise ImageDownloadError("The generation completed without image bytes")
    return {
        "created": result.created,
        "data": [
            {
                "b64_json": image.b64_json,
            }
            for image in result.images[:n]
        ],
    }


def _has_expected_image_signature(content: bytes, content_type: str) -> bool:
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


def create_app(
    settings: Optional[Settings] = None,
    service: Optional[ImageGenerationService] = None,
) -> FastAPI:
    app_settings = settings or Settings.load_from_files()
    app_settings.gateway.validate_remote_access()
    image_service = service or ImageGenerationService(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if app_settings.gateway.eager_start:
            try:
                # 启动前检查代理地理位置
                from ..utils.proxy_checker import ProxyLocationChecker
                proxy_url = app_settings.browser.proxy
                if proxy_url:
                    await ProxyLocationChecker.validate_proxy_for_gemini(proxy_url)
                
                await image_service.start()
            except Exception as exc:
                logger.error("Gateway dependency startup failed: %s", exc)
        yield
        await image_service.close()

    app = FastAPI(
        title="Gemini Image Gateway",
        version=__version__,
        docs_url="/docs" if app_settings.gateway.is_loopback else None,
        redoc_url=None,
        openapi_url="/openapi.json" if app_settings.gateway.is_loopback else None,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.image_service = image_service

    if app_settings.gateway.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.gateway.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request.state.request_id = (
            supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid.uuid4().hex
        )
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(APIRequestError)
    async def handle_api_error(request: Request, exc: APIRequestError):
        return _error_response(
            status_code=exc.status_code,
            message=exc.message,
            error_type=exc.error_type,
            code=exc.code,
            param=exc.param,
            request_id=_request_id(request),
        )

    @app.exception_handler(ImageGatewayError)
    async def handle_gateway_error(request: Request, exc: ImageGatewayError):
        return _error_response(
            status_code=_domain_error_status(exc),
            message=exc.message,
            error_type="image_generation_error",
            code=exc.code,
            param=exc.param,
            request_id=_request_id(request),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        first_error = exc.errors()[0] if exc.errors() else {}
        location = first_error.get("loc", [])
        param = str(location[-1]) if location else None
        return _error_response(
            status_code=400,
            message=first_error.get("msg", "Invalid request"),
            error_type="invalid_request_error",
            code="validation_error",
            param=param,
            request_id=_request_id(request),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        request_id = _request_id(request)
        logger.exception("Unhandled gateway error for request %s", request_id)
        return _error_response(
            status_code=500,
            message="The gateway encountered an internal error",
            error_type="server_error",
            code="internal_error",
            param=None,
            request_id=request_id,
        )

    async def require_auth(request: Request) -> None:
        expected_token = app_settings.gateway.api_token
        if not expected_token:
            return
        scheme, _, supplied_token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied_token,
            expected_token,
        ):
            raise APIRequestError(
                401,
                "Invalid or missing gateway token",
                code="invalid_api_key",
                error_type="authentication_error",
            )

    @app.get("/")
    async def root():
        return {
            "name": "Gemini Image Gateway",
            "version": __version__,
            "model": app_settings.gateway.model,
        }

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    async def readyz():
        status = image_service.status()
        status_code = 200 if status["ready"] else 503
        return JSONResponse(
            status_code=status_code,
            content={"status": "ready" if status["ready"] else "not_ready"},
        )

    @app.get("/v1/status", dependencies=[Depends(require_auth)])
    async def gateway_status():
        return {
            **image_service.status(),
            "model": app_settings.gateway.model,
            "auth_enabled": bool(app_settings.gateway.api_token),
        }

    @app.get("/v1/models", dependencies=[Depends(require_auth)])
    async def list_models():
        return {
            "object": "list",
            "data": [
                {
                    "id": app_settings.gateway.model,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "gemini-image-gateway",
                }
            ],
        }

    @app.post("/v1/images/generations", dependencies=[Depends(require_auth)])
    async def create_image(payload: ImageGenerationRequest, request: Request):
        _validate_generation_options(
            app_settings,
            model=payload.model,
            n=payload.n,
            size=payload.size,
            quality=payload.quality,
            style=payload.style,
            response_format=payload.response_format,
        )
        request_id = _request_id(request)
        result = await image_service.generate(
            prompt=payload.prompt,
            output_name=f"api_{request_id}",
            request_id=request_id,
        )
        return _generation_payload(result, payload.n)

    @app.post("/v1/images/edits", dependencies=[Depends(require_auth)])
    async def edit_image(
        request: Request,
        image: UploadFile = File(...),
        prompt: str = Form(..., min_length=1, max_length=20000),
        model: Optional[str] = Form(None),
        n: int = Form(1),
        size: Optional[str] = Form(None),
        quality: Optional[str] = Form(None),
        response_format: str = Form("b64_json"),
    ):
        _validate_generation_options(
            app_settings,
            model=model,
            n=n,
            size=size,
            quality=quality,
            style=None,
            response_format=response_format,
        )
        content_type = (image.content_type or "").lower()
        if content_type not in UPLOAD_MIME_TYPES:
            raise APIRequestError(
                400,
                "Uploaded image must be PNG, JPEG, or WebP",
                code="unsupported_image_type",
                param="image",
            )

        image_bytes = await image.read(app_settings.gateway.max_upload_bytes + 1)
        if not image_bytes:
            raise APIRequestError(
                400,
                "Uploaded image is empty",
                code="invalid_image",
                param="image",
            )
        if len(image_bytes) > app_settings.gateway.max_upload_bytes:
            raise APIRequestError(
                413,
                "Uploaded image exceeds the configured size limit",
                code="image_too_large",
                param="image",
            )
        if not _has_expected_image_signature(image_bytes, content_type):
            raise APIRequestError(
                400,
                "Uploaded content does not match its declared image type",
                code="invalid_image",
                param="image",
            )

        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="gemini-image-upload-",
                suffix=UPLOAD_MIME_TYPES[content_type],
                delete=False,
            ) as temporary_file:
                temporary_file.write(image_bytes)
                temporary_path = Path(temporary_file.name)

            request_id = _request_id(request)
            result = await image_service.generate(
                prompt=prompt,
                input_image=temporary_path,
                output_name=f"api_{request_id}",
                request_id=request_id,
            )
            return _generation_payload(result, n)
        finally:
            await image.close()
            if temporary_path:
                temporary_path.unlink(missing_ok=True)

    return app
