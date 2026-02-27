"""Capture a screenshot and return it as an image.

Requires: grim, slurp, Pillow (for shrinking oversized captures)
"""

import base64
import io
import os
import subprocess
import tempfile

MAX_BYTES = 5 * 1024 * 1024  # API limit

TOOL_SPEC = {
    "name": "screenshot",
    "description": (
        "Capture a screenshot of the screen or a selected region. Returns "
        "the image for analysis. Use when the user asks about something on "
        "their screen."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "region": {
                "type": "string",
                "enum": ["full", "select"],
                "description": (
                    "'select' lets the user pick a region with their cursor, "
                    "'full' captures the entire screen"
                ),
            },
        },
        "required": ["region"],
    },
}


def _shrink_to_fit(png_path: str) -> tuple[bytes, str]:
    """Re-encode as JPEG at decreasing quality/size until under MAX_BYTES."""
    from PIL import Image

    img = Image.open(png_path)
    if img.mode == "RGBA":
        img = img.convert("RGB")

    for quality in (85, 70, 50, 30):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue(), "image/jpeg"

    scaled = img
    for _ in range(5):
        scaled = scaled.resize(
            (scaled.width // 2, scaled.height // 2), Image.LANCZOS
        )
        buf = io.BytesIO()
        scaled.save(buf, format="JPEG", quality=40)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue(), "image/jpeg"

    return buf.getvalue(), "image/jpeg"


def run(region: str) -> dict:
    """Capture a screenshot and return base64-encoded image data."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name

    try:
        if region == "select":
            slurp = subprocess.run(
                ["slurp"], capture_output=True, text=True, check=True,
            )
            geometry = slurp.stdout.strip()
            subprocess.run(["grim", "-g", geometry, tmp_path], check=True)
        else:
            subprocess.run(["grim", tmp_path], check=True)

        if os.path.getsize(tmp_path) > MAX_BYTES:
            img_bytes, media_type = _shrink_to_fit(tmp_path)
        else:
            with open(tmp_path, "rb") as f:
                img_bytes = f.read()
            media_type = "image/png"

        data = base64.b64encode(img_bytes).decode("ascii")
        return {"type": "image", "data": data, "media_type": media_type}
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
