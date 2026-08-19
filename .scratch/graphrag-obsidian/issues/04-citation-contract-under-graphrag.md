# 04 — What does the Advisor cite when evidence is a relation chain?

Status: ready-for-human
Type: wayfinder:grilling
Map: ../MAP.md
Blocked by: none

## Question

Today the contract is concrete: `retrieve_passages` prefixes each chunk with
`[ชื่อตำรา หน้า X ย่อหน้าที่ Y]`, and the Advisor's system prompt requires a
trailing `(อ้างอิง: …)` line citing only tags actually provided (ADR 0008, ADR 0009).

GraphRAG breaks the one-to-one mapping. In `mix` mode, evidence arrives as three
different things: matched **entities**, matched **relations**, and retrieved
**chunks**. An entity like ธาตุไฟ is an abstraction over many paragraphs; a relation
chain may span sections.

- What does a citation mean when the answer came from a relation, not a paragraph?
- Do entities and relations get cited at all, or only the chunks behind them?
- If only chunks: does LightRAG reliably return the source chunks for a
  graph-derived answer, and does our frontmatter/page-marker provenance survive
  LightRAG's own chunking intact?
- Does the user-facing citation format change, or stay `หน้า X` exactly as now?
- Is a citation that names a *section* instead of a page acceptable, given ADR 0008's
  principle that users hold the physical book and only printed numbers are checkable?

## Why it matters

The citation contract is a user-facing promise and a thesis claim about grounding.
If provenance cannot survive graph retrieval, that is a reason to constrain the
design — and it is much cheaper to discover now than after the spike.

## Comments

### 2026-08-19 — two bullets answered by ticket 03

[Ticket 03](03-source-note-markdown-format.md) settled the source-note half of this
question. Do not re-grill these two:

- **"Does our frontmatter/page-marker provenance survive LightRAG's own chunking?"**
  Partly. `file_paths=` is attached to **every** chunk and is what returns as
  `references[].file_path` — so the filename is the durable carrier, and ticket 03
  put book, section, and page range into it for that reason. YAML frontmatter reaches
  **chunk 1 only** and is not a citation carrier. Inline `<!-- p.N -->` markers
  survive as literal text inside whatever chunk they fall in — usable, but only if
  the marker happens to land in the retrieved chunk.
- **"Is a citation that names a section instead of a page acceptable?"**
  Yes — decided in ticket 03. Grain moved from `หน้า X ย่อหน้าที่ Y` to section plus a
  page range, e.g. `[วิถีแห่งธรรมชาติกับธาตุทั้งสี่ — ราศีและการบำบัด, น.19–22]`.
  ADR 0008's checkability principle survives: a range is still checkable against the
  physical book, just coarser. LightRAG will never return a paragraph number.

**What is left for this ticket**, and it is the harder half: whether entities and
relations get cited at all or only the chunks behind them, what a citation *means*
when the answer came from a relation chain spanning sections, and whether the
user-facing `(อ้างอิง: …)` format changes.

One open risk worth carrying in: ADR 0009's flex footer and the Advisor prompt
require citing only tags actually provided. If `mix` mode answers partly from
relation descriptions with no chunk behind them, there may be nothing legitimate to
cite — that is a design constraint on the retrieval seam (ticket 09), not just a
formatting choice.
