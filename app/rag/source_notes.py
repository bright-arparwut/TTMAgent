"""Validate the source-note Markdown corpus against the ticket #12 format.

One `.md` per level-2 book section; the filename is the citation. Errors block ingest;
warnings are for a human to read (ticket #15 runs unattended).

Usage: uv run python -m app.rag.source_notes corpus
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

REQUIRED_STR_FIELDS = ("uid", "type", "book_id", "chapter", "section")
REQUIRED_PAIR_FIELDS = ("pages", "pdf_pages")
SHORT_BODY_CHARS = 200

FILENAME_RE = re.compile(r"^(\d{2})-(.*)-น\.(\d+)-(\d+)\.md$")
PAIR_RE = re.compile(r"^\[\s*(\d+)\s*,\s*(\d+)\s*\]$")
COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
PAGE_MARKER_RE = re.compile(r"^ p\.(\d+) $")
SIC_RE = re.compile(r"^ sic: (.+?) $")
CAPTION_RE = re.compile(r"^\*\*(.+)\*\*$")


@dataclass(frozen=True)
class SourceNote:
    path: Path
    ordinal: int
    uid: str
    type: str
    book_id: str
    chapter: str
    section: str
    pages: tuple[int, int]
    pdf_pages: tuple[int, int]
    body: str


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("file does not start with YAML frontmatter")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise ValueError("frontmatter is not terminated by a closing ---")
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"frontmatter line is not `key: value`: {line!r}")
        fields[key.strip()] = value.strip()
    return fields, text[end + 5 :]


def _parse_pair(value: str) -> tuple[int, int]:
    match = PAIR_RE.match(value)
    if not match:
        raise ValueError(f"expected [int, int], got {value!r}")
    return int(match.group(1)), int(match.group(2))


def parse_note(path: Path) -> SourceNote:
    """Parse one source note. Raises ValueError if frontmatter is missing or malformed."""
    fields, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    missing = [f for f in REQUIRED_STR_FIELDS + REQUIRED_PAIR_FIELDS if f not in fields]
    if missing:
        raise ValueError(f"missing frontmatter field(s): {', '.join(missing)}")
    match = FILENAME_RE.match(unicodedata.normalize("NFC", path.name))
    return SourceNote(
        path=path,
        ordinal=int(match.group(1)) if match else 0,
        uid=fields["uid"],
        type=fields["type"],
        book_id=fields["book_id"],
        chapter=fields["chapter"],
        section=fields["section"],
        pages=_parse_pair(fields["pages"]),
        pdf_pages=_parse_pair(fields["pdf_pages"]),
        body=body,
    )


def load_books(root: Path) -> dict[str, str]:
    """Read corpus/books.yaml. Flat `book_id: book_title`, so no YAML dependency."""
    path = root / "books.yaml"
    if not path.exists():
        return {}
    books: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition(":")
        if sep:
            books[key.strip()] = value.strip()
    return books


def _iter_tables(lines: list[str]):
    """Yield (start_index, block_lines) for each run of consecutive `|` lines."""
    index = 0
    while index < len(lines):
        if lines[index].lstrip().startswith("|"):
            start = index
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                index += 1
            yield start, lines[start:index]
        else:
            index += 1


def _columns(row: str) -> int:
    return len(row.strip().strip("|").split("|"))


def _is_separator(row: str) -> bool:
    cells = row.strip().strip("|").split("|")
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _check_comments(note: SourceNote, where: str) -> list[str]:
    errors: list[str] = []
    markers: list[int] = []
    for raw in COMMENT_RE.findall(note.body):
        marker = PAGE_MARKER_RE.match(raw)
        if marker:
            markers.append(int(marker.group(1)))
        elif SIC_RE.match(raw):
            continue
        elif raw.strip().startswith("sic:"):
            errors.append(f"{where}: malformed sic comment <!--{raw}-->")
        else:
            errors.append(f"{where}: unrecognised HTML comment <!--{raw}-->")

    start, end = note.pages
    for page in markers:
        if page <= start or page > end:
            errors.append(
                f"{where}: page marker p.{page} outside transitions for range "
                f"{start}-{end} (markers mark transitions only)"
            )
    if markers != sorted(set(markers)):
        errors.append(f"{where}: page markers must strictly ascend, got {markers}")
    return errors


def _check_body(note: SourceNote, where: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    # Structural checks ignore page markers and sic comments: a marker legitimately
    # prefixes any line, including a table caption that opens a page.
    lines = [COMMENT_RE.sub("", line) for line in note.body.splitlines()]

    for line in lines:
        if re.match(r"^#\s", line):
            errors.append(f"{where}: body contains an H1 {line.strip()!r}; subsections start at ##")
            break

    for start, block in _iter_tables(lines):
        if len(block) < 2 or not _is_separator(block[1]):
            errors.append(f"{where}: table at body line {start + 1} has no header separator row")
            continue
        widths = {_columns(row) for row in block if not _is_separator(row)}
        if len(widths) > 1:
            errors.append(
                f"{where}: table at body line {start + 1} has inconsistent column "
                f"counts {sorted(widths)}"
            )
        for above in reversed(lines[:start]):
            if not above.strip():
                continue
            caption = CAPTION_RE.match(above.strip())
            if caption:
                warnings.append(f"{where}: caption read above table: {caption.group(1)!r}")
            break

    text = COMMENT_RE.sub("", note.body).strip()
    if len(text) < SHORT_BODY_CHARS:
        warnings.append(f"{where}: body is short ({len(text)} chars) — possible empty section")
    return errors, warnings


def _check_filename(note: SourceNote, path: Path, where: str) -> list[str]:
    errors: list[str] = []
    if path.name != unicodedata.normalize("NFC", path.name):
        errors.append(f"{where}: filename is not NFC-normalized")
    match = FILENAME_RE.match(unicodedata.normalize("NFC", path.name))
    if not match:
        errors.append(f"{where}: filename does not match <NN>-<section>-น.<start>-<end>.md")
        return errors
    _, section, start, end = match.groups()
    if section != note.section:
        errors.append(
            f"{where}: filename section {section!r} disagrees with frontmatter {note.section!r}"
        )
    if (int(start), int(end)) != note.pages:
        errors.append(
            f"{where}: filename page range {start}-{end} disagrees with frontmatter "
            f"{note.pages[0]}-{note.pages[1]}"
        )
    return errors


def validate_corpus(root: Path) -> tuple[list[str], list[str]]:
    """Validate every source note under `root`. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    books = load_books(root)
    seen_uids: dict[str, Path] = {}

    for book_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        notes: list[SourceNote] = []
        for path in sorted(book_dir.glob("*.md")):
            where = f"{book_dir.name}/{path.name}"
            try:
                note = parse_note(path)
            except ValueError as exc:
                errors.append(f"{where}: {exc}")
                continue
            notes.append(note)

            errors.extend(_check_filename(note, path, where))

            if note.uid in seen_uids:
                errors.append(
                    f"{where}: duplicate uid {note.uid!r} (also {seen_uids[note.uid].name})"
                )
            else:
                seen_uids[note.uid] = path

            if note.book_id != book_dir.name:
                errors.append(
                    f"{where}: book_id {note.book_id!r} != parent directory {book_dir.name!r}"
                )
            if note.book_id not in books:
                errors.append(f"{where}: book_id {note.book_id!r} is not in books.yaml")

            if note.pages[0] > note.pages[1]:
                errors.append(f"{where}: pages {note.pages} run backwards")
            if note.pdf_pages[0] > note.pdf_pages[1]:
                errors.append(f"{where}: pdf_pages {note.pdf_pages} run backwards")

            errors.extend(_check_comments(note, where))
            body_errors, body_warnings = _check_body(note, where)
            errors.extend(body_errors)
            warnings.extend(body_warnings)

        ordered = sorted(notes, key=lambda n: n.path.name)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current.ordinal <= previous.ordinal:
                errors.append(
                    f"{book_dir.name}: ordinals move backwards at {current.path.name} "
                    f"(after {previous.path.name})"
                )
            if current.pages[0] < previous.pages[0]:
                errors.append(
                    f"{book_dir.name}: page ranges move backwards at {current.path.name} "
                    f"(after {previous.path.name})"
                )

        covered = {p for n in notes for p in range(n.pages[0], n.pages[1] + 1)}
        if covered:
            gaps = sorted(set(range(min(covered), max(covered) + 1)) - covered)
            if gaps:
                warnings.append(f"{book_dir.name}: page coverage gap at {gaps}")

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="corpus root (the directory holding books.yaml)")
    args = parser.parse_args()

    errors, warnings = validate_corpus(args.root)
    for warning in warnings:
        print(f"WARN  {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)", file=sys.stderr)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
