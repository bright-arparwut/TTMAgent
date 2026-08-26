# Slide image-generation prompts

Text-to-image prompts for three thesis slides. Each is grounded in what the
system actually does — see [`docs/message-flow.md`](../message-flow.md),
[ADR 0001](../adr/0001-two-model-pipeline.md),
[ADR 0002](../adr/0002-health-record-only-memory.md),
[ADR 0003](../adr/0003-health-profile-projection.md), and
[`spike/results/RESULTS.md`](../../spike/results/RESULTS.md).

## How to use these

1. **Never ask the generator for Thai text.** Every model renders Thai as
   gibberish. Generate the artwork text-free, then overlay Thai labels in
   PowerPoint / Keynote / Figma. Each prompt below ends with a `no text`
   instruction and a matching negative prompt.
2. Paste `[STYLE]` (below) verbatim in place of the `[STYLE]` token at the end
   of each prompt. It is what makes the three slides look like one deck.
3. Generate at **16:9**. The prompts reserve the top ~15% of the canvas for the
   slide title.
4. Model notes are at the bottom.

## [STYLE] — shared style block

```text
Style: flat vector editorial infographic for an academic conference slide, clean
geometric shapes, thin uniform 2px outlines, subtle soft shadows, no photorealism
and no 3D render, warm off-white background (#F6F4EF), restricted palette of deep
teal (#1F5E5B), turmeric amber (#D99A2B), terracotta (#B85C38) and slate grey
(#38414A), generous negative space, elements aligned on an invisible grid, the top
15% of the canvas left empty for a title, 16:9 canvas, crisp and uncluttered,
no text, no letters, no numbers, no watermark.
```

**Negative prompt** (for tools that take one — Stable Diffusion, Firefly, Leonardo):

```text
text, letters, words, labels, typography, gibberish writing, watermark, logo,
UI screenshot, photorealistic, 3D render, glossy, neon, cluttered, busy
background, human faces, stock photo look, drop shadow noise
```

## Slide 1 — VLM + RAG/KG + Health Profile working together

The system's shape: a deterministic vision stage in front, three context sources
converging on one Advisor, one reply back to the user.

```text
A wide 16:9 system-architecture illustration showing four parts working as one
pipeline, read left to right.

LEFT: a simplified flat-vector smartphone, a chat bubble floating above it and a
small square framed photo of a soft pink oval shape inside the screen — a user
sending a photo and a message.

MIDDLE-LEFT: an arrow leads to a rounded card containing a camera-lens/eye icon
with a dashed crop rectangle tightening around the pink shape; a small gauge arc
sits beside the lens. From the right edge of this card a small structured record
emerges, drawn as a stack of four short coloured rows in a rounded frame.

CENTER: a large rounded hexagon, clearly the biggest element on the canvas,
sitting on the centre line — the reasoning core. A circular loop arrow curls
inside it, suggesting an internal think-act cycle.

FROM ABOVE, feeding the hexagon: a stack of two closed books with a constellation
of small connected dots and thin lines rising out of the top cover like a network
growing from the pages, joined to the hexagon by a downward arrow.

FROM BELOW, feeding the hexagon: an upright clipboard chart card with a few ruled
horizontal lines and small coloured tags on its edge, with three smaller identical
cards stacked behind it in receding offset, joined to the hexagon by an upward
arrow.

RIGHT: an arrow leaves the hexagon toward a second smartphone showing a reply
bubble, with three small rounded pill-shaped buttons in a row beneath the bubble.

All arrows share the same line weight and are clearly directional; the three
incoming arrows meet the hexagon at distinct edges. Equal spacing between zones.

[STYLE]
```

**Labels to overlay afterwards:** vision card → `Tongue Detection + Vision
Describer (VLM)`; books/network → `TTM Corpus — RAG / Knowledge Graph`; chart
stack → `Health Profile + Health Record`; hexagon → `Advisor Model (ReAct)`;
pills → `Topic Menu`.

**Alternate concept** — if you prefer a metaphor over a block diagram: *"A flat
vector illustration of three streams of light in teal, amber and terracotta
flowing from three sources — an eye, a constellation over an open book, and a
medical chart — converging into a single bright braided beam that exits toward a
smartphone on the right. [STYLE]"*

## Slide 2 — Entities and relations in the TTM knowledge graph

Shaped after the real extracted graph: 288 entities, 403 relations, ~1.4 relations
per entity, 12 entity types, 14 isolates, with `ธาตุทั้งสี่` and `โหราศาสตร์` as the
top-degree hubs and the four elements as sub-hubs.

```text
A wide 16:9 knowledge-graph illustration in flat vector style: a force-directed
network of about 40 circular nodes connected by thin straight lines.

STRUCTURE: one large deep-teal node at the centre, noticeably bigger than every
other node. Four medium nodes arranged around it in a balanced diamond, each in a
different colour — terracotta red, deep blue-teal, amber ochre, pale sage — each
linked to the centre by a slightly thicker line. Each medium node carries its own
small cluster of five to eight tiny satellite nodes branching outward like a
constellation, and three or four thin lines cross between different clusters so the
graph reads as interconnected, not as four separate trees.

NODE VARIETY: node radius varies with importance; a handful of small nodes use
different simple shapes — circle, rounded square, diamond, hexagon — to suggest
different entity types; two or three faint grey dots float near the outer edges
with no lines attached to them.

ICONOGRAPHY: inside the four medium nodes only, a single simple line pictogram
each — a flame, a water droplet, a small mound of soil with a sprout, and a curling
swirl of air. No pictograms anywhere else.

The network is centred with a generous even margin; background completely empty.

[STYLE]
```

**Labels to overlay afterwards:** centre → `ธาตุทั้งสี่`; the four sub-hubs →
`ธาตุไฟ`, `ธาตุน้ำ`, `ธาตุดิน`, `ธาตุลม`; a couple of satellites → `ราศี…`,
`สมุนไพร…`, `อาการ…`; a stray dot → `isolated entity (degree 0)`. Edge labels for
the relations, e.g. `ประกอบด้วย`, `องค์ประกอบ`, `เกี่ยวข้องกับ`.

**Variant if you want the model to draw the labels:** append *"a few nodes carry
short single English words in a clean sans-serif: FIRE, WATER, EARTH, WIND"* and
remove `no text, no letters` from `[STYLE]`. English single words are usually
rendered correctly; anything longer is a lottery.

## Slide 3 — Health Profile / Patient Record as long-term memory

The story of ADR 0002 + ADR 0003: raw turns are transient, a gate decides what is
worth keeping, and what survives is distilled into an accumulating chart.

```text
A wide 16:9 flat vector illustration of a memory pipeline, read left to right in
three clearly separated zones.

LEFT ZONE — the transient part: a loose cluster of seven chat bubbles in mixed
sizes inside a dashed rounded rectangle. The bubbles nearest the top of the cluster
are fading out and breaking into small dissolving particles that drift upward and
disappear.

CENTER ZONE — the filter: a wide clean-lined funnel, with the dashed rectangle's
contents streaming into its mouth. Only a few solid, saturated droplets pass
through the narrow neck and fall to the right; several pale grey shapes are
deflected off the funnel's outer wall and drift away downward and out of frame.

RIGHT ZONE — the persistent part: an upright medical chart card with a few ruled
horizontal lines and small coloured tags down its left edge, catching the droplets
that came through the funnel. Four more identical cards are stacked behind it in
receding offset perspective, an accumulating series. Beneath the stack runs a thin
horizontal timeline with four evenly spaced dots on it, the dots growing subtly
larger from left to right.

A single thin arrow curves from the top of the right zone back over the top of the
canvas to the left zone, closing the loop.

Zones separated by clear empty space; nothing overlaps.

[STYLE]
```

**Labels to overlay afterwards:** dashed box → `Working Buffer (ครั้งเดียว, ลบทิ้ง)`;
funnel → `Relevance Gate`; deflected grey shapes → `discarded — no health content`;
front card → `Health Record entry`; stack → `Health Profile (face sheet)`;
timeline → `Consultation 1 … n`; return arrow → `injected into every turn`.

**Alternate concept** — the doctor's-desk metaphor: *"A flat vector illustration of
a doctor's desk seen from directly above: on the left, loose scattered note slips
some of which are dissolving into particles; in the centre, a hand-drawn funnel
shape; on the right, a neat open patient folder with a printed face sheet on the
left leaf and a tidy stack of dated chart notes on the right leaf, a thin timeline
ribbon running along the bottom edge. [STYLE]"*

## Model notes

| Tool | Notes |
|---|---|
| **Midjourney v6/v7** | Append `--ar 16:9 --style raw --stylize 150`. It ignores long compositional instructions — shorten each prompt to the two or three most important spatial facts, or generate each zone separately and assemble in the slide tool. |
| **Nano Banana / Gemini image** | Best of the group at following the long layout descriptions above, and the only one to trust with in-image English labels. Paste the prompt whole. Iterate conversationally: "make the central hexagon larger", "remove the labels". |
| **GPT-image (ChatGPT)** | Also good at layout and English text. Ask for "flat vector, no gradients" explicitly or it drifts toward glossy 3D. |
| **Stable Diffusion / Firefly / Leonardo** | Use the negative prompt. Weak at multi-zone composition — generate individual icons (funnel, chart stack, book-with-network) and lay them out yourself. |

**Consistency tip:** generate slide 1 first, keep the seed / use it as a style
reference image for slides 2 and 3 so all three share the same line weight and
palette.

**Honest alternative:** for slides 1 and 3 the content is a diagram, not an
illustration — a Mermaid diagram or hand-laid PowerPoint shapes will read more
precisely at the back of a defence room than any generated image. Consider using
generated art for the section-opener slides and real diagrams for the ones the
committee will actually interrogate. `docs/message-flow.md` already holds a
Mermaid flowchart you can render straight into a slide.
