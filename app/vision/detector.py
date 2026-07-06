import io

from inference_sdk import InferenceHTTPClient
from PIL import Image
from pydantic import BaseModel, ConfigDict

from app.config import Settings

ROBOFLOW_HOSTED_API_URL = "https://detect.roboflow.com"


class CroppedTongue(BaseModel):
    """A tongue photo cropped to the detected bounding box (plus padding)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    image: Image.Image
    confidence: float


class TongueDetector:
    """Wraps the Roboflow hosted inference API for the trained tongue model.

    See docs/adr and CONTEXT.md -> Tongue Assessment: below
    `confidence_threshold` counts as "no tongue detected" and should trigger
    retake guidance rather than a Tongue Assessment.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = InferenceHTTPClient(
            api_url=ROBOFLOW_HOSTED_API_URL, api_key=settings.roboflow_api_key
        )

    async def detect_and_crop(self, image_bytes: bytes) -> CroppedTongue | None:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        result = await self._client.infer_async(image, model_id=self._settings.roboflow_model_id)
        prediction = self._best_prediction(result)
        if prediction is None:
            return None

        cropped = self._crop_with_padding(image, prediction)
        return CroppedTongue(image=cropped, confidence=prediction["confidence"])

    def _best_prediction(self, result: dict) -> dict | None:
        predictions = result.get("predictions", [])
        if not predictions:
            return None
        best = max(predictions, key=lambda p: p["confidence"])
        if best["confidence"] < self._settings.roboflow_confidence_threshold:
            return None
        return best

    def _crop_with_padding(self, image: Image.Image, prediction: dict) -> Image.Image:
        padding_ratio = self._settings.roboflow_crop_padding_ratio
        cx, cy = prediction["x"], prediction["y"]
        half_w = prediction["width"] / 2 * (1 + padding_ratio)
        half_h = prediction["height"] / 2 * (1 + padding_ratio)

        left = max(0, int(cx - half_w))
        top = max(0, int(cy - half_h))
        right = min(image.width, int(cx + half_w))
        bottom = min(image.height, int(cy + half_h))
        return image.crop((left, top, right, bottom))
