"""Rebuild rag_storage/'s derived vector stores from the authoritative graph.

Run this after any (re-)index of the committed graph -- including after an
edited note's `adelete_by_doc_id` + re-insert (ADR 0010: LightRAG silently
rejects a same-name re-insert, and that re-insert's graph write does not
touch the vector stores on its own). Also the day-before step whenever
`vdb_*.json` is simply missing (it is gitignored and derived, never
committed): `docs/demo-runbook.md`.

The shipped `lightrag-rebuild-vdb` CLI cannot be pointed at this repo's
local BGE-M3 embedding func: its embedding factory
(`lightrag.api.lightrag_server.create_embedding_function_from_args`) only
builds hosted-provider bindings (openai, ollama, jina, azure_openai,
bedrock, gemini, voyageai, lollms) -- there is no local-HuggingFace option
-- and it is interactive (blocks on `input()`), so it cannot run
unattended even for a supported binding. This script instead drives
LightRAG's own library-level rebuild functions
(`lightrag.tools.rebuild_vdb.rebuild_entities_vdb` /
`rebuild_relationships_vdb` / `rebuild_chunks_vdb`) directly, wired to
`app.rag.embeddings.get_embeddings()` (this repo's BGE-M3, CLS-head
pooled) exactly as the live server wires it. See
.superpowers/sdd/phase-0-report.md for the investigation that ruled out
the shipped CLI.

Usage:
    uv run python scripts/rebuild_vdb.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import numpy as np
from lightrag.kg.factory import get_storage_class
from lightrag.kg.shared_storage import finalize_share_data, initialize_share_data
from lightrag.namespace import NameSpace
from lightrag.tools.rebuild_vdb import (
    rebuild_chunks_vdb,
    rebuild_entities_vdb,
    rebuild_relationships_vdb,
)
from lightrag.utils import EmbeddingFunc

# Allow `import app.*` when run as `python scripts/rebuild_vdb.py`
# (script dir, not repo root, is sys.path[0] otherwise) -- see scripts/chat.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.rag.embeddings import get_embeddings  # noqa: E402

EMBEDDING_DIM = 1024
MAX_TOKEN_SIZE = 8192

# BGE-M3 on MPS is not thread-safe and @lru_cache does not hold a lock while
# building its value (ADR 0010 standing hazard): warm single-threaded, then
# serialize every embedding call behind one lock.
_EMBED_LOCK = asyncio.Lock()


def warm_embeddings() -> None:
    get_embeddings().embed_documents(["warm"])


async def _embed(texts: list[str]) -> np.ndarray:
    embeddings = get_embeddings()
    async with _EMBED_LOCK:
        vectors = await asyncio.to_thread(embeddings.embed_documents, list(texts))
    return np.array(vectors, dtype=np.float32)


def build_embedding_func(embed=_embed) -> EmbeddingFunc:
    return EmbeddingFunc(embedding_dim=EMBEDDING_DIM, max_token_size=MAX_TOKEN_SIZE, func=embed)


def build_storages(working_dir: str, embedding_func: EmbeddingFunc) -> tuple[tuple, dict]:
    """Construct the five storages this rebuild touches, matching
    app/preflight.py's `_vdb_consistency_report` wiring so the check that
    runs afterward (`uv run python -m app.preflight`) inspects the exact
    same storages this function writes."""
    global_config: dict[str, Any] = {
        "working_dir": working_dir,
        "kv_storage": "JsonKVStorage",
        "vector_storage": "NanoVectorDBStorage",
        "graph_storage": "NetworkXStorage",
        "embedding_batch_num": 10,
        "vector_db_storage_cls_kwargs": {"cosine_better_than_threshold": 0.2},
        "embedding_func": embedding_func,
    }
    graph = get_storage_class("NetworkXStorage")(
        namespace=NameSpace.GRAPH_STORE_CHUNK_ENTITY_RELATION,
        workspace="",
        global_config=global_config,
        embedding_func=embedding_func,
    )
    entities_vdb = get_storage_class("NanoVectorDBStorage")(
        namespace=NameSpace.VECTOR_STORE_ENTITIES,
        workspace="",
        global_config=global_config,
        embedding_func=embedding_func,
        meta_fields={"entity_name", "source_id", "content", "file_path"},
    )
    relationships_vdb = get_storage_class("NanoVectorDBStorage")(
        namespace=NameSpace.VECTOR_STORE_RELATIONSHIPS,
        workspace="",
        global_config=global_config,
        embedding_func=embedding_func,
        meta_fields={"src_id", "tgt_id", "source_id", "content", "file_path"},
    )
    chunks_vdb = get_storage_class("NanoVectorDBStorage")(
        namespace=NameSpace.VECTOR_STORE_CHUNKS,
        workspace="",
        global_config=global_config,
        embedding_func=embedding_func,
        meta_fields={"full_doc_id", "content", "file_path"},
    )
    text_chunks = get_storage_class("JsonKVStorage")(
        namespace=NameSpace.KV_STORE_TEXT_CHUNKS,
        workspace="",
        global_config=global_config,
        embedding_func=embedding_func,
    )
    return (graph, entities_vdb, relationships_vdb, chunks_vdb, text_chunks), global_config


def _progress(label: str):
    def _report(done: int, total: int) -> None:
        print(f"  {label}: batch {done}/{total}")

    return _report


async def rebuild(working_dir: str, embedding_func: EmbeddingFunc) -> list[dict]:
    """Drop and rebuild the entities/relationships/chunks VDBs from the
    graph + text_chunks KV store. Returns one stats dict per store.

    Assumes `lightrag.kg.shared_storage.initialize_share_data()` has
    already been called once for this process -- the caller owns that
    lifecycle (and the matching `finalize_share_data()`), so this function
    can be exercised directly in tests without a second init clobbering
    shared state.
    """
    storages, global_config = build_storages(working_dir, embedding_func)
    graph, entities_vdb, relationships_vdb, chunks_vdb, text_chunks = storages
    for storage in storages:
        await storage.initialize()
    try:
        return [
            await rebuild_entities_vdb(
                graph, entities_vdb, global_config, progress_callback=_progress("entities")
            ),
            await rebuild_relationships_vdb(
                graph,
                relationships_vdb,
                global_config,
                progress_callback=_progress("relationships"),
            ),
            await rebuild_chunks_vdb(
                text_chunks, chunks_vdb, progress_callback=_progress("chunks")
            ),
        ]
    finally:
        for storage in storages:
            await storage.finalize()


def report(stats: list[dict]) -> bool:
    """Print per-store rebuild counts. Returns True if any store reported errors."""
    had_errors = False
    for s in stats:
        print(
            f"{s['label']}: prepared={s['prepared']} rebuilt={s['rebuilt']} "
            f"skipped={s['skipped']} duplicates={s['duplicates']} errors={len(s['errors'])}"
        )
        if s["errors"]:
            had_errors = True
            print(f"  errors: {s['errors']}")
    return had_errors


async def async_main() -> None:
    settings = get_settings()
    print("Warming BGE-M3 (single-threaded)...")
    warm_embeddings()
    embedding_func = build_embedding_func()

    initialize_share_data(workers=1)
    try:
        stats = await rebuild(settings.rag_storage_dir, embedding_func)
    finally:
        finalize_share_data()

    if report(stats):
        raise SystemExit("rebuild finished with errors -- see above")
    print("Rebuild completed successfully.")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
