"""One-off CLI script to embed the TTM corpus into Chroma.

Usage:
    uv run python -m app.rag.ingest corpus/tamra-ttm.jsonl
    uv run python -m app.rag.ingest path/to/ttm_book.md

Two input formats:

- `.jsonl` -- one record per paragraph, as produced by `app.rag.pdf_ocr` or
  `app.rag.corpus_merge` from a scanned book: {"book_id", "book_title",
  "page", "paragraph", "text", ...}. Each paragraph becomes a chunk whose
  metadata carries the book/page/paragraph provenance, stored under a
  deterministic ID (`<book_id>:p<page>:para<paragraph>`) so re-running
  ingest updates chunks in place instead of duplicating them. Oversized
  paragraphs are split by size; every piece keeps the full provenance
  metadata.

- `.md` -- a book digitized to Markdown with `#`/`##`/`###` section
  headers. Chunks by the section structure first, then by size, so each
  chunk's metadata carries the section headers it came from. No page
  provenance is available on this path.
"""

import json
import sys
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.rag.vector_store import get_vector_store

HEADERS_TO_SPLIT_ON = [("#", "chapter"), ("##", "section"), ("###", "subsection")]
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def load_and_chunk(markdown_path: Path) -> list[Document]:
    text = markdown_path.read_text(encoding="utf-8")

    header_splitter = MarkdownHeaderTextSplitter(HEADERS_TO_SPLIT_ON)
    by_section = header_splitter.split_text(text)

    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    return size_splitter.split_documents(by_section)


def load_jsonl(jsonl_path: Path) -> tuple[list[Document], list[str]]:
    """One chunk per paragraph record, with provenance metadata and a
    deterministic ID. A paragraph longer than the chunk size is split, each
    piece keeping the same page/paragraph metadata under a `:c<n>` ID suffix.
    """
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )

    documents: list[Document] = []
    ids: list[str] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        metadata = {
            "book_id": record["book_id"],
            "book_title": record["book_title"],
            "page": record["page"],
            "paragraph": record["paragraph"],
        }
        base_id = f"{record['book_id']}:p{record['page']}:para{record['paragraph']}"

        pieces = size_splitter.split_text(record["text"])
        for index, piece in enumerate(pieces, start=1):
            documents.append(Document(page_content=piece, metadata=dict(metadata)))
            ids.append(base_id if len(pieces) == 1 else f"{base_id}:c{index}")

    return documents, ids


def ingest(corpus_path: Path) -> int:
    store = get_vector_store()
    if corpus_path.suffix == ".jsonl":
        documents, ids = load_jsonl(corpus_path)
        store.add_documents(documents, ids=ids)
    else:
        documents = load_and_chunk(corpus_path)
        store.add_documents(documents)
    return len(documents)


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(1)

    corpus_path = Path(sys.argv[1])
    count = ingest(corpus_path)
    print(f"Ingested {count} chunks from {corpus_path} into Chroma.")


if __name__ == "__main__":
    main()
