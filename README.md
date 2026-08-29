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

The corpus is a LightRAG knowledge graph, committed at `rag_storage/` (BGE-M3
embeddings, both TTM books already indexed). Its derived vector stores are
gitignored, so rebuild them locally after `uv sync`:

```bash
uv run python scripts/rebuild_vdb.py
```

Source notes — the graph's input — live under `corpus/<book_id>/`: transcribed
Markdown, one file per book section, with frontmatter carrying provenance.
Validate them with:

```bash
uv run python -m app.rag.source_notes corpus
```

After any re-index, `--check-index` catches source notes that have drifted
from the committed graph:

```bash
uv run python -m app.rag.source_notes corpus --check-index
```

For how to add a book or edit a note — the re-indexing workflow itself — see
`docs/adr/0010-graphrag-lightrag-corpus.md`.

## Project layout

```
app/
  config.py       # every config-selected slot: Advisor Model, Vision Describer, thresholds, gap timing
  main.py         # FastAPI app
  line/           # webhook router, LINE messaging client (reply/push, loading animation)
  pipeline/       # per-user serialization, dispatcher tying the turn together
  vision/         # Roboflow tongue detector, Vision Describer
  advisor/        # config-selected chat model factory, system prompt, LangGraph tool loop, Health Record tools
  rag/            # BGE-M3 embeddings, LightRAG retrieval seam, source-note validation + staleness gate
  memory/         # MongoDB client, working buffer, Health Record repository, Relevance Gate summarizer
  models/         # shared pydantic schemas
```

## Dev tasks

```bash
uv run ruff check .
uv run pytest
```
