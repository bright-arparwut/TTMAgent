"""Unit tests for app.rag.concept_notes (Phase 6.2/6.3, ADR 0010 "Vault:
generated concept notes", ticket #17).

Fixtures are small synthetic corpus/graph.json payloads -- never the real
1,400-entity graph. Git-guard tests use a throwaway `git init` repo under
tmp_path, never this repo's own working tree.
"""

import json
import subprocess
from pathlib import Path

import pytest

from app.rag.concept_notes import (
    DirtyVaultError,
    build_entity_stems,
    ensure_concepts_clean,
    generate_concept_notes,
    main,
    regenerate,
    sanitize_filename,
)


def entity(name, *, type_="concept", description="d", degree=0, source_files=()):
    return {
        "name": name,
        "type": type_,
        "description": description,
        "degree": degree,
        "source_files": list(source_files),
    }


def relation(source, target, *, keywords="k", description="d", source_files=()):
    return {
        "source": source,
        "target": target,
        "keywords": keywords,
        "description": description,
        "source_files": list(source_files),
    }


def run_git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def init_git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    run_git(path, "init", "-q")
    run_git(path, "config", "user.email", "test@example.com")
    run_git(path, "config", "user.name", "Test")
    return path


# --- sanitize_filename -------------------------------------------------------


def test_sanitize_leaves_ordinary_names_untouched():
    assert sanitize_filename("ธาตุทั้งสี่") == "ธาตุทั้งสี่"


@pytest.mark.parametrize("char", list('/\\:*?"<>|'))
def test_sanitize_replaces_every_invalid_filesystem_character(char):
    assert sanitize_filename(f"a{char}b") == "a_b"


def test_sanitize_real_world_slash_example():
    # A real entity name from the committed graph.
    assert sanitize_filename("เลือดคั่ง/เฉื่อย (Blood Stagnation)") == (
        "เลือดคั่ง_เฉื่อย (Blood Stagnation)"
    )


# --- build_entity_stems -------------------------------------------------------


def test_build_entity_stems_maps_name_to_sanitized_stem():
    entities = [entity("หมา"), entity("a/b")]
    stems = build_entity_stems(entities)
    assert stems == {"หมา": "หมา", "a/b": "a_b"}


def test_build_entity_stems_raises_on_collision():
    # "a/b" and "a_b" both sanitize to "a_b" -- silently letting one clobber
    # the other on disk would lose a note with no trace.
    entities = [entity("a/b"), entity("a_b")]
    with pytest.raises(ValueError, match="collision"):
        build_entity_stems(entities)


# --- generate_concept_notes: frontmatter -------------------------------------


def test_note_frontmatter_has_exactly_the_five_documented_fields(tmp_path):
    graph = {"entities": [entity("หมา", type_="creature", degree=3)], "relations": []}
    output_dir = tmp_path / "concepts"

    generate_concept_notes(graph, output_dir)

    text = (output_dir / "หมา.md").read_text(encoding="utf-8")
    frontmatter = text.split("---\n")[1]
    keys = [line.split(":", 1)[0] for line in frontmatter.strip().splitlines()]
    assert keys == ["entity", "type", "degree", "generated", "aliases"]
    assert 'entity: "หมา"' in frontmatter
    assert 'type: "creature"' in frontmatter
    assert "degree: 3" in frontmatter
    assert "generated: true" in frontmatter
    assert "aliases: []" in frontmatter


def test_sanitized_entity_records_its_original_name_as_an_alias(tmp_path):
    graph = {"entities": [entity("a/b")], "relations": []}
    output_dir = tmp_path / "concepts"

    generate_concept_notes(graph, output_dir)

    assert (output_dir / "a_b.md").exists()
    assert not (output_dir / "a/b.md").exists()
    text = (output_dir / "a_b.md").read_text(encoding="utf-8")
    assert 'aliases: ["a/b"]' in text
    assert 'entity: "a/b"' in text  # frontmatter carries the true, verbatim name


def test_frontmatter_has_no_timestamp_field(tmp_path):
    graph = {"entities": [entity("หมา")], "relations": []}
    output_dir = tmp_path / "concepts"

    generate_concept_notes(graph, output_dir)

    text = (output_dir / "หมา.md").read_text(encoding="utf-8")
    frontmatter = text.split("---\n")[1]
    assert "time" not in frontmatter.lower()
    assert "date" not in frontmatter.lower()


# --- generate_concept_notes: body --------------------------------------------


def test_body_contains_description_verbatim(tmp_path):
    graph = {
        "entities": [entity("หมา", description="คำอธิบายตรงตัว<SEP>ต่อเนื่อง")],
        "relations": [],
    }
    output_dir = tmp_path / "concepts"

    generate_concept_notes(graph, output_dir)

    text = (output_dir / "หมา.md").read_text(encoding="utf-8")
    assert "คำอธิบายตรงตัว<SEP>ต่อเนื่อง" in text


def test_relation_renders_on_both_endpoints(tmp_path):
    graph = {
        "entities": [entity("หมา"), entity("แมว")],
        "relations": [relation("หมา", "แมว", keywords="เลี้ยงลูกด้วยนม", description="ทั้งคู่")],
    }
    output_dir = tmp_path / "concepts"

    generate_concept_notes(graph, output_dir)

    dog_text = (output_dir / "หมา.md").read_text(encoding="utf-8")
    cat_text = (output_dir / "แมว.md").read_text(encoding="utf-8")
    assert "- [[แมว]] — เลี้ยงลูกด้วยนม: ทั้งคู่" in dog_text
    assert "- [[หมา]] — เลี้ยงลูกด้วยนม: ทั้งคู่" in cat_text


def test_relation_bullet_links_to_the_target_entitys_sanitized_filename(tmp_path):
    graph = {
        "entities": [entity("หมา"), entity("a/b")],
        "relations": [relation("หมา", "a/b", keywords="k", description="d")],
    }
    output_dir = tmp_path / "concepts"

    generate_concept_notes(graph, output_dir)

    dog_text = (output_dir / "หมา.md").read_text(encoding="utf-8")
    # Must link to the file that actually exists on disk, not the raw name
    # (a bare "/" inside [[...]] would read as an Obsidian subfolder).
    assert "[[a_b]]" in dog_text
    assert "[[a/b]]" not in dog_text


def test_isolated_entity_has_no_relations_section(tmp_path):
    graph = {"entities": [entity("หมา", degree=0)], "relations": []}
    output_dir = tmp_path / "concepts"

    generate_concept_notes(graph, output_dir)

    text = (output_dir / "หมา.md").read_text(encoding="utf-8")
    assert "## Relations" not in text


def test_source_files_render_as_basename_wikilinks(tmp_path):
    graph = {
        "entities": [
            entity("หมา", source_files=["03-ในอดีต-น.18-19.md", "01-บทนำ-น.13-16.md"])
        ],
        "relations": [],
    }
    output_dir = tmp_path / "concepts"

    generate_concept_notes(graph, output_dir)

    text = (output_dir / "หมา.md").read_text(encoding="utf-8")
    assert "## Sources" in text
    assert "- [[01-บทนำ-น.13-16]]" in text
    assert "- [[03-ในอดีต-น.18-19]]" in text
    assert ".md]]" not in text  # basename wikilinks drop the extension


def test_flat_folder_no_subdirectories(tmp_path):
    graph = {"entities": [entity("หมา"), entity("แมว")], "relations": []}
    output_dir = tmp_path / "concepts"

    generate_concept_notes(graph, output_dir)

    children = list(output_dir.iterdir())
    assert all(child.is_file() for child in children)
    assert len(children) == 2


# --- determinism --------------------------------------------------------


def test_regeneration_is_byte_identical(tmp_path):
    graph = {
        "entities": [entity("หมา", degree=1, source_files=["a.md"]), entity("แมว", degree=1)],
        "relations": [relation("หมา", "แมว")],
    }
    output_dir = tmp_path / "concepts"

    generate_concept_notes(graph, output_dir)
    first = {p.name: p.read_bytes() for p in output_dir.iterdir()}

    generate_concept_notes(graph, output_dir)
    second = {p.name: p.read_bytes() for p in output_dir.iterdir()}

    assert first == second


# --- git-dirty guard (6.3) ---------------------------------------------------


def test_guard_passes_when_concepts_dir_does_not_exist_yet(tmp_path):
    repo_root = init_git_repo(tmp_path / "repo")
    ensure_concepts_clean(repo_root, repo_root / "corpus" / "concepts")  # no raise


def test_guard_passes_when_concepts_dir_is_clean(tmp_path):
    repo_root = init_git_repo(tmp_path / "repo")
    concepts = repo_root / "corpus" / "concepts"
    concepts.mkdir(parents=True)
    (concepts / "note.md").write_text("x", encoding="utf-8")
    run_git(repo_root, "add", "-A")
    run_git(repo_root, "commit", "-q", "-m", "seed")

    ensure_concepts_clean(repo_root, concepts)  # no raise


def test_guard_refuses_when_a_committed_note_was_hand_edited(tmp_path):
    repo_root = init_git_repo(tmp_path / "repo")
    concepts = repo_root / "corpus" / "concepts"
    concepts.mkdir(parents=True)
    (concepts / "note.md").write_text("original", encoding="utf-8")
    run_git(repo_root, "add", "-A")
    run_git(repo_root, "commit", "-q", "-m", "seed")

    (concepts / "note.md").write_text("hand-edited", encoding="utf-8")

    with pytest.raises(DirtyVaultError):
        ensure_concepts_clean(repo_root, concepts)


def test_guard_handles_a_concepts_dir_given_as_a_relative_path(tmp_path, monkeypatch):
    # The documented CLI usage passes `corpus/concepts` relative to the
    # current working directory, not relative to --repo-root.
    repo_root = init_git_repo(tmp_path / "repo")
    concepts = repo_root / "corpus" / "concepts"
    concepts.mkdir(parents=True)
    (concepts / "note.md").write_text("x", encoding="utf-8")
    run_git(repo_root, "add", "-A")
    run_git(repo_root, "commit", "-q", "-m", "seed")
    monkeypatch.chdir(repo_root)

    ensure_concepts_clean(repo_root, Path("corpus/concepts"))  # no raise


def test_guard_refuses_when_untracked_files_are_present(tmp_path):
    repo_root = init_git_repo(tmp_path / "repo")
    concepts = repo_root / "corpus" / "concepts"
    concepts.mkdir(parents=True)
    (concepts / "note.md").write_text("x", encoding="utf-8")
    run_git(repo_root, "add", "-A")
    run_git(repo_root, "commit", "-q", "-m", "seed")

    (concepts / "new-note.md").write_text("uncommitted", encoding="utf-8")

    with pytest.raises(DirtyVaultError):
        ensure_concepts_clean(repo_root, concepts)


# --- regenerate: wholesale delete + guard ------------------------------------


def test_regenerate_deletes_stale_notes_no_longer_in_the_graph(tmp_path):
    repo_root = init_git_repo(tmp_path / "repo")
    concepts = repo_root / "corpus" / "concepts"
    concepts.mkdir(parents=True)
    (concepts / "stale.md").write_text("old", encoding="utf-8")
    run_git(repo_root, "add", "-A")
    run_git(repo_root, "commit", "-q", "-m", "seed")

    graph_path = repo_root / "corpus" / "graph.json"
    graph_path.write_text(
        json.dumps({"entities": [entity("หมา")], "relations": []}), encoding="utf-8"
    )

    regenerate(graph_path, concepts, repo_root)

    assert not (concepts / "stale.md").exists()
    assert (concepts / "หมา.md").exists()


def test_regenerate_refuses_over_a_dirty_vault(tmp_path):
    repo_root = init_git_repo(tmp_path / "repo")
    concepts = repo_root / "corpus" / "concepts"
    concepts.mkdir(parents=True)
    (concepts / "note.md").write_text("original", encoding="utf-8")
    run_git(repo_root, "add", "-A")
    run_git(repo_root, "commit", "-q", "-m", "seed")
    (concepts / "note.md").write_text("hand-edited", encoding="utf-8")

    graph_path = repo_root / "corpus" / "graph.json"
    graph_path.write_text(json.dumps({"entities": [], "relations": []}), encoding="utf-8")

    with pytest.raises(DirtyVaultError):
        regenerate(graph_path, concepts, repo_root)
    # The guard runs before any deletion -- the hand edit must survive.
    assert (concepts / "note.md").read_text(encoding="utf-8") == "hand-edited"


# --- CLI ----------------------------------------------------------------


def test_main_regenerates_and_reports_count(tmp_path, capsys):
    repo_root = init_git_repo(tmp_path / "repo")
    graph_path = repo_root / "corpus" / "graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(
        json.dumps({"entities": [entity("หมา"), entity("แมว")], "relations": []}),
        encoding="utf-8",
    )
    concepts = repo_root / "corpus" / "concepts"

    main([str(graph_path), str(concepts), "--repo-root", str(repo_root)])

    assert (concepts / "หมา.md").exists()
    assert (concepts / "แมว.md").exists()
    assert "2 note" in capsys.readouterr().out
