"""PROTOTYPE (ticket #16) -- the naive-vs-mix question set.

Questions a real LINE user would plausibly type, in Thai. Each carries the
sections that actually hold the answer, so a run can be judged without
re-reading the book. `hops` is the number of distinct sections a complete
answer has to cross -- hops > 1 is where flat dense retrieval should
structurally fail, which is the thesis claim.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Question:
    qid: str
    text: str
    hops: int
    expects: tuple[str, ...]  # source-note numbers holding the answer
    why: str
    chain: tuple[str, ...] = field(default=())  # the reasoning steps, for multi-hop


QUESTIONS: tuple[Question, ...] = (
    Question(
        qid="Q01",
        text="ธาตุทั้งสี่ในการแพทย์แผนไทยมีอะไรบ้าง",
        hops=1,
        expects=("04",),
        why="Flat lookup. Control: if naive fails here the retrieval rig is broken, not the mode.",
    ),
    Question(
        qid="Q02",
        text="คนที่ธาตุไฟมากเกินไปจะมีอาการอย่างไรบ้าง",
        hops=1,
        expects=("18",),
        why="Single table row. Tests whether the imbalance table survived chunking at all.",
    ),
    Question(
        qid="Q03",
        text="ช่วงนี้นอนไม่หลับ ร้อนใน ผมร่วง เป็นเพราะธาตุอะไรเสียสมดุล",
        hops=1,
        expects=("18",),
        why="Reverse lookup: symptoms -> element. Same section as Q02 but entered from "
            "the symptom side, which is how a user actually talks.",
    ),
    Question(
        qid="Q04",
        text="อยากเสริมธาตุน้ำให้แข็งแรงขึ้น ควรทำอย่างไร",
        hops=1,
        expects=("15",),
        why="Remedy lookup. Pairs with Q03 -- together they are the two halves Q06 has to join.",
    ),
    Question(
        qid="Q05",
        text="ราศีสิงห์เกี่ยวข้องกับธาตุอะไร",
        hops=1,
        expects=("16",),
        why="The zodiac->element edge on its own. Isolates the hop Q06 depends on.",
    ),
    Question(
        qid="Q06",
        text="ฉันเกิดราศีสิงห์ ช่วงนี้นอนไม่หลับกับร้อนในบ่อยมาก ควรดูแลตัวเองยังไงดี",
        hops=3,
        expects=("16", "18", "15"),
        chain=(
            "ราศีสิงห์ -> ธาตุไฟแรง (note 16)",
            "นอนไม่หลับ + ร้อนใน -> ธาตุไฟที่มากไป (note 18, imbalance table)",
            "ธาตุไฟมากไป -> ลดไฟ / เสริมธาตุน้ำ เช่น แช่หรืออาบน้ำเย็น (notes 18, 15)",
        ),
        why="THE THESIS QUESTION. Three sections, and the user's own words ('ราศีสิงห์') "
            "share no vocabulary with the section that holds the remedy. Dense retrieval "
            "on the literal query should surface 18 and miss the 16->15 chain entirely.",
    ),
    Question(
        qid="Q07",
        text="ดวงกำเนิดของฉันมีดาวหลายดวงอยู่ราศีมิถุนกับกุมภ์ แปลว่าอะไร แล้วต้องระวังอะไรบ้าง",
        hops=2,
        expects=("16", "18"),
        chain=(
            "ราศีมิถุน + กุมภ์ -> ธาตุลมเด่น (note 16)",
            "ธาตุลมมากไป -> อาการทางกายและอารมณ์ (note 18, imbalance table)",
        ),
        why="Second multi-hop, different element, so Q06's result is not a single lucky draw.",
    ),
    Question(
        qid="Q08",
        text="เขาคำนวณน้ำหนักของธาตุจากดวงชะตากำเนิดกันยังไง",
        hops=2,
        expects=("17", "16"),
        chain=(
            "ตารางน้ำหนักดาวเคราะห์ อาทิตย์/จันทร์/ลัคนา = 3 (note 17)",
            "รวมคะแนนตามราศีที่ดาวสถิต -> ส่วนผสมธาตุของคนคนนั้น (notes 17, 16)",
        ),
        why="Table-heavy and procedural. Tests whether a Markdown table became usable "
            "graph structure or junk -- pain point #3's own example.",
    ),
    Question(
        qid="Q09",
        text="ฮิปโปเครติสเชื่อมโยงอารมณ์ของคนกับธาตุทั้งสี่ไว้อย่างไร",
        hops=1,
        expects=("04",),
        why="Named-entity lookup on a transliterated Western name inside Thai text. "
            "Tests whether EXTRACT keeps foreign proper nouns as coherent entities.",
    ),
    Question(
        qid="Q10",
        text="ธาตุดินสอนอะไรเราในการใช้ชีวิต และถ้าธาตุดินอ่อนไปจะเป็นยังไง",
        hops=2,
        expects=("15", "18"),
        chain=(
            "ธาตุดินสอนให้รู้จักเงียบ อดทน มั่นคง (note 15)",
            "ธาตุดินที่อ่อนไป -> ล่องลอย, สับสน, ระบบประสาทไม่ปกติ (note 18)",
        ),
        why="Two-part question in one message -- very LINE-user. A flat top-k has to "
            "split its budget across two sections; the graph should link them by entity.",
    ),
)

MULTI_HOP = tuple(q for q in QUESTIONS if q.hops > 1)
