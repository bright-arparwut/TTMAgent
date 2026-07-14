# Topic Menu Delimiter Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cap Advisor replies to one phone screen and render held-back follow-up topics as LINE Quick Reply buttons, parsed from a `[หัวข้อ]` delimiter block at the end of the Advisor's plain-text reply (ADR 0006).

**Architecture:** The Advisor's system prompt teaches it to end replies with a marked delimiter block listing 2–5 topics. A new pure parser (`app/advisor/topic_menu.py`) splits the raw reply into visible text + topics; the dispatcher stores the **raw** reply (block included) in the Working Buffer so the Advisor can resolve "ข้อสอง" next turn, and sends the **visible** text with Quick Reply buttons via `LineMessenger`. No structured output, no LangGraph changes — if the parser finds no block, everything degrades to today's behavior.

**Tech Stack:** Python 3.11, FastAPI, line-bot-sdk v3 (`QuickReply`/`QuickReplyItem`/`MessageAction`), pytest (asyncio_mode=auto), uv, ruff.

## Global Constraints

- Spec: `docs/adr/0006-topic-menu-delimiter-protocol.md` + CONTEXT.md → "Topic Menu".
- Delimiter marker is exactly `[หัวข้อ]` on its own line; the format is a **contract between `app/advisor/prompts.py` and the parser** — a task that changes one side must keep the contract test green against both.
- Hard limits live in code, not the prompt: at most **5 topics**, each topic **≤ 20 characters** (LINE Quick Reply caps: 13 items / 20-char labels; the SDK does NOT validate label length locally — verified on line-bot-sdk 3.24 — so our cap is the only guard against LINE API 400s).
- Parsing is forgiving: accepts `-`, `•`, `*`, numbered items (`1.` / `1)`), and bare lines after the marker; a missing/malformed block degrades to sending the whole text.
- Red-flag escalations carry no menu and are exempt from the length cap — enforced in the prompt (there is no code-level red-flag branch, matching the existing design).
- The in-body intake rule stays at one woven intake question; the menu may additionally carry at most one intake item (ADR 0006 consequence).
- Working Buffer stores the raw reply including the delimiter block.
- Frozen/immutable data types (house style: `frozen=True`), type annotations on all signatures, ruff line-length 100.
- Test runner: `uv run pytest` (asyncio auto mode — async tests need no decorator). Lint: `uv run ruff check .`
- All user-facing Thai copy in this plan is exact — copy it verbatim.

## File Structure

- **Create** `app/advisor/topic_menu.py` — the parser + `ParsedReply` type + the two limit constants. Lives in `advisor/` because it is the Advisor-output side of the contract, not LINE transport.
- **Create** `tests/advisor/test_topic_menu.py` — parser behavior.
- **Modify** `app/line/messaging.py` — new `build_text_message()` helper; `reply`/`push`/`reply_or_push` accept optional `topics`.
- **Create** `tests/line/test_messaging.py` — Quick Reply rendering.
- **Modify** `app/pipeline/dispatcher.py` — `_run_consultation_turn` returns `ParsedReply` (raw stored, visible sent); both handlers forward topics.
- **Create** `tests/pipeline/test_dispatcher_topic_menu.py` — end-to-end wiring.
- **Modify** `tests/pipeline/test_dispatcher_images.py`, `tests/pipeline/test_dispatcher_profile.py` — adapt to the new return type / messenger signature.
- **Modify** `app/advisor/prompts.py` — reply-length rule + Topic Menu block instructions.
- **Create** `tests/advisor/test_prompt_topic_menu_contract.py` — prompt↔parser contract.
- **Modify** `docs/message-flow.md` — reply lane now parses the Topic Menu.

---

### Task 1: Topic Menu parser

**Files:**
- Create: `app/advisor/topic_menu.py`
- Test: `tests/advisor/test_topic_menu.py`

**Interfaces:**
- Consumes: nothing (pure function over `str`).
- Produces: `TOPIC_MENU_MARKER: str` (`"[หัวข้อ]"`), `MAX_TOPICS: int` (5), `MAX_TOPIC_CHARS: int` (20), `ParsedReply` (frozen dataclass with fields `raw_text: str`, `visible_text: str`, `topics: tuple[str, ...]`), and `split_topic_menu(raw_text: str) -> ParsedReply`. Tasks 3 and 4 import these names exactly.

- [ ] **Step 1: Write the failing tests**

Create `tests/advisor/test_topic_menu.py`:

```python
"""The parser half of the ADR 0006 delimiter contract. The prompt half is
pinned by tests/advisor/test_prompt_topic_menu_contract.py."""

from app.advisor.topic_menu import (
    MAX_TOPIC_CHARS,
    MAX_TOPICS,
    TOPIC_MENU_MARKER,
    ParsedReply,
    split_topic_menu,
)

REPLY_BODY = "ธาตุเจ้าเรือนของคุณน่าจะเป็นธาตุไฟค่ะ ควรหลีกเลี่ยงของทอดและของเผ็ดจัด"


def test_reply_without_marker_passes_through_unchanged():
    parsed = split_topic_menu(REPLY_BODY)
    assert parsed == ParsedReply(raw_text=REPLY_BODY, visible_text=REPLY_BODY, topics=())


def test_dash_bullet_block_is_split_into_visible_text_and_topics():
    raw = f"{REPLY_BODY}\n\n{TOPIC_MENU_MARKER}\n- อาหารบำรุงธาตุไฟ\n- ท่าบริหารตอนเช้า"
    parsed = split_topic_menu(raw)
    assert parsed.visible_text == REPLY_BODY
    assert parsed.topics == ("อาหารบำรุงธาตุไฟ", "ท่าบริหารตอนเช้า")
    assert parsed.raw_text == raw  # Working Buffer stores the block too


def test_bullet_and_numbered_items_are_accepted():
    raw = f"{REPLY_BODY}\n{TOPIC_MENU_MARKER}\n• หัวข้อหนึ่ง\n1. หัวข้อสอง\n2) หัวข้อสาม\n* หัวข้อสี่"
    parsed = split_topic_menu(raw)
    assert parsed.topics == ("หัวข้อหนึ่ง", "หัวข้อสอง", "หัวข้อสาม", "หัวข้อสี่")


def test_bare_lines_after_marker_count_as_topics():
    raw = f"{REPLY_BODY}\n{TOPIC_MENU_MARKER}\nหัวข้อหนึ่ง\nหัวข้อสอง"
    parsed = split_topic_menu(raw)
    assert parsed.topics == ("หัวข้อหนึ่ง", "หัวข้อสอง")


def test_topics_are_capped_at_max_topics():
    items = "\n".join(f"- หัวข้อ{n}" for n in range(1, 8))
    parsed = split_topic_menu(f"{REPLY_BODY}\n{TOPIC_MENU_MARKER}\n{items}")
    assert len(parsed.topics) == MAX_TOPICS
    assert parsed.topics[0] == "หัวข้อ1"


def test_long_topics_are_truncated_to_line_label_cap():
    long_topic = "ก" * 30
    parsed = split_topic_menu(f"{REPLY_BODY}\n{TOPIC_MENU_MARKER}\n- {long_topic}")
    assert parsed.topics == ("ก" * MAX_TOPIC_CHARS,)


def test_marker_with_trailing_colon_and_whitespace_is_accepted():
    raw = f"{REPLY_BODY}\n  {TOPIC_MENU_MARKER}:  \n- หัวข้อหนึ่ง"
    assert split_topic_menu(raw).topics == ("หัวข้อหนึ่ง",)


def test_marker_mentioned_mid_sentence_is_not_a_block():
    raw = f"คำว่า {TOPIC_MENU_MARKER} เป็นเพียงตัวอย่างค่ะ"
    parsed = split_topic_menu(raw)
    assert parsed.visible_text == raw
    assert parsed.topics == ()


def test_marker_without_items_is_stripped_and_yields_no_topics():
    raw = f"{REPLY_BODY}\n{TOPIC_MENU_MARKER}\n"
    parsed = split_topic_menu(raw)
    assert parsed.visible_text == REPLY_BODY
    assert parsed.topics == ()


def test_menu_only_reply_degrades_to_full_raw_text():
    # An empty visible text would be rejected by LINE; degrade to the raw reply.
    raw = f"{TOPIC_MENU_MARKER}\n- หัวข้อหนึ่ง"
    parsed = split_topic_menu(raw)
    assert parsed.visible_text == raw
    assert parsed.topics == ()


def test_last_standalone_marker_wins():
    raw = (
        f"{TOPIC_MENU_MARKER}\nข้อความอธิบายรูปแบบ\n{REPLY_BODY}\n"
        f"{TOPIC_MENU_MARKER}\n- หัวข้อจริง"
    )
    parsed = split_topic_menu(raw)
    assert parsed.topics == ("หัวข้อจริง",)
    assert parsed.visible_text.endswith(REPLY_BODY)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/advisor/test_topic_menu.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.advisor.topic_menu'`

- [ ] **Step 3: Write the parser**

Create `app/advisor/topic_menu.py`:

```python
"""Topic Menu delimiter parsing (ADR 0006).

The block format is a CONTRACT between this parser and the Advisor
system prompt (app/advisor/prompts.py): changing either side alone
breaks the menu silently (replies fall back to full text). Keep
tests/advisor/test_prompt_topic_menu_contract.py green against both.
"""

import re
from dataclasses import dataclass

TOPIC_MENU_MARKER = "[หัวข้อ]"
# LINE Quick Reply hard caps are 13 items / 20-char labels; we cap topics
# lower by design and rely on this (the SDK does not validate locally).
MAX_TOPICS = 5
MAX_TOPIC_CHARS = 20

_ITEM_PREFIX = re.compile(r"^(?:[-•*]|\d+[.)])\s*")


@dataclass(frozen=True)
class ParsedReply:
    """An Advisor reply split into what the user sees and the Topic Menu.

    raw_text keeps the delimiter block: the Working Buffer stores it, so
    the Advisor can resolve "ข้อสอง" after LINE has hidden the buttons.
    """

    raw_text: str
    visible_text: str
    topics: tuple[str, ...]


def split_topic_menu(raw_text: str) -> ParsedReply:
    """Split a raw Advisor reply on its trailing `[หัวข้อ]` block.

    Forgiving by design: no standalone marker line means no menu, and a
    menu-only reply (empty visible text) degrades to the untouched reply
    -- the full text is always better than a LINE 400 on empty text.
    """
    lines = raw_text.splitlines()
    marker_index = _last_marker_line(lines)
    if marker_index is None:
        return ParsedReply(raw_text=raw_text, visible_text=raw_text, topics=())

    visible_text = "\n".join(lines[:marker_index]).strip()
    if not visible_text:
        return ParsedReply(raw_text=raw_text, visible_text=raw_text, topics=())

    topics = _parse_topics(lines[marker_index + 1 :])
    return ParsedReply(raw_text=raw_text, visible_text=visible_text, topics=topics)


def _last_marker_line(lines: list[str]) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip().rstrip(":") == TOPIC_MENU_MARKER:
            return index
    return None


def _parse_topics(lines: list[str]) -> tuple[str, ...]:
    topics = []
    for line in lines:
        item = _ITEM_PREFIX.sub("", line.strip(), count=1).strip()
        if item:
            topics.append(item[:MAX_TOPIC_CHARS])
    return tuple(topics[:MAX_TOPICS])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/advisor/test_topic_menu.py -v`
Expected: all 11 tests PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check app/advisor/topic_menu.py tests/advisor/test_topic_menu.py
git add app/advisor/topic_menu.py tests/advisor/test_topic_menu.py
git commit -m "feat: parse the Topic Menu delimiter block from Advisor replies (ADR 0006)"
```

---

### Task 2: Quick Reply transport in LineMessenger

**Files:**
- Modify: `app/line/messaging.py`
- Test: `tests/line/test_messaging.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1 (topics arrive as plain strings, already capped).
- Produces: `build_text_message(text: str, topics: Sequence[str] = ()) -> TextMessage`; `LineMessenger.reply(reply_token, text, topics=())`, `LineMessenger.push(user_id, text, topics=())`, `LineMessenger.reply_or_push(*, reply_token, user_id, text, topics=())`. Task 3 calls `reply_or_push` with `topics=`.

- [ ] **Step 1: Write the failing tests**

Create `tests/line/test_messaging.py`:

```python
from app.config import Settings
from app.line.messaging import LineMessenger, build_text_message


def _settings() -> Settings:
    return Settings(line_channel_secret="test", line_channel_access_token="test")


def test_build_text_message_without_topics_has_no_quick_reply():
    message = build_text_message("สวัสดีค่ะ")
    assert message.text == "สวัสดีค่ะ"
    assert message.quick_reply is None


def test_build_text_message_renders_topics_as_quick_reply_buttons():
    topics = ("อาหารบำรุงธาตุไฟ", "ท่าบริหารตอนเช้า")
    message = build_text_message("คำตอบ", topics)
    items = message.quick_reply.items
    # Each button echoes its label back as the user's next message, so the
    # tap re-enters the normal text pipeline.
    assert [item.action.label for item in items] == list(topics)
    assert [item.action.text for item in items] == list(topics)


async def test_reply_or_push_forwards_topics_to_reply():
    messenger = LineMessenger(_settings())
    calls = []

    async def fake_reply(reply_token, text, topics=()):
        calls.append((reply_token, text, tuple(topics)))

    messenger.reply = fake_reply

    await messenger.reply_or_push(
        reply_token="R1", user_id="U1", text="คำตอบ", topics=("หัวข้อหนึ่ง",)
    )

    assert calls == [("R1", "คำตอบ", ("หัวข้อหนึ่ง",))]


async def test_reply_or_push_falls_back_to_push_with_topics():
    messenger = LineMessenger(_settings())
    pushed = []

    async def failing_reply(reply_token, text, topics=()):
        raise RuntimeError("reply token expired")

    async def fake_push(user_id, text, topics=()):
        pushed.append((user_id, text, tuple(topics)))

    messenger.reply = failing_reply
    messenger.push = fake_push

    await messenger.reply_or_push(
        reply_token="R1", user_id="U1", text="คำตอบ", topics=("หัวข้อหนึ่ง",)
    )

    assert pushed == [("U1", "คำตอบ", ("หัวข้อหนึ่ง",))]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/line/test_messaging.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_text_message'`

- [ ] **Step 3: Add Quick Reply support**

In `app/line/messaging.py`, replace the import block at the top with:

```python
from collections.abc import Sequence

from linebot.v3.messaging import (
    ApiClient,
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    Configuration,
    MessageAction,
    PushMessageRequest,
    QuickReply,
    QuickReplyItem,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)

from app.config import Settings
```

Add this module-level function after the imports (before `class LineMessenger`):

```python
def build_text_message(text: str, topics: Sequence[str] = ()) -> TextMessage:
    """Render a reply with its Topic Menu as LINE Quick Reply buttons.

    Topics must already be capped (ADR 0006, enforced by
    app/advisor/topic_menu.py: at most 5 topics of <= 20 chars -- LINE
    rejects longer labels at the API, not in the SDK). Tapping a button
    sends its text as the user's next message.
    """
    if not topics:
        return TextMessage(text=text)
    items = [QuickReplyItem(action=MessageAction(label=topic, text=topic)) for topic in topics]
    return TextMessage(text=text, quickReply=QuickReply(items=items))
```

Replace the `reply`, `push`, and `reply_or_push` methods with:

```python
    async def reply(self, reply_token: str, text: str, topics: Sequence[str] = ()) -> None:
        async with self._client() as client:
            api = AsyncMessagingApi(client)
            await api.reply_message(
                ReplyMessageRequest(
                    replyToken=reply_token, messages=[build_text_message(text, topics)]
                )
            )

    async def push(self, user_id: str, text: str, topics: Sequence[str] = ()) -> None:
        async with self._client() as client:
            api = AsyncMessagingApi(client)
            await api.push_message(
                PushMessageRequest(to=user_id, messages=[build_text_message(text, topics)])
            )

    async def reply_or_push(
        self, *, reply_token: str, user_id: str, text: str, topics: Sequence[str] = ()
    ) -> None:
        """Attempt the reply token; fall back to a push message if it's expired."""
        try:
            await self.reply(reply_token, text, topics)
        except Exception:
            await self.push(user_id, text, topics)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/line/test_messaging.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Run the full suite (existing callers pass no topics and must be unaffected), lint, commit**

Run: `uv run pytest`
Expected: all PASS

```bash
uv run ruff check app/line/messaging.py tests/line/test_messaging.py
git add app/line/messaging.py tests/line/test_messaging.py
git commit -m "feat: render Topic Menu topics as LINE Quick Reply buttons"
```

---

### Task 3: Dispatcher wiring — store raw, send visible + topics

**Files:**
- Modify: `app/pipeline/dispatcher.py` (imports; `handle_text_message`; tail of `handle_image_message`; `_run_consultation_turn` signature + tail)
- Modify: `tests/pipeline/test_dispatcher_images.py:36-52` (fake messenger + fake consultation)
- Modify: `tests/pipeline/test_dispatcher_profile.py:85-87` (return-type assertion)
- Test: `tests/pipeline/test_dispatcher_topic_menu.py` (create)

**Interfaces:**
- Consumes: `split_topic_menu`, `ParsedReply` (Task 1); `reply_or_push(..., topics=)` (Task 2).
- Produces: `_run_consultation_turn(user_id: str, incoming_text: str, settings: Settings) -> ParsedReply` — raw text (block included) stored in the Working Buffer; callers send `parsed.visible_text` + `parsed.topics`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pipeline/test_dispatcher_topic_menu.py`:

```python
"""ADR 0006 wiring: the Working Buffer stores the RAW Advisor reply
(delimiter block included) while LINE receives the visible text with the
topics as Quick Reply buttons."""

from types import SimpleNamespace

from mongomock_motor import AsyncMongoMockClient

import app.pipeline.dispatcher as dispatcher
from app.advisor.topic_menu import TOPIC_MENU_MARKER
from app.config import Settings
from app.memory.working_buffer import WorkingBufferRepository

VISIBLE = "ธาตุเจ้าเรือนของคุณน่าจะเป็นธาตุไฟค่ะ"
RAW_WITH_MENU = f"{VISIBLE}\n\n{TOPIC_MENU_MARKER}\n- อาหารบำรุงธาตุไฟ\n- ท่าบริหารตอนเช้า"


def _settings() -> Settings:
    return Settings(line_channel_secret="test", line_channel_access_token="test")


def _event() -> SimpleNamespace:
    return SimpleNamespace(
        source=SimpleNamespace(user_id="U1"),
        message=SimpleNamespace(text="ขอคำแนะนำค่ะ"),
        reply_token="R1",
    )


class _FakeMessenger:
    def __init__(self) -> None:
        self.sent: list[tuple[str, tuple[str, ...]]] = []

    async def reply_or_push(self, *, reply_token, user_id, text, topics=()) -> None:
        self.sent.append((text, tuple(topics)))


def _patch_spine(monkeypatch, advisor_reply: str) -> tuple[_FakeMessenger, list]:
    db = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(dispatcher, "get_database", lambda settings: db)

    messenger = _FakeMessenger()
    monkeypatch.setattr(dispatcher, "LineMessenger", lambda settings: messenger)

    appended = []

    async def fake_pop_if_stale(self, user_id, gap_hours):
        return None

    async def fake_current_turns(self, user_id):
        return []

    async def fake_append_turn(self, user_id, turn):
        appended.append(turn)

    monkeypatch.setattr(WorkingBufferRepository, "pop_if_stale", fake_pop_if_stale)
    monkeypatch.setattr(WorkingBufferRepository, "current_turns", fake_current_turns)
    monkeypatch.setattr(WorkingBufferRepository, "append_turn", fake_append_turn)

    async def fake_retrieve(text):
        return []

    monkeypatch.setattr(dispatcher, "retrieve_passages", fake_retrieve)
    monkeypatch.setattr(dispatcher, "build_advisor_agent", lambda settings, tools: None)

    async def fake_run_advisor(agent, **kwargs):
        return advisor_reply

    monkeypatch.setattr(dispatcher, "run_advisor", fake_run_advisor)
    return messenger, appended


async def test_menu_reply_stores_raw_and_sends_visible_with_topics(monkeypatch):
    messenger, appended = _patch_spine(monkeypatch, RAW_WITH_MENU)

    await dispatcher.handle_text_message(_event(), _settings())

    advisor_turns = [turn for turn in appended if turn.role == "advisor"]
    assert advisor_turns[0].text == RAW_WITH_MENU  # block survives in the buffer
    assert messenger.sent == [(VISIBLE, ("อาหารบำรุงธาตุไฟ", "ท่าบริหารตอนเช้า"))]


async def test_plain_reply_sends_full_text_with_no_topics(monkeypatch):
    messenger, appended = _patch_spine(monkeypatch, VISIBLE)

    await dispatcher.handle_text_message(_event(), _settings())

    advisor_turns = [turn for turn in appended if turn.role == "advisor"]
    assert advisor_turns[0].text == VISIBLE
    assert messenger.sent == [(VISIBLE, ())]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/pipeline/test_dispatcher_topic_menu.py -v`
Expected: FAIL — `messenger.sent` holds the raw text (menu block still attached) and no topics tuple matches, because the dispatcher neither parses nor forwards topics yet.

- [ ] **Step 3: Wire the dispatcher**

In `app/pipeline/dispatcher.py`:

Add to the imports (after `from app.advisor.tools import build_health_record_tools`):

```python
from app.advisor.topic_menu import ParsedReply, split_topic_menu
```

Replace `handle_text_message` with:

```python
async def handle_text_message(event: MessageEvent, settings: Settings) -> None:
    user_id = event.source.user_id
    async with user_queue.lock_for(user_id):
        parsed = await _run_consultation_turn(user_id, event.message.text, settings)

    messenger = LineMessenger(settings)
    await messenger.reply_or_push(
        reply_token=event.reply_token,
        user_id=user_id,
        text=parsed.visible_text,
        topics=parsed.topics,
    )
```

Replace the tail of `handle_image_message` (the final `async with` block and the `reply_or_push` call after it) with:

```python
    async with user_queue.lock_for(user_id):
        parsed = await _run_consultation_turn(user_id, turn_text, settings)

    await messenger.reply_or_push(
        reply_token=event.reply_token,
        user_id=user_id,
        text=parsed.visible_text,
        topics=parsed.topics,
    )
```

Change `_run_consultation_turn`'s signature line to:

```python
async def _run_consultation_turn(
    user_id: str, incoming_text: str, settings: Settings
) -> ParsedReply:
```

Replace its final advisor-turn append and return (the last four lines of the function) with:

```python
    # The raw reply -- delimiter block included -- goes into the Working
    # Buffer so the Advisor can resolve "ข้อสอง" after LINE hides the
    # buttons (ADR 0006). Only the LINE transport sees the split.
    parsed = split_topic_menu(reply_text)
    await buffer_repo.append_turn(
        user_id,
        ConsultationTurn(role="advisor", text=parsed.raw_text, timestamp=datetime.now(UTC)),
    )
    return parsed
```

- [ ] **Step 4: Fix the two existing test files that assume the old contract**

In `tests/pipeline/test_dispatcher_images.py`, replace the `_FakeMessenger.reply_or_push` method (line 36) with:

```python
    async def reply_or_push(self, *, reply_token, user_id, text, topics=()) -> None:
        self.sent.append(text)
```

and replace `fake_consultation` (lines 47-49) with:

```python
    async def fake_consultation(user_id, incoming_text, settings):
        consultation_inputs.append(incoming_text)
        return dispatcher.split_topic_menu("คำแนะนำจากผู้ช่วย")
```

(`split_topic_menu` on a plain string returns a `ParsedReply` whose `visible_text` is the string itself, so the existing `messenger.sent == ["คำแนะนำจากผู้ช่วย"]` assertions keep passing unchanged.)

In `tests/pipeline/test_dispatcher_profile.py`, replace the assertion at line 85-87:

```python
    reply = await dispatcher._run_consultation_turn("U1", "สวัสดี", _settings())

    assert reply.visible_text == "คำตอบ"
```

- [ ] **Step 5: Run the full suite to verify everything passes**

Run: `uv run pytest`
Expected: all PASS (the two new tests plus every pre-existing test).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check app/pipeline/dispatcher.py tests/pipeline/
git add app/pipeline/dispatcher.py tests/pipeline/test_dispatcher_topic_menu.py \
    tests/pipeline/test_dispatcher_images.py tests/pipeline/test_dispatcher_profile.py
git commit -m "feat: split Advisor replies into visible text and Topic Menu buttons"
```

---

### Task 4: System prompt — one-screen cap + Topic Menu contract

**Files:**
- Modify: `app/advisor/prompts.py` (append two sections to `SYSTEM_PROMPT`)
- Test: `tests/advisor/test_prompt_topic_menu_contract.py` (create)

**Interfaces:**
- Consumes: `TOPIC_MENU_MARKER`, `MAX_TOPICS`, `MAX_TOPIC_CHARS`, `split_topic_menu` (Task 1); `SYSTEM_PROMPT`.
- Produces: the prompt half of the delimiter contract. No new code symbols.

- [ ] **Step 1: Write the failing contract tests**

Create `tests/advisor/test_prompt_topic_menu_contract.py`:

```python
"""The prompt half of the ADR 0006 delimiter contract: the format the
system prompt TEACHES must be the format the parser ACCEPTS. Changing
either side alone breaks the menu silently -- these tests fail loudly
instead."""

from app.advisor.prompts import SYSTEM_PROMPT
from app.advisor.topic_menu import TOPIC_MENU_MARKER, split_topic_menu


def test_prompt_shows_the_marker_as_a_standalone_line():
    # The parser only accepts the marker on its own line (_last_marker_line),
    # so the prompt must display it the same way -- a substring match would
    # keep passing even if the example collapsed into running prose.
    assert any(line.strip() == TOPIC_MENU_MARKER for line in SYSTEM_PROMPT.splitlines())


def test_the_prompts_own_example_block_parses_into_its_topics():
    # Extract the example block exactly as the LLM will see it: the marker
    # line plus its run of bullet lines. Hardcoding a copy here would let
    # the prompt's real example drift without failing this test.
    lines = SYSTEM_PROMPT.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == TOPIC_MENU_MARKER)
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.strip().startswith("-"):
            break
        block.append(line)
    reply = "คำตอบหลัก\n" + "\n".join(block)

    parsed = split_topic_menu(reply)

    assert parsed.visible_text == "คำตอบหลัก"
    assert parsed.topics == ("อาหารบำรุงธาตุ", "ท่าบริหารแก้ปวดหลัง")


def test_prompt_forbids_menus_on_red_flag_escalations():
    assert "NEVER attach a Topic Menu to a red-flag escalation" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/advisor/test_prompt_topic_menu_contract.py -v`
Expected: all 3 FAIL (the marker, the example block, and the red-flag rule are not yet in the prompt; test 2 fails with `StopIteration` from the marker-line search).

- [ ] **Step 3: Extend the system prompt**

In `app/advisor/prompts.py`, append the following to the end of `SYSTEM_PROMPT` (after the Memory section's final line `automatically after consultations.`; keep the existing intake paragraph as-is and keep the `\`-continuation style):

```python
## Reply length (one phone screen)
Keep every reply to ONE main point, at most 4-5 short sentences -- what \
fits on a phone screen without scrolling. When you have more to say, hold \
the rest back and offer it through the Topic Menu below instead of \
writing a longer reply. Red-flag escalations are exempt from this cap.

## Topic Menu
When you held content back (or the missing-information list has an item \
the user could volunteer), end your reply with this exact block as the \
last lines of the message:

[หัวข้อ]
- อาหารบำรุงธาตุ
- ท่าบริหารแก้ปวดหลัง

Rules for the block:
- 2 to 5 topics, each at most 20 Thai characters, phrased as things the \
user may want to ask next.
- At most ONE topic may be an intake item from the missing-information \
list (e.g. "บอกวันเดือนปีเกิด"); the in-body rule above (one woven intake \
question) still applies separately.
- The block is stripped from the text the user sees and shown as tappable \
buttons, so never refer to it in the body text.
- When the user taps a button or writes a topic's text, its number, or \
"ข้อสอง", answer that topic -- one screen again, with a fresh Topic Menu \
if you again hold content back.
- NEVER attach a Topic Menu to a red-flag escalation.
- Skip the block entirely when you held nothing back.
"""
```

(The closing `"""` shown is the string's existing terminator — the new text goes inside it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/advisor/ -v`
Expected: all PASS (the 3 contract tests plus the existing advisor tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check app/advisor/prompts.py tests/advisor/test_prompt_topic_menu_contract.py
git add app/advisor/prompts.py tests/advisor/test_prompt_topic_menu_contract.py
git commit -m "feat: teach the Advisor the one-screen cap and Topic Menu block"
```

---

### Task 5: Documentation — message flow reflects the parse step

**Files:**
- Modify: `docs/message-flow.md` (the `REPLY` node in the mermaid spine, lines 41-42, and the `**text**` branch note)

**Interfaces:**
- Consumes: the shipped behavior from Tasks 1-4. Produces: docs only.

- [ ] **Step 1: Update the mermaid spine**

In `docs/message-flow.md`, replace:

```
        AGENT -->|answer| REPLY["Reply in Thai"]
        REPLY --> APPADV["Append advisor turn to Working Buffer"]
```

with:

```
        AGENT -->|answer| REPLY["Reply in Thai"]
        REPLY --> MENU["Parse Topic Menu block<br/>(ADR 0006): visible text +<br/>Quick Reply topics"]
        MENU --> APPADV["Append RAW advisor turn<br/>(menu block included)<br/>to Working Buffer"]
```

and add `MENU` to the deterministic class list — replace:

```
    class TF,STALE deterministic
```

with:

```
    class TF,STALE,MENU deterministic
```

- [ ] **Step 2: Update the `**text**` branch note**

Replace the sentence ending `reply in Thai.` (line 77) with:

```
by config), reply in Thai. The reply's trailing `[หัวข้อ]` block, if any,
becomes [Topic Menu](../CONTEXT.md) Quick Reply buttons
([ADR 0006](adr/0006-topic-menu-delimiter-protocol.md)); the raw reply --
block included -- is what the Working Buffer stores, so "ข้อสอง" still
resolves after the buttons disappear.
```

- [ ] **Step 3: Verify the suite is still green and commit everything**

Run: `uv run pytest && uv run ruff check .`
Expected: all PASS, no lint errors.

```bash
git add docs/message-flow.md
git commit -m "docs: add the Topic Menu parse step to the message flow"
```

---

## Self-Review

- **Spec coverage:** delimiter block instead of structured output (Tasks 1, 4); parse-out → Quick Reply conversion (Tasks 2, 3); forgiving parsing of `-`/`•`/numbered items (Task 1); code-owned hard limits of 5 topics / 20 chars (Task 1); safe degradation when no block (Task 1 + Task 3 plain-reply test); prompt↔parser contract tested together (Task 4); topics stay in the Working Buffer advisor turn (Task 3); menu-carried intake item + preserved in-body rule (Task 4); red-flag exemption from menu and length cap (Task 4); one-screen reply cap (Task 4). ✓
- **Placeholder scan:** none — every code step shows complete code, every run step names the command and expected outcome. ✓
- **Type consistency:** `ParsedReply(raw_text, visible_text, topics)`, `split_topic_menu`, `TOPIC_MENU_MARKER`, `MAX_TOPICS`, `MAX_TOPIC_CHARS`, `build_text_message(text, topics)`, `reply_or_push(..., topics=())` used identically across Tasks 1-4. ✓
