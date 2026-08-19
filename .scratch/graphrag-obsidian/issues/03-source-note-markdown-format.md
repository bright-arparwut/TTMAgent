# 03 — The Source-note Markdown format

Status: in-progress
Type: wayfinder:grilling
Map: ../MAP.md
Blocked by: none
Assignee: Bright Arparwut (claimed 2026-08-19)

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

## Comments
