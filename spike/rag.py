"""PROTOTYPE (ticket #16) -- throwaway LightRAG wiring for the naive-vs-mix spike.

Not production code. This deliberately re-uses the repo's real embedding and
model-slot plumbing so the spike also acts as a live check on ticket #11's
plumbing decision, but it is scoped to spike/ and dies with this branch.
"""

import asyncio
import os

import numpy as np
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from lightrag import LightRAG
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.llm_roles import RoleLLMConfig
from lightrag.utils import EmbeddingFunc

from app.advisor.llm import build_chat_model
from app.config import get_settings
from app.rag.embeddings import get_embeddings
from spike.claude_code_llm import build_claude_code_llm

WORKING_DIR = os.path.join(os.path.dirname(__file__), "rag_storage")

# Ticket #11: BGE-M3's CLS head, 1024-dim, 8192-token window. Deliberately NOT
# lightrag.llm.hf.hf_embed, which mean-pools and is wrong for BGE-M3.
EMBEDDING_DIM = 1024
MAX_TOKEN_SIZE = 8192


# PyTorch's MPS backend is not thread-safe, and @lru_cache does not hold a lock
# while it builds its value -- so LightRAG's 8 embedding workers all missed the
# cache at once, each constructed a SentenceTransformer on MPS, and the process
# segfaulted (exit 139) after one document. Pre-warm single-threaded, then admit
# one caller at a time.
_EMBED_LOCK = asyncio.Lock()


def warm_embeddings() -> None:
    """Build the model once, on this thread, before LightRAG can race for it."""
    get_embeddings().embed_documents(["warm"])


async def _embed(texts: list[str]) -> np.ndarray:
    """Local BGE-M3 via the repo's existing HuggingFaceEmbeddings, off-thread."""
    embeddings = get_embeddings()
    async with _EMBED_LOCK:
        vectors = await asyncio.to_thread(embeddings.embed_documents, list(texts))
    return np.array(vectors, dtype=np.float32)


async def _llm(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict] | None = None,
    **kwargs,
) -> str:
    """Adapter over the repo's build_chat_model, as ticket #11 specified.

    LightRAG hands roles a bare async func. Only response_format is forwarded --
    everything else in kwargs is LightRAG internals (hashing_kv, cache keys).
    """
    model = build_chat_model(get_settings().advisor_slot())

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


async def build_spike_rag(
    working_dir: str = WORKING_DIR,
    extract_model: str = "sonnet",
    extract_max_async: int = 3,
) -> LightRAG:
    """LightRAG on its defaults (ticket #10): JsonKV + NanoVectorDB + NetworkX.

    Role split, per map #9: EXTRACT is a batch job and runs on Claude Code
    headless; KEYWORD is in the request path on every LINE message and cannot,
    so it stays on the configured Advisor slot (Gemini 2.5 Flash). QUERY is
    unused -- ticket #13 removed it via only_need_context=True.
    """
    os.makedirs(working_dir, exist_ok=True)
    warm_embeddings()
    rag = LightRAG(
        working_dir=working_dir,
        llm_model_func=_llm,
        llm_model_name=get_settings().advisor_model,
        role_llm_configs={
            "extract": RoleLLMConfig(
                func=build_claude_code_llm(model=extract_model),
                max_async=extract_max_async,
                timeout=600,
                metadata={"backend": "claude-code-headless", "model": extract_model},
            ),
        },
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM,
            max_token_size=MAX_TOKEN_SIZE,
            func=_embed,
        ),
        # One local model on one GPU: extra workers only queue behind the lock.
        embedding_func_max_async=1,
        # Ticket #11: MANDATORY. The default is "English" and would silently
        # extract this Thai book into an English graph.
        addon_params={"language": "Thai"},
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag
