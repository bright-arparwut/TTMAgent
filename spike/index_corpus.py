"""PROTOTYPE (ticket #16) -- feed the four-elements source notes into LightRAG.

Ticket #12 decided the contract this relies on: the filename IS the citation,
and frontmatter `uid` becomes LightRAG's `ids=` so a page correction renames a
file without churning the graph.
"""

import os
import re
from dataclasses import dataclass

# Ticket #30: book two joins the graph. Both books enter through the same
# standard pipeline; the stores build fresh because the spike's graph was
# never committed and #24 makes the committed store the authoritative one.
CORPUS_DIRS = ("corpus/four-elements", "corpus/tongue-100")

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


@dataclass(frozen=True)
class SourceNote:
    uid: str
    file_path: str  # repo-relative -- the citation carrier
    content: str


def _parse_uid(raw: str, fallback: str) -> str:
    match = _FRONTMATTER.match(raw)
    if not match:
        return fallback
    for line in match.group(1).splitlines():
        if line.startswith("uid:"):
            return line.split(":", 1)[1].strip()
    return fallback


def load_source_notes(corpus_dirs: tuple[str, ...] = CORPUS_DIRS) -> list[SourceNote]:
    notes: list[SourceNote] = []
    for corpus_dir in corpus_dirs:
        notes.extend(_load_book(corpus_dir))
    return notes


def _load_book(corpus_dir: str) -> list[SourceNote]:
    notes: list[SourceNote] = []
    for name in sorted(os.listdir(corpus_dir)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(corpus_dir, name)
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
        notes.append(
            SourceNote(
                uid=_parse_uid(raw, fallback=name),
                file_path=path,
                # The whole file, frontmatter included: ticket #12 established
                # frontmatter only reaches chunk 1, which is why the filename
                # (not the frontmatter) is the citation.
                content=raw,
            )
        )
    return notes


async def index_corpus(rag, notes: list[SourceNote]) -> None:
    await rag.ainsert(
        input=[note.content for note in notes],
        ids=[note.uid for note in notes],
        file_paths=[note.file_path for note in notes],
    )
