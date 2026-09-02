import base64
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    mime_type: str
    source_url: str
    path: Optional[Path] = None

    @property
    def b64_json(self) -> str:
        return base64.b64encode(self.content).decode("ascii")


@dataclass(frozen=True)
class GenerationResult:
    request_id: str
    prompt: str
    created: int
    duration_seconds: float
    images: List[GeneratedImage]
    output_name: Optional[str] = None
    chat_id: Optional[str] = None

    @property
    def paths(self) -> List[Path]:
        return [image.path for image in self.images if image.path is not None]
