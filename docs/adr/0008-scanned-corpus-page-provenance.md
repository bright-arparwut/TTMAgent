# TTM Corpus: scanned-book digitization with page/paragraph provenance

The [TTM Corpus](../../CONTEXT.md) is digitized from scanned book PDFs at **paragraph granularity**, with every chunk carrying `book_id`, `book_title`, the **printed** page number, and the 1-based paragraph number on that page. The pipeline is two one-off CLIs: `app.rag.pdf_ocr` renders each PDF page and has a vision model transcribe it into paragraph-level JSONL, and `app.rag.ingest` embeds that JSONL into Chroma under deterministic IDs (`<book_id>:p<page>:para<paragraph>`). `retrieve_passages` prefixes every retrieved chunk with a source tag (`[ชื่อตำรา หน้า X ย่อหน้าที่ Y]`) and the Advisor's system prompt requires a trailing `(อ้างอิง: …)` line citing only tags actually provided.

The first corpus book is the Thai translation of 中医临床舌诊 ("การตรวจรักษาโรคแบบแพทย์แผนจีนโดยการวินิจฉัยโรคจากลิ้น", Hu Zhen, Chulalongkorn University Press) — a two-column layout with Thai on the left and Chinese on the right; only the Thai column is transcribed.

## Why

- **Paragraph as the chunk unit, not fixed-size splits.** The paragraph is the smallest unit a citation names; a chunk that crosses a paragraph boundary makes "ย่อหน้าที่ N" ambiguous. Paragraphs in this book fit comfortably in one chunk; the rare oversized paragraph is size-split with every piece keeping the same page/paragraph metadata (ID suffix `:c<n>`).
- **Printed page numbers are the citation authority, never the PDF index.** The scan's PDF index drifts against the printed numbering (unscanned blanks and photo inserts shift the offset from −16 to −13 across this book), so the transcription step reads the italic corner number on each page and only falls back to interpolation on unnumbered chapter openers. Users hold the physical book; only printed numbers are checkable.
- **Provenance must survive retrieval.** Metadata that stops at the vector store is invisible to the model: `retrieve_passages` previously returned bare `page_content`. Formatting the source tag into the passage text is what lets the Advisor cite without new plumbing.
- **Deterministic chunk IDs make re-ingest an upsert.** OCR corrections are expected (spot-checks against the physical book); re-running ingest with `<book_id>:p<page>:para<paragraph>` IDs updates chunks in place instead of duplicating them.
- **Front matter is excluded from the corpus.** Prefaces, imprint, and table of contents are not advice-grounding material, and their unnumbered pages would collide with printed body pages 3–16 in the ID scheme. They are kept in a separate JSONL under a distinct `book_id` and normally not ingested.
- **Faithful transcription, no editorial fixes.** The book's own typos (e.g. "อุณภูมิ") are transcribed as printed — a citation should match what the reader finds on the page. The one exception: Chinese characters referenced inline by the Thai text itself (ลิ้น "รูปตัว 人") are kept, because dropping them breaks the sentence they anchor.

## Considered and rejected

- **Tesseract/dedicated OCR engines**: weak on Thai diacritics and useless for the two-column Thai/Chinese separation; a vision LLM handles both and reads the corner page numbers in the same pass.
- **Markdown + header-based chunking (the original path)**: kept working for born-digital sources, but it cannot express page/paragraph provenance; scanned books go through the JSONL path.
- **Storing the corpus in git**: the digitized text is copyrighted; `corpus/` is gitignored and the JSONL is transferred out-of-band.

## Consequences

- The Advisor's citations are only as accurate as the transcription; OCR uncertainty concentrates in tone marks of Thai transliterations of Chinese terms — spot-checking against the physical book remains a manual step after any re-digitization.
- Printed pages missing from the scan (68–69, 106, 128 in this book) simply do not exist in the corpus; a citation will never name them.
- BGE-M3 embeds Thai (and any retained inline Chinese) in one multilingual space, so one collection serves all books; per-book filtering stays available via `book_id` metadata.
