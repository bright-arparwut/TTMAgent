"""One-off CLI to merge per-page transcription JSON into ADR 0008 corpus JSONL.

Usage:
    uv run python -m app.rag.corpus_merge $SCRATCH/out/tcm-basic-theory \
        --book-id tcm-basic-theory --book-title "ทฤษฎีพื้นฐานการแพทย์แผนจีน" \
        --pdf-pages 104 [--first-body-pdf-page 11] \
        [--out corpus/tcm-basic-theory.jsonl] \
        [--front-out corpus/tcm-basic-theory-front-matter.jsonl]

Input: one p<NNN>.json per PDF page, written by the transcription/verify
sub-agents: {"printed_page_number": int|null, "paragraphs": [str], ...}.
Leading/trailing runs of unnumbered pages become front/back matter under
book_id "<book-id>-front" with page = pdf_page; unnumbered pages inside the
body get their printed page interpolated from the nearest numbered page.
By default the body's leading edge is guessed as the first printed page
number, which misfiles an unnumbered chapter opener into front matter;
pass --first-body-pdf-page to state the boundary explicitly instead.
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
            printed_page_number = data["printed_page_number"]
            is_valid_printed_page = printed_page_number is None or (
                isinstance(printed_page_number, int) and not isinstance(printed_page_number, bool)
            )
            if not is_valid_printed_page:
                errors.append(
                    f"unreadable {path.name}: printed_page_number must be int or null, "
                    f"got {printed_page_number!r}"
                )
                continue
            pages.append(
                PageFile(
                    pdf_page=index,
                    printed_page_number=printed_page_number,
                    paragraphs=list(data["paragraphs"]),
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            errors.append(f"unreadable {path.name}: {exc}")
    return pages, errors


def split_runs(
    pages: list[PageFile], *, first_body_pdf_page: int | None = None
) -> tuple[list[PageFile], list[PageFile], list[PageFile]]:
    """Split into (front, body, back): leading/trailing unnumbered runs vs the numbered body.

    By default the body's leading edge is guessed as the first page carrying a printed
    page number, which misfiles an unnumbered chapter opener (no printed number, but
    body prose) into front matter. Pass first_body_pdf_page to state the boundary
    explicitly instead of guessing: the front run becomes exactly the pages before it,
    and the body starts there. The trailing back-matter split is unaffected either way
    -- the body always ends at the last numbered page.
    """
    numbered = [i for i, p in enumerate(pages) if p.printed_page_number is not None]
    if first_body_pdf_page is not None:
        first = next((i for i, p in enumerate(pages) if p.pdf_page >= first_body_pdf_page), None)
    else:
        first = numbered[0] if numbered else None
    if first is None or not numbered:
        return list(pages), [], []
    last = max(numbered)
    return list(pages[:first]), list(pages[first : last + 1]), list(pages[last + 1 :])


def assign_printed_pages(body: list[PageFile]) -> list[tuple[int, int, list[str]]]:
    """Resolve each body page to its printed number, interpolating unnumbered pages.

    Unnumbered body pages anchor to the nearest following numbered page's offset,
    since scan gaps typically precede chapter openers. The preceding-page fallback
    is defensive only: it is unreachable from main(), since split_runs always ends
    the body on the last numbered page, so a following anchor always exists.
    """
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
            following = [pdf for pdf in known_offsets if pdf > page_file.pdf_page]
            preceding = [pdf for pdf in known_offsets if pdf < page_file.pdf_page]
            anchor = min(following) if following else max(preceding)
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
    """ADR 0008 conformance errors; empty list means the records are clean.

    Paragraph contiguity is keyed on the printed `page`, not `pdf_page`: chunk IDs
    are `<book_id>:p<page>:para<paragraph>`, so two different pdf pages resolving to
    the same printed page must not silently produce colliding IDs. A separate,
    explicit duplicate-chunk-ID check catches exactly that collision.
    """
    errors = []
    previous_page = None
    expected_paragraph: dict[int, int] = {}
    seen_chunk_ids: dict[str, int] = {}
    for line, record in enumerate(records, start=1):
        if list(record.keys()) != REQUIRED_KEYS:
            errors.append(f"line {line}: keys {list(record.keys())} != {REQUIRED_KEYS}")
            continue
        if record["book_id"] != book_id:
            errors.append(f"line {line}: book_id mismatch: {record['book_id']!r} != {book_id!r}")
        if record["book_title"] != book_title:
            errors.append(
                f"line {line}: book_title mismatch: {record['book_title']!r} != {book_title!r}"
            )
        for field in ("page", "pdf_page", "paragraph"):
            value = record[field]
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"line {line}: {field} {value!r} is not an int")
        if not isinstance(record["text"], str):
            errors.append(f"line {line}: text {record['text']!r} is not a str")
        if not str(record["text"]).strip():
            errors.append(f"line {line}: empty text")
        page = record["page"]
        expected = expected_paragraph.get(page, 1)
        if record["paragraph"] != expected:
            errors.append(
                f"line {line}: paragraph {record['paragraph']} on page {page}, expected {expected}"
            )
        expected_paragraph[page] = record["paragraph"] + 1
        chunk_id = f"{record['book_id']}:p{page}:para{record['paragraph']}"
        if chunk_id in seen_chunk_ids:
            errors.append(
                f"line {line}: duplicate chunk id {chunk_id} "
                f"(first seen at line {seen_chunk_ids[chunk_id]})"
            )
        else:
            seen_chunk_ids[chunk_id] = line
        page_is_int = isinstance(page, int) and not isinstance(page, bool)
        if previous_page is not None and page_is_int and page < previous_page:
            errors.append(f"line {line}: page {page} decreasing (after {previous_page})")
        if page_is_int:
            previous_page = page
    return errors


def front_matter_records(
    front: list[PageFile], back: list[PageFile], *, book_id: str, book_title: str
) -> list[dict]:
    """Build front/back-matter records: ADR 0008 sets page = pdf_page under book_id-front."""
    return to_records(
        [(p.pdf_page, p.pdf_page, p.paragraphs) for p in front + back],
        book_id=f"{book_id}-front",
        book_title=book_title,
    )


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
    parser.add_argument(
        "--first-body-pdf-page",
        type=int,
        default=None,
        help=(
            "1-based pdf page where the body starts, when the guessed boundary "
            "(first printed page number) would misfile an unnumbered chapter "
            "opener into front matter."
        ),
    )
    args = parser.parse_args()

    out_path = args.out or Path("corpus") / f"{args.book_id}.jsonl"
    front_path = args.front_out or Path("corpus") / f"{args.book_id}-front-matter.jsonl"

    pages, errors = load_page_files(args.pages_dir, args.pdf_pages)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)

    front, body, back = split_runs(pages, first_body_pdf_page=args.first_body_pdf_page)
    body_records = to_records(
        assign_printed_pages(body), book_id=args.book_id, book_title=args.book_title
    )
    front_records = front_matter_records(
        front, back, book_id=args.book_id, book_title=args.book_title
    )

    validation_errors = validate_records(
        body_records, book_id=args.book_id, book_title=args.book_title
    ) + validate_records(front_records, book_id=f"{args.book_id}-front", book_title=args.book_title)
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
