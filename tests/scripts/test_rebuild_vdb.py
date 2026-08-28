"""Unit test for scripts/rebuild_vdb.py -- the local BGE-M3 VDB rebuild driver
(ADR 0010, .superpowers/sdd/phase-0-report.md).

Exercises the real rebuild path (real LightRAG storage classes, real
rag_storage/ file layout) against a tiny synthetic graph seeded directly
through the storage API, with a fake embedding func standing in for BGE-M3
-- no model download, no network, safe to run in CI.
"""

import numpy as np
from lightrag.kg.factory import get_storage_class
from lightrag.kg.shared_storage import finalize_share_data, initialize_share_data
from lightrag.namespace import NameSpace
from lightrag.utils import EmbeddingFunc

from scripts.rebuild_vdb import build_embedding_func, rebuild, report

FAKE_DIM = 8


async def _fake_embed(texts: list[str]) -> np.ndarray:
    # Deterministic, non-zero vectors -- nano-vectordb L2-normalizes on
    # store, and an all-zero vector divides by a zero norm.
    rng = np.random.default_rng(seed=0)
    return rng.random((len(texts), FAKE_DIM)).astype(np.float32)


def _seed_global_config(working_dir, embedding_func: EmbeddingFunc) -> dict:
    return {
        "working_dir": str(working_dir),
        "kv_storage": "JsonKVStorage",
        "vector_storage": "NanoVectorDBStorage",
        "graph_storage": "NetworkXStorage",
        "embedding_batch_num": 10,
        "vector_db_storage_cls_kwargs": {"cosine_better_than_threshold": 0.2},
        "embedding_func": embedding_func,
    }


async def _seed_rag_storage(working_dir, embedding_func: EmbeddingFunc) -> None:
    """Write a minimal graph (2 nodes, 1 edge) + 1 text chunk directly
    through the real storage classes, so the rebuild under test reads real
    on-disk files -- the same shape app/preflight.py inspects afterward."""
    global_config = _seed_global_config(working_dir, embedding_func)
    graph = get_storage_class("NetworkXStorage")(
        namespace=NameSpace.GRAPH_STORE_CHUNK_ENTITY_RELATION,
        workspace="",
        global_config=global_config,
        embedding_func=embedding_func,
    )
    text_chunks = get_storage_class("JsonKVStorage")(
        namespace=NameSpace.KV_STORE_TEXT_CHUNKS,
        workspace="",
        global_config=global_config,
        embedding_func=embedding_func,
    )
    await graph.initialize()
    await text_chunks.initialize()

    await graph.upsert_node(
        "ธาตุไฟ",
        {"description": "fire element", "source_id": "chunk-1", "file_path": "corpus/x.md"},
    )
    await graph.upsert_node(
        "ธาตุน้ำ",
        {"description": "water element", "source_id": "chunk-1", "file_path": "corpus/x.md"},
    )
    await graph.upsert_edge(
        "ธาตุไฟ",
        "ธาตุน้ำ",
        {
            "description": "opposes",
            "keywords": "opposition",
            "weight": 1.0,
            "source_id": "chunk-1",
            "file_path": "corpus/x.md",
        },
    )
    await text_chunks.upsert(
        {
            "chunk-1": {
                "content": "some chunk text",
                "tokens": 5,
                "chunk_order_index": 0,
                "full_doc_id": "doc-1",
            }
        }
    )

    await graph.index_done_callback()
    await text_chunks.index_done_callback()
    await graph.finalize()
    await text_chunks.finalize()


async def test_rebuild_writes_vdb_files_matching_the_seeded_graph(tmp_path):
    working_dir = tmp_path / "rag_storage"
    working_dir.mkdir()
    embedding_func = EmbeddingFunc(embedding_dim=FAKE_DIM, max_token_size=100, func=_fake_embed)

    initialize_share_data(workers=1)
    try:
        await _seed_rag_storage(working_dir, embedding_func)
        stats = await rebuild(str(working_dir), embedding_func)
    finally:
        finalize_share_data()

    by_label = {s["label"]: s for s in stats}
    assert by_label["entities"]["rebuilt"] == 2
    assert by_label["entities"]["errors"] == []
    assert by_label["relationships"]["rebuilt"] == 1
    assert by_label["relationships"]["errors"] == []
    assert by_label["chunks"]["rebuilt"] == 1
    assert by_label["chunks"]["errors"] == []
    assert report(stats) is False

    assert (working_dir / "vdb_entities.json").exists()
    assert (working_dir / "vdb_relationships.json").exists()
    assert (working_dir / "vdb_chunks.json").exists()


def _stats(label: str, *, rebuilt: int, errors: list | None = None) -> dict:
    return {
        "label": label,
        "prepared": rebuilt,
        "rebuilt": rebuilt,
        "skipped": 0,
        "duplicates": 0,
        "errors": errors or [],
    }


def test_report_returns_true_when_any_store_has_errors():
    stats = [
        _stats("entities", rebuilt=1),
        _stats(
            "chunks",
            rebuilt=0,
            errors=[{"batch": 1, "error_type": "RuntimeError", "error_msg": "boom"}],
        ),
    ]
    assert report(stats) is True


def test_report_returns_false_when_no_store_has_errors():
    assert report([_stats("entities", rebuilt=1)]) is False


def test_build_embedding_func_carries_the_bge_m3_dimensions():
    embedding_func = build_embedding_func(embed=_fake_embed)
    assert embedding_func.embedding_dim == 1024
    assert embedding_func.max_token_size == 8192
