"""Cut book three's repaired text into the 84 source notes ticket #62 needs.

Ticket #62 (map #45), implementing the grain #50 settled and the citation
contract #51 settled. Reads the two files #60 committed --
`corpus/herbs-50.jsonl` (202 page records of repaired text) and
`corpus/herbs-50-structure.json` (the structural index) -- and writes
`corpus/herbs-50/*.md` in ticket #12's source-note format.

Deterministic and byte-identical on re-run: no LLM, no network, no PDF. The
jsonl is the archive, `corpus/herbs-50/` is the in-scope view, and this script
is the documented relationship between them (#50 decision F).

**84 notes, two families** (#50 decision D):

- `301`-`334` -- the 34 *expanded* symptom sections, printed pp.3-32. Their
  `ลำดับ / ชื่อสมุนไพร / หน้าที่` table is the book's own symptom -> herb edge
  list, and becomes a Markdown table so the edges survive as structure.
- `340`-`389` -- the 50 monographs, printed pp.34-191, carrying **fields 1-6
  only**. Fields 7-9 (องค์ประกอบทางเคมี, ข้อมูลวิจัยที่สนับสนุนสรรพคุณ,
  เอกสารอ้างอิง) are simply not transcribed; the jsonl keeps them.

The gap at `335`-`339` is the deliberate seam between the book's two halves.

Two corrections this script makes to the map's picture of the book, both
measured from the committed text rather than assumed:

- **The section band is printed 3-32, not 3-31.** Section 6.4's
  `การรักษาด้วยสมุนไพรเดี่ยว` table sits on printed p.32.
- **Printed p.33 is a decorative half-title** (`ร า ย ก า ร / พืชสมุนไพร`,
  letter-spaced and printed twice), so it is the book's only in-band page that
  becomes no note.

Usage:

    uv run python scripts/build_herbs_notes.py
    uv run python -m app.rag.source_notes corpus
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

BOOK_ID = "herbs-50"
# printed folio = pdf page - PAGE_OFFSET (#46, confirmed by #60).
PAGE_OFFSET = 8

# The expanded symptom sections, and the monographs. Both printed-page spans.
SECTION_SPAN = (3, 32)
MONOGRAPH_SPAN = (34, 191)

# #50 decision D. Sections keep the book's own 1.1 ... 6.4 order; a monograph's
# ordinal is its own number in the book, which is also page order.
SECTION_ORDINAL_BASE = 300
MONOGRAPH_ORDINAL_BASE = 339

MONOGRAPH_CHAPTER = "รายการพืชสมุนไพร"
# The first numbered field that is out of scope (#50 decision F).
FIRST_DROPPED_FIELD = 7

RUNNING_TITLE = "แนวทางการใช้ยาสมุนไพร"
RUNNING_SUBTITLE = "ในการดูแลอาการเจ็บป่วยเบื้องต้น"
# The page header sits directly above the running title and is either a body
# system (`1. ระบบทางเดินอาหาร`) or a herb (`1. กระเจี๊ยบแดง`). Recognising it
# by position rather than by content is what keeps a real numbered body line --
# advice item `4.` running to the foot of a page -- from being eaten as furniture.
PAGE_HEADER_RE = re.compile(r"^\d{1,2}\.[ \t]*\S")
FOLIO_RE = re.compile(r"^\d{1,3}$")

# `N.M<TAB or spaces><title>`. The same shape also occurs inside 4.4's and 4.5's
# advice prose, which `_in_sequence` filters out.
SECTION_HEADING_RE = re.compile(r"^(\d)\.(\d+)[ \t]+(\S.*?)[ \t]*$", re.M)
MONOGRAPH_START_RE = re.compile(r"^1\.[ \t]*ชื่อวิทยาศาสตร์", re.M)
DROPPED_FIELD_RE = re.compile(rf"^{FIRST_DROPPED_FIELD}\.[ \t]*\S", re.M)

# Two headings the PDF draws as dingbats: an em space, and a Wingdings glyph
# that `pdftotext` maps to the digit 3. Left alone, `3 การรักษา...` reads as
# item 3 of the advice list above it. Both become real `##` subheadings.
ADVICE_HEADING_RE = re.compile(r"^ [ \t]*(คำแนะนำ\S.*?)[ \t]*$")
REMEDY_HEADING_RE = re.compile(r"^3[ \t]+(การรักษาด้วยสมุนไพร\S.*?)[ \t]*$")

TABLE_HEADER = ("ลำดับ", "ชื่อสมุนไพร", "หน้าที่")
TABLE_HEADER_LINE = " ".join(TABLE_HEADER)
TABLE_ROW_RE = re.compile(r"^(\d+)[ \t]+(\S.*?)[ \t]+(\d+)[ \t]*$")


@dataclass(frozen=True)
class Cut:
    """A half-open slice of the book, in printed pages and character offsets."""

    start_page: int
    start_char: int
    end_page: int
    end_char: int


@dataclass(frozen=True)
class Note:
    ordinal: int
    chapter: str
    section: str
    body: str
    pages: tuple[int, int]

    @property
    def uid(self) -> str:
        return f"{BOOK_ID}-{self.ordinal:03d}"

    @property
    def pdf_pages(self) -> tuple[int, int]:
        return self.pages[0] + PAGE_OFFSET, self.pages[1] + PAGE_OFFSET

    @property
    def filename(self) -> str:
        stem = f"{self.ordinal:03d}-{self.section}-น.{self.pages[0]}-{self.pages[1]}.md"
        return unicodedata.normalize("NFC", stem)


def load_pages(path: Path) -> dict[int, str]:
    """printed page number -> repaired page text, from #60's jsonl."""
    pages: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        pages[record["page"]] = record["text"]
    return pages


def strip_furniture(text: str) -> str:
    """Drop the running title, its second line, the folio and the page header.

    All four sit at the foot of the page in `pdftotext -raw`'s reading order, so
    this walks in from the end and stops at the first line that is real content.
    """
    lines = text.splitlines()
    while lines and (not lines[-1].strip() or FOLIO_RE.match(lines[-1].strip())):
        lines.pop()
    if lines and lines[-1].strip() == RUNNING_SUBTITLE:
        lines.pop()
    if not (lines and lines[-1].strip() == RUNNING_TITLE):
        return "\n".join(lines).rstrip()
    lines.pop()
    if lines and PAGE_HEADER_RE.match(lines[-1].strip()):
        lines.pop()
    return "\n".join(lines).rstrip()


def _in_sequence(number: tuple[int, int], previous: tuple[int, int] | None) -> bool:
    """Whether `number` continues the book's 1.1 ... 6.4 section sequence.

    Printed p.21 carries `1.1`, `1.2` and `2.1`-`2.4` as advice sub-items inside
    sections 4.4 and 4.5. They are real text, not headings, and the only thing
    that distinguishes them is that they do not continue the sequence.
    """
    group, index = number
    if previous is None:
        return number == (1, 1)
    last_group, last_index = previous
    if group == last_group:
        return index == last_index + 1
    return group == last_group + 1 and index == 1


def find_sections(pages: dict[int, str]) -> list[tuple[tuple[int, int], str, int, int]]:
    """(number, title, page, char offset) for each expanded symptom section."""
    found: list[tuple[tuple[int, int], str, int, int]] = []
    previous: tuple[int, int] | None = None
    for page in range(SECTION_SPAN[0], SECTION_SPAN[1] + 1):
        for match in SECTION_HEADING_RE.finditer(pages[page]):
            number = (int(match.group(1)), int(match.group(2)))
            if not _in_sequence(number, previous):
                continue
            found.append((number, match.group(3).strip(), page, match.start()))
            previous = number
    return found


def find_monographs(pages: dict[int, str]) -> list[tuple[int, int]]:
    """(page, char offset) of each `1. ชื่อวิทยาศาสตร์`, in book order."""
    starts: list[tuple[int, int]] = []
    for page in range(MONOGRAPH_SPAN[0], MONOGRAPH_SPAN[1] + 1):
        match = MONOGRAPH_START_RE.search(pages[page])
        if match:
            starts.append((page, match.start()))
    return starts


def find_dropped_field(pages: dict[int, str], start: tuple[int, int], limit: int) -> tuple[int, int]:
    """Where a monograph's in-scope text ends: the first `7.` at or after `start`."""
    start_page, start_char = start
    for page in range(start_page, limit + 1):
        offset = start_char if page == start_page else 0
        match = DROPPED_FIELD_RE.search(pages[page], offset)
        if match:
            return page, match.start()
    return limit, len(pages[limit])


def render_table(rows: list[tuple[str, str, str]]) -> list[str]:
    """The `ลำดับ / ชื่อสมุนไพร / หน้าที่` table as Markdown."""
    header = "| " + " | ".join(TABLE_HEADER) + " |"
    separator = "| " + " | ".join("---" for _ in TABLE_HEADER) + " |"
    return [header, separator] + ["| " + " | ".join(row) + " |" for row in rows]


def format_section_body(text: str) -> str:
    """Promote the two dingbat headings, and rebuild the herb table as Markdown.

    The table may be split across a page boundary, in which case its header line
    repeats; the rows are collected in order and rendered once, at the position
    of the first header.
    """
    out: list[str] = []
    rows: list[tuple[str, str, str]] = []
    table_at: int | None = None
    for line in text.splitlines():
        stripped = line.strip()
        advice = ADVICE_HEADING_RE.match(line)
        remedy = REMEDY_HEADING_RE.match(line)
        if advice or remedy:
            out.extend(["", f"## {(advice or remedy).group(1)}", ""])
            continue
        if stripped == TABLE_HEADER_LINE:
            if table_at is None:
                table_at = len(out)
            continue
        row = TABLE_ROW_RE.match(stripped) if table_at is not None else None
        if row:
            rows.append(row.groups())
            continue
        out.append(line)
    if table_at is not None and rows:
        out[table_at:table_at] = ["", *render_table(rows), ""]
    return _collapse(out)


def _collapse(lines: list[str]) -> str:
    """Join lines, collapsing runs of blanks, with no leading or trailing blank."""
    out: list[str] = []
    for line in lines:
        if not line.strip():
            if not out or not out[-1]:
                continue
            out.append("")
        else:
            out.append(line.rstrip())
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def slice_body(pages: dict[int, str], cut: Cut, section: bool) -> tuple[str, tuple[int, int]]:
    """Text of `cut` with `<!-- p.N -->` at page transitions, and the pages it covers.

    A page whose slice is empty after furniture stripping contributes neither
    content nor a marker, so the returned range names what the note actually
    transcribes -- which is what the citation promises (#51).
    """
    parts: list[str] = []
    covered: list[int] = []
    for page in range(cut.start_page, cut.end_page + 1):
        text = pages[page]
        start = cut.start_char if page == cut.start_page else 0
        end = cut.end_char if page == cut.end_page else len(text)
        chunk = strip_furniture(text[start:end])
        if not chunk.strip():
            continue
        if covered:
            parts.append(f"<!-- p.{page} -->")
        parts.append(chunk)
        covered.append(page)
    body = "\n".join(parts)
    body = format_section_body(body) if section else _collapse(body.splitlines())
    return body, (covered[0], covered[-1])


def build_section_notes(pages: dict[int, str], groups: dict[int, str]) -> list[Note]:
    found = find_sections(pages)
    notes: list[Note] = []
    for index, (number, title, page, offset) in enumerate(found):
        if index + 1 < len(found):
            _, _, next_page, next_offset = found[index + 1]
        else:
            next_page, next_offset = SECTION_SPAN[1], len(pages[SECTION_SPAN[1]])
        cut = Cut(page, offset, next_page, next_offset)
        body, covered = slice_body(pages, cut, section=True)
        notes.append(
            Note(
                ordinal=SECTION_ORDINAL_BASE + index + 1,
                chapter=groups[number[0]],
                section=title,
                body=body,
                pages=covered,
            )
        )
    return notes


def build_monograph_notes(pages: dict[int, str], monographs: list[dict]) -> list[Note]:
    starts = find_monographs(pages)
    if len(starts) != len(monographs):
        raise SystemExit(
            f"found {len(starts)} monograph starts but structure.json has {len(monographs)}"
        )
    notes: list[Note] = []
    for index, (start, monograph) in enumerate(zip(starts, monographs, strict=True)):
        limit = starts[index + 1][0] if index + 1 < len(starts) else MONOGRAPH_SPAN[1]
        end_page, end_char = find_dropped_field(pages, start, limit)
        cut = Cut(start[0], start[1], end_page, end_char)
        body, covered = slice_body(pages, cut, section=False)
        notes.append(
            Note(
                ordinal=MONOGRAPH_ORDINAL_BASE + monograph["ordinal"],
                chapter=MONOGRAPH_CHAPTER,
                section=monograph["name"],
                body=body,
                pages=covered,
            )
        )
    return notes


def render_note(note: Note) -> str:
    return (
        "---\n"
        f"uid: {note.uid}\n"
        "type: source-note\n"
        f"book_id: {BOOK_ID}\n"
        f"chapter: {note.chapter}\n"
        f"section: {note.section}\n"
        f"pages: [{note.pages[0]}, {note.pages[1]}]\n"
        f"pdf_pages: [{note.pdf_pages[0]}, {note.pdf_pages[1]}]\n"
        "---\n\n"
        f"{note.body}\n"
    )


def build_notes(jsonl: Path, structure: Path) -> list[Note]:
    pages = load_pages(jsonl)
    index = json.loads(structure.read_text(encoding="utf-8"))
    groups = {s["group"]: s["group_title"] for s in index["symptom_sections"]}
    return build_section_notes(pages, groups) + build_monograph_notes(pages, index["monographs"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("corpus"))
    args = parser.parse_args(argv)

    notes = build_notes(args.corpus / f"{BOOK_ID}.jsonl", args.corpus / f"{BOOK_ID}-structure.json")
    out_dir = args.corpus / BOOK_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.md"):
        stale.unlink()
    for note in notes:
        (out_dir / note.filename).write_text(render_note(note), encoding="utf-8")
    print(f"wrote {len(notes)} notes to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
