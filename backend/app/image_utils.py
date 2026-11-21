"""Photo preprocessing: fix rotation, strip metadata, shrink, re-encode as JPEG.

Shrinking the photo before it goes to the model keeps the request small and the
token cost low; re-encoding also drops EXIF data (GPS location etc.) so it never
leaves the server.
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


class InvalidImageError(ValueError):
    """Raised when the upload is not a readable image."""


def preprocess_image(data: bytes, max_edge: int = 1024, quality: int = 85) -> bytes:
    """Return JPEG bytes whose longest edge is at most `max_edge` pixels."""
    if not data:
        raise InvalidImageError("empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImageError(f"file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError("file is not a readable image") from exc

    img = ImageOps.exif_transpose(img)  # phone photos are often stored sideways
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_edge, max_edge), Image.LANCZOS)  # keeps aspect ratio, never upscales

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)  # no exif= -> metadata dropped
    return out.getvalue()
