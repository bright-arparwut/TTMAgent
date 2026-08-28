# csb-thesis: TTM Consultation Assistant

A LINE chatbot acting as a Thai Traditional Medicine (TTM) self-care advisor: Thai chat, tongue
assessment from photos, and doctor-style memory across visits. Built as a computer science thesis
project.

For the design rationale, glossary, and evaluation plan, see:
- `CONTEXT.md` -- ubiquitous language
- `docs/adr/` -- architecture decision records
- `docs/design-decisions.html` -- visual overview of the pipeline and decisions

## Setup

```bash
uv sync
cp .env.example .env   # then fill in LINE, Advisor Model, Vision Describer, and Roboflow credentials
docker compose up -d   # starts local MongoDB
```

## Run the dev server

```bash
uv run uvicorn app.main:app --reload --reload-exclude 'rag_storage/*'
```

The exclude matters once `rag_storage/` exists: LightRAG writes into its working directory
at query time, so without it an incoming message can restart the server.

LINE only delivers webhooks to a public HTTPS URL. For local development, expose the dev server
through a tunnel (e.g. a Cloudflare named tunnel) and set that URL + `/webhook` as the channel's
webhook URL in the LINE Developers Console.

For a live demo (or anything watched), do **not** use the dev command — follow
`docs/demo-runbook.md`: reload-free single-worker launch with `EMBEDDING_PREWARM=1`, then
`uv run python -m app.preflight` to verify everything green before anyone touches the bot.

## Ingest the TTM corpus

For a scanned book (PDF), transcribe it first — each page image goes through the
Vision Describer model slot (handles Thai and mixed-in Chinese), producing one
JSONL record per paragraph with book/page/paragraph provenance:

```bash
uv run python -m app.rag.pdf_ocr path/to/book.pdf \
    --book-id tamra-ttm --book-title "ตำราแพทย์แผนไทย"
uv run python -m app.rag.ingest corpus/tamra-ttm.jsonl
```

Spot-check the JSONL against the scan before ingesting (OCR is not perfect).
Re-running either command is safe: `pdf_ocr` skips pages already transcribed,
and JSONL chunks use deterministic IDs so re-ingesting updates in place.
Retrieved passages carry a `[book title หน้า X ย่อหน้าที่ Y]` source tag that
the Advisor cites back to the user.

A book already digitized to Markdown with `#`/`##`/`###` section headers still
works, with section-header (not page) provenance:

```bash
uv run python -m app.rag.ingest path/to/ttm_book.md
```

Both paths embed the corpus into the local Chroma store at `CHROMA_PERSIST_DIR`
using BGE-M3 (multilingual — Thai and Chinese embed fine in one collection).

## Project layout

```
app/
  config.py       # every config-selected slot: Advisor Model, Vision Describer, thresholds, gap timing
  main.py         # FastAPI app
  line/           # webhook router, LINE messaging client (reply/push, loading animation)
  pipeline/       # per-user serialization, dispatcher tying the turn together
  vision/         # Roboflow tongue detector, Vision Describer
  advisor/        # config-selected chat model factory, system prompt, LangGraph tool loop, Health Record tools
  rag/            # BGE-M3 embeddings, Chroma vector store, scanned-book OCR + corpus ingestion scripts
  memory/         # MongoDB client, working buffer, Health Record repository, Relevance Gate summarizer
  models/         # shared pydantic schemas
```

## Dev tasks

```bash
uv run ruff check .
uv run pytest
```
