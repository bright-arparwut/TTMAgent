"""Generate docs/architecture-overview.svg -- the C4 container diagram for the thesis.

Hand-placed coordinates, not auto-layout. The figure is sized for a full A4
portrait page (160 mm text width), which fixes the type scale: the canvas is
1640 x 2460 units, so one unit is ~0.098 mm and a 22-unit label prints at ~6 pt.
Every box position and arrow elbow is chosen to keep the diagram crossing-free,
and every description is trimmed to what fits at that size -- the numbered key
lives in docs/architecture-overview.md, not in the figure, because a legible key
panel does not fit on the same page.

    uv run python scripts/build_architecture_diagram.py
"""

from pathlib import Path

W, H = 1640, 2460

INK = "#1C2B22"
MUTED = "#66766B"
GREEN = "#2E6B4C"
GREEN_SOFT = "#E3EDE5"
TURMERIC = "#C08A2D"
TURMERIC_SOFT = "#F6EDDC"
GREY = "#66766B"
GREY_SOFT = "#EFF1EE"
RULE = "#C7D2C4"

FONT = "Liberation Sans, Arial, Helvetica, sans-serif"

# Type scale, in canvas units. At 160 mm print width: 30u ~ 8.5 pt, 22u ~ 6 pt.
APP_TITLE = 38
BOX_TITLE = 30
STORE_TITLE = 26
GROUP_TITLE = 26
TECH = 22
BODY = 22
SMALL = 21
TINY = 20
BADGE_TEXT = 24
BADGE_R = 20

out: list[str] = []


def esc(body: str) -> str:
    return body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def add(markup: str) -> None:
    out.append(markup)


def text(
    x: float,
    y: float,
    body: str,
    size: float = BODY,
    fill: str = INK,
    weight: str = "normal",
    anchor: str = "start",
    style: str = "",
) -> None:
    extra = f' font-style="{style}"' if style else ""
    add(
        f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
        f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}"{extra}>'
        f"{esc(body)}</text>"
    )


def wrap(body: str, size: float, width: float) -> list[str]:
    """Greedy wrap using an average glyph width for the sans stack."""
    limit = max(1, int(width / (size * 0.52)))
    lines: list[str] = []
    current = ""
    for word in body.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def paragraph(
    x: float,
    y: float,
    body: str,
    size: float,
    width: float,
    fill: str = MUTED,
    leading: float = 1.36,
) -> None:
    step = size * leading
    for i, line in enumerate(wrap(body, size, width)):
        text(x, y + i * step, line, size=size, fill=fill)


def rect(
    x: float,
    y: float,
    w: float,
    h: float,
    fill: str,
    stroke: str,
    sw: float = 2.4,
    rx: float = 8,
    dash: str = "",
) -> None:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'
    )


def path(points: list[tuple[float, float]], dash: str = "") -> None:
    d = "M " + " L ".join(f"{px} {py}" for px, py in points)
    da = f' stroke-dasharray="{dash}"' if dash else ""
    add(
        f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="2.6" '
        f'stroke-linejoin="round" marker-end="url(#arrow)"{da}/>'
    )


def badge(x: float, y: float, label: str) -> None:
    add(
        f'<circle cx="{x}" cy="{y}" r="{BADGE_R}" fill="#FFFFFF" stroke="{INK}" '
        'stroke-width="2.4"/>'
    )
    text(x, y + 8.5, label, size=BADGE_TEXT, weight="bold", anchor="middle")


def container(
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    tech: str,
    body: str,
    kind: str,
    title_size: float = BOX_TITLE,
) -> None:
    """kind: app | store | external | planned"""
    if kind == "app":
        rect(x, y, w, h, GREEN_SOFT, GREEN, sw=4)
    elif kind == "store":
        rect(x, y, w, h, TURMERIC_SOFT, TURMERIC, sw=2.6)
        add(f'<rect x="{x}" y="{y + 2}" width="8" height="{h - 4}" rx="4" fill="{TURMERIC}"/>')
    elif kind == "external":
        rect(x, y, w, h, GREY_SOFT, GREY, sw=2.6, dash="11 8")
    else:
        rect(x, y, w, h, "#FFFFFF", TURMERIC, sw=2.6, dash="3 8")

    pad = 26
    cy = y + 45
    text(x + pad, cy, title, size=title_size, weight="bold")
    if kind == "planned":
        pill_w = 100
        pill_x = x + w - pill_w - 18
        add(
            f'<rect x="{pill_x}" y="{y + 24}" width="{pill_w}" height="30" rx="15" '
            f'fill="{TURMERIC}"/>'
        )
        text(
            pill_x + pill_w / 2,
            y + 45,
            "PLANNED",
            size=18,
            fill="#FFFFFF",
            weight="bold",
            anchor="middle",
        )
    cy += 31
    text(x + pad, cy, tech, size=TECH, fill=MUTED, style="italic")
    cy += 36
    paragraph(x + pad, cy, body, SMALL, w - 2 * pad - 6, fill=INK)


# ------------------------------------------------------------------- canvas
add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
add(
    '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
    f'markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="{INK}"/>'
    "</marker></defs>"
)
add(f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')

# ------------------------------------------------------------ band A: actors
rect(55, 40, 395, 220, "#FFFFFF", INK, sw=3, rx=100)
text(90, 110, "TTM User", size=BOX_TITLE, weight="bold")
text(90, 145, "[Person]", size=TECH, fill=MUTED, style="italic")
paragraph(90, 183, "Chats in Thai and sends tongue photos in LINE.", SMALL, 320, fill=INK)

container(
    700,
    40,
    600,
    220,
    "LINE Platform",
    "[External system - LINE Messaging API]",
    "Delivers webhook events, and renders the app's replies as Flex bubbles, images "
    "and Quick Reply buttons.",
    kind="external",
)

path([(450, 125), (692, 125)])
badge(571, 125, "1")
text(571, 88, "sends message / photo", size=SMALL, fill=MUTED, anchor="middle")

path([(700, 205), (458, 205)])
badge(579, 205, "11")
text(579, 250, "delivers reply", size=SMALL, fill=MUTED, anchor="middle")

# --------------------------------------------------- band B: system boundary
rect(30, 320, 1130, 1370, "none", GREEN, sw=3, rx=18, dash="16 11")
text(55, 364, "TTM Consultation Assistant", size=GROUP_TITLE, weight="bold", fill=GREEN)
text(
    55,
    396,
    "system boundary - one deployable process and the stores it owns",
    size=TECH,
    fill=MUTED,
    style="italic",
)

# the one application container
rect(65, 430, 1015, 470, GREEN_SOFT, GREEN, sw=4)
text(95, 487, "TTM Advisor App", size=APP_TITLE, weight="bold")
text(
    95,
    522,
    "[Container: Python 3.11 - FastAPI - LangGraph]",
    size=TECH + 2,
    fill=MUTED,
    style="italic",
)
paragraph(
    95,
    562,
    "The single deployable process. Every deterministic decision lives here.",
    BODY + 1,
    960,
    fill=INK,
)

RESPONSIBILITIES = [
    ("Webhook intake", "signature check, per-user turn serialization"),
    ("Tongue-detection gate", 'the sole authority on "is there a tongue here?" - ADR 0004'),
    ("Context assembly", "buffer replay + Health Profile + recent entries + passages - ADR 0005"),
    ("Advisor ReAct loop", "two read-only Health Record tools, no write tools - ADR 0002"),
    (
        "Relevance Gate + Profile Updater",
        "code-triggered, LLM-scored, only at close - ADR 0002/0003",
    ),
    ("Topic Menu + citations", "delimiter blocks parsed into Quick Reply + Flex - ADR 0006/0009"),
]
for i, (head, detail) in enumerate(RESPONSIBILITIES):
    bx = 95 + (i % 2) * 500
    by = 622 + (i // 2) * 95
    add(f'<circle cx="{bx + 6}" cy="{by - 8}" r="6" fill="{GREEN}"/>')
    text(bx + 26, by, head, size=TECH + 2, weight="bold")
    paragraph(bx + 26, by + 30, detail, SMALL - 1, 450)

# ------------------------------------------------------------ knowledge column
rect(55, 960, 500, 670, "none", RULE, sw=2, rx=12)
text(78, 1004, "Knowledge", size=GROUP_TITLE, weight="bold", fill=TURMERIC)
text(78, 1034, "what every Assessment is grounded in", size=SMALL, fill=MUTED, style="italic")

container(
    85,
    1060,
    440,
    250,
    "TTM Knowledge Graph",
    "[Container: LightRAG - under evaluation]",
    "Entities and relations from the same corpus, for multi-hop questions. Prototyped "
    "in spike/; not wired into app/ yet - spike #16.",
    kind="planned",
    title_size=24,
)

container(
    85,
    1350,
    440,
    250,
    "TTM Corpus Store",
    "[Container: Chroma - embedded, local files]",
    "Digitized TTM books, one chunk per paragraph, BGE-M3 vectors, with "
    "book / page / paragraph provenance - ADR 0008.",
    kind="store",
)

# --------------------------------------------------------------- memory column
rect(655, 960, 405, 670, "none", RULE, sw=2, rx=12)
text(677, 1004, "Memory", size=GROUP_TITLE, weight="bold", fill=TURMERIC)
text(677, 1034, "[Container: MongoDB 7]", size=SMALL, fill=MUTED, style="italic")

STORES = [
    (1060, "Working Buffer", "Raw turns of the open Consultation; deleted at close."),
    (1200, "Health Record", "One entry per relevant Consultation - the only long-term memory."),
    (1340, "Health Profile", "Face sheet: a rebuildable projection of Health Record entries."),
    (
        1480,
        "Tongue Photos",
        "Every crop, gate-passed or not. Outside the memory lifecycle - ADR 0007.",
    ),
]
for sy, name, detail in STORES:
    rect(685, sy, 355, 130, TURMERIC_SOFT, TURMERIC, sw=2.6)
    add(f'<rect x="685" y="{sy + 2}" width="8" height="126" rx="4" fill="{TURMERIC}"/>')
    text(715, sy + 40, name, size=STORE_TITLE, weight="bold")
    paragraph(715, sy + 70, detail, TINY, 300, fill=INK, leading=1.25)

# ---------------------------------------------------------- external services
container(
    1180,
    430,
    400,
    260,
    "Tongue Detection",
    "[External service - Roboflow]",
    "Serverless workflow: detects and crops the tongue server-side, returns the crop "
    "with its confidence - ADR 0004.",
    kind="external",
)
container(
    1180,
    740,
    400,
    290,
    "Vision Describer",
    "[External service - VLM slot]",
    "Vision-language model, config-selected. Turns a cropped photo into a structured "
    "Tongue Description: it observes, never assesses - ADR 0001.",
    kind="external",
)
container(
    1180,
    1080,
    400,
    300,
    "Advisor Model",
    "[External service - LLM slot]",
    "Chat model, config-selected and independent of the VLM slot. Conducts the "
    "Consultation and both close-time reasoning steps - ADR 0001.",
    kind="external",
)

# ---------------------------------------------------------------------- arrows
path([(900, 260), (900, 422)])
badge(900, 340, "2")
text(930, 348, "webhook event [HTTPS/JSON]", size=SMALL, fill=MUTED)

path([(760, 430), (760, 268)])
badge(760, 340, "10")
text(730, 348, "reply [HTTPS/JSON]", size=SMALL, fill=MUTED, anchor="end")

path([(1080, 520), (1172, 520)])
badge(1126, 520, "3")

path([(1080, 620), (1145, 620), (1145, 860), (1172, 860)])
badge(1145, 722, "5")

path([(1080, 700), (1085, 700), (1085, 1160), (1172, 1160)])
badge(1085, 940, "9")

path([(1080, 760), (1105, 760), (1105, 1230), (1172, 1230)])
badge(1105, 1030, "12")

path([(1080, 820), (1125, 820), (1125, 1300), (1172, 1300)])
badge(1125, 1120, "14")

path([(300, 900), (300, 940), (585, 940), (585, 1480), (533, 1480)])
badge(585, 1210, "8")

path([(430, 900), (430, 1052)], dash="6 8")
text(450, 935, "planned", size=TINY, fill=TURMERIC, style="italic")

path([(900, 900), (900, 968), (625, 968), (625, 1552)])
BRANCHES = [(1125, "6"), (1240, "7"), (1300, "13"), (1380, "7"), (1440, "15"), (1545, "4")]
for branch_y, label in BRANCHES:
    path([(625, branch_y), (677, branch_y)])
    badge(651, branch_y, label)

# -------------------------------------------------------- offline / build-time
rect(30, 1760, 690, 420, "none", GREY, sw=2, rx=12, dash="10 9")
text(55, 1804, "Offline / build-time", size=GROUP_TITLE, weight="bold", fill=GREY)
text(
    55,
    1836,
    "run once per book, outside the request path",
    size=SMALL,
    fill=MUTED,
    style="italic",
)

container(
    60,
    1870,
    280,
    200,
    "Scanned books",
    "[Source - PDF]",
    "Purchased TTM books, scanned page by page.",
    kind="external",
    title_size=STORE_TITLE,
)
container(
    400,
    1870,
    300,
    260,
    "Digitization CLI",
    "[Container: Python]",
    "pdf_ocr, corpus_merge, ingest. Transcribes each page through the Vision "
    "Describer slot, then embeds paragraph records - ADR 0008.",
    kind="external",
    title_size=STORE_TITLE,
)

path([(340, 1950), (392, 1950)])
badge(366, 1950, "A")

path([(700, 2000), (1605, 2000), (1605, 900), (1588, 900)], dash="10 9")
badge(1150, 2000, "B")

path([(500, 1870), (500, 1730), (300, 1730), (300, 1608)], dash="10 9")
badge(300, 1672, "C")

# ---------------------------------------------------------------------- legend
add(f'<line x1="30" y1="2225" x2="1610" y2="2225" stroke="{RULE}" stroke-width="2"/>')
text(30, 2272, "Legend", size=GROUP_TITLE, weight="bold")

LEGEND = [
    ("app", "Container we build and deploy", 30),
    ("store", "Data store we own", 480),
    ("external", "External system / service", 810),
    ("planned", "Planned - not in app/ yet", 1200),
]
for kind, label, lx in LEGEND:
    if kind == "app":
        rect(lx, 2300, 52, 30, GREEN_SOFT, GREEN, sw=3.4, rx=4)
    elif kind == "store":
        rect(lx, 2300, 52, 30, TURMERIC_SOFT, TURMERIC, sw=2.6, rx=4)
        add(f'<rect x="{lx}" y="2302" width="7" height="26" rx="3" fill="{TURMERIC}"/>')
    elif kind == "external":
        rect(lx, 2300, 52, 30, GREY_SOFT, GREY, sw=2.6, rx=4, dash="8 6")
    else:
        rect(lx, 2300, 52, 30, "#FFFFFF", TURMERIC, sw=2.6, rx=4, dash="3 7")
    text(lx + 68, 2323, label, size=TECH, fill=INK)

badge(50, 2390, "n")
text(
    96,
    2398,
    "step in the numbered flow - see the key in architecture-overview.md",
    size=TECH,
    fill=INK,
)
add(
    f'<line x1="900" y1="2390" x2="960" y2="2390" stroke="{INK}" stroke-width="2.6" '
    'stroke-dasharray="10 9"/>'
)
text(976, 2398, "offline or planned path", size=TECH, fill=INK)

add("</svg>")

target = Path(__file__).resolve().parent.parent / "docs" / "architecture-overview.svg"
target.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"wrote {target} ({target.stat().st_size} bytes)")
