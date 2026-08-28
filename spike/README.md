# PROTOTYPE — LightRAG `naive` vs `mix` on four-elements

Throwaway spike for **[ticket #16](https://github.com/bright-arparwut/TTMAgent/issues/16)**
on wayfinder map **[#9](https://github.com/bright-arparwut/TTMAgent/issues/9)**.
Not production code. It lives on the `spike/lightrag-naive-vs-mix` branch and
dies with it; the validated decisions go into the ADR, not into `app/`.

## Run

```bash
uv run python -m spike index      # build the graph  (~5 min, Claude Code EXTRACT)
uv run python -m spike graph      # what the graph actually contains
uv run python -m spike compare    # naive vs mix over 10 Thai questions
uv run python -m spike landing    # ticket #36: do Tongue Description values land on node names?
```

`landing` is the [ticket #36](https://github.com/bright-arparwut/TTMAgent/issues/36)
check: it scores Tongue Description axis values (per #31's decided schema) against
the entity names in `results/graph-raw.json`, tiering each value as landed
(exact/containment), near (spelling drift), or miss. Until
[#30](https://github.com/bright-arparwut/TTMAgent/issues/30) indexes the tongue
book the built-in normal-tongue probe is a negative control — expect ~zero
landing. Pass `--descriptions photos.json` to score real described photos and
`--out report.json` to keep the evidence.

Results land in `spike/results/` (gitignored raw dumps aside from the summaries).

## What it answers

1. **The graph itself** — entity/relation counts from 39 pages; rich enough to
   traverse, or so sparse `mix` degenerates to `naive`?
2. **What the entities are** — the ontology is LLM-discovered with no schema
   (map decision). `graph` reports entity types, degree, isolates, and a Thai
   near-duplicate pass (same concept under several spellings = fractured graph).
3. **`naive` vs `mix`** — 10 questions a real LINE user would type, 4 of them
   multi-hop. Headline metric is **section recall**: did the returned context
   contain every source note the answer needs?
4. **Whether provenance survives** — is there enough left to build the
   `(อ้างอิง: …)` footer? Feeds back into ticket #13.

## Design notes

- Queries run `only_need_context=True`, which is what **ticket #13** decided the
  real system does — so this measures *retrieval*, not generation.
- **Role split** (map #9 Notes): `EXTRACT` is a batch job and runs on **Claude
  Code headless**; `KEYWORD` is in the request path on every LINE message and
  cannot, so it stays on the configured Advisor slot (Gemini 2.5 Flash).
  `QUERY` is unused.
- Embedding is the repo's own BGE-M3 via `app.rag.embeddings`, wrapped per
  **ticket #11** — *not* LightRAG's `hf_embed`, which mean-pools and is wrong
  for BGE-M3's CLS head.
- `addon_params={"language": "Thai"}` is mandatory (ticket #11); the default is
  English and would silently extract a Thai book into an English graph.
- The `claude` binary is called by **absolute path** so the user's shell alias,
  which carries `--dangerously-skip-permissions`, is never picked up.

## Measured: Claude Code headless as an EXTRACT backend

A **two-word** prompt costs $0.24 and 65k tokens on the default config — the
floor is Claude Code's own agent preamble, re-sent every invocation. Stripping
settings/MCP/system-prompt gets it to 28k / $0.17. Real numbers for this run are
in `results/index-cost.json`.

That floor is per-*call*, so it amortizes if you call once per **section**
instead of once per **chunk** — which is exactly the `ainsert_custom_kg` option
in [ticket #19](https://github.com/bright-arparwut/TTMAgent/issues/19).
