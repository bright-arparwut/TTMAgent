import logging
from functools import lru_cache
from pathlib import Path

from langchain_chroma import Chroma

from app.config import get_settings
from app.rag.embeddings import get_embeddings

COLLECTION_NAME = "ttm_corpus"

logger = logging.getLogger(__name__)


@lru_cache
def get_vector_store() -> Chroma:
    """Embedded Chroma store persisted to a local folder -- no separate
    Docker service, no MongoDB Atlas dependency. A thesis-scale corpus of a
    few books doesn't need more than this; see CONTEXT.md (TTM Corpus) and
    docs/adr/0008-scanned-corpus-page-provenance.md.
    """
    settings = get_settings()
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=settings.chroma_persist_dir,
    )


def _format_passage(document) -> str:
    """Prefix a retrieved chunk with its source tag so the Advisor can cite it.

    JSONL-ingested chunks (scanned books, see app.rag.pdf_ocr) carry
    book/page/paragraph provenance; Markdown-ingested chunks carry section
    headers. Chunks with neither pass through untagged.
    """
    metadata = document.metadata or {}
    if "page" in metadata:
        title = metadata.get("book_title") or metadata.get("book_id", "")
        tag = f"[{title} หน้า {metadata['page']} ย่อหน้าที่ {metadata['paragraph']}]"
        return f"{tag}\n{document.page_content}"

    headers = [metadata[key] for key in ("chapter", "section", "subsection") if metadata.get(key)]
    if headers:
        return f"[{' > '.join(headers)}]\n{document.page_content}"
    return document.page_content


async def retrieve_passages(query: str) -> list[str]:
    """Top-k similarity search over the TTM corpus for one Advisor turn.
    Each passage is prefixed with a source tag (book / page / paragraph)
    so the Advisor can tell the user where its advice comes from.

    When the corpus has never been ingested (no persist dir), skip retrieval
    entirely: building the store would load the multi-GB embedding model --
    synchronously, on the event loop -- just to search an empty collection.
    """
    settings = get_settings()
    if not Path(settings.chroma_persist_dir).exists():
        logger.warning(
            "Chroma persist dir %s does not exist -- TTM corpus not ingested; "
            "Advisor runs without retrieved passages",
            settings.chroma_persist_dir,
        )
        return []

    store = get_vector_store()
    documents = await store.asimilarity_search(query, k=settings.rag_top_k)
    return [_format_passage(document) for document in documents]
