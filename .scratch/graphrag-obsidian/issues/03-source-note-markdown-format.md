# 03 — The Source-note Markdown format

Status: closed
Type: wayfinder:grilling
Map: ../MAP.md
Blocked by: none
Assignee: Bright Arparwut
Resolved: 2026-08-19

## Question

Markdown is now the corpus source of truth (JSONL retired). Pin the exact format
OCR writes, because ticket 06 transcribes against it and it cannot cheaply change
afterwards.

- **File granularity** — one `.md` per section, per chapter, or per book? Section
  was the intent, but "section" needs defining against this book's actual structure.
- **Frontmatter fields** — `book_id`, `book_title`, page range, and what else?
  Does a section note need a stable id for wikilinking from Concept notes?
- **Page markers** — `<!-- p.15 -->` inline was the sketch. Where exactly do they
  go (start of the page's first paragraph?), and how does a chunk spanning a page
  break get cited?
- **Heading depth** — `#`/`##`/`###` maps to `chapter`/`section`/`subsection` in
  `app/rag/ingest.py`. Does this book have deeper nesting?
- **Figure and table content** — the old corpus turned diagram labels into
  content-free chunks (pain point #3: "ไม้ น้ำ ไฟ | โลหะ ดิน"). What happens to them
  now: dropped, kept as captions, or converted to Markdown tables?
- **Validator rules** — what makes a source note invalid? (frontmatter present,
  page markers monotonic, no empty sections...)
- **Faithful transcription** — ADR 0008 kept the book's own typos deliberately.
  Does that survive into the Markdown format?

## Why it matters

Blocks the re-OCR. Also quietly decides Source-note granularity, which decides how
big a retrieved chunk is, which decides retrieval quality.

## Resolution (2026-08-19)

**One `.md` per level-2 section, and the filename is the citation.**

### The fact that drove everything

In LightRAG, `file_paths=` is the citation carrier — it comes back as
`references[].file_path`. And `ainsert()` *always* fixed-token chunks, so Markdown
structure is ignored: headings and page markers survive only as literal text inside
a chunk, never as metadata. Structure-aware chunking (`R`, `P`) exists but only via
`apipeline_enqueue_documents(process_options=…)`, and `P` needs a `.blocks.jsonl`
sidecar we will not have, so it silently degrades to `R`.

Consequence: **the file is the citation unit**, and YAML frontmatter reaches
**chunk 1 only**. The filename is the one carrier attached to every chunk.

### The format

**Granularity** — one source note per level-2 section. Each chapter's lead prose
(the text before its first `##`) becomes its own note; `บทนำ` is a chapter whose
only note is its opener. ~20 notes for the scanned range. Measured: 23 sections,
median 1,787 chars ≈ 1,680 tokens, whole scanned body 42,539 tokens.

**Filename** — `corpus/<book_id>/<NN>-<section title>-น.<start>-<end>.md`, e.g.
`corpus/four-elements/03-ราศีและการบำบัด-น.19-22.md`. Directory per `book_id`;
zero-padded ordinal for book order; Thai title (the Obsidian note title and
wikilink target); page range in the name so every citation is self-sufficient.
A `corpus/books.yaml` maps `book_id → book_title`, because ADR 0008's citation
names the title, not the slug.

**Frontmatter**

```yaml
---
uid: four-elements-03
type: source-note
book_id: four-elements
chapter: ประวัติศาสตร์และการใช้วิธีการบำบัดด้วยธาตุทั้งสี่
section: ราศีและการบำบัด
pages: [19, 22]
pdf_pages: [14, 17]
---
```

`uid` is passed as LightRAG's `ids=`, so correcting a misread page number renames
the file **without churning the graph** — Obsidian fixes the wikilinks, the uid holds
the document identity steady. `type` keeps generated concept notes (ticket 08) from
being re-ingested as sources — corpus pain point #2 solved at note level.
`chapter` is the `heading_path` fix; it serves the vault, validator, and
concept-note generation, not per-chunk retrieval (chapter linkage at retrieval time
is the graph's job). No `book_title` — it lives once in `books.yaml`.

**Body** — no `#`/`##` repeating the note's own title (Obsidian treats the filename
as the title). Subsections inside a note start at `##`. The file boundary now carries
what `#`/`##`/`###` used to, so heading depth inside a file stays shallow.

**Page markers** — `<!-- p.19 -->` HTML comments at the **exact** page-break point,
even mid-word: `...จะร่วมใช้โหรา<!-- p.18 -->ศาสตร์เพื่อ...` (`โหราศาสตร์` really is
cut across p17/p18). Invisible in Obsidian reading view. Markers mark *transitions*
only — a note spanning 19–22 carries markers for 20, 21, 22 and none for 19.
Measured cost: ~32 markers ≈ 256 tokens against 42,539 = **0.6% dilution**.

**Tables** — real Markdown tables, reunified across page breaks with the reprinted
header row dropped (a printing artifact, same category as a reunified paragraph).
A page marker inside a table goes in the last cell of the last row printed on the
earlier page, because an HTML comment on its own line breaks the table:

```markdown
| Cancer | ♋ | ราศีกรกฎ | หน้าอก, ท้อง <!-- p.21 --> |
```

Under GraphRAG tables invert from junk to the densest signal in the book — a row like
`ราศีเมษ → ศีรษะ, หน้า, ตา, จมูก, หู` is exactly the relation EXTRACT wants. Note
that nothing protects a table from being cut mid-grid (`P` is unavailable), so a
table must be small enough to fit a chunk.

**Captions and labels** — a short line that repeats above a table is a **caption**,
not a heading: `**bold**`, never `##`. This is the `การแสดงออก (modalities)` trap —
it appears three times on p42–43 as a table caption, indistinguishable from a heading
by length. Bare diagram labels (`ไม้ น้ำ ไฟ | โลหะ ดิน`) are **dropped**; under
GraphRAG they would extract garbage entities, not merely waste a vector. A printed
caption is kept as `> **ภาพ:** …`.

**Faithful transcription** — ADR 0008's rule stands, with one narrow exception.
A typo'd **domain term** is corrected in the body with the original preserved inline:
`อุณหภูมิ<!-- sic: อุณภูมิ -->`. Reason: BGE-M3 embedded `อุณภูมิ` and `อุณหภูมิ`
almost identically, so the typo was harmless — but LightRAG's EXTRACT creates an
**entity named after the typo** that never merges with the correct one, splitting a
node in two. Incidental typos in ordinary prose stay as printed. The inline-Chinese
exception is unchanged. This is the weakest link in the format: "is this a domain
term" is a human judgment the validator cannot check.

### Validator

**Errors** (block ingest):

1. Frontmatter parses; `uid`, `type`, `book_id`, `chapter`, `section`, `pages`,
   `pdf_pages` present and correctly typed.
2. `uid` unique corpus-wide; `book_id` matches parent directory and exists in
   `books.yaml`.
3. Filename agrees with frontmatter on ordinal, section title, and page range.
4. Filename is **NFC**-normalized (macOS stores NFD; Thai combining vowels and tone
   marks round-trip badly to git/CI otherwise).
5. `pages[0] <= pages[1]`; ordinals ascending within a book; ranges never move
   backwards. **Not** non-overlapping — `ธาตุทั้งสี่` and `ราศีและการบำบัด` both
   start on p19, correctly.
6. Markers strictly ascending, each within the declared range, transitions only.
7. No `#` H1 in body; subsections start at `##`.
8. Every table has a header row and consistent column count.
9. `<!-- sic: … -->` well-formed.

**Warnings** (human decides, pipeline continues — ticket 06 runs unattended):

10. Body under ~200 chars — the "empty section" case, and the shape junk chunks took.
11. Every dropped bare-label run, listed verbatim, so the drop rule can be overruled.
12. Any short line above a table read as a caption — where a heading gets silently
    demoted.
13. Gaps in page coverage across a book's notes.

### Scope findings

The scan is **39 PDF pages covering printed 1–43**; the book is 200 pages with prose
to p76. So it holds ~4 of 7 chapters and ends mid-chapter. **Decision: re-OCR the
39-page scan as-is, do not re-scan now** — ticket 07 compares `naive` against `mix`
on the *same* text, so the comparison is valid on a partial book, and re-scanning
delays the spike to improve a variable it is not measuring.

Two findings recorded on the map rather than actioned: pp.77–199 (the birth-date
lookup table) are **out of scope**, and `app/memory/element.py`'s provisional
month→element mapping appears **contradicted** by the book — see the map's
Out of scope section.

## Comments
