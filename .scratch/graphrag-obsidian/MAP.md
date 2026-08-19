# GraphRAG for TTMAgent, via an Obsidian vault

Label: `wayfinder:map`
Charted: 2026-08-19

## Destination

A decided, written GraphRAG architecture for TTMAgent — ontology approach, engine,
storage, vault generation, retrieval seam, and citation contract — validated by a
working spike over the re-OCR'd `four-elements` book, ready to hand to an
implementation plan.

Done means: an ADR (superseding 0008) that an implementer could build from without
asking another design question, plus spike evidence about how LightRAG's graph
retrieval compares to flat dense retrieval on Thai TTM text.

This map **plans**. It does not roll GraphRAG into production; that is a separate
effort begun from the ADR this map produces. The one exception is ticket 06
(re-OCR), which is a `task` — it exists because the spike cannot run without it.

## Notes

**Domain**: Thai Traditional Medicine (แพทย์แผนไทย). Read `CONTEXT.md` for the
ubiquitous language before working any ticket — the terms Assessment, TTM Corpus,
Advisor Model, Consultation are load-bearing and have deliberate _Avoid_ lists.

**Skills every session should consult**: `mattpocock-skills:grilling` and
`mattpocock-skills:domain-modeling` for the `grilling` tickets;
`mattpocock-skills:research` for the `research` tickets;
`mattpocock-skills:prototype` for ticket 07.

**Thesis constraint**: the objective is "GraphRAG replaces vector RAG". This is
settled and is not to be re-litigated. It does mean the thesis needs a defensible
comparison, which is why the engine choice deliberately keeps `naive` mode
available as a same-infrastructure baseline.

**Copyright constraint** (from `CONTEXT.md`): corpus text is copyrighted and
committed only because this repo is private. The vault lives **inside the repo**.
It must never be placed in `~/Documents/Obsidian Vault` or any folder on Obsidian
Sync / iCloud, which would copy the book to a third-party server.

**Blast radius**: `retrieve_passages` has exactly one caller —
`app/pipeline/dispatcher.py:237` — so the runtime swap is one function. Design
freely behind that seam.

**Retrieval stops being free**: LightRAG configures four LLM roles independently —
`EXTRACT` (index time), `KEYWORDS` and `QUERY` (**every** query), and `VLM`. The
current system makes zero LLM calls to retrieve; GraphRAG adds at least one per LINE
message. `EXTRACT` is a batch job and can run on any backend, including Claude Code
headless; `KEYWORDS`/`QUERY` are in the request path and cannot. See tickets 02 and 09.

## Decisions so far

<!-- one line per closed ticket; the detail lives in the ticket -->

- [01 — Can local MongoDB actually back LightRAG?](issues/01-mongo-as-lightrag-backend.md)
  — No: `MongoVectorDBStorage` requires Atlas Search. LightRAG runs on its **defaults**
  instead (JsonKV + NanoVectorDB + NetworkX + JsonDocStatus), all file-persisted in the
  repo — core deps of `lightrag-hku`, zero services, swappable per-store later.

### Settled during charting, before any ticket existed

- **Thesis objective** — GraphRAG replaces vector RAG. Not a go/no-go; the map
  assumes graph retrieval is happening.
- **Map scope** — spec plus a one-book spike. No production rollout here.
- **Ontology** — LLM-discovered entity and relation types, no hand-authored schema
  (LightRAG's default). Chosen over a constrained TTM schema; the ontology-collapse
  risk that argued against it dissolved when the Chinese books were dropped.
- **Pipeline direction** — sources → extraction → graph → generated concept notes.
  Obsidian is a **view over** the graph, never a runtime dependency: TTMAgent is a
  headless FastAPI webhook and cannot require a desktop GUI to answer a LINE message.
- **Note grain** — two note types. Source notes (one per book section) and Concept
  notes (one per extracted entity), wikilinked. Maps 1:1 onto GraphRAG's
  chunks + entities, so the vault and the engine agree on what a node is.
- **Source format** — **Markdown is the source of truth; JSONL is retired.** OCR
  writes `.md` per section with frontmatter (`book_id`, `book_title`, page range)
  and inline `<!-- p.N -->` markers. This solves corpus pain points #1 (`kind`) and
  #2 (`heading_path`) by format rather than by schema, and reuses the
  `MarkdownHeaderTextSplitter` path `app/rag/ingest.py` already has.
- **Engine** — LightRAG (`lightrag-hku`), `mix` query mode (entity + relation +
  dense, merged). This is `obsidian-neural-composer`'s engine with the Obsidian
  plugin layer removed. _(The MongoDB backend chosen here was superseded by
  ticket 01 — see Decisions so far.)_
- **Baseline** — LightRAG `naive` vs `mix`: same corpus, same embeddings, same code,
  one parameter changed. The thesis comparison comes free rather than needing a
  separate rig.
- **Corpus** — Thai only. `tcm-basic-theory` and `tcm-tongue-diagnosis` (1,701 of
  1,862 body chunks, both 中医 rather than แพทย์แผนไทย) are dropped.
  `four-elements` (39pp) is re-OCR'd to Markdown. The 100-page Thai tongue-analysis
  book joins on delivery.

## Not yet specified

<!-- in-scope fog: real, but not sharp enough to ticket -->

- **Thesis evaluation design** — the question set, gold answers, and who or what
  judges `naive` vs `mix`. Ticket 07 produces a rough ~10-question comparison; a
  defensible evaluation is a bigger thing. Sharpens once 07 shows what the two modes
  actually differ on, and once book two is in the corpus (39 pages is thin evidence).
- **Book two: the 100-page Thai tongue-analysis text** — digitization, and whether
  the Markdown format decided in ticket 03 survives contact with it. Blocked on
  delivery; not yet in hand.
- **`TongueDescription` schema finalization** — `app/models/schemas.py:35` documents
  its fields as *"a placeholder pending the TTM textbook's tongue-inspection
  categories"*. Book two is that textbook. Blocked on the same delivery.
- **ธาตุเจ้าเรือน as a graph entry point** — `app/memory/element.py` already derives
  the user's element from their birth date, and the Health Profile carries it. A
  graph makes it possible to enter retrieval at the user's own element node rather
  than at their words. Genuinely interesting, not yet a sharp question.
- **Deployment shape** — LightRAG in-process in FastAPI vs a sidecar; cold-start
  cost of loading the graph; when and how the index rebuilds on deploy. Sharpened by
  ticket 01: with file-persisted storage the graph is a directory that has to be
  built, versioned, and shipped alongside the code — not a database the app connects
  to. Whether that directory is committed, gitignored, or rebuilt on deploy is the
  question this fog will graduate into.

## Out of scope

<!-- ruled beyond the destination; never graduates -->

- **`obsidian-neural-composer` as a runtime dependency.** Reviewed at charting: it
  is an Obsidian plugin (TypeScript) that supervises a local Python LightRAG server.
  The portable part is LightRAG, which this map adopts directly. A LINE webhook
  cannot depend on a running desktop GUI. The repo stays useful as documentation of
  LightRAG's configuration surface.
- **The six Chroma retrieval fixes** in `docs/corpus-embedding-painpoints.html`
  (junk-chunk merging, cross-encoder reranker, `heading_path` embedding, hybrid
  sparse+dense, normalization test). Superseded — Chroma is being replaced, and
  LightRAG owns retrieval. Pain points #1 and #2 are solved by the Markdown format
  decision instead. Worth re-reading only if ticket 01 forces a retreat from LightRAG.
- **A hand-authored TTM ontology.** Considered and decided against; entity types are
  LLM-discovered.
- **Production rollout of GraphRAG.** A separate effort, begun from this map's ADR.

## Tickets

Child tickets live in `issues/`. Open tickets are the files whose `Status:` is not
`closed`; the frontier is those with `Blocked by: none`. Blocking edges are recorded
in each ticket's header, not here — this map is an index, not a store.
