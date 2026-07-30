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
                f"line {line}: paragraph {record['paragraph']} on pdf_page {pdf_page}, "
                f"expected {expected}"
            )
        expected_paragraph[pdf_page] = record["paragraph"] + 1
        if previous_page is not None and record["page"] < previous_page:
            errors.append(
                f"line {line}: page {record['page']} decreasing "
                f"(after {previous_page})"
            )
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
                f"OFFSET pdf_page {page_file.pdf_page}: printed-pdf offset "
                f"{previous} -> {offset}"
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
