from datetime import date

from langchain_core.tools import BaseTool, tool

from app.memory.health_record import HealthRecordRepository


def build_health_record_tools(repo: HealthRecordRepository, user_id: str) -> list[BaseTool]:
    """Read-only Health Record tools for one user's Advisor turn.

    Deliberately no write/update/delete tools -- writes happen once,
    deterministically, at Consultation close via the Relevance Gate. See
    docs/adr/0002-health-record-only-memory.md.
    """

    @tool
    async def search_health_records(query: str) -> str:
        """Search this user's past Health Record entries for a keyword or
        topic (e.g. a symptom name) beyond what was already provided in
        the recent-entries summary at the start of this conversation."""
        entries = await repo.search(user_id, query)
        if not entries:
            return "No matching Health Record entries found."
        return "\n\n".join(
            f"{entry.consultation_date.date()}: {entry.conversation_summary}"
            for entry in entries
        )

    @tool
    async def get_health_record_by_date(iso_date: str) -> str:
        """Look up this user's Health Record entries from a specific date
        (ISO format, e.g. 2026-05-01)."""
        entries = await repo.get_by_date(user_id, date.fromisoformat(iso_date))
        if not entries:
            return f"No Health Record entries found for {iso_date}."
        return "\n\n".join(entry.conversation_summary for entry in entries)

    return [search_health_records, get_health_record_by_date]
