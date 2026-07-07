from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from app.advisor.llm import build_chat_model
from app.advisor.prompts import SYSTEM_PROMPT
from app.config import Settings


def build_advisor_agent(settings: Settings, tools: list[BaseTool]) -> CompiledStateGraph:
    """The Advisor Model's tool-calling loop.

    A prebuilt ReAct-style graph is deliberately used instead of a hand-rolled
    StateGraph: the only agentic part of the pipeline is this tool loop (see
    docs/design-decisions.html -> "Deterministic spine in plain Python;
    LangGraph only for the advisor loop"). Continuity across turns comes
    from our own Health Record system (see app/memory), not from LangGraph
    checkpointing, so no checkpointer is configured here.
    """
    model = build_chat_model(settings.advisor_slot())
    return create_react_agent(model, tools, prompt=SYSTEM_PROMPT)


def _content_to_text(content: object) -> str:
    """Flatten an LLM message's `.content` to a plain string.

    Gemini (and other providers) return `.content` as a *list* of content
    blocks when thinking is enabled -- a thought-signature block alongside the
    visible text block(s) -- instead of a bare string. ConsultationTurn.text
    requires a str, so extract and join the text blocks and drop the rest.
    See docs/message-flow.md -> the advisor reply lane.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def _build_context_block(
    retrieved_passages: list[str],
    recent_records_summary: str,
    health_profile_block: str,
) -> str:
    sections = []
    if health_profile_block:
        sections.append(f"Health Profile (current face sheet):\n{health_profile_block}")
    if recent_records_summary:
        sections.append(f"Recent Health Record entries for this user:\n{recent_records_summary}")
    if retrieved_passages:
        joined = "\n\n".join(retrieved_passages)
        sections.append(f"Relevant TTM reference material:\n{joined}")
    return "\n\n".join(sections)


async def run_advisor(
    agent: CompiledStateGraph,
    *,
    user_message: str,
    retrieved_passages: list[str],
    recent_records_summary: str,
    health_profile_block: str = "",
) -> str:
    """Run one Advisor turn and return its final Thai-language reply text."""
    context_block = _build_context_block(
        retrieved_passages, recent_records_summary, health_profile_block
    )
    text = (
        f"{context_block}\n\n---\n\nUser message: {user_message}"
        if context_block
        else user_message
    )

    result = await agent.ainvoke({"messages": [HumanMessage(content=text)]})
    final_message = result["messages"][-1]
    return _content_to_text(final_message.content)
