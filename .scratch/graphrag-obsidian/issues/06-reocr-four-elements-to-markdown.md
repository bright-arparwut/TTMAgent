# 06 — Re-OCR four-elements (39pp) to Markdown

Status: ready-for-agent
Type: wayfinder:task
Map: ../MAP.md
Blocked by: 03

## Question

Nothing to decide — this is the manual work the spike cannot start without.

Transcribe `วิถีแห่งธรรมชาติกับธาตุทั้งสี่` (อนุสรณ์ วรมงคล, 39 PDF pages,
printed pages 12–43) into the Markdown format decided in ticket 03.

Source PDF: the owner's Google Drive, `วิถีธรรมชาติกับธาตุทั้งสี่.pdf`
(39 MB, file id `1qI9ZZ5iY5DvYGpXLFTfv1rs_EhamRfB4`). Fetch a local copy first —
do not depend on Drive at build time.

Prior art to reuse, not repeat: `docs/superpowers/plans/2026-07-30-two-book-corpus-digitization.md`
already describes the working pipeline — render pages to JPEG, fan out transcription
sub-agents, then an **independent verify pass** against the same images. That
verify pass is what made the existing transcription trustworthy; keep it.

Output lands in the vault's `sources/` folder, inside the repo. The corpus is
copyrighted — it must not be written anywhere that syncs off-machine.

Done when: every printed page 12–43 is represented, the ticket 03 validator passes,
and a spot-check against the scan confirms no fabricated or dropped paragraphs.

## Why it matters

The spike (07) has no corpus without it. Also the first real test of whether the
ticket 03 format survives contact with an actual book.

## Comments

### 2026-08-19 — unblocked by ticket 03

The format is decided: see
[03 — The Source-note Markdown format](03-source-note-markdown-format.md), section
**Resolution**. Transcribe against that, not against ADR 0008's JSONL record format.

Three things from ticket 03 that change this ticket's shape:

- **Output is ~20 files, not one.** One `.md` per level-2 section, plus one per
  chapter's lead prose. Filename is the citation and must be NFC-normalized:
  `corpus/four-elements/03-ราศีและการบำบัด-น.19-22.md`. Also write
  `corpus/books.yaml` mapping `four-elements` → `วิถีแห่งธรรมชาติกับธาตุทั้งสี่`.
- **The TOC under-reports headings.** `ธาตุ (elements)` (p37) is in the body but not
  in the TOC, so heading level must be judged from typography on the page, not from
  the contents list. And a short line that repeats above a table is a **caption**, not
  a heading — `การแสดงออก (modalities)` appears three times on p42–43 exactly that
  way. Getting this wrong is how junk headings entered the last corpus.
- **Scope is confirmed as the 39-page scan only** (printed 12–43). The book is 200
  pages and its prose runs to p76; pp.44–76 are a known gap (map: Not yet specified)
  and pp.77–199 are out of scope. Do not chase the rest of the book.

Run the ticket 03 validator before declaring done. Its **warnings** — dropped
label runs, captions read from short lines, coverage gaps — are the spot-check list;
they do not block the pipeline but a human must read them.
