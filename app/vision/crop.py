import base64
import binascii
import io

from PIL import Image


def decode_crop(crop: str | dict) -> Image.Image:
    """Decode a Roboflow workflow crop output into a PIL image.

    The inference SDK unwraps image outputs to bare base64 strings; the raw
    HTTP API wraps them as {"type": "base64", "value": ...} — accept both.
    Raises ValueError on anything that is not a decodable image -- the
    detector wraps it into TongueDetectionError.
    """
    try:
        encoded = crop if isinstance(crop, str) else crop["value"]
        raw = base64.b64decode(encoded, validate=True)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except (KeyError, TypeError, binascii.Error, OSError) as exc:
        raise ValueError(f"Workflow crop did not decode to an image: {exc!r}") from exc
