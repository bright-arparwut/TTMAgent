"""Citation-line parsing and rendering (the `(อ้างอิง: ...)` contract).

The line format is a CONTRACT between this parser and the Advisor system
prompt (app/advisor/prompts.py), like the Topic Menu delimiter (ADR 0006):
changing either side alone silently loses the styled footer (replies fall
back to the citation staying inline in the text, which is correct but
plain). Keep tests/advisor/test_prompt_citation_contract.py green against
both.

Only the LINE transport strips the line and re-renders it as a Flex
footer; the Working Buffer stores the raw reply with the line inline, so
the Advisor sees its own citations in history.

render_references() is the other half of ADR 0010's citation contract: the
Advisor emits bare ids -- `(อ้างอิง: [1] [3])`, never a title or page
(`book_title` lives only in corpus/books.yaml and never enters the
model's context) -- and this module renders the real citation from them,
grouped by book, capped at 3 books, in ascending reference_id order.
Resolution happens *before* the Working Buffer write, so everything below
this docstring -- split_citation, the Flex footer, the degrade ladder --
consumes the rendered line exactly like it always consumed the model's
own line; only the provenance of the string inside the parens changed.
"""

import logging
import re
from pathlib import Path

from app.config import get_settings
from app.rag.source_notes import NON_BOOK_DIR_NAMES, load_books

logger = logging.getLogger(__name__)

CITATION_PREFIX = "(อ้างอิง:"
_CITATION_LINE = re.compile(r"^\(อ้างอิง:\s*(?P<citation>.+?)\s*\)$")
_NOTE_LABEL_RE = re.compile(r"^\[(?P<id>\d+)\]\s+(?P<filename>.+)$")
_CITED_ID_RE = re.compile(r"\[(\d+)\]")
_PAGE_RANGE_RE = re.compile(r"-น\.(?P<first>\d+)-(?P<last>\d+)$")

# "Grouped by book, cap 3, reference_id order" (ADR 0010, "The citation
# contract") -- bounds the footer's length regardless of how many notes a
# reply draws on.
MAX_CITED_BOOKS = 3


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


def _passage_labels(passages: list[str]) -> dict[str, str]:
    """id -> filename (without `.md`), read off each note's own `[n]
    <filename>` label (app/rag/vector_store.py's `_build_numbered_notes`).
    The trailing graph-context block has no such label -- it never had an
    id to cite, so it is silently skipped rather than specially handled.
    """
    labels: dict[str, str] = {}
    for passage in passages:
        first_line = passage.splitlines()[0] if passage else ""
        match = _NOTE_LABEL_RE.match(first_line)
        if match is not None:
            labels[match.group("id")] = match.group("filename")
    return labels


def _locate_book_id(corpus_dir: Path, filename: str) -> str | None:
    """Which `corpus/<book_id>/` holds `<filename>.md`.

    The note label alone doesn't carry book_id (ADR 0010: book_title lives
    only in books.yaml, never in frontmatter or the filename, so it never
    reaches the model's context) -- the directory layout is the only place
    left to resolve it, mirroring vector_store.py's `_find_note_body`.
    `corpus/concepts/` (the generated vault, Phase 6) and `corpus/archive/`
    are never book folders and are skipped by name (source_notes.py's
    `NON_BOOK_DIR_NAMES`) -- LightRAG never indexes either, so a real
    citation filename never actually lives there, but skipping keeps this
    function honest about what counts as a book.
    """
    if not corpus_dir.is_dir():
        return None
    for book_dir in sorted(p for p in corpus_dir.iterdir() if p.is_dir()):
        if book_dir.name in NON_BOOK_DIR_NAMES:
            continue
        if (book_dir / f"{filename}.md").exists():
            return book_dir.name
    return None


def _page_range(filename: str) -> str | None:
    """The printed page range straight off the citation filename
    (`<NN>-<section>-น.<first>-<last>`, ADR 0010)."""
    match = _PAGE_RANGE_RE.search(filename)
    if match is None:
        return None
    return f"{match.group('first')}-{match.group('last')}"


def _render_grouped_citation(bare_citation: str, passages: list[str]) -> str | None:
    """Bare ids -> the rendered Thai citation body (without the
    surrounding `(อ้างอิง: ...)` wrapper): resolve each id to its note's
    filename, drop ids with no matching passage (the invented-id
    guarantee), then group by book title, cap at MAX_CITED_BOOKS, in
    ascending reference_id order. Returns None when nothing survives, so
    the caller can drop the citation line entirely rather than render an
    empty one.
    """
    settings = get_settings()
    corpus_dir = Path(settings.corpus_dir)
    books = load_books(corpus_dir)
    labels = _passage_labels(passages)

    cited_ids = sorted({int(raw_id) for raw_id in _CITED_ID_RE.findall(bare_citation)})

    groups: dict[str, list[str]] = {}
    for cited_id in cited_ids:
        filename = labels.get(str(cited_id))
        if filename is None:
            continue  # invented id -- not a note the Advisor was handed
        book_id = _locate_book_id(corpus_dir, filename)
        page_range = _page_range(filename)
        if book_id is None or page_range is None:
            logger.warning(
                f"Failed to resolve citation id={cited_id}: filename={filename}; "
                f"corpus_dir={corpus_dir} may have drifted or file not found"
            )
            continue
        title = books.get(book_id, book_id)
        groups.setdefault(title, []).append(page_range)

    if not groups:
        return None

    kept = list(groups.items())[:MAX_CITED_BOOKS]
    return "; ".join(f"{title} หน้า {', '.join(pages)}" for title, pages in kept)


def render_references(reply_text: str, passages: list[str]) -> str:
    """Replace the Advisor's bare-id `(อ้างอิง: [1] [3])` line with the
    rendered Thai citation, in the SAME `(อ้างอิง: ...)` line format so
    split_citation, the Flex footer, and the degrade ladder (ADR 0009)
    consume it unchanged. Must run before the Working Buffer write (ADR
    0010) so the buffer -- and the Advisor's own turn history -- holds the
    resolved citation, never the bare ids.

    Scans for the last line matching the citation format, independent of
    whatever else follows it (typically the ADR 0006 `[หัวข้อ]` block, since
    this runs on the raw reply before the topic-menu split) -- so it works
    the same whether or not a topic menu trails the citation.
    """
    lines = reply_text.splitlines()
    citation_index = next(
        (index for index in range(len(lines) - 1, -1, -1) if is_citation_line(lines[index])),
        None,
    )
    if citation_index is None:
        return reply_text

    match = _CITATION_LINE.match(lines[citation_index].strip())
    bare_citation = match.group("citation") if match is not None else ""
    rendered = _render_grouped_citation(bare_citation, passages)

    if rendered is None:
        del lines[citation_index]
        return "\n".join(lines)

    lines[citation_index] = f"{CITATION_PREFIX} {rendered})"
    return "\n".join(lines)
