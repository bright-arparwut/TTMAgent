# 07 — The spike: LightRAG `naive` vs `mix` on four-elements

Status: ready-for-human
Type: wayfinder:prototype
Map: ../MAP.md
Blocked by: 01, 02, 06

## Question

This is the ticket the destination is defined against. Build a throwaway spike that
indexes the re-OCR'd book in LightRAG and shows what graph retrieval actually does
to Thai TTM text.

Deliberately cheap and disposable — a script and a results file, not production code.

Produce:

- **The graph itself.** How many entities and relations came out of 39 pages? Is it
  rich enough to be worth traversing, or so sparse that `mix` degenerates to `naive`?
- **What the entities actually are.** The ontology is LLM-discovered with no schema
  (map decision), so the only way to know if that was right is to look. Are they
  coherent TTM concepts (ธาตุไฟ, ธาตุเจ้าเรือน, อาการกำเริบ), or noise? Are Thai
  entity names consistent, or does the same concept appear under several spellings?
- **`naive` vs `mix` on ~10 real questions.** Use questions a real LINE user would
  ask, in Thai. Include at least one multi-hop question that flat retrieval should
  structurally fail — that is the whole thesis claim, and it needs a concrete example.
- **Whether provenance survives.** Do returned chunks still carry enough to build the
  `(อ้างอิง: …)` footer? Feeds back into ticket 04.

Record the results as an asset linked from this ticket, not pasted into it.

## Why it matters

Every remaining design decision (08, 09) is waiting to see real entities. If the
graph turns out sparse or incoherent on 39 pages, that is a finding worth having
before book two arrives, not after.

## Comments
