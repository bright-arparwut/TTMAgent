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
