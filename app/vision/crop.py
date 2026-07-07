import base64
import binascii
import io

from PIL import Image


def decode_crop(crop: dict) -> Image.Image:
    """Decode a Roboflow workflow crop output ({"type": "base64", "value": ...})
    into a PIL image. Raises ValueError on anything that is not a decodable
    image -- the detector wraps it into TongueDetectionError.
    """
    try:
        raw = base64.b64decode(crop["value"], validate=True)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except (KeyError, TypeError, binascii.Error, OSError) as exc:
        raise ValueError(f"Workflow crop did not decode to an image: {exc!r}") from exc
