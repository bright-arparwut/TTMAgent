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
