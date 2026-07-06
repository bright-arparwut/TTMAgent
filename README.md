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
uv run uvicorn app.main:app --reload
```

LINE only delivers webhooks to a public HTTPS URL. For local development, expose the dev server
through a tunnel (e.g. a Cloudflare named tunnel) and set that URL + `/webhook` as the channel's
webhook URL in the LINE Developers Console.

## Ingest the TTM corpus

Digitize the purchased TTM book into Markdown with `#`/`##`/`###` section headers, then:

```bash
uv run python -m app.rag.ingest path/to/ttm_book.md
```

This embeds the corpus into the local Chroma store at `CHROMA_PERSIST_DIR` using BGE-M3.

## Project layout

```
app/
  config.py       # every config-selected slot: Advisor Model, Vision Describer, thresholds, gap timing
  main.py         # FastAPI app
  line/           # webhook router, LINE messaging client (reply/push, loading animation)
  pipeline/       # per-user serialization, dispatcher tying the turn together
  vision/         # Roboflow tongue detector, Vision Describer
  advisor/        # config-selected chat model factory, system prompt, LangGraph tool loop, Health Record tools
  rag/            # BGE-M3 embeddings, Chroma vector store, corpus ingestion script
  memory/         # MongoDB client, working buffer, Health Record repository, Relevance Gate summarizer
  models/         # shared pydantic schemas
```

## Dev tasks

```bash
uv run ruff check .
uv run pytest
```
