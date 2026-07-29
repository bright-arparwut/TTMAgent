"""Citation-line parsing (the `(อ้างอิง: ...)` contract).

The line format is a CONTRACT between this parser and the Advisor system
prompt (app/advisor/prompts.py), like the Topic Menu delimiter (ADR 0006):
changing either side alone silently loses the styled footer (replies fall
back to the citation staying inline in the text, which is correct but
plain). Keep tests/advisor/test_prompt_citation_contract.py green against
both.

Only the LINE transport strips the line and re-renders it as a Flex
footer; the Working Buffer stores the raw reply with the line inline, so
the Advisor sees its own citations in history.
"""

import re

CITATION_PREFIX = "(อ้างอิง:"
_CITATION_LINE = re.compile(r"^\(อ้างอิง:\s*(?P<citation>.+?)\s*\)$")


def is_citation_line(line: str) -> bool:
    return bool(_CITATION_LINE.match(line.strip()))


def split_citation(text: str) -> tuple[str, str | None]:
    """Split a reply on its trailing `(อ้างอิง: ...)` line.

    Returns (body, citation) where citation is the text inside the marker,
    or (text, None) when the last non-blank line is not a citation.
    Forgiving by design: a citation-only reply (empty body after the
    split) degrades to the untouched text -- same philosophy as
    split_topic_menu.
    """
    lines = text.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index].strip()
        if not line:
            continue
        match = _CITATION_LINE.match(line)
        if match is None:
            return text, None
        body = "\n".join(lines[:index]).strip()
        if not body:
            return text, None
        return body, match.group("citation")
    return text, None


def inline_citation(text: str, citation: str | None) -> str:
    """Re-join a split citation for plain-text transports (degrade path)."""
    if citation is None:
        return text
    return f"{text}\n\n(อ้างอิง: {citation})"
