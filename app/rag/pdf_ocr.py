"""One-off CLI to transcribe a scanned TTM book (PDF) into corpus JSONL.

Usage:
    uv run python -m app.rag.pdf_ocr path/to/book.pdf \
        --book-id tamra-ttm --book-title "ตำราแพทย์แผนไทย" \
        [--out corpus/tamra-ttm.jsonl] [--dpi 200]

Each PDF page is rendered to an image and sent to the Vision Describer
model slot (config-selected, must be vision-capable) to transcribe the
Thai/Chinese text page by page, split into paragraphs. The output is one
JSONL record per paragraph:

    {"book_id": ..., "book_title": ..., "page": <printed page number>,
     "pdf_page": <1-based PDF page>, "paragraph": <1-based on the page>,
     "text": ...}

`page` is the page number printed on the scanned page when the model can
read one, falling back to the PDF page index. The JSONL is what
`app.rag.ingest` consumes, so every chunk in Chroma carries the
book/page/paragraph provenance the Advisor cites back to users.

The script appends to an existing output file and skips PDF pages already
present in it, so an interrupted run can simply be re-run.
"""

import argparse
import base64
import json
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage
from PIL import Image
from pydantic import BaseModel, Field

TRANSCRIBE_PROMPT = (
    "You are digitizing one scanned page of a Thai Traditional Medicine "
    "textbook (Thai text with occasional Chinese terms). Transcribe ALL body "
    "text on this page exactly as printed -- keep Thai as Thai and Chinese "
    "characters as Chinese, do not translate, summarize, or correct anything. "
    "Split the transcription into the page's paragraphs, in reading order; "
    "treat headings as their own paragraph. Exclude running headers, footers, "
    "and the printed page number from the paragraph text, but report the "
    "printed page number separately if one is visible. If the page has no "
    "body text (blank page, pure illustration), return an empty paragraph "
    "list."
)


class PageTranscription(BaseModel):
    """Structured output the vision model returns for one scanned page."""

    printed_page_number: int | None = Field(
        default=None,
        description="The page number printed on the page, if visible.",
    )
    paragraphs: list[str] = Field(
        default_factory=list,
        description="Body-text paragraphs in reading order.",
    )


def paragraph_records(
    transcription: PageTranscription,
    *,
    book_id: str,
    book_title: str,
    pdf_page: int,
) -> list[dict]:
    """Turn one page's transcription into corpus JSONL records."""
    page = transcription.printed_page_number or pdf_page
    return [
        {
            "book_id": book_id,
            "book_title": book_title,
            "page": page,
            "pdf_page": pdf_page,
            "paragraph": index,
            "text": text,
        }
        for index, text in enumerate(
            (p.strip() for p in transcription.paragraphs if p.strip()), start=1
        )
    ]


def _already_transcribed(out_path: Path) -> set[int]:
    if not out_path.exists():
        return set()
    return {
        json.loads(line)["pdf_page"]
        for line in out_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _render_page_jpeg(page, dpi: int) -> bytes:
    import io

    pixmap = page.get_pixmap(dpi=dpi)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def transcribe_pdf(
    pdf_path: Path, out_path: Path, *, book_id: str, book_title: str, dpi: int
) -> int:
    import pymupdf

    from app.advisor.llm import build_chat_model
    from app.config import get_settings

    model = build_chat_model(get_settings().describer_slot())
    structured_model = model.with_structured_output(PageTranscription)

    done = _already_transcribed(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0

    with pymupdf.open(pdf_path) as pdf, out_path.open("a", encoding="utf-8") as out:
        for index, page in enumerate(pdf, start=1):
            if index in done:
                continue

            encoded = base64.standard_b64encode(_render_page_jpeg(page, dpi)).decode("utf-8")
            message = HumanMessage(
                content=[
                    {"type": "text", "text": TRANSCRIBE_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                    },
                ]
            )
            transcription = structured_model.invoke([message])

            records = paragraph_records(
                transcription, book_id=book_id, book_title=book_title, pdf_page=index
            )
            for record in records:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            written += len(records)
            print(f"PDF page {index}/{pdf.page_count}: {len(records)} paragraphs", file=sys.stderr)

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--book-id", required=True, help="Stable slug, e.g. tamra-ttm")
    parser.add_argument("--book-title", required=True, help="Title the Advisor cites")
    parser.add_argument("--out", type=Path, default=None, help="Defaults to corpus/<book-id>.jsonl")
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()

    out_path = args.out or Path("corpus") / f"{args.book_id}.jsonl"
    count = transcribe_pdf(
        args.pdf, out_path, book_id=args.book_id, book_title=args.book_title, dpi=args.dpi
    )
    print(f"Wrote {count} paragraph records to {out_path}.")


if __name__ == "__main__":
    main()
