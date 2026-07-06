from functools import lru_cache

from langchain_huggingface import HuggingFaceEmbeddings

from app.config import get_settings


@lru_cache
def get_embeddings() -> HuggingFaceEmbeddings:
    """BGE-M3 embeddings, run locally (no hosted API) -- see
    docs/adr and CONTEXT.md for why Chroma + BGE-M3 was chosen over
    Mongo's Atlas-only vector search.
    """
    settings = get_settings()
    return HuggingFaceEmbeddings(model_name=settings.embedding_model_name)
