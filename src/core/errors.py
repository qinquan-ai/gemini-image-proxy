from typing import Optional


class ImageGatewayError(Exception):
    """Base error that can be translated at transport boundaries."""

    code = "image_gateway_error"
    retryable = False

    def __init__(self, message: str, *, param: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.param = param


class InvalidGenerationRequest(ImageGatewayError):
    code = "invalid_request"


class GeminiAuthenticationError(ImageGatewayError):
    code = "gemini_authentication_failed"


class BrowserUnavailableError(ImageGatewayError):
    code = "browser_unavailable"
    retryable = True


class InputAttachmentError(ImageGatewayError):
    code = "input_attachment_failed"
    retryable = True


class GenerationTimeoutError(ImageGatewayError):
    code = "generation_timeout"
    retryable = True


class GenerationRejectedError(ImageGatewayError):
    code = "generation_rejected"


class ImageDownloadError(ImageGatewayError):
    code = "image_download_failed"
    retryable = True
