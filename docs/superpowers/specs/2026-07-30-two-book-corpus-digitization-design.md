# Design: Digitize two new scanned books into the TTM corpus

**Date:** 2026-07-30
**Status:** Approved by owner (this doc records the design agreed in conversation)

## Goal

Produce ADR 0008-conformant corpus JSONL for two newly scanned books and open a
PR to `main`. Ingestion into Chroma (`app.rag.ingest`) is out of scope — it runs
later on the deploy machine against the same JSONL.

Deliverables:

- `corpus/tcm-basic-theory.jsonl` (+ `corpus/tcm-basic-theory-front-matter.jsonl`)
- `corpus/four-elements.jsonl` (+ `corpus/four-elements-front-matter.jsonl`, if any front matter exists)
- ADR 0008 updated so its book list covers the two new books
- PR from this branch into `main`

## Source material

| | Book 1 | Book 2 |
|---|---|---|
| Title (`book_title`) | ทฤษฎีพื้นฐานการแพทย์แผนจีน | วิถีแห่งธรรมชาติกับธาตุทั้งสี่ |
| Author | นพ.โกวิท คัมภีรภาพ | อนุสรณ์ วรมงคล |
| ISBN | 974-03-0131-2 | 974-323-521-3 |
| `book_id` | `tcm-basic-theory` | `four-elements` |
| PDF pages | 104 | 39 |
| Text layer | none (pure scan) | none (pure scan) |
| Layout | single-column Thai | single-column Thai |
| Printed page number | top corner, with running header | bottom, with title/author footer |
| Observed offset (printed − pdf) | ≈ −10 (pdf 40 → printed 30) | ≈ +5 (pdf 10 → printed 15; pdf 25 → printed 30) |

Book 2 appears to be a partial scan of the printed book; per ADR 0008, pages not
in the scan simply never exist in the corpus and are never cited.

Chunk-ID collision check: existing book is `tcm-tongue-diagnosis`; all three
slugs are distinct, and every chunk ID is prefixed by `book_id`, so no collision.

Source PDFs live in the session scratchpad only and are never committed
(`corpus/` gets JSONL only; repo stays private per ADR 0008).

## Approach (chosen)

Claude sub-agent parallel transcription with an independent verify pass,
instead of the sequential `app.rag.pdf_ocr` CLI (Gemini describer slot). Chosen
because the owner explicitly wants sub-agents, extraction quality is the top
priority, and parallel batches with an adversarial second pass give better
throughput and QC. The JSONL contract is identical, so `app.rag.ingest`
consumes it unchanged.

## Architecture — four stages, all resumable (per-page files on disk)

1. **Render.** Script converts every PDF page to JPEG sized for vision input
   into scratchpad `pages/<book_id>/pNNN.jpg` (143 pages total).
2. **Transcribe (parallel sub-agents).** Pages batched ~8–10 per agent. Each
   agent reads page images and writes one `out/<book_id>/pNNN.json` per page:
   `{"printed_page_number": int|null, "paragraphs": [str, ...]}` following the
   ADR 0008 rules: faithful transcription (book's own typos kept, no
   translation/summary/correction); headings are their own paragraph; running
   headers/footers and the page number excluded from paragraph text but the
   printed page number reported separately; blank/pure-illustration pages give
   an empty paragraph list.
3. **Verify (independent sub-agents).** Different agents re-read each page
   image against the stage-2 JSON and fix: Thai diacritic/vowel errors, missing
   paragraphs, header/footer leakage, wrong printed page number. Pages an agent
   cannot confidently resolve are collected for a final manual check by the
   orchestrator.
4. **Merge + validate + PR.** Script assembles JSONL sorted by `pdf_page`,
   assigns 1-based `paragraph` per page, validates records against the exact
   ADR 0008 key set, checks printed-page continuity against the per-book offset
   (deviating pages get flagged and re-checked), splits unnumbered front-matter
   pages (cover, title page, preface, TOC) into `<book_id>-front-matter.jsonl`
   under a distinct `book_id` (`<book_id>-front`, matching the existing
   `tcm-tongue-diagnosis-front` convention), then commit + push +
   open PR to `main`, including the ADR 0008 book-list update.

## Record format (unchanged, ADR 0008)

```json
{"book_id": "tcm-basic-theory", "book_title": "ทฤษฎีพื้นฐานการแพทย์แผนจีน",
 "page": 30, "pdf_page": 40, "paragraph": 2, "text": "..."}
```

`page` = printed page number when readable, interpolated from the per-book
offset on unnumbered body pages (chapter openers), never the raw PDF index when
a printed numbering exists.

## Error handling

- Every stage writes per-page artifacts; any interrupted stage re-runs and
  skips completed pages.
- Validation failures (schema, page-offset anomalies) block the merge until
  resolved — no silently dropped or mangled pages.
- Low-confidence pages surface in a review list rather than being guessed at.

## Testing / acceptance

- Validator passes: every line has exactly the six ADR 0008 keys, correct
  types, non-empty `text`, per-page `paragraph` numbering contiguous from 1.
- Printed-page offset consistent per book (with explained exceptions only).
- Spot-check: a sample of pages per book compared side-by-side against the
  rendered image (done by the verify pass; final sample re-checked by the
  orchestrator).
- CI (ruff + pytest) green on the PR; no application code changes expected.
