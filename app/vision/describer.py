import base64
import io

from langchain_core.messages import HumanMessage
from PIL import Image

from app.advisor.llm import build_chat_model
from app.config import Settings
from app.models.schemas import TongueDescription

# Placeholder prompt pending the TTM textbook's tongue-inspection categories
# (see CONTEXT.md -> Tongue Description). Extend this once the book schema
# is finalized -- it should name the exact categories the model must fill.
DESCRIBE_PROMPT = (
    "You are examining a cropped photo of a human tongue for a Thai Traditional "
    "Medicine (TTM) self-care assistant. Describe only what you observe -- color, "
    "shape, coating, moisture, cracks, teeth marks. Do not interpret or diagnose; "
    "a separate step handles TTM interpretation. If the photo is blurry, partially "
    "framed, or poorly lit, say so via the quality field rather than guessing."
)


class VisionDescriber:
    """Config-selected model that turns a cropped tongue photo into a
    structured Tongue Description. Describes; never assesses -- see
    docs/adr/0001-two-model-pipeline.md.
    """

    def __init__(self, settings: Settings) -> None:
        model = build_chat_model(settings.describer_slot())
        self._structured_model = model.with_structured_output(TongueDescription)

    async def describe(self, image: Image.Image) -> TongueDescription:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        encoded = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

        message = HumanMessage(
            content=[
                {"type": "text", "text": DESCRIBE_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                },
            ]
        )
        return await self._structured_model.ainvoke([message])
