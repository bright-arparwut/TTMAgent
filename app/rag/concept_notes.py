"""Generate `corpus/concepts/` from `corpus/graph.json` (ADR 0010, "Vault:
generated concept notes", ticket #17): one Markdown note per extracted
entity -- all of them, no degree threshold, isolates included for thesis
honesty. Zero LLM calls; every write is a pure function of graph.json, so
`git diff corpus/concepts/` is the re-index quality instrument.

Filename = the verbatim entity name, with one sanitize rule applied for
characters invalid on common filesystems; when that changes the name, the
original is recorded in the note's `aliases` frontmatter. Frontmatter is
exactly `entity`/`type`/`degree`/`generated`/`aliases` -- no timestamps,
because generation is deterministic and a timestamp would make every note
re-diff on every run for no content reason. Relations render as
`- [[target]] — keywords: description` on both endpoints, linking to the
target's own (possibly sanitized) filename so the wikilink actually
resolves. Source-note wikilinks use the source note's basename, matching
LightRAG's own basenamed `file_path`.

Rebuild is a wholesale delete + regenerate, behind a git-dirty guard: any
uncommitted change under the output directory (a hand edit, or a prior
generation nobody committed yet) refuses the rebuild rather than silently
destroying it.

Usage:
    uv run python -m app.rag.concept_notes corpus/graph.json corpus/concepts
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

INVALID_FILENAME_CHARS = frozenset('/\\:*?"<>|')
FILENAME_REPLACEMENT = "_"

RELATIONS_HEADING = "## Relations"
SOURCES_HEADING = "## Sources"


class DirtyVaultError(RuntimeError):
    """corpus/concepts/ carries uncommitted changes; refuse to regenerate
    over them so a hand edit surfaces instead of dying silently."""


def sanitize_filename(name: str) -> str:
    """Replace characters invalid on common filesystems with `_`. One rule,
    applied verbatim otherwise (ADR 0010) -- everything else about the name,
    including spacing and case, passes through untouched."""
    return "".join(
        FILENAME_REPLACEMENT if char in INVALID_FILENAME_CHARS else char for char in name
    )


def build_entity_stems(entities: list[dict]) -> dict[str, str]:
    """entity name -> sanitized filename stem (no `.md`). Raises if two
    different entity names sanitize to the same stem -- silently letting
    one clobber the other's file on disk would lose a note with no trace."""
    stems: dict[str, str] = {}
    owner_by_stem: dict[str, str] = {}
    for entity in entities:
        name = entity["name"]
        stem = sanitize_filename(name)
        existing_owner = owner_by_stem.get(stem)
        if existing_owner is not None and existing_owner != name:
            raise ValueError(
                f"sanitize collision: {name!r} and {existing_owner!r} both sanitize to"
                f" {stem!r}.md"
            )
        owner_by_stem[stem] = name
        stems[name] = stem
    return stems


def group_relations_by_entity(relations: list[dict]) -> dict[str, list[dict]]:
    """entity name -> every relation touching it, from either side."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for relation in relations:
        grouped[relation["source"]].append(relation)
        grouped[relation["target"]].append(relation)
    return grouped


def _yaml_string(value: str) -> str:
    """A double-quoted YAML scalar, safe for any entity/type name (backslash
    and double-quote are the only characters that need escaping inside
    one)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _frontmatter(entity: dict, aliases: list[str]) -> str:
    alias_list = ", ".join(_yaml_string(alias) for alias in aliases)
    lines = [
        "---",
        f"entity: {_yaml_string(entity['name'])}",
        f"type: {_yaml_string(entity['type'])}",
        f"degree: {entity['degree']}",
        "generated: true",
        f"aliases: [{alias_list}]",
        "---",
    ]
    return "\n".join(lines)


def _relation_bullets(entity_name: str, relations: list[dict], stems: dict[str, str]) -> list[str]:
    labelled: list[tuple[str, str]] = []
    for relation in relations:
        if relation["source"] == entity_name:
            other = relation["target"]
        elif relation["target"] == entity_name:
            other = relation["source"]
        else:
            continue
        target_stem = stems[other]
        line = f"- [[{target_stem}]] — {relation['keywords']}: {relation['description']}"
        labelled.append((other, line))
    labelled.sort(key=lambda item: item[0])
    return [line for _, line in labelled]


def _source_bullets(source_files: list[str]) -> list[str]:
    return [f"- [[{Path(file_path).stem}]]" for file_path in sorted(source_files)]


def render_note(entity: dict, relations: list[dict], stems: dict[str, str]) -> str:
    name = entity["name"]
    stem = stems[name]
    aliases = [] if stem == name else [name]

    parts = [_frontmatter(entity, aliases), "", entity["description"]]

    relation_bullets = _relation_bullets(name, relations, stems)
    if relation_bullets:
        parts += ["", RELATIONS_HEADING, "", *relation_bullets]

    source_bullets = _source_bullets(entity["source_files"])
    if source_bullets:
        parts += ["", SOURCES_HEADING, "", *source_bullets]

    return "\n".join(parts) + "\n"


def generate_concept_notes(graph: dict, output_dir: Path) -> list[Path]:
    """Write one note per entity into `output_dir` (flat, no subfolders).
    Assumes `output_dir` is ready to receive files -- callers that need the
    git-dirty guard and wholesale delete use `regenerate` instead."""
    entities = graph["entities"]
    relations = graph["relations"]
    stems = build_entity_stems(entities)
    grouped = group_relations_by_entity(relations)

    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for entity in entities:
        note_text = render_note(entity, grouped.get(entity["name"], []), stems)
        path = output_dir / f"{stems[entity['name']]}.md"
        path.write_text(note_text, encoding="utf-8")
        written.append(path)
    return written


# --- rebuild: git-dirty guard + wholesale delete (6.3) -----------------------


def _git_status_lines(repo_root: Path, path: Path) -> list[str]:
    # Resolve both sides -- callers (notably the CLI) pass paths relative to
    # the current working directory, not necessarily to repo_root.
    relative = path.resolve().relative_to(repo_root.resolve())
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", str(relative)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def ensure_concepts_clean(repo_root: Path, concepts_dir: Path) -> None:
    """Refuse to proceed while `concepts_dir` carries uncommitted changes
    (modified, staged, or untracked) under git -- so a hand edit, or a prior
    generation nobody committed, surfaces instead of being silently
    destroyed by the wholesale delete. A directory that does not exist yet,
    or one that is fully committed and unchanged, passes cleanly."""
    dirty = _git_status_lines(repo_root, concepts_dir)
    if dirty:
        raise DirtyVaultError(
            f"{concepts_dir} has uncommitted changes -- commit or stash them before"
            " regenerating:\n" + "\n".join(dirty)
        )


def regenerate(graph_path: Path, output_dir: Path, repo_root: Path) -> list[Path]:
    """Wholesale delete + regenerate `output_dir` from `graph_path`, behind
    the git-dirty guard (ADR 0010, ticket #17)."""
    ensure_concepts_clean(repo_root, output_dir)
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    if output_dir.exists():
        shutil.rmtree(output_dir)
    return generate_concept_notes(graph, output_dir)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph_path", type=Path, help="path to corpus/graph.json")
    parser.add_argument("output_dir", type=Path, help="output directory, e.g. corpus/concepts")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="git repository root (default: this checkout)",
    )
    args = parser.parse_args(argv)
    written = regenerate(args.graph_path, args.output_dir, args.repo_root)
    print(f"wrote {len(written)} note(s) to {args.output_dir}")


if __name__ == "__main__":
    main()
