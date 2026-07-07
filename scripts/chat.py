"""Local terminal chat harness for the TTM advisor -- no LINE, no Chroma.

Drives the *real* consultation spine (`_run_consultation_turn` in the
dispatcher) straight from your terminal against a local MongoDB, so you can
watch the Working Buffer, Health Record, and Health Profile flow work without
a LINE channel, a public tunnel, or an ingested TTM corpus.

What it needs:
  * A Gemini API key (fills both the Advisor Model and Vision Describer slots).
  * MongoDB reachable at MONGODB_URI (the docker-compose one is fine).
  * Dummy LINE_* values in .env -- required by Settings but never used here,
    because this harness never calls the LINE messenger.

What it skips:
  * RAG retrieval is stubbed to return no passages, so Chroma is never opened
    and the BGE-M3 embedding model is never downloaded. Advice is therefore
    *ungrounded* -- fine for smoke-testing plumbing, not a faithful thesis run.
  * The image path (needs Roboflow); this harness is text-only.

Run:
    uv run python scripts/chat.py

Commands inside the REPL:
    /state   show Working Buffer + recent Health Records + Health Profile
    /close   force the current Consultation to close before your next message
             (simulates the >6 h inactivity gap: gate -> record -> profile)
    /user X  switch to acting as user id X (default: local-tester)
    /help    list commands
    /quit    exit
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow `import app.*` when run as `python scripts/chat.py` (script dir, not
# repo root, is sys.path[0] otherwise).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings, get_settings  # noqa: E402
from app.memory.db import get_database  # noqa: E402
from app.memory.health_profile import HealthProfileRepository, empty_profile  # noqa: E402
from app.memory.health_record import HealthRecordRepository  # noqa: E402
from app.memory.profile_render import render_profile  # noqa: E402
from app.memory.working_buffer import WorkingBufferRepository  # noqa: E402
from app.pipeline import dispatcher  # noqa: E402

DEFAULT_USER = "local-tester"
RECORDS_TO_SHOW = 5


async def _no_rag(query: str) -> list[str]:
    """Stub for `retrieve_passages`: no corpus ingested, so no passages.

    Keeping this here (instead of touching the real vector store) is what lets
    the harness run with no Chroma directory and no embedding-model download.
    """
    return []


def _load_settings() -> Settings:
    """Load Settings from .env, failing with a clear message if it can't."""
    try:
        return get_settings()
    except Exception as exc:  # pydantic ValidationError on missing required env
        print(
            "Could not load settings. Copy .env.example to .env and fill in at "
            "least:\n"
            "  ADVISOR_PROVIDER=google / ADVISOR_MODEL / ADVISOR_API_KEY\n"
            "  DESCRIBER_PROVIDER=google / DESCRIBER_MODEL / DESCRIBER_API_KEY\n"
            "  MONGODB_URI (your docker Mongo)\n"
            "  LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN (any dummy value)\n"
            f"\nOriginal error: {exc}"
        )
        raise SystemExit(1) from exc


async def _print_state(settings: Settings, user_id: str) -> None:
    """Dump the three memory stores for `user_id` -- the whole point of the harness."""
    db = get_database(settings)
    buffer_repo = WorkingBufferRepository(db)
    record_repo = HealthRecordRepository(db)
    profile_repo = HealthProfileRepository(db)

    turns = await buffer_repo.current_turns(user_id)
    print(f"\n--- Working Buffer ({len(turns)} turn(s), open Consultation) ---")
    for turn in turns:
        print(f"  [{turn.role}] {turn.text}")

    records = await record_repo.recent(user_id, RECORDS_TO_SHOW)
    print(f"\n--- Health Records (latest {len(records)}) ---")
    if not records:
        print("  (none yet -- close a Consultation with health content to create one)")
    for entry in records:
        print(f"  {entry.consultation_date:%Y-%m-%d}  {entry.chief_complaint}")
        print(f"      summary: {entry.conversation_summary}")

    now = datetime.now(UTC)
    profile = await profile_repo.get(user_id) or empty_profile(user_id, now)
    print("\n--- Health Profile (face sheet) ---")
    print(render_profile(profile, today=now.date()))
    print()


async def _run_turn(settings: Settings, user_id: str, text: str) -> str:
    """One consultation turn through the real dispatcher spine."""
    return await dispatcher._run_consultation_turn(user_id, text, settings)


def _print_help() -> None:
    print(
        "\nCommands:\n"
        "  /state   show Working Buffer + recent Health Records + Health Profile\n"
        "  /close   force-close the current Consultation before your next message\n"
        "  /user X  act as user id X\n"
        "  /help    this help\n"
        "  /quit    exit\n"
        "Anything else is sent to the advisor as a Thai chat message.\n"
    )


async def main() -> None:
    settings = _load_settings()

    # Skip RAG entirely: no Chroma, no BGE-M3 download.
    dispatcher.retrieve_passages = _no_rag

    user_id = DEFAULT_USER
    force_close_next = False

    print("TTM advisor -- local chat harness (no LINE, no Chroma).")
    print(f"Acting as user '{user_id}'. RAG is stubbed -> advice is ungrounded.")
    print("Type /help for commands. First Gemini call may take a few seconds.\n")

    loop = asyncio.get_event_loop()
    while True:
        try:
            raw = await loop.run_in_executor(None, input, f"{user_id}> ")
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return

        text = raw.strip()
        if not text:
            continue

        if text in ("/quit", "/exit"):
            print("bye")
            return
        if text == "/help":
            _print_help()
            continue
        if text == "/state":
            await _print_state(settings, user_id)
            continue
        if text == "/close":
            # The Consultation closes lazily when the next message arrives after
            # the gap. Arm a 0-hour gap so your next real message triggers the
            # Relevance Gate -> Health Record -> Profile Updater path.
            force_close_next = True
            print("Armed: your next message will first close the current Consultation.")
            continue
        if text.startswith("/user "):
            user_id = text[len("/user ") :].strip() or DEFAULT_USER
            print(f"Now acting as user '{user_id}'.")
            continue
        if text.startswith("/"):
            print(f"Unknown command: {text}. Try /help.")
            continue

        turn_settings = settings
        if force_close_next:
            turn_settings = settings.model_copy(update={"consultation_gap_hours": 0.0})
            force_close_next = False

        try:
            reply = await _run_turn(turn_settings, user_id, text)
        except Exception as exc:
            print(f"[error running turn] {type(exc).__name__}: {exc}")
            continue

        print(f"advisor> {reply}\n")


if __name__ == "__main__":
    asyncio.run(main())
