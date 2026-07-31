# Two-Book Corpus Digitization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce ADR 0008-conformant corpus JSONL for two scanned books (`tcm-basic-theory`, `four-elements`) via parallel sub-agent transcription + independent verify pass, then open a PR to `main`.

**Architecture:** Four resumable stages — (1) render every PDF page to JPEG in the scratchpad, (2) fan out transcription sub-agents that write one JSON per page, (3) fan out independent verifier sub-agents that fix the per-page JSON against the images, (4) a tested merge/validate CLI (`app.rag.corpus_merge`) assembles the JSONL, splits front/back matter, and validates; then commit + PR.

**Tech Stack:** Python 3.11, pymupdf + Pillow (already deps), pytest, Claude sub-agents with vision (Read tool on JPEGs), gh CLI.

**Spec:** `docs/superpowers/specs/2026-07-30-two-book-corpus-digitization-design.md`

## Global Constraints

- Record format (ADR 0008, exact key order): `{"book_id": ..., "book_title": ..., "page": <int>, "pdf_page": <int>, "paragraph": <int>, "text": ...}` — one JSON object per line, UTF-8, `ensure_ascii=False`.
- `book_id` values: `tcm-basic-theory` (เล่ม 1), `four-elements` (เล่ม 2). Front/back-matter records use `<book_id>-front` (matches existing `tcm-tongue-diagnosis-front`).
- `book_title` values: `ทฤษฎีพื้นฐานการแพทย์แผนจีน` (เล่ม 1), `วิถีแห่งธรรมชาติกับธาตุทั้งสี่` (เล่ม 2).
- Faithful transcription: keep the book's own typos; no translation, summary, or correction. Headings are their own paragraph. Running headers/footers and printed page numbers are excluded from paragraph text.
- Printed page number is the citation authority; interpolate only for unnumbered body pages; front/back matter uses `page = pdf_page`.
- Source PDFs and page images live in the scratchpad only — never committed. Only JSONL (+ code/docs) enters git.
- Repo conventions: ruff line-length 100, py311; commit format `<type>: <description>`, no attribution footer.
- Scratchpad root (this session): `/private/tmp/claude-501/-Users-bright-Github-TTMAgent--claude-worktrees-using-superpowers-544587/3304d949-1821-4703-88d1-25981a8bd2d5/scratchpad` — referred to as `$SCRATCH` below. PDFs already downloaded there: `tcm-fundamentals.pdf` (104 pages), `four-elements.pdf` (39 pages).
- Sub-agent selection: transcription/verification is vision work with no matching `ecc:*` agent — use `general-purpose` agents there. For the code task (Task 2), follow the user's ecc rule: if an `ecc:python-reviewer`/`code-reviewer` agent resolves, use it for the post-implementation review.

---

### Task 1: Render all pages to JPEGs

**Files:**
- Create: `$SCRATCH/render_pages.py` (scratchpad only, not committed)
- Output: `$SCRATCH/pages/tcm-basic-theory/p001.jpg … p104.jpg`, `$SCRATCH/pages/four-elements/p001.jpg … p039.jpg`

**Interfaces:**
- Produces: page images named `p<NNN>.jpg` (zero-padded to 3), long side ≤ 1600 px, JPEG q85 — the input contract for Tasks 3–5.

- [ ] **Step 1: Write the render script**

```python
# $SCRATCH/render_pages.py
"""Render every PDF page to a vision-sized JPEG: pages/<book_id>/pNNN.jpg."""
import sys
from pathlib import Path

import pymupdf
from PIL import Image

SCRATCH = Path(__file__).parent
MAX_LONG_SIDE = 1600
BOOKS = {
    "tcm-basic-theory": SCRATCH / "tcm-fundamentals.pdf",
    "four-elements": SCRATCH / "four-elements.pdf",
}


def render_book(book_id: str, pdf_path: Path) -> None:
    out_dir = SCRATCH / "pages" / book_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf_path) as pdf:
        for index, page in enumerate(pdf, start=1):
            out_path = out_dir / f"p{index:03d}.jpg"
            if out_path.exists():
                continue
            rect = page.rect
            zoom = MAX_LONG_SIDE / max(rect.width, rect.height)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            image.save(out_path, format="JPEG", quality=85)
        print(f"{book_id}: {pdf.page_count} pages rendered", file=sys.stderr)


if __name__ == "__main__":
    for book_id, pdf_path in BOOKS.items():
        render_book(book_id, pdf_path)
```

- [ ] **Step 2: Run it**

Run: `cd $SCRATCH && uv run --project <worktree> python render_pages.py`
Expected stderr: `tcm-basic-theory: 104 pages rendered` and `four-elements: 39 pages rendered`

- [ ] **Step 3: Verify output**

Run: `ls $SCRATCH/pages/tcm-basic-theory | wc -l` → `104`; `ls $SCRATCH/pages/four-elements | wc -l` → `39`. Open one sample per book with Read and confirm the text is legible (Thai diacritics distinguishable).

No commit (nothing in the repo changed).

---

### Task 2: `app.rag.corpus_merge` — merge/validate CLI (TDD)

**Files:**
- Create: `app/rag/corpus_merge.py`
- Test: `tests/rag/test_corpus_merge.py`

**Interfaces:**
- Consumes: per-page JSON files `p<NNN>.json` in a directory, schema `{"printed_page_number": int|null, "paragraphs": [str], "uncertain": bool, "note": str}` (extra keys like `"verified"` tolerated and ignored).
- Produces: CLI `uv run python -m app.rag.corpus_merge <pages_json_dir> --book-id X --book-title Y --pdf-pages N [--out corpus/X.jsonl] [--front-out corpus/X-front-matter.jsonl]`. Exit 0 = wrote both files and validation passed; exit 1 = missing pages / validation errors (printed to stderr). Offset change-points are printed as `OFFSET page …` warnings for the human spot-check, not failures.
- Public functions used by tests: `split_runs(pages) -> tuple[list, list, list]`, `assign_printed_pages(body) -> list[tuple[int, int, list[str]]]`, `to_records(assigned, book_id, book_title) -> list[dict]`, `validate_records(records, book_id, book_title) -> list[str]`, `offset_changes(body) -> list[str]`. A page is the dataclass `PageFile(pdf_page: int, printed_page_number: int | None, paragraphs: list[str])`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/rag/test_corpus_merge.py
"""Unit tests for app.rag.corpus_merge (ADR 0008 JSONL assembly)."""

from app.rag.corpus_merge import (
    PageFile,
    assign_printed_pages,
    offset_changes,
    split_runs,
    to_records,
    validate_records,
)


def page(pdf_page, printed, paragraphs):
    return PageFile(pdf_page=pdf_page, printed_page_number=printed, paragraphs=paragraphs)


def test_split_runs_separates_leading_and_trailing_unnumbered_pages():
    pages = [
        page(1, None, ["ปกหน้า"]),
        page(2, None, []),
        page(3, 1, ["บทที่หนึ่ง"]),
        page(4, None, ["หน้าไม่มีเลขกลางเล่ม"]),
        page(5, 3, ["เนื้อหา"]),
        page(6, None, ["ปกหลัง"]),
    ]
    front, body, back = split_runs(pages)
    assert [p.pdf_page for p in front] == [1, 2]
    assert [p.pdf_page for p in body] == [3, 4, 5]
    assert [p.pdf_page for p in back] == [6]


def test_assign_printed_pages_uses_printed_number_and_interpolates_from_preceding():
    body = [page(10, 15, ["ก"]), page(11, None, ["ข"]), page(12, 17, ["ค"])]
    assigned = assign_printed_pages(body)
    assert [(pdf, printed) for pdf, printed, _ in assigned] == [(10, 15), (11, 16), (12, 17)]


def test_assign_printed_pages_interpolates_from_following_when_no_preceding_number():
    body = [page(3, None, ["เปิดบท"]), page(4, 2, ["เนื้อหา"])]
    assigned = assign_printed_pages(body)
    assert [(pdf, printed) for pdf, printed, _ in assigned] == [(3, 1), (4, 2)]


def test_to_records_numbers_paragraphs_per_page_and_uses_adr_key_order():
    assigned = [(3, 1, ["หัวข้อ", "ย่อหน้า"]), (4, 2, ["ต่อ"])]
    records = to_records(assigned, book_id="b", book_title="ชื่อ")
    assert [r["paragraph"] for r in records] == [1, 2, 1]
    assert list(records[0].keys()) == ["book_id", "book_title", "page", "pdf_page", "paragraph", "text"]
    assert records[2] == {
        "book_id": "b", "book_title": "ชื่อ", "page": 2, "pdf_page": 4, "paragraph": 1, "text": "ต่อ",
    }


def test_to_records_skips_blank_pages_and_whitespace_paragraphs():
    assigned = [(3, 1, []), (4, 2, ["  ", "จริง"])]
    records = to_records(assigned, book_id="b", book_title="ชื่อ")
    assert [(r["pdf_page"], r["paragraph"], r["text"]) for r in records] == [(4, 1, "จริง")]


def test_validate_records_passes_clean_records():
    records = to_records([(3, 1, ["ก", "ข"])], book_id="b", book_title="ชื่อ")
    assert validate_records(records, book_id="b", book_title="ชื่อ") == []


def test_validate_records_flags_empty_text_bad_keys_and_gaps():
    bad = [
        {"book_id": "b", "book_title": "ชื่อ", "page": 1, "pdf_page": 3, "paragraph": 1, "text": ""},
        {"book_id": "b", "book_title": "ชื่อ", "page": 1, "pdf_page": 3, "paragraph": 3, "text": "ข"},
        {"book_id": "x", "book_title": "ชื่อ", "page": 1, "pdf_page": 4, "paragraph": 1, "text": "ค", "extra": 1},
    ]
    errors = validate_records(bad, book_id="b", book_title="ชื่อ")
    assert any("empty text" in e for e in errors)
    assert any("paragraph" in e for e in errors)  # 1 then 3: not contiguous
    assert any("keys" in e for e in errors)
    assert any("book_id" in e for e in errors)


def test_validate_records_flags_page_going_backwards():
    records = [
        {"book_id": "b", "book_title": "ชื่อ", "page": 9, "pdf_page": 3, "paragraph": 1, "text": "ก"},
        {"book_id": "b", "book_title": "ชื่อ", "page": 7, "pdf_page": 4, "paragraph": 1, "text": "ข"},
    ]
    errors = validate_records(records, book_id="b", book_title="ชื่อ")
    assert any("decreas" in e for e in errors)


def test_offset_changes_reports_change_points_only():
    body = [page(10, 15, ["ก"]), page(11, 16, ["ข"]), page(12, 18, ["ค"])]
    changes = offset_changes(body)
    assert len(changes) == 1
    assert "pdf_page 12" in changes[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rag/test_corpus_merge.py -v`
Expected: FAIL / errors with `ModuleNotFoundError: No module named 'app.rag.corpus_merge'`

- [ ] **Step 3: Implement `app/rag/corpus_merge.py`**

```python
# app/rag/corpus_merge.py
"""One-off CLI to merge per-page transcription JSON into ADR 0008 corpus JSONL.

Usage:
    uv run python -m app.rag.corpus_merge $SCRATCH/out/tcm-basic-theory \
        --book-id tcm-basic-theory --book-title "ทฤษฎีพื้นฐานการแพทย์แผนจีน" \
        --pdf-pages 104 [--out corpus/tcm-basic-theory.jsonl] \
        [--front-out corpus/tcm-basic-theory-front-matter.jsonl]

Input: one p<NNN>.json per PDF page, written by the transcription/verify
sub-agents: {"printed_page_number": int|null, "paragraphs": [str], ...}.
Leading/trailing runs of unnumbered pages become front/back matter under
book_id "<book-id>-front" with page = pdf_page; unnumbered pages inside the
body get their printed page interpolated from the nearest numbered page.
The output is what app.rag.ingest consumes (see docs/adr/0008).
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED_KEYS = ["book_id", "book_title", "page", "pdf_page", "paragraph", "text"]


@dataclass(frozen=True)
class PageFile:
    """One page's transcription as produced by the sub-agents."""

    pdf_page: int
    printed_page_number: int | None
    paragraphs: list[str]


def load_page_files(pages_dir: Path, pdf_pages: int) -> tuple[list[PageFile], list[str]]:
    """Read p001.json..p<N>.json; report missing/unparseable files as errors."""
    pages: list[PageFile] = []
    errors: list[str] = []
    for index in range(1, pdf_pages + 1):
        path = pages_dir / f"p{index:03d}.json"
        if not path.exists():
            errors.append(f"missing {path.name}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pages.append(
                PageFile(
                    pdf_page=index,
                    printed_page_number=data["printed_page_number"],
                    paragraphs=list(data["paragraphs"]),
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            errors.append(f"unreadable {path.name}: {exc}")
    return pages, errors


def split_runs(pages: list[PageFile]) -> tuple[list[PageFile], list[PageFile], list[PageFile]]:
    """Split into (front, body, back): leading/trailing unnumbered runs vs the numbered body."""
    first = next((i for i, p in enumerate(pages) if p.printed_page_number is not None), None)
    if first is None:
        return list(pages), [], []
    last = max(i for i, p in enumerate(pages) if p.printed_page_number is not None)
    return list(pages[:first]), list(pages[first : last + 1]), list(pages[last + 1 :])


def assign_printed_pages(body: list[PageFile]) -> list[tuple[int, int, list[str]]]:
    """Resolve each body page to its printed number, interpolating unnumbered pages."""
    known_offsets = {
        p.pdf_page: p.printed_page_number - p.pdf_page
        for p in body
        if p.printed_page_number is not None
    }
    assigned = []
    for page_file in body:
        if page_file.printed_page_number is not None:
            printed = page_file.printed_page_number
        else:
            preceding = [pdf for pdf in known_offsets if pdf < page_file.pdf_page]
            anchor = max(preceding) if preceding else min(known_offsets)
            printed = page_file.pdf_page + known_offsets[anchor]
        assigned.append((page_file.pdf_page, printed, page_file.paragraphs))
    return assigned


def to_records(
    assigned: list[tuple[int, int, list[str]]], *, book_id: str, book_title: str
) -> list[dict]:
    """Build ADR 0008 records; paragraph numbering restarts at 1 on every page."""
    records = []
    for pdf_page, printed, paragraphs in assigned:
        texts = [text.strip() for text in paragraphs if text.strip()]
        for paragraph, text in enumerate(texts, start=1):
            records.append(
                {
                    "book_id": book_id,
                    "book_title": book_title,
                    "page": printed,
                    "pdf_page": pdf_page,
                    "paragraph": paragraph,
                    "text": text,
                }
            )
    return records


def validate_records(records: list[dict], *, book_id: str, book_title: str) -> list[str]:
    """ADR 0008 conformance errors; empty list means the records are clean."""
    errors = []
    previous_page = None
    expected_paragraph: dict[int, int] = {}
    for line, record in enumerate(records, start=1):
        if list(record.keys()) != REQUIRED_KEYS:
            errors.append(f"line {line}: keys {list(record.keys())} != {REQUIRED_KEYS}")
            continue
        if record["book_id"] != book_id or record["book_title"] != book_title:
            errors.append(f"line {line}: book_id/book_title mismatch")
        if not str(record["text"]).strip():
            errors.append(f"line {line}: empty text")
        pdf_page = record["pdf_page"]
        expected = expected_paragraph.get(pdf_page, 1)
        if record["paragraph"] != expected:
            errors.append(
                f"line {line}: paragraph {record['paragraph']} on pdf_page {pdf_page}, expected {expected}"
            )
        expected_paragraph[pdf_page] = record["paragraph"] + 1
        if previous_page is not None and record["page"] < previous_page:
            errors.append(f"line {line}: page {record['page']} decreasing (after {previous_page})")
        previous_page = record["page"]
    return errors


def offset_changes(body: list[PageFile]) -> list[str]:
    """Human-readable change points of (printed - pdf) offset, for spot-checking."""
    changes = []
    previous: int | None = None
    for page_file in body:
        if page_file.printed_page_number is None:
            continue
        offset = page_file.printed_page_number - page_file.pdf_page
        if previous is not None and offset != previous:
            changes.append(
                f"OFFSET pdf_page {page_file.pdf_page}: printed-pdf offset {previous} -> {offset}"
            )
        previous = offset
    return changes


def write_jsonl(records: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages_dir", type=Path)
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--book-title", required=True)
    parser.add_argument("--pdf-pages", type=int, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--front-out", type=Path, default=None)
    args = parser.parse_args()

    out_path = args.out or Path("corpus") / f"{args.book_id}.jsonl"
    front_path = args.front_out or Path("corpus") / f"{args.book_id}-front-matter.jsonl"

    pages, errors = load_page_files(args.pages_dir, args.pdf_pages)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)

    front, body, back = split_runs(pages)
    body_records = to_records(
        assign_printed_pages(body), book_id=args.book_id, book_title=args.book_title
    )
    front_records = to_records(
        [(p.pdf_page, p.pdf_page, p.paragraphs) for p in front + back],
        book_id=f"{args.book_id}-front",
        book_title=args.book_title,
    )

    validation_errors = validate_records(
        body_records, book_id=args.book_id, book_title=args.book_title
    ) + validate_records(
        front_records, book_id=f"{args.book_id}-front", book_title=args.book_title
    )
    if validation_errors:
        print("\n".join(validation_errors), file=sys.stderr)
        sys.exit(1)

    for warning in offset_changes(body):
        print(warning, file=sys.stderr)

    write_jsonl(body_records, out_path)
    write_jsonl(front_records, front_path)
    print(
        f"{args.book_id}: {len(body_records)} body records -> {out_path}, "
        f"{len(front_records)} front/back records -> {front_path}"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rag/test_corpus_merge.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Lint + full test suite**

Run: `uv run ruff check . && uv run pytest -q`
Expected: clean / all pass

- [ ] **Step 6: Commit**

```bash
git add app/rag/corpus_merge.py tests/rag/test_corpus_merge.py
git commit -m "feat: corpus_merge CLI assembling per-page transcriptions into ADR 0008 JSONL"
```

---

### Task 3: Transcribe เล่ม 1 (tcm-basic-theory) with parallel sub-agents

**Files:**
- Output: `$SCRATCH/out/tcm-basic-theory/p001.json … p104.json`

**Interfaces:**
- Consumes: `$SCRATCH/pages/tcm-basic-theory/p<NNN>.jpg` (Task 1).
- Produces: per-page JSON, schema `{"printed_page_number": int|null, "paragraphs": [str], "uncertain": bool, "note": str}` — input for Tasks 4 and 6.

- [ ] **Step 1: Dispatch 11 transcription agents in parallel** (batches: pages 1–10, 11–20, …, 101–104). All in one message so they run concurrently. Prompt template per agent (fill `{BATCH}` with the page numbers, `{BOOK}` = `tcm-basic-theory`):

```
You are transcribing scanned pages of a Thai book (ทฤษฎีพื้นฐานการแพทย์แผนจีน — Thai text, occasional Chinese terms) into per-page JSON files.

For each page number NNN in {BATCH} (zero-padded to 3 digits):
1. Read the image $SCRATCH/pages/{BOOK}/pNNN.jpg
2. Write $SCRATCH/out/{BOOK}/pNNN.json (UTF-8) with exactly:
   {"printed_page_number": <int or null>, "paragraphs": ["...", ...], "uncertain": <bool>, "note": "<string>"}

Transcription rules — follow exactly:
- Transcribe ALL body text exactly as printed. Thai stays Thai; Chinese characters stay Chinese. Never translate, summarize, or correct anything — keep the book's own typos as printed.
- Split into paragraphs in reading order. A heading is its own paragraph. A paragraph continuing from the previous page still starts this page's paragraph list.
- EXCLUDE running headers/footers and the printed page number from paragraph text. This book prints the page number in the top corner beside a running-header line with the book title — neither goes into any paragraph.
- Report the printed page number as "printed_page_number" when visible on the page; null when the page shows none (covers, blank pages, some chapter openers).
- Blank or pure-illustration pages: "paragraphs": [] (front/back cover text such as title, author, blurb IS text — transcribe it).
- Lists/tables: keep each entry's text, reading order, inside one paragraph per visual block.
- If any word is unreadable or you are unsure of a diacritic, set "uncertain": true and describe the spot in "note"; otherwise "uncertain": false, "note": "".

Write each JSON file with the Write tool before moving to the next page. Do not skip any page in your batch. Your final message: one line per page — page number, paragraph count, printed page number, uncertain flag.
```

- [ ] **Step 2: Completeness check after all agents return**

Run in Bash (heredoc python via `uv run`):

```python
import json
from pathlib import Path
out = Path("$SCRATCH/out/tcm-basic-theory")
missing, bad, uncertain = [], [], []
for i in range(1, 105):
    p = out / f"p{i:03d}.json"
    if not p.exists():
        missing.append(i); continue
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        assert isinstance(d["paragraphs"], list)
        assert d["printed_page_number"] is None or isinstance(d["printed_page_number"], int)
        if d.get("uncertain"):
            uncertain.append((i, d.get("note", "")))
    except Exception as e:
        bad.append((i, str(e)))
print("missing:", missing)
print("bad:", bad)
print("uncertain:", uncertain)
```

Expected: `missing: []`, `bad: []`. Re-dispatch a single agent for any missing/bad pages (same prompt, just those pages) until clean. Keep the `uncertain` list for Task 4.

No commit (scratchpad only).

---

### Task 4: Verify เล่ม 1 with independent sub-agents

**Files:**
- Modify (in place): `$SCRATCH/out/tcm-basic-theory/p<NNN>.json`

**Interfaces:**
- Consumes: Task 3 output + Task 1 images.
- Produces: same files, corrected, each gaining `"verified": true`; a final list of still-uncertain pages for orchestrator review.

- [ ] **Step 1: Dispatch 11 verifier agents in parallel** — same batch split, but these are fresh agents that did not do the transcription. Prompt template:

```
You are the second-pass verifier for a Thai book transcription (ทฤษฎีพื้นฐานการแพทย์แผนจีน). The scanned image is the ONLY authority.

For each page number NNN in {BATCH} (zero-padded to 3 digits):
1. Read the image $SCRATCH/pages/tcm-basic-theory/pNNN.jpg
2. Read $SCRATCH/out/tcm-basic-theory/pNNN.json
3. Compare word by word against the image and fix the JSON file:
   - Thai spelling/diacritic/vowel errors vs the image. Do NOT "fix" typos that are genuinely printed in the book — the image decides.
   - Missing paragraphs, wrongly merged/split paragraphs, wrong reading order.
   - Running header/footer or page-number text leaked into paragraphs (remove it).
   - Wrong or missing "printed_page_number" (this book: top corner).
4. Rewrite the file (Write tool) only if something changed. Every file you finish must contain "verified": true. Keep "uncertain"/"note" accurate after your fixes — clear them if you resolved the doubt, keep/raise them if not.

Your final message: pages changed (one line each: page, what was wrong), and pages still uncertain with reasons.
```

- [ ] **Step 2: Confirm every page is verified**

Same completeness script as Task 3 Step 2, plus assert `d.get("verified") is True` for all 104 files. Re-dispatch for any page not verified.

- [ ] **Step 3: Orchestrator reviews remaining uncertain pages**

For each page still flagged uncertain: Read the image + JSON yourself, resolve the doubt (or accept the reading and clear the flag). Target: zero pages uncertain.

No commit (scratchpad only).

---

### Task 5: Transcribe + verify เล่ม 2 (four-elements)

**Files:**
- Output: `$SCRATCH/out/four-elements/p001.json … p039.json`

**Interfaces:** identical to Tasks 3–4 with `{BOOK}` = `four-elements`, 39 pages, 4 batches (1–10, 11–20, 21–30, 31–39).

- [ ] **Step 1: Dispatch 4 transcription agents in parallel** — same prompt template as Task 3 Step 1 with these substitutions: book title `วิถีแห่งธรรมชาติกับธาตุทั้งสี่`, and the header/footer rule reads: "This book prints the page number at the BOTTOM of the page beside the book title (odd pages: `วิถีแห่งธรรมชาติกับธาตุทั้งสี่ NN`) or the author name (even pages: `NN อนุสรณ์ วรมงคล`) — the whole footer line is excluded from paragraphs."
- [ ] **Step 2: Completeness check** — Task 3 Step 2 script with `four-elements` and `range(1, 40)`. Expected: no missing, no bad.
- [ ] **Step 3: Dispatch 4 verifier agents in parallel** — Task 4 Step 1 prompt with the four-elements substitutions (printed page number: bottom footer).
- [ ] **Step 4: Verified-completeness check + orchestrator uncertain review** — as Task 4 Steps 2–3.

No commit (scratchpad only). Note: Tasks 3 and 5 transcription batches may be dispatched in the same message if context budget allows; verification must still be a separate later wave.

---

### Task 6: Merge, validate, spot-check, commit corpus JSONL

**Files:**
- Create: `corpus/tcm-basic-theory.jsonl`, `corpus/tcm-basic-theory-front-matter.jsonl`, `corpus/four-elements.jsonl`, `corpus/four-elements-front-matter.jsonl`

**Interfaces:**
- Consumes: Task 2 CLI + Tasks 4/5 verified page JSON.

- [ ] **Step 1: Run the merge CLI for both books**

```bash
uv run python -m app.rag.corpus_merge $SCRATCH/out/tcm-basic-theory \
  --book-id tcm-basic-theory --book-title "ทฤษฎีพื้นฐานการแพทย์แผนจีน" --pdf-pages 104
uv run python -m app.rag.corpus_merge $SCRATCH/out/four-elements \
  --book-id four-elements --book-title "วิถีแห่งธรรมชาติกับธาตุทั้งสี่" --pdf-pages 39
```

Expected: both exit 0 with a `N body records -> corpus/...` summary line. Investigate every `OFFSET` warning: expected shape is a stable offset ≈ −10 (เล่ม 1) and ≈ +5 (เล่ม 2); an unexplained jump means a misread page number — Read that page image, fix the page JSON, re-run.

- [ ] **Step 2: Spot-check 5 pages per book against the images**

For each book pick 5 pdf_pages (mix of: first body page, a flagged-offset page if any, 3 spread across the book). Read the image and the JSONL records side by side; confirm text fidelity, paragraph boundaries, printed page number. Fix + re-run merge on any miss.

- [ ] **Step 3: Commit**

```bash
git add corpus/tcm-basic-theory.jsonl corpus/tcm-basic-theory-front-matter.jsonl \
        corpus/four-elements.jsonl corpus/four-elements-front-matter.jsonl
git commit -m "feat: corpus JSONL for tcm-basic-theory and four-elements (ADR 0008)"
```

---

### Task 7: ADR update + PR

**Files:**
- Modify: `docs/adr/0008-scanned-corpus-page-provenance.md:5` (the "first corpus book" paragraph)

- [ ] **Step 1: Extend the ADR book paragraph**

Replace the single-sentence paragraph at line 5 with:

```markdown
The first corpus book is the Thai translation of 中医临床舌诊 ("การตรวจรักษาโรคแบบแพทย์แผนจีนโดยการวินิจฉัยโรคจากลิ้น", Hu Zhen, Chulalongkorn University Press) — a two-column layout with Thai on the left and Chinese on the right; only the Thai column is transcribed. Books two and three — "ทฤษฎีพื้นฐานการแพทย์แผนจีน" (นพ.โกวิท คัมภีรภาพ, `tcm-basic-theory`) and "วิถีแห่งธรรมชาติกับธาตุทั้งสี่" (อนุสรณ์ วรมงคล, `four-elements`) — are single-column Thai scans digitized by parallel vision sub-agents (transcribe + independent verify passes) into the same record format, merged by `app.rag.corpus_merge`; the four-elements scan covers only part of the printed book, so its missing pages simply never appear in the corpus.
```

- [ ] **Step 2: Full check + commit**

Run: `uv run ruff check . && uv run pytest -q` → clean.

```bash
git add docs/adr/0008-scanned-corpus-page-provenance.md
git commit -m "docs: record books two and three in ADR 0008"
```

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin claude/using-superpowers-544587
gh pr create --base main --title "feat: add tcm-basic-theory and four-elements to the TTM corpus" --body "$(cat <<'EOF'
## Summary
- Digitize two scanned books into ADR 0008 corpus JSONL at paragraph granularity with page/paragraph provenance:
  - `corpus/tcm-basic-theory.jsonl` — ทฤษฎีพื้นฐานการแพทย์แผนจีน (นพ.โกวิท คัมภีรภาพ)
  - `corpus/four-elements.jsonl` — วิถีแห่งธรรมชาติกับธาตุทั้งสี่ (อนุสรณ์ วรมงคล)
  - front/back matter split into `-front-matter.jsonl` files (book_id `-front`, not ingested)
- New `app.rag.corpus_merge` CLI (tested) that assembles per-page transcription JSON into validated ADR 0008 JSONL
- ADR 0008 updated with the new books
- Design spec + plan under `docs/superpowers/`

Transcription: parallel Claude vision sub-agents, one JSON per page, then an independent verify pass against the page images; printed page numbers are the citation authority (offsets validated at merge).

## Test plan
- [x] `uv run pytest` (includes new `tests/rag/test_corpus_merge.py`)
- [x] `uv run ruff check .`
- [x] Merge validator: exact ADR 0008 keys, contiguous per-page paragraph numbering, non-decreasing printed pages, offset change-points reviewed
- [x] Manual spot-check of 5 pages/book against the scans
- [ ] After merge: run `app.rag.ingest` on the deploy machine to upsert the new books into Chroma
EOF
)"
```

Expected: PR URL printed. Report it to the owner.

---

## Self-Review Notes

- Spec coverage: render (T1), transcribe (T3/T5), verify (T4/T5), merge+validate+front-matter split (T2/T6), ADR update + PR (T7), resumability (per-page files + `if exists: continue`), acceptance checks (T2 tests, T6 validation + spot-check, T7 CI) — all covered.
- `page = pdf_page` for front/back matter matches the existing `tcm-tongue-diagnosis-front` records (verified against the committed file).
- Key-order stability: records are built with the ADR key order and `validate_records` enforces it; `json.dumps` preserves insertion order.
