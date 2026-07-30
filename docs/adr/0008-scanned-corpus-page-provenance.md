# TTM Corpus: scanned-book digitization with page/paragraph provenance

The [TTM Corpus](../../CONTEXT.md) is digitized from scanned book PDFs at **paragraph granularity**, with every chunk carrying `book_id`, `book_title`, the **printed** page number, and the 1-based paragraph number on that page. The pipeline is three one-off CLIs: `app.rag.pdf_ocr` renders each PDF page and has a vision model transcribe it into paragraph-level JSONL, `app.rag.corpus_merge` assembles per-page transcription JSON from parallel vision sub-agents into that same JSONL format, and `app.rag.ingest` embeds the JSONL into Chroma under deterministic IDs (`<book_id>:p<page>:para<paragraph>`). `retrieve_passages` prefixes every retrieved chunk with a source tag (`[ชื่อตำรา หน้า X ย่อหน้าที่ Y]`) and the Advisor's system prompt requires a trailing `(อ้างอิง: …)` line citing only tags actually provided.

The first corpus book is the Thai translation of 中医临床舌诊 ("การตรวจรักษาโรคแบบแพทย์แผนจีนโดยการวินิจฉัยโรคจากลิ้น", Hu Zhen, Chulalongkorn University Press) — a two-column layout with Thai on the left and Chinese on the right; only the Thai column is transcribed. Books two and three — "ทฤษฎีพื้นฐานการแพทย์แผนจีน" (นพ.โกวิท คัมภีรภาพ, `tcm-basic-theory`) and "วิถีแห่งธรรมชาติกับธาตุทั้งสี่" (อนุสรณ์ วรมงคล, `four-elements`) — are single-column Thai scans digitized by parallel vision sub-agents (a transcribe pass, then an independent verify pass against the same page images) and assembled by `app.rag.corpus_merge`, which turns per-page transcription JSON into this record format. Both are partial scans: printed pages missing from the scan simply never appear in the corpus.

## Record format

One JSONL line per paragraph, UTF-8, exactly these keys:

```json
{"book_id": "tcm-tongue-diagnosis",
 "book_title": "การตรวจรักษาโรคแบบแพทย์แผนจีนโดยการวินิจฉัยโรคจากลิ้น",
 "page": 98, "pdf_page": 113, "paragraph": 3,
 "text": "การที่ลิ้นไม่มีฝ้าและมีรอยแตกอย่างเห็นได้ชัด ..."}
```

| Field | Meaning | Where it goes at ingest |
|---|---|---|
| `book_id` | Stable slug, unique per book; also distinguishes books inside the one `ttm_corpus` collection | chunk metadata + ID prefix |
| `book_title` | The title the Advisor cites to users | chunk metadata (source tag) |
| `page` | The **printed** page number (citation authority — see Why) | chunk metadata (source tag) + ID |
| `pdf_page` | 1-based page index in the scanned PDF, kept to trace a record back to the scan | not ingested |
| `paragraph` | 1-based paragraph position on that printed page; headings and figure captions count; a paragraph continuing from the previous page is paragraph 1 of its page | chunk metadata (source tag) + ID |
| `text` | The paragraph exactly as printed (Thai column only for this book) | chunk text (embedded) |

Chunk ID: `<book_id>:p<page>:para<paragraph>`, with a `:c<n>` suffix only when an oversized paragraph is size-split. `app.rag.pdf_ocr` and `app.rag.corpus_merge` are the producing halves of this format, and `app.rag.ingest` is the consuming half; their docstrings restate it.

## Why

- **Paragraph as the chunk unit, not fixed-size splits.** The paragraph is the smallest unit a citation names; a chunk that crosses a paragraph boundary makes "ย่อหน้าที่ N" ambiguous. Paragraphs in this book fit comfortably in one chunk; the rare oversized paragraph is size-split with every piece keeping the same page/paragraph metadata (ID suffix `:c<n>`).
- **Printed page numbers are the citation authority, never the PDF index.** The scan's PDF index drifts against the printed numbering (unscanned blanks and photo inserts shift the offset from −16 to −13 across this book), so the transcription step reads the italic corner number on each page and only falls back to interpolation on unnumbered chapter openers. An interpolated page takes the offset of the nearest **following** numbered page, not the preceding one: a scan gap lands immediately before a chapter opener, so the opener belongs to the run that follows it (in `tcm-basic-theory` this is the difference between citing page 85 and citing page 75). Users hold the physical book; only printed numbers are checkable.
- **Provenance must survive retrieval.** Metadata that stops at the vector store is invisible to the model: `retrieve_passages` previously returned bare `page_content`. Formatting the source tag into the passage text is what lets the Advisor cite without new plumbing.
- **Deterministic chunk IDs make re-ingest an upsert.** OCR corrections are expected (spot-checks against the physical book); re-running ingest with `<book_id>:p<page>:para<paragraph>` IDs updates chunks in place instead of duplicating them.
- **Front and back matter are excluded from the corpus.** Prefaces, imprint, and table of contents are not advice-grounding material, and their unnumbered pages would collide with printed body pages 3–16 in the ID scheme. The leading and trailing runs of unnumbered pages (covers, imprint, TOC; bibliography, back cover) are kept in a separate `<book_id>-front-matter.jsonl` under the distinct `book_id` `<book_id>-front`, with `page` set to `pdf_page`, and are normally not ingested.
- **The corpus JSONL is committed to this private repo.** Initially kept out of git for copyright reasons; the owner decided to commit it (a purchased copy digitized for thesis use, repo is private). Standing constraint: the repo must never be made public and `corpus/` must never be copied into a public repo.
- **Faithful transcription, no editorial fixes.** The book's own typos (e.g. "อุณภูมิ") are transcribed as printed — a citation should match what the reader finds on the page. The one exception: Chinese characters referenced inline by the Thai text itself (ลิ้น "รูปตัว 人") are kept, because dropping them breaks the sentence they anchor.

## Considered and rejected

- **Tesseract/dedicated OCR engines**: weak on Thai diacritics and useless for the two-column Thai/Chinese separation; a vision LLM handles both and reads the corner page numbers in the same pass.
- **Markdown + header-based chunking (the original path)**: kept working for born-digital sources, but it cannot express page/paragraph provenance; scanned books go through the JSONL path.
- **Keeping the corpus out of git entirely** (the initial position): transferring the JSONL out-of-band on every deploy adds friction for a single-owner private repo; superseded by the commit-to-private-repo decision above.

## Consequences

- The Advisor's citations are only as accurate as the transcription; OCR uncertainty concentrates in tone marks of Thai transliterations of Chinese terms — spot-checking against the physical book remains a manual step after any re-digitization.
- Printed pages missing from the scan (68–69, 106, 128 in this book) simply do not exist in the corpus; a citation will never name them.
- BGE-M3 embeds Thai (and any retained inline Chinese) in one multilingual space, so one collection serves all books; per-book filtering stays available via `book_id` metadata.
