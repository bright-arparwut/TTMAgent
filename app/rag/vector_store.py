"""The retrieval seam: `retrieve_passages` over a LightRAG knowledge graph.

ADR 0010 ("TTM Corpus as a LightRAG knowledge graph") is the design source
of truth. One pre-fetched `mix` (or `naive`, the thesis baseline arm) query
per turn via `aquery_data` -- never `aquery(only_need_context=True)`, whose
bare `reference_id`s carry no file_path map and would leave the citation
footer unbuildable.

Citation contract: relations in, entities out. A matched relation
contributes its source note; entities contribute none. `naive` mode has no
relations by construction, so its chunks stand in. Each surviving
reference expands to its complete source note read off disk (whole notes
first, honest chunk-grain fallback when a note would blow the token
budget), numbered in the order the Advisor will cite them. Entity/relation
descriptions ride along as a final, unnumbered "graph context" block --
evidence the Advisor may read but has no id to cite.
"""

import asyncio
import logging
from pathlib import Path

import numpy as np
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from lightrag import LightRAG, QueryParam
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.llm_roles import RoleLLMConfig
from lightrag.utils import EmbeddingFunc

from app.advisor.llm import build_chat_model
from app.config import Settings, get_settings
from app.rag.embeddings import get_embeddings
from app.rag.source_notes import NON_BOOK_DIR_NAMES

logger = logging.getLogger(__name__)

# BGE-M3's CLS head, 1024-dim, 8192-token window. Deliberately NOT
# lightrag's own hf_embed, which mean-pools -- wrong for BGE-M3.
EMBEDDING_DIM = 1024
MAX_TOKEN_SIZE = 8192

# Mirrors app.preflight.AUTHORITATIVE_FILES + DERIVED_VDB_FILES. Duplicated
# rather than imported: preflight is an ops/CLI module and this is a
# request-path seam -- keeping the dependency one-directional (ops checks
# the runtime's assumptions, not the other way around) is worth the two
# short tuples staying in sync by hand.
REQUIRED_STORE_FILES = (
    "graph_chunk_entity_relation.graphml",
    "kv_store_text_chunks.json",
    "kv_store_full_docs.json",
    "kv_store_doc_status.json",
    "vdb_entities.json",
    "vdb_relationships.json",
    "vdb_chunks.json",
)

GRAPH_CONTEXT_LABEL = "[บริบทจากกราฟความรู้ -- หลักฐานประกอบ ไม่มีเลขอ้างอิง]"

# PyTorch's MPS backend is not thread-safe, and @lru_cache does not hold a
# lock while it builds its value -- so unserialized embedding workers can
# each construct a SentenceTransformer on MPS at once and segfault the
# process. Warm single-threaded, then admit one embed call at a time.
_EMBED_LOCK = asyncio.Lock()

# Guards the one process-wide LightRAG build so two concurrent first callers
# of get_rag() can't race to build (and warm-embed) it twice.
_rag: LightRAG | None = None
_rag_build_lock = asyncio.Lock()


def _warm_embeddings() -> None:
    """Build the embedding model once, on this thread, before LightRAG's
    embedding workers can race for it."""
    get_embeddings().embed_documents(["warm"])


async def _embed(texts: list[str]) -> np.ndarray:
    """Local BGE-M3 via the repo's existing HuggingFaceEmbeddings, off-thread."""
    embeddings = get_embeddings()
    async with _EMBED_LOCK:
        vectors = await asyncio.to_thread(embeddings.embed_documents, list(texts))
    return np.array(vectors, dtype=np.float32)


async def _keyword_llm(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict] | None = None,
    **kwargs,
) -> str:
    """Adapter over app.advisor.llm.build_chat_model for LightRAG's KEYWORD
    (and, for construction validity only, QUERY) role. LightRAG hands roles
    a bare async func; only response_format is forwarded from kwargs --
    everything else is LightRAG internals (hashing_kv, cache keys).

    KEYWORD is the one place LINE user text leaves the machine, so it runs
    on a dedicated flash-tier hosted slot -- never Claude Code headless,
    never the Advisor slot.
    """
    model = build_chat_model(get_settings().keyword_slot())

    response_format = kwargs.get("response_format")
    if response_format is None and kwargs.get("keyword_extraction"):
        response_format = {"type": "json_object"}  # deprecated shim, 1.5.6
    if response_format is not None:
        model = model.bind(response_format=response_format)

    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    for turn in history_messages or []:
        role = turn.get("role")
        content = turn.get("content", "")
        cls = AIMessage if role == "assistant" else HumanMessage
        messages.append(cls(content=content))
    messages.append(HumanMessage(content=prompt))

    result = await model.ainvoke(messages)
    return result.content if isinstance(result.content, str) else str(result.content)


def _check_store_present(settings: Settings) -> None:
    """Boot failure, not silent degrade (ADR 0010): `[]` is never a silent
    steady state, so a missing graph or missing derived vectors must be
    loud, not a quiet empty-retrieval fallback.
    """
    storage = Path(settings.rag_storage_dir)
    missing = [name for name in REQUIRED_STORE_FILES if not (storage / name).exists()]
    if missing:
        raise RuntimeError(
            f"{settings.rag_storage_dir} is missing required file(s): {', '.join(missing)}. "
            "The committed graph (graphml + KV stores) restores from git; the derived "
            "vdb_*.json files rebuild locally via `lightrag-rebuild-vdb` "
            "(docs/adr/0010-graphrag-lightrag-corpus.md) -- run it before starting the app."
        )


async def _build_rag(settings: Settings) -> LightRAG:
    _check_store_present(settings)
    await asyncio.to_thread(_warm_embeddings)

    rag = LightRAG(
        working_dir=settings.rag_storage_dir,
        llm_model_func=_keyword_llm,
        llm_model_name=settings.keyword_model,
        # Role keys are singular (LightRAG raises on plural). QUERY gets the
        # same adapter for construction validity but is never invoked: we
        # only ever call aquery_data, which stops before generation.
        role_llm_configs={
            "keyword": RoleLLMConfig(func=_keyword_llm),
            "query": RoleLLMConfig(func=_keyword_llm),
        },
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM, max_token_size=MAX_TOKEN_SIZE, func=_embed
        ),
        # One local model on one GPU: extra workers only queue behind the lock.
        embedding_func_max_async=1,
        # MANDATORY (ADR 0010): the default is "English" and would silently
        # extract/query this Thai corpus in English.
        addon_params={"language": "Thai"},
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag


async def get_rag() -> LightRAG:
    """The one process-wide LightRAG instance, built once and reused."""
    global _rag
    if _rag is not None:
        return _rag
    async with _rag_build_lock:
        if _rag is None:
            _rag = await _build_rag(get_settings())
    return _rag


def _count_tokens(rag: LightRAG, text: str) -> int:
    return len(rag.tokenizer.encode(text))


def _strip_frontmatter(raw: str) -> str:
    """Source notes carry YAML frontmatter (ticket #12); the Advisor reads
    the body only -- metadata that must survive chunking already rides in
    the filename, which becomes the note's citation label.
    """
    if not raw.startswith("---\n"):
        return raw.strip()
    end = raw.find("\n---\n", 4)
    if end == -1:
        return raw.strip()
    return raw[end + len("\n---\n") :].strip()


def _find_note_body(corpus_dir: Path, filename: str) -> str | None:
    """Search the book folders for `filename` -- the filename is unique
    (it's the citation), so the first hit across book dirs is the note."""
    if not corpus_dir.is_dir():
        return None
    for book_dir in sorted(p for p in corpus_dir.iterdir() if p.is_dir()):
        if book_dir.name in NON_BOOK_DIR_NAMES:
            continue
        candidate = book_dir / filename
        if candidate.exists():
            return _strip_frontmatter(candidate.read_text(encoding="utf-8"))
    return None


def _chunk_content_for_file_path(chunks: list[dict], file_path: str) -> str | None:
    for chunk in chunks:
        if chunk.get("file_path") == file_path and chunk.get("content"):
            return chunk["content"].strip()
    return None


def _fit_reference(
    rag: LightRAG,
    corpus_dir: Path,
    chunks: list[dict],
    file_path: str,
    label: str,
    remaining_budget: int,
) -> tuple[str, int] | None:
    """Whole note first; when it would blow the remaining budget, fall back
    to the (smaller) indexed chunk text for the same reference -- an honest
    chunk-grain fallback rather than silently dropping the reference."""
    filename = Path(file_path).name
    note_body = _find_note_body(corpus_dir, filename)
    if note_body is not None:
        whole = f"{label}\n{note_body}"
        cost = _count_tokens(rag, whole)
        if cost <= remaining_budget:
            return whole, cost

    chunk_text = _chunk_content_for_file_path(chunks, file_path)
    if chunk_text is not None:
        fallback = f"{label}\n{chunk_text}"
        cost = _count_tokens(rag, fallback)
        if cost <= remaining_budget:
            return fallback, cost

    return None


def _build_numbered_notes(
    rag: LightRAG, settings: Settings, reference_items: list[dict], chunks: list[dict]
) -> list[str]:
    corpus_dir = Path(settings.corpus_dir)
    budget = settings.rag_section_token_budget
    used = 0
    notes: list[str] = []
    seen: set[str] = set()

    for item in reference_items:
        file_path = item.get("file_path")
        if not file_path or file_path in seen:
            continue
        seen.add(file_path)

        label = f"[{len(notes) + 1}] {Path(file_path).name.removesuffix('.md')}"
        fit = _fit_reference(rag, corpus_dir, chunks, file_path, label, budget - used)
        if fit is None:
            continue
        note_text, cost = fit
        notes.append(note_text)
        used += cost

    return notes


def _budgeted_lines(rag: LightRAG, lines: list[str], budget: int) -> list[str]:
    used = 0
    kept: list[str] = []
    for line in lines:
        cost = _count_tokens(rag, line)
        if used + cost > budget:
            continue
        kept.append(line)
        used += cost
    return kept


def _build_graph_context(
    rag: LightRAG, settings: Settings, entities: list[dict], relationships: list[dict]
) -> str | None:
    """Entity/relation descriptions, capped separately -- evidence the
    Advisor may read but has no id to cite (ADR 0010's open question on how
    much weight to give this is a prompt concern, not this seam's)."""
    entity_lines = _budgeted_lines(
        rag,
        [
            f"- {entity.get('entity_name', '')} ({entity.get('entity_type', '')}): "
            f"{entity.get('description', '')}"
            for entity in entities
            if entity.get("description")
        ],
        settings.rag_entity_token_budget,
    )
    relation_lines = _budgeted_lines(
        rag,
        [
            f"- {relation.get('src_id', '')} – {relation.get('tgt_id', '')}: "
            f"{relation.get('description', '')}"
            for relation in relationships
            if relation.get("description")
        ],
        settings.rag_relation_token_budget,
    )

    if not entity_lines and not relation_lines:
        return None

    sections = [GRAPH_CONTEXT_LABEL]
    if entity_lines:
        sections.append("เอนทิตี:\n" + "\n".join(entity_lines))
    if relation_lines:
        sections.append("ความสัมพันธ์:\n" + "\n".join(relation_lines))
    return "\n".join(sections)


async def _query_with_degrade(rag: LightRAG, query: str, mode: str) -> tuple[dict, str] | None:
    """Run `aquery_data` in `mode`; on failure (a transient KEYWORD-call
    failure is the expected case for kg modes), retry once in `naive` --
    grounded but flat -- logged at ERROR. `[]` is never a silent steady
    state, so a second failure is also logged, not swallowed quietly."""
    try:
        raw = await rag.aquery_data(query, param=QueryParam(mode=mode, enable_rerank=False))
        return raw, mode
    except Exception:
        logger.error(
            "LightRAG retrieval failed in mode=%r; degrading to naive", mode, exc_info=True
        )

    if mode == "naive":
        return None

    try:
        raw = await rag.aquery_data(query, param=QueryParam(mode="naive", enable_rerank=False))
        return raw, "naive"
    except Exception:
        logger.error(
            "LightRAG naive-mode degrade also failed; returning no passages", exc_info=True
        )
        return None


async def retrieve_passages(query: str) -> list[str]:
    """One pre-fetched LightRAG query for this Advisor turn. Returns
    numbered, citable source notes (relations in, entities out; `naive`
    mode's chunks stand in for the relations it doesn't have) followed by
    an optional unnumbered graph-context passage. See module docstring and
    ADR 0010 -- "The retrieval seam" -- for the full contract.
    """
    settings = get_settings()
    rag = await get_rag()

    result = await _query_with_degrade(rag, query, settings.rag_query_mode)
    if result is None:
        return []
    raw, mode = result

    data = raw.get("data") or {}
    entities = data.get("entities") or []
    relationships = data.get("relationships") or []
    chunks = data.get("chunks") or []

    reference_items = list(relationships)
    if mode == "naive":
        reference_items = reference_items + list(chunks)

    passages = _build_numbered_notes(rag, settings, reference_items, chunks)

    graph_context = _build_graph_context(rag, settings, entities, relationships)
    if graph_context is not None:
        passages.append(graph_context)

    return passages
