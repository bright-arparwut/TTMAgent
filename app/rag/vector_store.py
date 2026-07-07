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
    Docker service, no MongoDB Atlas dependency. See
    docs/adr and CONTEXT.md for why one TTM book doesn't need more than this.
    """
    settings = get_settings()
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=settings.chroma_persist_dir,
    )


async def retrieve_passages(query: str) -> list[str]:
    """Top-k similarity search over the TTM corpus for one Advisor turn.

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
    return [document.page_content for document in documents]
