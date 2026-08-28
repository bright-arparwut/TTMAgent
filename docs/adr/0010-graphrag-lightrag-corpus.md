# TTM Corpus as a LightRAG knowledge graph: source notes, `mix` retrieval, section-grain citations

**Supersedes [ADR 0008](0008-scanned-corpus-page-provenance.md) wholesale.** [ADR 0009](0009-citation-flex-footer.md) (the Flex citation footer) stands untouched. This ADR consolidates the decisions of the wayfinder map [GraphRAG for TTMAgent, via an Obsidian vault](https://github.com/bright-arparwut/TTMAgent/issues/9); each section links the ticket that decided it, where the full reasoning and evidence live.

The [TTM Corpus](../../CONTEXT.md) becomes a **knowledge graph built by LightRAG** (`lightrag-hku`, ≥1.5.6) over a corpus of **Markdown source notes** — one note per book section, transcribed by agent sessions and validated by `app/rag/source_notes.py`. Retrieval is **one pre-fetched LightRAG `mix` query per turn** (entity + relation + dense, merged) behind the unchanged `retrieve_passages` seam; the thesis baseline is the same engine in `naive` mode, one config value away. The graph is **evidence**; the source notes are **attribution**: the Advisor reads whole sections and cites them by book title and printed page range. A generated Obsidian vault of concept notes is a **view over** the graph, never a runtime dependency.

Two principles carry forward verbatim from ADR 0008 — they decided the citation contract here and remain load-bearing ([#14](https://github.com/bright-arparwut/TTMAgent/issues/14), [#13](https://github.com/bright-arparwut/TTMAgent/issues/13)):

- **Printed page numbers are the citation authority, never the PDF index.**
- **Users hold the physical book; only checkable things may be cited.**

## Engine and storage ([#10](https://github.com/bright-arparwut/TTMAgent/issues/10), [#24](https://github.com/bright-arparwut/TTMAgent/issues/24))

LightRAG runs on its **file-persisted defaults**: JsonKV + NanoVectorDB + NetworkX + JsonDocStatus, all core deps of `lightrag-hku`, zero services, swappable per-store later. Local MongoDB cannot back it — `MongoVectorDBStorage` requires Atlas Search.

The working directory is repo-root **`rag_storage/`**, split in two:

- **Committed (authoritative)**: the graphml and *all* KV stores (~1.15 MB). A full EXTRACT costs real money and a logged-in session; the committed half is the artifact. LightRAG 1.5.6 writes four KV stores beyond the subset `app/preflight.py` lists as `AUTHORITATIVE_FILES` — those are authoritative and committed too ([#30](https://github.com/bright-arparwut/TTMAgent/issues/30)).
- **Gitignored (regenerated)**: `vdb_*.json` (~6.4 MB) and the LLM response cache. Rebuilt locally by LightRAG's own `lightrag-rebuild-vdb` in ~1 min for $0 (measured 16.9 texts/s). Committing vectors would cost ~4.5 MB of git history per re-index — `vdb_entities.json` is a monolithic base64 matrix that gzips 1.4×, against the graphml's 10.5×. Missing vectors are a **visible boot failure**, never a silent rebuild.

**LightRAG 1.5.6 has no in-place update.** Any same-name record is treated as a duplicate: an edited source note re-inserted as-is is **silently rejected** and the stale graph survives. Edits require `adelete_by_doc_id` then re-insert. Staleness detection is a committed manifest plus `source_notes --check-index` in CI — **not** `git diff`, because every storage layer carries timestamps.

## Ontology ([#16](https://github.com/bright-arparwut/TTMAgent/issues/16), [#19](https://github.com/bright-arparwut/TTMAgent/issues/19))

Entity and relation types are **LLM-discovered** — LightRAG's default, no hand-authored TTM schema. The spike validated this on real Thai text: coherent hubs (`ธาตุทั้งสี่`, `โหราศาสตร์`, `การบำบัดด้วยธาตุทั้งสี่`), consistent Thai naming, and the coherence held at 5× scale after book two. `addon_params` is `{"language": "Thai"}` and **nothing else** — the default is `English` and would silently extract a Thai book into an English graph. `entity_types_guidance` is a deliberately un-pulled knob.

## Source notes: the corpus format ([#12](https://github.com/bright-arparwut/TTMAgent/issues/12), amended by [#28](https://github.com/bright-arparwut/TTMAgent/issues/28), [#29](https://github.com/bright-arparwut/TTMAgent/issues/29), [#32](https://github.com/bright-arparwut/TTMAgent/issues/32), [#33](https://github.com/bright-arparwut/TTMAgent/issues/33))

One `.md` per level-2 section (chapter lead prose gets its own note); a book that numbers its material finely — `tongue-100`'s 100 characteristics — amends the grain to **one note per numbered characteristic**. Notes live at `corpus/<book_id>/`, validated by `uv run python -m app.rag.source_notes corpus`.

**The filename is the citation**: `<NN>-<section>-น.<first>-<last>.md` (`FILENAME_RE` = `^(\d{2,3})-(.*)-น\.(\d+)-(\d+)\.md$`). LightRAG's `file_paths=` is the citation carrier, and LightRAG **basenames** it — the directory does not survive indexing, so nothing may depend on the path around the filename. Forced by `ainsert` always fixed-token chunking: frontmatter reaches chunk 1 only, so metadata that must survive chunking rides in the filename.

- **`NN` is a page-order sort key and citation label, not the book's own numbering** (the book skips, doubles, and merges numbers). 2-digit or 3-digit per book, never mixed within one (validator error — notes sort lexically). Pre-allocating NN bands for parallel transcription sizes them **on the pages covered, not on a count of things a survey named**.
- **Frontmatter** (`uid`, `type: source-note`, `book_id`, `chapter`, `section`, `pages`, `pdf_pages`): `uid` becomes LightRAG's `ids=`, so a page correction renames the file without churning the graph — a renumber is a pure rename, no re-index.
- **`book_title` lives in `corpus/books.yaml`** (`book_id` → title), never in frontmatter — so the Thai title is never in the model's context and citation rendering owns it.
- **Section labels are citation keys, not transcriptions**: Thai is 3 bytes/char and the OS caps filenames at 255 bytes, so long labels truncate at the first clause boundary (~70 Thai chars) with the full heading kept verbatim as an H2 on the first body line. A `/` in a label becomes `-` in filename and `section` (a citation cannot hold a path separator).
- **Page markers** are `<!-- p.N -->` inline at the exact break point. Inside tables, the marker **prefixes the first row that begins on the new page** — a marker-only line would split the table — and a straddling row belongs to the page it starts on.
- **Typo'd domain terms are corrected in the body with the printed form preserved**: `<!-- sic: <as-printed> -->`. EXTRACT would otherwise split one entity in two. Everything else is transcribed as printed.
- **Tables** are reunified as real Markdown; row spans expand by repetition into every row they cover; the book's explicit `-` and genuinely blank cells stay distinct. **Statistical charts are figures, not tables** — reading values off bars invents precision the book never printed.
- **Images**: photos and third-party image text are never transcribed; the book's own typeset Thai captions are kept. A figure label that carries a section's whole substance (diagram-only content) is transcribed as text — the test is whether the line still asserts anything once the image is gone.

## Vault: generated concept notes ([#17](https://github.com/bright-arparwut/TTMAgent/issues/17))

**`corpus/` is the vault.** `corpus/<book_id>/` folders are the sources; generated **`corpus/concepts/`** is one note per extracted entity — **all of them, no degree threshold** (isolates included for thesis honesty). Each note is the entity description verbatim, relations as link-first labelled bullets on **both** endpoints (`- [[target]] — keywords: description`; weight dropped, no plugins), and source-note wikilinks — basename wikilink resolution matches LightRAG's basenamed `file_path` exactly.

Filename = **verbatim entity name** (one sanitize rule plus `aliases`); flat folder. Frontmatter is five fields (`entity`/`type`/`degree`/`generated`/`aliases`), **no timestamps: generation is deterministic**, so `git diff corpus/concepts/` is the re-index quality instrument. `concepts/` is **committed**; rebuilds are wholesale deletes behind a git-dirty guard, so hand edits surface rather than silently dying. The generator reads a committed graph export at **`corpus/graph.json`** — zero LLM calls, no LightRAG import, rebuildable from git alone.

The generated half is **write-only at runtime**; only source notes are read (by citation expansion). Obsidian is a view for humans — TTMAgent is a headless FastAPI webhook and cannot require a desktop GUI to answer a LINE message. **Copyright**: the vault lives inside this private repo and must never be placed in `~/Documents/Obsidian Vault` or any folder on Obsidian Sync / iCloud, which would copy the books to a third-party server.

## Indexing: model plumbing and the EXTRACT backend ([#11](https://github.com/bright-arparwut/TTMAgent/issues/11), [#19](https://github.com/bright-arparwut/TTMAgent/issues/19))

LightRAG configures four LLM roles independently — `extract` (index time), `keyword` and `query` (query time), `vlm` (unused; photos are never ingested). The role keys are singular; the plural raises at construction.

- **Embeddings: BGE-M3 stays, local at index and query time.** An async `EmbeddingFunc(embedding_dim=1024, max_token_size=8192)` wraps our existing `HuggingFaceEmbeddings` (`app/rag/embeddings.py`) — **not** LightRAG's `hf_embed`, which mean-pools and is wrong for BGE-M3's CLS head. Local embedding preserves the privacy property.
- **Chunking**: LightRAG's default fixed-token chunker. The `R`/`V` splitters are CJK-only and degrade on Thai.
- **EXTRACT runs on Claude Code headless (`claude -p --model sonnet`)** — the owner's Max plan covers it, so the measured 3–13× token premium over direct API (each invocation re-sends a ~28–37k-token preamble) costs no marginal dollars, while direct API costs real spend (~$0.33 Haiku 4.5 to ~$1.63 Opus 5 for the 39-page book, ~$4.27 measured via headless). `spike/claude_code_llm.py` is the reference implementation. The binding is to a **logged-in `claude` session, not to hardware** — book two's EXTRACT ran off-Mac: 376 calls, 0 failures, 46m23s ([#30](https://github.com/bright-arparwut/TTMAgent/issues/30)). Swapping the extract model is config-level (`extract_slot()` in the existing slot pattern, plus an adapter over `build_chat_model`) but **invalidates the spike's quality evidence** — re-index and diff against `spike/results/graph-summary.json` and `corpus/concepts/` first.
- **LightRAG's own pipeline owns EXTRACT.** `ainsert_custom_kg` is rejected: it would give up `doc_status` recovery (deletion fails closed until repair), flatten entity→chunk provenance to one chunk — cutting against the citation contract — and take on chunking, entity merging, dedup, and description summarization ourselves. The ingestion path is **standard LightRAG, no bespoke pipeline**.

## The retrieval seam ([#18](https://github.com/bright-arparwut/TTMAgent/issues/18), [#13](https://github.com/bright-arparwut/TTMAgent/issues/13))

`retrieve_passages` keeps its name and signature; its one caller is the dispatcher spine (`app/pipeline/dispatcher.py`). Behind it:

- **One pre-fetched `mix` query per turn.** Mode is fixed by a new **`rag_query_mode`** setting; `naive` stays available as the same-infrastructure thesis baseline arm. **No per-turn mode router** — it would cost what it saves and confound the thesis arms.
- **No LLM query rewrite.** The KEYWORD role *is* the rewriter. `QueryParam.conversation_history` is not used for retrieval, so the spine concatenates the **last 2–3 user turns** into the query string (zero extra LLM calls). Pre-supplied `hl_keywords`/`ll_keywords` skip KEYWORD entirely — a verified but unused escape hatch.
- **The retrieval call is `aquery_data`** — not `aquery(only_need_context=True)`, which returns bare `reference_id`s with no id→file_path map and would leave the citation footer unbuildable. `aquery_data` returns entities, relations, chunks, and a resolving `references` list.
- **The QUERY role never runs.** LightRAG returns full structured context before its QUERY-role call; the **Advisor Model writes the reply**, unchanged. KEYWORD is the one hosted LLM call per message, on a new flash-tier **`keyword_slot()`** (not Claude Code — request path; not the Advisor slot) — and the one place LINE user text leaves the machine.
- **Token budgets replace `rag_top_k`** (retired), as settings: ~**5 full sections (~5k tok)** to the Advisor, ~2k each for entity and relation descriptions, ~10k total. **`enable_rerank` must be explicitly disabled** — it defaults `true` with no reranker configured.
- **Failure behavior**: a missing store is a **visible boot failure** (ablation only by explicit setting). A transient KEYWORD failure degrades that query to `naive` — grounded but flat — logged at ERROR. **`[]` is never a silent steady state.**
- The Health Profile stays prompt-only; Advisor-as-tool retrieval is deferred future work (it would confound the thesis arms and unbound latency).

## The citation contract ([#13](https://github.com/bright-arparwut/TTMAgent/issues/13), corrected by [#16](https://github.com/bright-arparwut/TTMAgent/issues/16))

**The Advisor cites the sections a relation was extracted from, because it reads them in full.** Graph is evidence, notes are attribution: LightRAG strips `file_path` from entity/relation context before the prompt, so graph elements are structurally uncitable — and an entity's `file_path` is a multi-source bibliography anyway.

- **Relations in, entities out**: a matched relation contributes its source notes; entities contribute none.
- **Evidence grain is the whole section**: each `reference_id` expands to its complete `.md` read off disk (~1,000 tok/section against LightRAG's 1,200-token chunk — nearly free), so citation and evidence are the same object. Per-note token cap with honest chunk-grain fallback.
- **The model emits bare ids** — `(อ้างอิง: [1] [2])` — and **our code renders** the citation: grouped by book, cap 3, `reference_id` order, Thai titles from `books.yaml`. An invented id is dropped at render, which a model-composed citation could never guarantee.
- **Invariant: every note handed to the Advisor is citable, and every citation names a note the Advisor was handed.**
- Resolution happens **before the Working Buffer write**, so ADR 0009's parser, Flex footer, and degrade ladder are untouched; only the provenance of the string inside `(อ้างอิง: …)` changed.

## The Tongue Description contract ([#31](https://github.com/bright-arparwut/TTMAgent/issues/31), [#36](https://github.com/bright-arparwut/TTMAgent/issues/36))

The Vision Describer's schema is **five of the six inspection axes** from `100 ลักษณะวินิจฉัยลิ้น` ch. 12 — สี, ฝ้า, ขนาด, รูปร่าง, จุดบนลิ้น — as **free Thai text**, prompt-steered, never enum-enforced. การเคลื่อนไหว is excluded (a still photo cannot witness movement); sublingual veins likewise (a top-side crop cannot witness them; `notes` catches the rare visible case). JSON keys stay English (structured-output property names risk rejecting Thai), which is safe because **the tongue turn contractually renders Thai axis labels, never raw `model_dump_json()`** — the rendered description *is* the retrieval query, so the book's own vocabulary reaches KEYWORD.

Free text is validated against the committed graph: the book's entry names land 99 exact / 6 substring / 1 near-variant on graph node names, and KEYWORD matches by BGE-M3 embedding, so exactness is not required. **No hardening to Literals.** `DESCRIBE_PROMPT` pins per-axis steering to ch. 12's tables (source notes `206`–`209`, `211`; รูปร่าง draws from `210` too) — examples, never enums. The live re-describe of stored photos is the **implementation effort's acceptance check**; a poor landing there reopens hardening with real data.

## Deployment shape ([#24](https://github.com/bright-arparwut/TTMAgent/issues/24), [#26](https://github.com/bright-arparwut/TTMAgent/issues/26))

**There is no deployment**: one pre-warmed, reload-free uvicorn process on the owner's M1 Mac, LightRAG **in-process**. Measured: BGE-M3 alone is 14.5 s / 986 MB / `mps:0`; LightRAG plus the whole store adds 0.33 s and no measurable memory (warm query 0.03 s). A sidecar would buy a second 986 MB model to serve a 0.03 s lookup. BGE-M3 on MPS binds the runtime to this machine far harder than anything binds indexing.

Three defaults are demo-killers and therefore architecture:

1. **`--reload` must go.** LightRAG persists KEYWORD responses into its working directory *at query time*, and uvicorn watches that directory — a LINE message can restart the server.
2. **BGE-M3 pre-warms in a lifespan handler** (`EMBEDDING_PREWARM`; `/health` reports `embedding: ready|cold`). Lazy `@lru_cache` construction would spend 15–23 s on the first message *and* is the unlocked-construction segfault below.
3. **One worker, `embedding_func_max_async=1`.**

Preflight (`uv run python -m app.preflight`) checks the store read-only; any change to `rag_storage/` filenames must update `app/preflight.py`.

## Spike evidence: `naive` vs `mix` ([#16](https://github.com/bright-arparwut/TTMAgent/issues/16), re-baselined by [#30](https://github.com/bright-arparwut/TTMAgent/issues/30))

- **four-elements alone (39 pp)**: 288 entities / 403 relations / 28 chunks. The graph was rich but the corpus too small to prove it matters — `naive` returned 20 chunks (71% of the book) on every query, so section recall saturated (97% `naive` vs 100% `mix`). The one genuine separation, **Q06**, is the thesis claim exactly: `naive` read 71% of the book and missed the remedy section; `mix` used fewer chunks and recovered it **through a relation, not a chunk**. n=1 — an illustration, not evidence.
- **Both books (#30)**: 1,400 entities / 1,837 relations / 177 chunks. A 20-chunk `naive` return now covers **11%** of the corpus — **the recall-saturation blocker on the thesis comparison is gone**. Graph quality held at 5× scale.
- **Provenance survives retrieval**: 10/10 questions returned resolving reference lists (~13 refs/question) — via `aquery_data` only.

## Operational hazards (learned, load-bearing)

- **BGE-M3 on MPS is not thread-safe under LightRAG's embedding workers**: `@lru_cache` does not lock during construction, so 8 workers each built a model and the process segfaulted after one document. Pre-warm, serialize, `embedding_func_max_async=1`. Confirmed a runtime hazard, not just an indexing one.
- **The `--reload` query-time restart trap** (above).
- **Silent English extraction** without `addon_params={"language": "Thai"}`.
- **Silent stale graph** on re-inserting an edited note without `adelete_by_doc_id` first.
- **`enable_rerank=true` by default** with no reranker configured.

## Migration from the Chroma path ([#14](https://github.com/bright-arparwut/TTMAgent/issues/14))

Ruled here; **executed by the rollout effort**, not by this planning effort:

1. **TCM books archived, not deleted**: `tcm-basic-theory.jsonl`, `tcm-tongue-diagnosis.jsonl`, and both front-matter JSONLs move to `corpus/archive/` — kept for the thesis's digitization narrative, never ingested. `four-elements.jsonl` (+ front-matter) stays in place as a safety net until rollout completes, then is deleted (its verify-pass value was spent; its Markdown notes are its successor).
2. **`app/rag/vector_store.py` rewritten in place** — the seam keeps its module path, so the dispatcher call site and every test monkeypatch survive with zero import churn. `ingest.py` deleted (LightRAG owns ingestion); `embeddings.py` stays; `pdf_ocr.py` and `corpus_merge.py` deleted with their tests (the Markdown corpus was never produced by them; their successor is the agent transcription workflow plus `source_notes.py`).
3. **Chroma retires fully**: `data/chroma/` removed, its `.gitignore` line dropped, `langchain-chroma` leaves the dependencies, the `chroma_persist_dir` setting retires (`rag_top_k` already retired for the token knobs).
4. **Tests follow their modules**: `test_pdf_ocr.py` / `test_corpus_merge.py` / `test_ingest.py` deleted; `test_vector_store.py` rewritten alongside the in-place rewrite; the dispatcher tests monkeypatch the unchanged seam and survive untouched; `test_source_notes.py` lives on. `scripts/chat.py`'s `retrieve_passages` stub keeps working unchanged.
5. **`lightrag-hku` moves out of the `spike` dependency group** into the main dependencies.
6. **`CONTEXT.md`'s TTM Corpus entry is rewritten** — it still says Chroma, cites ADR 0008's paragraph provenance, and names a retired 中医 book as the corpus's one book.
7. **Preflight's graph checks go green** (they WARN until rollout) and rollout owes the `source_notes --check-index` staleness gate.
8. **`corpus/concepts/` and `corpus/graph.json` are generated for the first time** per the vault layout above.
9. **ADR 0008 keeps its Superseded-by header** and is otherwise untouched.

## Considered and rejected

- **MongoDB as the LightRAG backend** — `MongoVectorDBStorage` requires Atlas Search; local Mongo cannot back it. Defaults win.
- **`ainsert_custom_kg` with our own extraction pipeline** — zero LLM calls at insert, but gives up recovery, flattens provenance, and takes on merging/dedup/summarization. Rejected on quality-for-effort once the spike showed default extraction is good.
- **A hand-authored TTM ontology** — the discovered ontology came out coherent; the collapse risk dissolved when the Chinese books were dropped.
- **A per-turn retrieval-mode router, LLM query rewriting, Advisor-as-tool retrieval** — each costs latency or confounds the thesis arms; the last is deferred, not dead.
- **Hardening Tongue Description axes to Literal enums** — would re-block on every new transcription and push interpretation into the Describer against ADR 0001; measured landing shows free text reaches the graph.
- **A LightRAG sidecar process** — a second 986 MB embedding model to serve a 0.03 s in-process lookup.
- **`obsidian-neural-composer` as a runtime dependency** — an Obsidian plugin supervising a Python server; the portable part is LightRAG, adopted directly.
- **Committing `vdb_*.json`** — ~4.5 MB of near-incompressible history per re-index for something rebuildable in a minute for free.
- **LightRAG's `hf_embed` and its `R`/`V` chunkers** — mean-pooling is wrong for BGE-M3; the splitters are CJK-only.

## Open questions (deliberately not decided here)

Carried out of the map's fog as explicitly open — the implementation and evaluation efforts own them:

1. **How much weight the Advisor prompt gives LLM-synthesized graph descriptions.** Entity/relation descriptions are evidence the Advisor reads but cannot cite — the one input with no page behind it. Open whether the prompt ranks them below the verbatim sections ("use the graph to connect the sections, not to replace them") or trusts the model. The tongue book adds its own caveat: it warns tongue findings must combine with other examinations — that weighting belongs to the Advisor prompt, not the Tongue Description schema.
2. **Thesis evaluation design**: gold answers, the judge, and whether to score *answers* rather than retrieved sections — the spike measured retrieval only. Its 10-question set and section-recall metric are reusable, and the saturation objection is gone at 177 chunks; if saturation somehow survives, `top_k`/`chunk_top_k` tuning is the remaining lever, not another scan (the four-elements extension was retired out of scope — [#22](https://github.com/bright-arparwut/TTMAgent/issues/22)).
3. **ธาตุเจ้าเรือน as a graph entry point** — entering retrieval at the user's own element node rather than at their words. Interesting, not yet sharp; gated behind confirming `app/memory/element.py`'s provisional month-to-element map against the book, which is a separate effort (the book appears to contradict it).

## Consequences

- **Retrieval stops being free**: the current system makes zero LLM calls to retrieve; this design makes exactly one hosted call (KEYWORD) per LINE message — also the one place user text leaves the machine. Embeddings stay local, so the rest of the privacy property survives.
- The Advisor's context grows to ~10k tokens of retrieved material per turn — the price of whole-section evidence.
- The committed graph is a build artifact of a logged-in Claude session; anyone re-indexing without one pays direct-API prices, and swapping the extract model silently invalidates the spike's quality evidence unless re-baselined.
- Corpus edits are no longer upserts (ADR 0008's deterministic-ID property is lost): every edit is a delete-and-re-insert, policed by the staleness gate, with the graph diff instruments (`corpus/concepts/`, `spike/results/graph-summary.json`) as the quality check.
- The runtime is bound to the owner's Mac by BGE-M3-on-MPS; that is stated scope, not an accident.
- The thesis comparison (`naive` vs `mix`) rides the same infrastructure with one config change, so it stays cheap to run and hard to confound.
- No remedy answer for a user's own ธาตุเจ้าเรือน can be grounded in book one — its remedy half (printed pp. 50–68) was never scanned and its transcription was ruled out of scope; corpus content, not architecture.
