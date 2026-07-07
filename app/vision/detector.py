import asyncio
import io

from inference_sdk import InferenceHTTPClient
from PIL import Image
from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.vision.crop import decode_crop

ROBOFLOW_SERVERLESS_API_URL = "https://serverless.roboflow.com"
WORKFLOW_TIMEOUT_SECONDS = 30


class TongueDetectionError(Exception):
    """The Roboflow workflow call failed: network, timeout, or a response
    that violates the contract in docs/adr/0004-serverless-workflow-crop.md.

    Distinct from a clean "no tongue" (detect_and_crop -> None): callers
    should reply with a system-hiccup message, never retake guidance.
    """


class CroppedTongue(BaseModel):
    """A tongue photo cropped server-side by the Roboflow workflow."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    image: Image.Image
    confidence: float


class TongueDetector:
    """Wraps the Roboflow serverless workflow (tongue-detect-crop), which
    detects the tongue, keeps the top-1 detection, and crops server-side.

    Console-side invariants (docs/adr/0004-serverless-workflow-crop.md):
    the workflow's model-node threshold must stay BELOW
    `roboflow_confidence_threshold` (the app-side gate is the only
    authoritative "tongue found?" decision -- docs/message-flow.md), and a
    top-1 detections filter keeps both output lists at <= 1 entry. The
    argmax pairing below is insurance against console edits breaking that.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = InferenceHTTPClient(
            api_url=ROBOFLOW_SERVERLESS_API_URL, api_key=settings.roboflow_api_key
        )

    async def detect_and_crop(self, image_bytes: bytes) -> CroppedTongue | None:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.run_workflow,
                    workspace_name=self._settings.roboflow_workspace_name,
                    workflow_id=self._settings.roboflow_workflow_id,
                    images={"image": image},
                    use_cache=False,
                ),
                timeout=WORKFLOW_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise TongueDetectionError("Roboflow workflow call timed out") from exc
        except Exception as exc:
            raise TongueDetectionError("Roboflow workflow call failed") from exc

        return self._parse_result(results)

    def _parse_result(self, results: object) -> CroppedTongue | None:
        try:
            entry = results[0]
            predictions = entry["raw_predictions"]["predictions"]
            crops = entry["output_tongue_crop"]

            if not predictions:
                return None
            if len(crops) != len(predictions):
                raise TongueDetectionError(
                    f"Workflow contract violation: {len(crops)} crops for "
                    f"{len(predictions)} predictions"
                )

            best_index = max(
                range(len(predictions)), key=lambda i: predictions[i]["confidence"]
            )
            best = predictions[best_index]
            if best["confidence"] < self._settings.roboflow_confidence_threshold:
                return None

            return CroppedTongue(
                image=decode_crop(crops[best_index]), confidence=best["confidence"]
            )
        except TongueDetectionError:
            raise
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise TongueDetectionError(f"Malformed workflow response: {exc!r}") from exc
