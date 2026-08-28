# GraphRAG rollout: implementation plan

**Goal**: make the knowledge graph live behind LINE — every text message and every tongue-photo turn retrieves through LightRAG `mix` instead of Chroma — and execute the Chroma retirement, ending with a green preflight and an updated demo runbook.

**Source of truth**: [ADR 0010](../adr/0010-graphrag-lightrag-corpus.md). Every design question this plan touches is already decided there; if an implementation step seems to require a new design decision, re-read the ADR section linked from the task before inventing one. The graph itself is already built and committed (`rag_storage/`: 1,400 entities / 1,837 relations / 177 chunks, both books).

**Out of scope** (per the ADR's Open questions): thesis evaluation design, Advisor prompt weighting of graph descriptions beyond a first sensible prompt, ธาตุเจ้าเรือน as a retrieval entry point, and confirming `app/memory/element.py` against the book.

**How to work this plan**: phases are ordered by dependency; each is roughly one focused session and ends with its verification gate green. Tasks within a phase are bite-sized and name exact files. Work on a branch per phase and PR to `main` (repo convention); never push a phase whose gate is red. Phase 6 is independent of 3–5 and can run any time after Phase 1.

**Cutover strategy**: the Chroma path keeps working until Phase 1 lands, because Phase 1 rewrites `app/rag/vector_store.py` in place — there is no dual-running period and no feature flag. The safety net is git plus `four-elements.jsonl`, which stays in the repo until Phase 5's final task.

---

## Phase 0 — Dependencies and vectors

**Gate**: `uv run python -c "import lightrag"` works from the main dependency group; local `vdb_*.json` files exist and are consistent with the committed stores.

### 0.1 Promote `lightrag-hku` to a main dependency

- `pyproject.toml`: move `lightrag-hku>=1.5.6` from the `spike` group into `[project] dependencies`. Leave the `spike` group otherwise intact (the spike stays runnable as evidence).
- `uv lock && uv sync`.
- Verify: `uv run python -c "from lightrag import LightRAG, QueryParam"`.

### 0.2 Rebuild the local vector stores

The committed half of `rag_storage/` is authoritative; vectors are local-only (ADR 0010, Engine and storage).

- Run LightRAG's rebuild (`lightrag-rebuild-vdb`, pointed at `rag_storage/` with the BGE-M3 embedding func — the spike's `spike/index_corpus.py` shows the embedding wiring). Expect ~1 min.
- Verify: `uv run python -m app.preflight` — the existing `check_vdb_consistency` check sees matching stores. `vdb_*.json` must remain gitignored; `git status` stays clean.

---

## Phase 1 — The retrieval seam: `retrieve_passages` on LightRAG

**Gate**: `uv run pytest tests/rag tests/pipeline` green; `uv run python scripts/chat.py` answers a Thai question with passages retrieved from the graph and resolvable note references; dispatcher tests untouched and green.

### 1.1 Settings (`app/config.py`)

Replace the `# Chroma (TTM corpus RAG)` block with the LightRAG block. Add:

- `rag_query_mode: str = "mix"` — `"naive"` is the thesis baseline arm; any other value is a config error at boot.
- KEYWORD slot, mirroring the advisor/describer slot pattern exactly: `keyword_provider`, `keyword_model`, `keyword_api_key`, `keyword_base_url`, and a `keyword_slot() -> ModelSlotSettings` method. Default to a flash-tier hosted model (this is the request path — never Claude Code headless, never the Advisor slot).
- Token budgets (replacing `rag_top_k`): `rag_section_token_budget: int = 5000` (whole sections handed to the Advisor), `rag_entity_token_budget: int = 2000`, `rag_relation_token_budget: int = 2000`.
- `rag_storage_dir: str = "./rag_storage"` and `corpus_dir: str = "./corpus"`.
- Keep `embedding_model_name` and `embedding_prewarm` as they are. **Do not delete `chroma_persist_dir`/`rag_top_k` yet** — they die in Phase 5 with the rest of the Chroma path, so this phase's diff stays reviewable.

### 1.2 LightRAG construction (`app/rag/vector_store.py`, rewritten in place)

Replace `get_vector_store()` with a cached `get_rag()` that builds the one process-wide LightRAG instance:

- `EmbeddingFunc(embedding_dim=1024, max_token_size=8192, func=...)` wrapping the existing `HuggingFaceEmbeddings` from `app/rag/embeddings.py` (async wrapper; **not** LightRAG's `hf_embed` — it mean-pools, wrong for BGE-M3's CLS head).
- `addon_params={"language": "Thai"}` — and nothing else.
- `embedding_func_max_async=1` (the MPS segfault rule), `enable_rerank=False` (defaults `true` with no reranker), `working_dir=settings.rag_storage_dir`.
- KEYWORD role bound via an adapter over `app/advisor/llm.py:build_chat_model(settings.keyword_slot())` — a bare async `def (prompt, **kwargs) -> str`. The role key is `keyword`, singular. The QUERY role gets the same adapter for construction validity but is never invoked (we never call `aquery` for generation).
- **Boot failure, not silent degrade**: if the authoritative store files are missing or `vdb_*.json` are absent, raise at startup with a message naming `lightrag-rebuild-vdb`. Delete the current "persist dir does not exist → return []" warning path — `[]` is never a silent steady state (ADR 0010, retrieval seam).

### 1.3 `retrieve_passages` rewrite (same file, same signature)

`async def retrieve_passages(query: str) -> list[str]` — the dispatcher call site (`app/pipeline/dispatcher.py`) and every test monkeypatch survive unchanged.

1. `await rag.aquery_data(query, param=QueryParam(mode=settings.rag_query_mode, ...))` — **never** `aquery(only_need_context=True)` (bare `reference_id`s, unbuildable citations).
2. **Relations in, entities out**: collect `reference_id`s from matched *relations* (and `naive`-mode chunks); entities contribute none.
3. Resolve each `reference_id` through the result's `references` list to a basenamed `file_path`, then read the complete source note from `corpus/<book_id>/<filename>` (search the book folders; filename is unique — it is the citation). Cap at `rag_section_token_budget` total, whole notes first; when a note doesn't fit, fall back to the chunk text for that reference (honest chunk-grain fallback).
4. Return numbered notes: each list element is one note prefixed `[n] <filename-without-.md>` followed by its body. The number is the id the Advisor will cite; the filename carries book position and printed page range.
5. Entity/relation descriptions (up to their budgets) are appended as a final unnumbered context element, clearly labelled as graph context — evidence the Advisor may read but has no id to cite.
6. **Degrade**: on a KEYWORD-call failure, retry the same query with `mode="naive"` and log at ERROR. Only if that also fails, return `[]` (and log at ERROR).

### 1.4 Tests (`tests/rag/test_vector_store.py`, rewritten)

Fake the LightRAG instance (monkeypatch `get_rag`); no model downloads in CI. Cover: relations-in-entities-out; whole-note expansion from a temp corpus tree; the token-budget chunk fallback; numbering stability; KEYWORD-failure degrade to `naive` logged at ERROR; missing-store boot failure. Confirm `tests/pipeline/test_dispatcher_*.py` pass **without modification** — that is the seam-shape guarantee.

---

## Phase 2 — Citations: bare ids in, rendered Thai out

**Gate**: `uv run pytest tests/advisor tests/pipeline` green, including the updated prompt contract test; a `scripts/chat.py` reply ends with a rendered citation naming real book titles and page ranges, and an invented id disappears.

### 2.1 Advisor prompt (`app/advisor/prompts.py`)

Rewrite the retrieval-passage section of `SYSTEM_PROMPT`: passages arrive as numbered notes `[n]`; the reply's final line cites **bare ids only** — `(อ้างอิง: [1] [3])` — never titles or page numbers (the model does not know them; `book_title` never enters its context). Cite only notes actually used; the graph-context block is uncitable background. Keep the ADR 0009 ordering rule: citation line before the `[หัวข้อ]` topic block.

### 2.2 Reference rendering (`app/advisor/citation.py`)

Add `render_references(reply_text: str, passages: list[str]) -> str`:

- Parse the trailing `(อ้างอิง: [..])` line; map each id to its passage's filename; drop ids with no passage (the invented-id guarantee).
- Render grouped by book, cap 3, `reference_id` order: book title from `corpus/books.yaml` (`book_id` → title), page range from the filename's `น.<แรก>-<สุดท้าย>`.
- Replace the bare-id line with the rendered Thai line **in the same `(อ้างอิง: …)` format**, so ADR 0009's `split_citation`, Flex footer, and degrade ladder work untouched downstream.
- **Invariant to test**: every note handed to the Advisor is citable, and every rendered citation names a handed note.

### 2.3 Dispatcher spine (`app/pipeline/dispatcher.py`)

- Retrieval query = concatenation of the **last 2–3 user turns** from the Working Buffer plus the incoming text (ADR 0010, retrieval seam; `QueryParam.conversation_history` does nothing for retrieval). Small helper, no seam change.
- Call `render_references` on the Advisor reply **before the Working Buffer write**, so the buffer (and the model's own history) holds the resolved citation.

### 2.4 Contract tests

Update `tests/advisor/test_prompt_citation_contract.py` to the bare-id contract. New tests for `render_references`: grouping, cap 3, ordering, invented-id drop, no-citation passthrough, and the invariant above.

---

## Phase 3 — Tongue Description contract

**Gate**: `uv run pytest tests/models tests/vision tests/pipeline` green; the acceptance script reports its landing rate on stored photos.

### 3.1 Schema (`app/models/schemas.py`)

Replace `TongueDescription`'s placeholder fields with the five axes as **free Thai text** with English keys — `color` (สี), `coating` (ฝ้า), `size` (ขนาด), `shape` (รูปร่าง), `spots` (จุดบนลิ้น) — keeping `notes` and `quality` exactly as they are. No Literals, no booleans, no `moisture` (their content folds into the axes via the prompt). `การเคลื่อนไหว` and sublingual veins stay out (a still top-side crop cannot witness them; `notes` catches the rare visible case).

### 3.2 Describer prompt (`app/vision/describer.py`)

Rewrite `DESCRIBE_PROMPT` per axis, pinned to ch. 12's tables as **examples, never enums**: source notes `206`–`209`, `211` under `corpus/tongue-100/`, with รูปร่าง drawing from `210` too (cracks/teeth marks band). Steer toward the book's vocabulary; instruct Thai values.

### 3.3 The rendered description is the retrieval query

Where the tongue turn builds the Advisor input from the description (dispatcher/tongue path), render **Thai axis labels** — `สี: …\nฝ้า: …` — plus `notes`. Never `model_dump_json()` (English keys must not reach KEYWORD or the Working Buffer). Add a test asserting the render contains the Thai labels and no English key names.

### 3.4 Acceptance check (`scripts/redescribe_photos.py`, new)

Re-describe stored Tongue Photos with the new prompt and report per-axis landing against the committed graph's node names (exact / substring / near-variant, as ticket #36 measured). This is the check that reopens Literal-hardening **only** if the landing is poor — record the numbers in the PR description.

---

## Phase 4 — Runtime shape, preflight, staleness gate

**Gate**: `uv run python -m app.preflight` fully green on a machine with rebuilt vectors; CI runs the staleness gate.

### 4.1 Preflight (`app/preflight.py`)

- Graph checks become authoritative (they WARN today): all committed `rag_storage/` files present (`graph_chunk_entity_relation.graphml` + the seven `kv_store_*.json`), `check_vdb_consistency` red on mismatch, `corpus/books.yaml` covers every `corpus/<book_id>/` folder.
- Remove the Chroma check together with Phase 5 (keep preflight passing at every merge — if Phase 4 lands first, leave the Chroma check WARN-only).
- Any `rag_storage/` filename change must update `AUTHORITATIVE_FILES` — keep the list and the ADR in sync.

### 4.2 Staleness gate (`app/rag/source_notes.py` + CI)

- Add `--check-index`: compare a committed manifest (note `uid` → content hash, e.g. `rag_storage/index-manifest.json`, written at index time) against the current source notes; any drift is a failure naming the stale notes and the fix (`adelete_by_doc_id` + re-insert — LightRAG silently rejects same-name re-inserts).
- Wire into `.github/workflows/ci.yml` next to the existing validator run.

### 4.3 Demo runbook (`docs/demo-runbook.md`)

Update the launch ritual: no `--reload` ever (LightRAG writes its working dir at query time; uvicorn's watcher would restart the server mid-demo), `EMBEDDING_PREWARM=1`, one worker, `lightrag-rebuild-vdb` as a setup step, preflight before demo.

---

## Phase 5 — Chroma retirement (executes ADR 0010's migration section)

**Gate**: full `uv run pytest` green; `grep -ri chroma app/ tests/` returns nothing; preflight green.

- 5.1 `git mv` the four TCM files (`tcm-basic-theory.jsonl`, `tcm-tongue-diagnosis.jsonl`, both `-front-matter.jsonl`) to `corpus/archive/`. Nothing ingests from `archive/`.
- 5.2 Delete `app/rag/ingest.py`, `app/rag/pdf_ocr.py`, `app/rag/corpus_merge.py` and their tests (`test_ingest.py`, `test_pdf_ocr.py`, `test_corpus_merge.py`). `app/rag/embeddings.py` stays.
- 5.3 Remove `langchain-chroma` from `pyproject.toml` (+ `uv lock`); delete the `data/chroma/` `.gitignore` line; remove `chroma_persist_dir` and `rag_top_k` from `app/config.py`; remove the preflight Chroma check.
- 5.4 Rewrite `CONTEXT.md`'s **TTM Corpus** entry: the graph + source-note story, the two Thai books, ADR 0010 — keeping the copyright paragraph's force (private repo only, never copied out, vault never on Obsidian Sync/iCloud).
- 5.5 **Last, its own commit, only after a live end-to-end LINE session against the graph**: delete `four-elements.jsonl` + `four-elements-front-matter.jsonl`. This is the point where "rollout completes" (ticket #14's ruling).

---

## Phase 6 — The vault: `corpus/graph.json` + concept notes

Independent of Phases 3–5; needs only the committed stores. **Gate**: `uv run pytest tests/rag` green; regeneration twice in a row produces an empty `git diff corpus/concepts/`.

- 6.1 `app/rag/graph_export.py` (new): read the committed graphml + KV stores directly (no LightRAG import, zero LLM calls) and write **`corpus/graph.json`** — entities (name, type, description, degree, source files), relations (endpoints, keywords, description, source files). Deterministic ordering.
- 6.2 `app/rag/concept_notes.py` (new): generate `corpus/concepts/` from `corpus/graph.json` — one note per entity, **all entities, no degree threshold**; filename = verbatim entity name (one sanitize rule + `aliases` frontmatter); flat folder; frontmatter exactly `entity/type/degree/generated/aliases`, **no timestamps**; body = description verbatim, relations as `- [[target]] — keywords: description` on **both** endpoints, source-note wikilinks by basename.
- 6.3 Rebuild = wholesale delete + regenerate **behind a git-dirty guard**: refuse if `corpus/concepts/` has uncommitted changes, so hand edits surface instead of dying.
- 6.4 Commit the generated vault. `git diff corpus/concepts/` is now the re-index quality instrument (use it whenever the extract model changes, alongside `spike/results/graph-summary.json`).

---

## Done means

1. A LINE text message answers through one `mix` query with a rendered `(อ้างอิง: …)` citation naming book titles and printed pages the user can check.
2. A tongue photo produces a five-axis Thai description whose rendered text retrieves through the graph the same way.
3. `rag_query_mode=naive` flips the thesis baseline arm with no other change.
4. `uv run python -m app.preflight` is fully green; CI enforces note validation + the staleness gate.
5. No Chroma code, dependency, setting, or data path remains outside `corpus/archive/`; CONTEXT.md tells the graph story.
6. `corpus/concepts/` + `corpus/graph.json` are committed and deterministic.
7. The re-describe acceptance numbers are recorded (and Literal-hardening stays closed unless they are poor).

## Standing hazards (ADR 0010, restated so nobody relearns them)

- BGE-M3 on MPS: pre-warm in lifespan, serialize (`embedding_func_max_async=1`), one worker — or it segfaults.
- Never `--reload`.
- `addon_params={"language": "Thai"}` or the graph silently goes English on the next index.
- An edited note re-inserted without `adelete_by_doc_id` is silently ignored.
- `enable_rerank` must be explicitly `False`.
- KEYWORD is the one place LINE user text leaves the machine — keep it that way.
