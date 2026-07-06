from functools import lru_cache

from langchain_chroma import Chroma

from app.config import get_settings
from app.rag.embeddings import get_embeddings

COLLECTION_NAME = "ttm_corpus"


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
    """Top-k similarity search over the TTM corpus for one Advisor turn."""
    settings = get_settings()
    store = get_vector_store()
    documents = await store.asimilarity_search(query, k=settings.rag_top_k)
    return [document.page_content for document in documents]
