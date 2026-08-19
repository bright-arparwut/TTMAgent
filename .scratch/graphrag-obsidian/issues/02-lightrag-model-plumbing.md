# 02 — LightRAG's model plumbing and index cost

Status: ready-for-agent
Type: wayfinder:research
Map: ../MAP.md
Blocked by: none

## Question

What exactly does LightRAG need wired in, and what does one full index cost?

- **Embedding function**: can BGE-M3 stay? It is already the corpus embedder
  (`app/rag/embeddings.py`, `BAAI/bge-m3`, run locally via `langchain_huggingface`)
  and is multilingual, which matters for Thai. What signature does LightRAG expect,
  and does it need the embedding dimension declared up front?
- **Gemini is built in** (established): `google-genai>=1.0.0,<3.0.0` is a **core**
  dependency of `lightrag-hku`, not an extra. Both model slots are Gemini 2.5 Flash
  today, so the EXTRACT/KEYWORDS/QUERY roles may need no new plumbing at all.
- **Extraction LLM**: TTMAgent already has two config-selected model slots (Advisor
  Model, Vision Describer), both currently Gemini 2.5 Flash. Can the extraction LLM
  be a third slot on the same pattern, and what call shape does LightRAG require?
- **Cost and time**: how many LLM calls does indexing ~39 pages of Thai text take,
  and roughly how long? Entity extraction runs per chunk, sometimes with
  "gleaning" re-passes — quantify it, because every schema change means re-indexing.
- **Thai behaviour**: does LightRAG's extraction prompt need a language hint, or does
  it produce Thai entity names unprompted? Any known non-English issues.

## Why it matters

Determines whether GraphRAG is cheap enough to re-index freely during the spike, or
expensive enough that indexing runs need to be planned. Also decides whether the
local-embedding privacy property survives.

## Comments

## Added 2026-08-19 — can EXTRACT run through Claude Code instead of an API?

Established already (do not re-research):

- LightRAG has **four independently configurable LLM roles**: `EXTRACT` (index
  time, per chunk), `KEYWORDS` (every query — pulls keywords from the user message),
  `QUERY` (every query — writes the final answer), and `VLM`. So the extraction
  backend and the query backend can differ.
- Claude Code headless mode (`claude -p`) is a supported automation surface, with
  `--output-format json`, `--json-schema` for structured output, and
  `--append-system-prompt`.
- **`--bare` does not use the subscription login** — it requires `ANTHROPIC_API_KEY`.
  Running non-bare to get subscription billing loads `CLAUDE.md`, hooks, skills and
  MCP servers into every call, polluting the extraction prompt and adding seconds of
  startup per chunk.

Still open:

- **Does LightRAG accept a pre-built graph?** Is there an `insert_custom_kg()` or
  equivalent that takes entities + relationships directly, bypassing its own LLM
  extraction? The README does not mention one. This is the deciding fact: if it
  exists, extraction can be done by Claude Code sub-agents with a transcribe-then-
  verify pass (the pattern that already worked for OCR), which gives real control
  over extraction quality — the top risk given the no-schema ontology. If it does
  not, the only Claude Code route is `claude -p` wired into `llm_model_func` for
  the EXTRACT role.
- What is the actual `llm_model_func` signature (async? `prompt`, `system_prompt`,
  `history_messages`, `keyword_extraction`, `**kwargs`?) — the README does not show
  it. Check `docs/ProgramingWithCore.md` in the LightRAG repo.
- Rough cost baseline to beat, for the eventual two-book corpus (~139pp, ~300
  chunks, incl. gleaning re-passes): order of 1.3M input + 0.5M output tokens per
  full index — roughly $4 on Haiku 4.5, ~$18 on Opus 5, less on Gemini Flash.
  Confirm against real chunk counts once ticket 06 lands. If the real figure stays
  in this range, the plumbing may not be worth the savings.

## Comments
