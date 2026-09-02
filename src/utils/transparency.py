"""White-background keying utilities for generated sticker assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

SUPPORTED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


@dataclass(frozen=True)
class TransparencyResult:
    source: Path
    destination: Path
    transparent_pixels: int
    total_pixels: int


def make_white_background_transparent(
    source: Path,
    destination: Path,
    *,
    tolerance: int = 35,
) -> TransparencyResult:
    """Replace near-white RGB pixels with fully transparent pixels."""
    if not 0 <= tolerance <= 255:
        raise ValueError("tolerance must be between 0 and 255")

    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        raise ValueError("source and destination must be different files")

    threshold = 255 - tolerance
    with Image.open(source) as image:
        rgba = image.convert("RGBA")

    pixels = list(rgba.getdata())
    processed: list[tuple[int, int, int, int]] = []
    transparent_pixels = 0
    for red, green, blue, alpha in pixels:
        if red >= threshold and green >= threshold and blue >= threshold:
            processed.append((255, 255, 255, 0))
            transparent_pixels += 1
        else:
            processed.append((red, green, blue, alpha))

    rgba.putdata(processed)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(destination, "PNG")
    return TransparencyResult(
        source=source,
        destination=destination,
        transparent_pixels=transparent_pixels,
        total_pixels=len(processed),
    )
