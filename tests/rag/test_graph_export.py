"""Unit tests for app.rag.graph_export (Phase 6.1, ADR 0010 "Vault: generated
concept notes", ticket #17).

Fixtures are small synthetic rag_storage/ directories under tmp_path -- never
the real 1,400-entity graph. Facts this file is built on, confirmed against
the real committed rag_storage/ before writing this module:

- graph_chunk_entity_relation.graphml is `edgedefault="undirected"`, no
  duplicate pairs, no self-loops (1,400 nodes / 1,837 edges match the ADR's
  numbers exactly).
- kv_store_full_entities.json / kv_store_full_relations.json are keyed by
  source-note doc id (e.g. "four-elements-01"), pre-merge -- every doc an
  entity/relation was extracted from. kv_store_full_docs.json maps that doc
  id to the note's basename (its `file_path`).
- The graphml node/edge's own `file_path` attribute is LightRAG's *merged*
  view and can be silently incomplete for a high-degree entity: spot-checking
  book two's real graph found 8 of 1,400 entities where the KV-derived
  source-file set has an entry the graphml `file_path` lacks. graph_export
  must therefore build `source_files` from the KV stores, never by trusting
  the graphml attribute.
"""

import json

import networkx as nx
import pytest

from app.rag.graph_export import load_graph, main, to_json_dict, write_graph_json


def _write_kv(path, mapping):
    (path).write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")


def make_storage(
    tmp_path,
    nodes,
    edges,
    full_docs,
    full_entities,
    full_relations,
):
    """nodes: list of (name, {attrs}); edges: list of (u, v, {attrs}).
    full_docs/full_entities/full_relations mirror the real KV store shape."""
    storage = tmp_path / "rag_storage"
    storage.mkdir()

    graph = nx.Graph()
    for name, attrs in nodes:
        graph.add_node(name, **attrs)
    for u, v, attrs in edges:
        graph.add_edge(u, v, **attrs)
    nx.write_graphml(graph, storage / "graph_chunk_entity_relation.graphml")

    _write_kv(storage / "kv_store_full_docs.json", full_docs)
    _write_kv(storage / "kv_store_full_entities.json", full_entities)
    _write_kv(storage / "kv_store_full_relations.json", full_relations)
    return storage


def two_entity_storage(tmp_path, *, node_a_file_path="a.md"):
    """One relation, both endpoints attributed to the same single source
    note in both the graphml and the KV stores -- the baseline fixture that
    other tests start from and override."""
    return make_storage(
        tmp_path,
        nodes=[
            (
                "หมา",
                {
                    "entity_type": "creature",
                    "description": "สัตว์เลี้ยงลูกด้วยนม",
                    "file_path": node_a_file_path,
                },
            ),
            (
                "แมว",
                {
                    "entity_type": "creature",
                    "description": "สัตว์เลี้ยงอีกชนิด",
                    "file_path": "a.md",
                },
            ),
        ],
        edges=[
            (
                "หมา",
                "แมว",
                {
                    "keywords": "เลี้ยงลูกด้วยนม",
                    "description": "ทั้งคู่เป็นสัตว์เลี้ยง",
                    "file_path": "a.md",
                },
            )
        ],
        full_docs={"book-01": {"file_path": "a.md"}},
        full_entities={"book-01": {"entity_names": ["หมา", "แมว"]}},
        full_relations={"book-01": {"relation_pairs": [["หมา", "แมว"]]}},
    )


# --- load_graph: shape and content ------------------------------------------


def test_load_graph_reads_entity_fields(tmp_path):
    storage = two_entity_storage(tmp_path)

    entities, _ = load_graph(storage)

    dog = next(e for e in entities if e.name == "หมา")
    assert dog.type == "creature"
    assert dog.description == "สัตว์เลี้ยงลูกด้วยนม"
    assert dog.degree == 1
    assert dog.source_files == ("a.md",)


def test_load_graph_reads_relation_fields(tmp_path):
    storage = two_entity_storage(tmp_path)

    _, relations = load_graph(storage)

    assert len(relations) == 1
    relation = relations[0]
    assert {relation.source, relation.target} == {"หมา", "แมว"}
    assert relation.keywords == "เลี้ยงลูกด้วยนม"
    assert relation.description == "ทั้งคู่เป็นสัตว์เลี้ยง"
    assert relation.source_files == ("a.md",)


# --- source_files come from the KV stores, not the graphml attribute -------


def test_entity_source_files_use_kv_store_even_when_graphml_disagrees(tmp_path):
    """The graphml `file_path` on "หมา" only names one source note; the KV
    stores show it was really extracted from two. graph_export must report
    both -- trusting the graphml attribute would silently under-report."""
    storage = make_storage(
        tmp_path,
        nodes=[
            (
                "หมา",
                {
                    "entity_type": "creature",
                    "description": "d",
                    "file_path": "a.md",  # incomplete -- book two's real truncation shape
                },
            )
        ],
        edges=[],
        full_docs={
            "book-01": {"file_path": "a.md"},
            "book-02": {"file_path": "b.md"},
        },
        full_entities={
            "book-01": {"entity_names": ["หมา"]},
            "book-02": {"entity_names": ["หมา"]},
        },
        full_relations={
            "book-01": {"relation_pairs": []},
            "book-02": {"relation_pairs": []},
        },
    )

    entities, _ = load_graph(storage)

    assert entities[0].source_files == ("a.md", "b.md")


def test_relation_source_files_merge_across_docs_regardless_of_pair_order(tmp_path):
    """One doc records the pair as (a, b), another as (b, a) -- both must
    count towards the same undirected relation's source files."""
    storage = make_storage(
        tmp_path,
        nodes=[
            ("หมา", {"entity_type": "creature", "description": "d", "file_path": "a.md"}),
            ("แมว", {"entity_type": "creature", "description": "d", "file_path": "a.md"}),
        ],
        edges=[("หมา", "แมว", {"keywords": "k", "description": "d", "file_path": "a.md"})],
        full_docs={
            "book-01": {"file_path": "a.md"},
            "book-02": {"file_path": "b.md"},
        },
        full_entities={
            "book-01": {"entity_names": ["หมา", "แมว"]},
            "book-02": {"entity_names": ["หมา", "แมว"]},
        },
        full_relations={
            "book-01": {"relation_pairs": [["หมา", "แมว"]]},
            "book-02": {"relation_pairs": [["แมว", "หมา"]]},
        },
    )

    _, relations = load_graph(storage)

    assert relations[0].source_files == ("a.md", "b.md")


# --- deterministic ordering --------------------------------------------------


def test_entities_are_sorted_by_name(tmp_path):
    storage = make_storage(
        tmp_path,
        nodes=[
            ("แมว", {"entity_type": "creature", "description": "d", "file_path": "a.md"}),
            ("หมา", {"entity_type": "creature", "description": "d", "file_path": "a.md"}),
            ("กา", {"entity_type": "creature", "description": "d", "file_path": "a.md"}),
        ],
        edges=[],
        full_docs={"book-01": {"file_path": "a.md"}},
        full_entities={"book-01": {"entity_names": ["แมว", "หมา", "กา"]}},
        full_relations={"book-01": {"relation_pairs": []}},
    )

    entities, _ = load_graph(storage)

    assert [e.name for e in entities] == sorted(["แมว", "หมา", "กา"])


def test_relation_endpoints_are_canonically_sorted(tmp_path):
    """Regardless of which side networkx reports as source/target, the
    exported relation always orders its two endpoints the same way, so
    re-running never flips (source, target) and dirties the diff."""
    storage = two_entity_storage(tmp_path)

    _, relations = load_graph(storage)

    relation = relations[0]
    assert (relation.source, relation.target) == tuple(sorted(["หมา", "แมว"]))


def test_write_graph_json_is_byte_stable_across_two_runs(tmp_path):
    storage = two_entity_storage(tmp_path)
    output_path = tmp_path / "corpus" / "graph.json"

    write_graph_json(storage, output_path)
    first = output_path.read_bytes()
    write_graph_json(storage, output_path)
    second = output_path.read_bytes()

    assert first == second
    assert len(first) > 0


# --- JSON shape --------------------------------------------------------------


def test_to_json_dict_has_the_documented_fields_only(tmp_path):
    storage = two_entity_storage(tmp_path)
    entities, relations = load_graph(storage)

    payload = to_json_dict(entities, relations)

    assert set(payload.keys()) == {"entities", "relations"}
    entity = payload["entities"][0]
    assert set(entity.keys()) == {"name", "type", "description", "degree", "source_files"}
    relation = payload["relations"][0]
    assert set(relation.keys()) == {
        "source",
        "target",
        "keywords",
        "description",
        "source_files",
    }


def test_write_graph_json_round_trips_through_disk(tmp_path):
    storage = two_entity_storage(tmp_path)
    output_path = tmp_path / "corpus" / "graph.json"

    write_graph_json(storage, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert len(payload["entities"]) == 2
    assert len(payload["relations"]) == 1
    assert output_path.read_text(encoding="utf-8").endswith("\n")


# --- CLI ----------------------------------------------------------------


def test_main_writes_file_and_reports_counts(tmp_path, capsys):
    storage = two_entity_storage(tmp_path)
    output_path = tmp_path / "corpus" / "graph.json"

    main([str(storage), str(output_path)])

    assert output_path.exists()
    out = capsys.readouterr().out
    assert "2 entities" in out
    assert "1 relations" in out


@pytest.mark.parametrize("missing_file", ["kv_store_full_docs.json"])
def test_missing_kv_store_raises(tmp_path, missing_file):
    storage = two_entity_storage(tmp_path)
    (storage / missing_file).unlink()

    with pytest.raises(FileNotFoundError):
        load_graph(storage)
