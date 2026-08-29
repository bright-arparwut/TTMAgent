import base64

from langchain_core.messages import HumanMessage
from PIL import Image

from app.advisor.llm import build_chat_model
from app.config import Settings
from app.models.schemas import TongueDescription
from app.vision.crop import encode_jpeg

# Per-axis vocabulary steers toward '100 ลักษณะวินิจฉัยลิ้น' ch. 12's synthesis
# tables (corpus/tongue-100/, source notes 206-209 + 211; รูปร่าง also draws
# from 210, the cracks/teeth-marks band -- issue #36's resolution and its
# addendum). These are EXAMPLES, never enums (issue #36: ~96% of the
# steering vocabulary lands on the committed graph's node names via
# embedding-similar retrieval, so free Thai text keeps the Describer
# observational -- ADR 0001 -- without forcing compound observations into
# one Literal). movement (การเคลื่อนไหว) and sublingual veins are
# deliberately not steered: a still top-side crop cannot normally witness
# either, and a prompt nudge would invite speculation about them; `notes`
# is the escape hatch for the rare visible case.
DESCRIBE_PROMPT = (
    "คุณกำลังตรวจภาพถ่ายลิ้นมนุษย์ที่ครอปมาแล้ว สำหรับผู้ช่วยให้คำแนะนำด้านแพทย์แผนไทย (TTM) "
    "เบื้องต้น ให้บรรยายเฉพาะสิ่งที่สังเกตเห็นจริงในภาพเท่านั้น อย่าตีความหรือวินิจฉัย -- "
    "ขั้นตอนแยกต่างหากจะรับผิดชอบการตีความทางการแพทย์แผนไทย\n\n"
    "กรอกลักษณะทั้งห้าด้านต่อไปนี้เป็นข้อความภาษาไทยอิสระ (ประโยคหรือวลี ไม่ใช่คำเดียวหรือรหัส) "
    "โดยใช้คำศัพท์ต่อไปนี้เป็นตัวอย่างชี้แนะแนวทาง ไม่ใช่ตัวเลือกที่ต้องเลือกให้ตรงเป๊ะ -- "
    "หากลักษณะที่เห็นจริงต่างจากตัวอย่าง ให้บรรยายตามที่เห็นจริงด้วยคำศัพท์ใกล้เคียงที่สุด "
    'และสามารถผสมหลายลักษณะในค่าเดียวได้ (เช่น "แดงเข้มและแห้ง"):\n\n'
    "- สี (color): สีของตัวลิ้นและความชื้น/ความมันวาวของผิว เช่น ซีด, แดง, แดงเข้ม, ม่วง, "
    "ม่วงแดง, น้ำเงิน, ชื้น, แห้ง, มันวาว, เป็นเกล็ด, มีจุดแดง\n"
    "- ฝ้า (coating): ฝ้าที่ปกคลุมผิวลิ้น ทั้งสี ความหนา และเนื้อสัมผัส เช่น ไม่มีฝ้า, ฝ้าบาง, "
    "ฝ้าหนา, ฝ้าขาว, ฝ้าเหลือง, ฝ้าสีเทา, ฝ้าดำ, เหนียวและเลี่ยน, ลื่น, แห้ง, เปียก\n"
    "- ขนาด (size): ขนาดของลิ้นเทียบกับปกติ เช่น ลิ้นผอมเล็ก, ลิ้นอ้วนใหญ่, ขนาดปกติ\n"
    "- รูปร่าง (shape): รูปทรงของตัวลิ้นและพื้นผิว รวมถึงรอยแตกและรอยหยักของฟัน เช่น บาง, บวม, "
    "ขอบลิ้นบวม, ปลายลิ้นบวม, ลิ้นรูปร่างค้อน, ลิ้นยาว, ลิ้นสั้น, มีรอยแตกกลาง, มีรอยแตกบางส่วน, "
    "มีรอยแตกทั้งลิ้น, มีรอยหยักของฟันที่ขอบลิ้น, ตุ่มรับรสบนผิวลิ้นนูน, รูปร่างปกติไม่มีรอยแตกหรือรอยหยัก\n"
    "- จุดบนลิ้น (spots): จุดหรือตุ่มที่ปรากฏบนผิวลิ้น เช่น ไม่มีจุด, จุดแดง, จุดขาว, จุดม่วง, "
    "จุดดำ, จุดเว้า, จุดนูน, จุดกระจายตัวสม่ำเสมอ\n\n"
    "หากมีลักษณะอื่นที่น่าสนใจแต่ไม่เข้าห้าหมวดข้างต้น ให้บันทึกไว้ในฟิลด์ notes "
    "หากภาพเบลอ ไม่เต็มกรอบ หรือแสงไม่พอ ให้ระบุผ่านฟิลด์ quality แทนการเดา"
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
        encoded = base64.standard_b64encode(encode_jpeg(image)).decode("utf-8")

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
