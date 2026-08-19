# 05 — Retiring the TCM books, Chroma, and ADR 0008

Status: ready-for-human
Type: wayfinder:grilling
Map: ../MAP.md
Blocked by: none

## Question

The corpus is going Thai-only. Decide what happens to what is being left behind.

- **The two TCM books** — `corpus/tcm-basic-theory.jsonl` (1,080 chunks) and
  `corpus/tcm-tongue-diagnosis.jsonl` (621), plus their front-matter files. Delete
  from the repo, keep committed but un-ingested, or move to an `archive/` folder?
  They represent real transcription effort and the thesis may still want to cite
  the digitization work even if the bot no longer reads them.
- **`corpus/four-elements.jsonl`** — superseded by the Markdown re-OCR in ticket 06.
  Keep as a cross-check against the new transcription, or delete once 06 lands?
- **The Chroma store and its code** — `app/rag/vector_store.py`,
  `app/rag/embeddings.py`, `app/rag/ingest.py`, `data/chroma/`. Does `retrieve_passages`
  keep its name and signature with a LightRAG body behind it (so `dispatcher.py:237`
  never changes), or does the seam move?
- **`app/rag/pdf_ocr.py` and `app/rag/corpus_merge.py`** — the JSONL producers.
  Rewritten to emit Markdown, or replaced?
- **ADR 0008** — superseded by a new ADR, or amended in place? Its reasoning about
  printed-page citation authority survives; its record format does not.
- **Tests** — `tests/rag/` and the dispatcher tests that monkeypatch
  `retrieve_passages`. What has to change?

## Why it matters

Unblocked and independent of the graph design, so it can be resolved any time. Left
undecided, the repo carries two contradictory corpus formats and an ADR that
describes a retired pipeline.

## Comments
