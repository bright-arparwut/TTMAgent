# Research: moving the TTM corpus to Graph RAG, curated in Obsidian

**Date:** 2026-08-19
**Status:** Research only — no decision taken, no code changed. Written to answer
the owner's question "how can I move to graph RAG using Obsidian with this project?"

## The question, restated

Today `retrieve_passages` does one dense top-5 similarity search over a flat
Chroma collection of 1,862 paragraph chunks (`app/rag/vector_store.py`). The
owner asked whether this should become a Graph RAG system whose knowledge graph
is authored and maintained in Obsidian.

## Answer in one paragraph

**Yes to a graph, no to "GraphRAG" as the term is usually sold, and Obsidian is
the right tool for the wrong-sounding reason.** Running Microsoft GraphRAG (or
LightRAG) over this corpus would be a mistake: the corpus is far below the size
where automatic entity extraction plus community summarization pays off, and its
LLM-extracted entities would quietly break the citation contract that ADR 0008
and ADR 0009 exist to protect. But the *queries* this bot answers really are
graph-shaped — tongue sign → syndrome → ธาตุ → advice is a three-to-four-hop
traversal that no single paragraph contains — and the highest-value fix is a
**small, hand-curated TTM ontology layered on top of the existing corpus, never
replacing it**. Obsidian's contribution is not retrieval; it is the authoring,
verification and visualization surface for that ontology. That distinction is
the whole design.

## Part 1 — What Obsidian actually is, stated plainly

Obsidian is a Markdown editor over a folder. Its "graph" is the link graph
induced by `[[wikilinks]]`, plus whatever YAML frontmatter you write. There is
no database, no query engine, no embedding, no traversal API that a Python
process can call.

Practically, this means:

- **Obsidian contributes nothing at runtime.** The LINE webhook will never talk
  to Obsidian. Parsing a vault into nodes and edges is roughly 150 lines of
  Python (`re` for `[[...]]`, a YAML parse for frontmatter) — every published
  "Obsidian GraphRAG" project does exactly this and no more.
- **The Local REST API plugin exists** and now ships an MCP server on
  `https://127.0.0.1:27124/mcp/`, which is genuinely useful — but for *an agent
  helping the owner edit the vault*, not for serving LINE traffic.
- **What Obsidian actually buys is human throughput on curation**: backlinks,
  local graph view, aliases, unresolved-link detection, and instant navigation
  while a person reads a TTM book and writes down what it says.

So the honest framing is: the deliverable is *a plaintext knowledge graph in the
repo*. Obsidian is the IDE for it. That is not a downgrade — for a thesis it is
the point, because the graph stays greppable, diffable in git, reviewable by a
TTM domain expert who is not a programmer, and screenshot-able for the thesis
book.

## Part 2 — Why generic GraphRAG is wrong for this corpus

Real numbers from `corpus/*.jsonl` (body files, front matter excluded), measured
on 2026-08-19:

| | |
|---|---|
| Paragraph records | 1,862 |
| Characters | 329,401 |
| Distinct printed pages | 266 (92 + 142 + 32) |
| Rough token count | ~165K |

The corpus is **266 printed pages**. The whole thing fits inside a single Gemini
2.5 Flash context window with room to spare.

Against that, the practitioner consensus on graph RAG is consistent: the
threshold where graph construction pays for itself is around 500–2,000 pages
minimum, graph indexing costs 10–40× more than plain embedding, and below that
line the graph mostly adds cost and dilutes precision by pulling in large
neighborhoods of loosely-related entities. GraphRAG-Bench puts it bluntly:
GraphRAG "frequently underperforms vanilla RAG on many real-world tasks."

Concretely for this project:

- **Microsoft GraphRAG** — entity extraction + Leiden community detection +
  hierarchical community summaries. Designed for "what are the themes across the
  corpus" questions. This bot never asks those. Indexing a 500-page corpus runs
  $50–200. Rejected.
- **LightRAG** — much cheaper (~$0.15 vs $4–7 for the same documents),
  incremental updates without rebuilding, and it already recommends `BAAI/bge-m3`,
  which is the exact embedding model in `app/config.py`. Not rejected outright:
  it is the natural **baseline arm** to benchmark a curated graph against
  (see Part 6). But its entities are LLM-extracted, so it inherits the problem
  below.

### The disqualifying problem: entity resolution vs. the citation contract

Automatic extraction fails on identity. The canonical failure is a medical KG
that produced three separate nodes for "Type 2 Diabetes", "T2D", and the same
patient written two ways.

This corpus is a *worse* case than English medical text, for reasons ADR 0008
already documents:

- Terms are **Thai transliterations of Chinese** — ลมปราณหยวน / หยวนชี่ / 元气 are
  one concept in three surface forms across three books.
- ADR 0008 states outright that "OCR uncertainty concentrates in tone marks of
  Thai transliterations of Chinese terms." An extractor keying on surface strings
  will split a concept on an OCR tone-mark error.
- The pain-points doc already found the same string repeated as its own chunk —
  "1. การสร้าง" ×6, "3. หน้าที่ทางสรีรวิทยา" ×4 — headings that mean something
  different under each parent. An extractor has no way to tell those apart.

And the contract that would break: ADR 0008 makes the printed page number the
citation authority, ADR 0009 renders it as a Flex footer, and the Advisor's
system prompt says "Cite only tags actually provided — never invent a book, page,
or paragraph number." An LLM-generated entity summary has **no printed page**.
The moment retrieval returns graph-generated prose instead of book paragraphs,
either the citation is fabricated or it disappears. Both are thesis-fatal for a
health advisor.

**This constraint drives the entire proposed design: the graph may decide *what*
to retrieve; it must never be *what is retrieved*.**

## Part 3 — Why a graph is nonetheless the right answer here

The same literature that says "don't bother below 500 pages" names the
exceptions, and this project hits them:

1. **Multi-hop diagnostic flows.** OpenTCM names the exact path shape:
   `symptom → syndrome → treatment → ingredient`. This bot's path is
   `tongue sign → syndrome → ธาตุ → advice`. No single paragraph in
   `tcm-tongue-diagnosis.jsonl` contains that chain; the books assume the reader
   already holds the ontology in their head.
2. **Citation accuracy as a hard requirement.** Named as a graph-RAG
   justification for regulated/health domains — and it is already a written
   contract here (ADR 0008/0009).
3. **There is already a graph node in the running system.** The Health Profile
   derives ธาตุเจ้าเรือน from the user's birth date (`app/memory/element.py`).
   That is a typed entity the Advisor holds every single turn, with no edges to
   anything in the corpus. Today it is a string in a prompt. In a graph it is an
   entry point.

And critically, **the project's own pain-points analysis is already describing a
graph problem in vector-RAG vocabulary.** Pain point 2 — a bullet under
"ก. ลมปราณหยวน > 3. หน้าที่ทางสรีรวิทยา" that never says the words
"ลมปราณหยวน", so it cannot be retrieved by a question that does — is a *missing
edge*, not a bad embedding. Proposal 2 (prepend `heading_path` before embedding)
is a one-hop graph traversal flattened into a string. It works, and it should be
done regardless. But it stops at one hop and only ever walks *up* the section
tree.

### The near-exact precedent

**OpenTCM** (arXiv 2504.20118) is the same domain, one step larger: 68 classical
Chinese TCM gynecology books, 3.73M characters → 48,406 entities across 152,754
relationships in 10 relation types. Method: LLM extraction with role-based
prompts producing structured JSON, then **review and correction by experienced
TCM practitioners**. Result: 98.55% precision / 99.60% recall on 1,795 sampled
triples judged by 5 domain experts, and it beats GPT-4o on both ingredient
retrieval (89.6% vs 84.3%) and diagnostic Q&A (75.1% vs 69.0%).

Two things to take from it: the entity/relation schema is a good starting
template, and **the human verification pass is not optional** — it is where the
98.55% comes from.

**MedGraphRAG** (arXiv 2408.04187) contributes the other half: a three-tier graph
linking user documents → credible medical sources → controlled vocabularies,
built specifically so responses carry "credible source documentation and
definitions." Evidence traceability as an architectural tier, not an
afterthought. That is the same instinct as the layer separation proposed below.

Supporting this, a 2026 comparison of KG construction strategies found that
**ontology-guided KGs that retain chunk information substantially outperform
vector retrieval baselines**, and that a one-time ontology design costs less in
LLM spend than repeated text-driven extraction.

## Part 4 — Proposed architecture: four layers, one invariant

**The invariant: citations always come from `corpus/*.jsonl`, never from the
graph.** The graph is a routing index over paragraph IDs that already exist.

```
Layer 0  corpus/*.jsonl              UNCHANGED. ADR 0008. Citation authority.
                                     book_id / book_title / page / paragraph.
              ▲ every concept note points down into these IDs
              │
Layer 1  kb/ (Obsidian vault)        One Markdown note per TTM concept.
                                     Frontmatter: id, type, aliases, sources[].
                                     Body: prose + typed [[wikilinks]].
                                     Committed to git. Human-curated.
              │ build step (~150 lines, no new service)
              ▼
Layer 2  networkx graph + Chroma     Concept notes embedded into a SECOND
         collection `ttm_concepts`   collection. Graph held in memory.
              │
              ▼
Layer 3  retrieve_passages()         hybrid seed → graph expand → resolve to
                                     Layer 0 paragraphs → return with the
                                     existing [ชื่อตำรา หน้า X ย่อหน้าที่ Y] tags.
```

At no point does a graph-generated sentence reach the Advisor. `_format_passage`
in `app/rag/vector_store.py` keeps working exactly as written, and ADR 0009's
Flex footer keeps rendering real printed page numbers.

### Layer 1: the vault note format

One note per concept, e.g. `kb/ลมปราณหยวน.md`:

```markdown
---
id: qi-yuan
type: concept          # concept | sign | syndrome | element | organ | advice
aliases: [หยวนชี่, ลมปราณหยวน, 元气]
sources:
  - tcm-basic-theory:p90:para10   # ลมปราณที่สำคัญที่สุดในร่างกาย
  - tcm-basic-theory:p90:para12   # เปลี่ยนแปลงมาจากสารจำเป็น ... เก็บสะสมในไต
  - tcm-basic-theory:p91:para5    # the orphan bullet from pain point 2
---

ลมปราณพื้นฐานที่ติดตัวมาแต่กำเนิด เก็บไว้ที่ไต ...

## หน้าที่
- สร้างความอบอุ่นและกระตุ้นการทำงานของอวัยวะ

## สัมพันธ์กับ
- [[ธาตุน้ำ]]
- [[ไต]]

## แสดงถึง
- [[ลิ้นซีด]]
```

Three things this format does that matter:

1. **`aliases` solves entity resolution by construction.** ลมปราณหยวน, หยวนชี่ and
   元气 are one node because a human said so, not because a cosine similarity
   guessed so. Obsidian's alias autocomplete makes wikilinks resolve to the
   canonical note while typing. This is the single strongest argument for
   curating in Obsidian rather than extracting.
2. **`sources` are exactly the chunk IDs `app/rag/ingest.py` already mints**
   (`<book_id>:p<page>:para<paragraph>`). No new identifier scheme, and a
   validator can assert every one resolves — a *test* that the graph is grounded.
3. **`##` headings become typed edges.** `## แสดงถึง` under a syndrome yields
   `(syndrome) --แสดงถึง--> (sign)`. Typed traversal without asking a
   non-programmer to write RDF.
4. **Junk chunks become node names instead of competing vectors.** The heading
   `tcm-basic-theory:p90:para9` is the bare string "ก. ลมปราณหยวน" — one of the
   240 junk chunks currently holding its own vector in Chroma and eating a
   top-5 seat. In the vault it is the note's *title*, and the orphan bullet at
   `p91:para5` that never names its own topic becomes reachable through it.
   Pain points 2 and 3 dissolve into the same structure.

(The chunk IDs above are real — all three resolve in
`corpus/tcm-basic-theory.jsonl`.)

### Layer 3: the retrieval algorithm

Replacing the single `asimilarity_search` call:

1. **Seed** — hybrid retrieval (dense + BM25, i.e. pain-point proposals 4 and 5)
   over `ttm_concepts` → top ~5 concept notes.
2. **Inject** — if the Health Profile has a ธาตุเจ้าเรือน, add that element node
   as a free seed. This is the piece that is impossible today.
3. **Expand** — walk 1–2 typed hops. Depth and allowed edge types are config,
   so the traversal is an ablation knob, not a rewrite.
4. **Resolve** — union the `sources` of every reached concept → a set of Layer 0
   chunk IDs.
5. **Fetch and rank** — pull those exact paragraphs from Chroma by ID, rerank
   with a cross-encoder against the query (pain-point proposal 4), take top-k.
6. **Return** — through the unchanged `_format_passage`, with real page tags.

Step 5 is where graph recall gets traded back for precision, which is the
documented failure mode of graph RAG (over-broad neighborhoods). The reranker is
the defense, and it is already on the pain-points roadmap.

## Part 5 — How this relates to the six pain points

The pain-points doc is not superseded by this. **Proposals 1–6 are prerequisites,
not alternatives**, and one of them changes character:

| Proposal | Relationship to the graph plan |
|---|---|
| 1 — add `kind` + `heading_path` to the OCR schema | **Promoted to top priority.** `heading_path` is the section tree, which is the skeleton the concept graph hangs off, and `kind` tells the vault bootstrapper which paragraphs are headings vs. body. Ranked last in the doc because it needs a re-OCR; under this plan the re-OCR pays for two things at once. |
| 2 — embed `heading_path + text` | Do it now. It is a cheap one-hop approximation and stays useful as the vector baseline arm. |
| 3 — merge junk heading chunks into the following body | Do it now. 240 junk vectors (12.9%) also become 240 junk *nodes* otherwise. |
| 4 — cross-encoder reranker | **Becomes load-bearing.** It is the precision defense on graph-expanded candidate sets. |
| 5 — hybrid dense + sparse from BGE-M3 | Becomes the seed step. Highest value on rare transliterated terms — exactly the concept names that seed traversal. |
| 6 — assert embeddings are unit length | Unchanged, one line, do it today. |

**Sequencing: proposals 3, 6, 2, 4, 5 first; then 1 with a re-OCR; then the
vault.** Anything else builds a graph on top of a corpus with 240 junk records
and no section tree.

## Part 6 — Phased plan and honest effort

| Phase | Work | Effort | Risk |
|---|---|---|---|
| 0 | Pain-point proposals 3, 6, 2 — ingest-side fixes, re-ingest | ~1 day | none |
| 1 | Proposals 4 + 5 — reranker + hybrid retrieval in `retrieve_passages` | ~2–3 days | new dependency, latency budget on LINE |
| 2 | Proposal 1 — `kind` + `heading_path` in `PageTranscription`, re-OCR all 3 books | ~2–3 days wall clock, mostly machine | OCR regression; mitigate by diffing against current JSONL |
| 3 | Ontology design — decide entity types and relation types. Start from OpenTCM's 10 relations, cut to what these 3 books support | ~1 day, needs the owner | scope creep; cap the type list |
| 4 | Bootstrap the vault — LLM drafts concept notes from the corpus (Gemini slot already available), one note per candidate concept, `sources` filled from chunk IDs | ~1 day machine | drafts will be wrong; that is expected |
| 5 | **Human verification pass in Obsidian** — the OpenTCM lesson. Merge duplicate concepts, fix aliases, delete junk, correct edges | **~1–2 weeks, the real cost** | this is the thesis contribution; do not shortcut it |
| 6 | Build step + `retrieve_passages` graph path, behind a config flag | ~3–4 days | none if the flag defaults off |
| 7 | Evaluation | ~3–4 days | needs a question set built first |

Phase 5 is the honest answer to "how hard is this." Everything else is
straightforward engineering. A realistic target is **150–300 concept nodes** —
small enough to verify by hand, large enough to cover three books, and directly
comparable to OpenTCM's methodology at a scale one person can defend.

Also note: Chroma stays. networkx holds a 300-node graph in memory without
noticing. **No Neo4j, no new Docker service** — which matters for a project whose
ADRs deliberately chose embedded Chroma over a hosted vector service.

## Part 7 — Thesis framing

This slots into the ablation pattern the codebase already uses
(`advisor_history_max_turns: 0` disables replay, `health_profile_enabled: False`
disables the profile). Add `rag_mode` with four arms:

| Arm | Description |
|---|---|
| `dense` | today's baseline — flat top-5 dense |
| `hybrid` | + heading paths, hybrid seeds, reranker (pain-point fixes only) |
| `graph` | curated ontology + traversal (the proposal) |
| `lightrag` | LightRAG auto-extracted graph, same BGE-M3 embeddings (optional but strong) |

That fourth arm is what makes the thesis argument rather than an assertion: it
directly tests "does hand-curated beat auto-extracted on a small
Thai/Chinese-transliterated corpus?" Given the entity-resolution analysis in
Part 2, there is a real, defensible hypothesis with a plausible mechanism —
which is worth far more than a system that merely works.

Metrics: retrieval recall against a hand-built question set,
**citation validity rate** (does every cited page/paragraph actually exist and
actually support the claim — this is the one the health domain demands), and
answer quality scored by a TTM practitioner, following OpenTCM's expert-rating
design.

## Part 8 — Considered and rejected

- **Microsoft GraphRAG.** Built for global thematic queries over large corpora;
  266 pages is far under its break-even; community summaries have no printed page
  number and cannot be cited.
- **Neo4j / a graph database.** ~300 nodes. `networkx` is enough. Adding a
  service contradicts the embedded-Chroma reasoning already in the ADRs.
- **Obsidian as a runtime dependency** (Local REST API in the request path).
  Would put a desktop app in a LINE webhook's critical path. The vault is a
  build-time source; the build output is what production reads.
- **Replacing `corpus/*.jsonl` with the vault.** Breaks ADR 0008 outright. The
  corpus is the citation authority and must remain a faithful transcription;
  the vault is interpretation layered on top and must be separately auditable.
- **Just stuffing the whole corpus in context.** ~165K tokens fits in Gemini 2.5
  Flash, and this genuinely deserves to be measured as a control arm. Rejected as
  the production path: per-turn cost and latency on every LINE message, and it
  makes precise citation *harder*, not easier — the model must locate the page
  itself rather than being handed a tagged passage.

## Open questions for the owner

1. **Is the re-OCR (phase 2) acceptable?** It gates the clean version of this.
   Doing the vault without `heading_path` is possible but noticeably worse.
2. **Is there a TTM domain expert available to review the ontology?** OpenTCM's
   numbers come from practitioner review. If the answer is "only the owner," the
   thesis should say so plainly as a limitation.
3. **How many concepts?** 150–300 is the recommendation. Fewer is not worth the
   machinery; many more is not verifiable by one person.
4. **Should the LightRAG arm be built?** It roughly doubles the evaluation work
   and roughly doubles the strength of the thesis claim.

## Sources

- [OpenTCM: A GraphRAG-Empowered LLM-based System for TCM Knowledge Retrieval and Diagnosis](https://arxiv.org/html/2504.20118v2)
- [Medical Graph RAG: Towards Safe Medical LLM via Graph RAG](https://arxiv.org/abs/2408.04187)
- [When to use Graphs in RAG (GraphRAG-Bench)](https://arxiv.org/abs/2506.05690)
- [Ontology Learning and Knowledge Graph Construction: Comparison of Approaches and Impact on RAG Performance](https://arxiv.org/pdf/2511.05991)
- [LightRAG (HKUDS)](https://github.com/HKUDS/LightRAG) · [paper](https://arxiv.org/html/2410.05779v1)
- [Do You Really Need GraphRAG? A Practitioner's Guide Beyond the Hype](https://towardsdatascience.com/do-you-really-need-graphrag-a-practitioners-guide-beyond-the-hype/)
- [Graph RAG in 2026: What Works in Production](https://www.paperclipped.de/en/blog/graph-rag-production/)
- [Obsidian Local REST API (with MCP server)](https://github.com/coddingtonbear/obsidian-local-rest-api)
- [Kwipu — local Graph RAG over Obsidian vaults](https://github.com/benmaster82/Kwipu)
- [Obsidian_RAG_System — wikilink graph expansion + hybrid retrieval](https://github.com/dario-marcolin/Obsidian_RAG_System)
- [AppHerb: Language Model for Recommending Traditional Thai Medicine](https://doi.org/10.3390/ai6080170)
