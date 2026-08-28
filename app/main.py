import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.line.router import router as line_router
from app.rag.embeddings import get_embeddings
from app.tongue_photos.router import router as tongue_photos_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Serving starts only after this completes, so with prewarm on, a
    # reachable server implies the embedding model is resident -- the
    # preflight check (app/preflight.py) relies on that via /health.
    if get_settings().embedding_prewarm:
        await asyncio.to_thread(lambda: get_embeddings().embed_query("อุ่นเครื่อง"))
    yield


app = FastAPI(title="TTM Consultation Assistant", lifespan=lifespan)
app.include_router(line_router)
app.include_router(tongue_photos_router)


@app.get("/health")
async def health() -> dict[str, str]:
    embedding = "ready" if get_embeddings.cache_info().currsize else "cold"
    return {"status": "ok", "embedding": embedding}
