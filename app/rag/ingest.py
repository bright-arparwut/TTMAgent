"""One-off CLI script to embed the TTM corpus into Chroma.

Usage:
    uv run python -m app.rag.ingest path/to/ttm_book.md

Expects the book to already be digitized into Markdown with `#`/`##`/`###`
section headers (OCR + manual structuring happens outside this repo -- see
CONTEXT.md and docs/adr for why the corpus is a single purchased book).
Chunks by the book's own section structure first, then by size, so each
chunk's metadata carries the section headers it came from.
"""

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


def ingest(markdown_path: Path) -> int:
    documents = load_and_chunk(markdown_path)
    store = get_vector_store()
    store.add_documents(documents)
    return len(documents)


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(1)

    markdown_path = Path(sys.argv[1])
    count = ingest(markdown_path)
    print(f"Ingested {count} chunks from {markdown_path} into Chroma.")


if __name__ == "__main__":
    main()
