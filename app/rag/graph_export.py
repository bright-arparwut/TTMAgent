"""Export the committed LightRAG graph store into `corpus/graph.json` (ADR
0010, "Vault: generated concept notes", ticket #17).

Reads `rag_storage/graph_chunk_entity_relation.graphml` (entity/relation
identity, description, keywords, degree) plus `kv_store_full_docs.json` /
`kv_store_full_entities.json` / `kv_store_full_relations.json` (the
per-source-note attribution) directly off disk -- zero LLM calls, no
LightRAG import. `app/rag/concept_notes.py` generates `corpus/concepts/`
from this file's output.

The graphml node/edge's own `file_path` attribute is LightRAG's *merged*
view and can be silently incomplete: spot-checked against the real,
committed two-book graph, 8 of 1,400 entities have a KV-derived source file
their graphml `file_path` omits (LightRAG truncates the merged field for
high-degree entities without flagging it). `source_files` below is always
built from the KV stores -- the pre-merge, per-document record of every
extraction -- never by trusting the graphml attribute.

Usage:
    uv run python -m app.rag.graph_export rag_storage corpus/graph.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

GRAPHML_FILENAME = "graph_chunk_entity_relation.graphml"
FULL_DOCS_FILENAME = "kv_store_full_docs.json"
FULL_ENTITIES_FILENAME = "kv_store_full_entities.json"
FULL_RELATIONS_FILENAME = "kv_store_full_relations.json"


@dataclass(frozen=True)
class ExportedEntity:
    name: str
    type: str
    description: str
    degree: int
    source_files: tuple[str, ...]


@dataclass(frozen=True)
class ExportedRelation:
    source: str
    target: str
    keywords: str
    description: str
    source_files: tuple[str, ...]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _doc_file_paths(storage_dir: Path) -> dict[str, str]:
    """doc_id -> source-note basename, from kv_store_full_docs.json."""
    docs = _read_json(storage_dir / FULL_DOCS_FILENAME)
    return {doc_id: record["file_path"] for doc_id, record in docs.items()}


def _entity_source_files(storage_dir: Path, doc_files: dict[str, str]) -> dict[str, set[str]]:
    """entity name -> the set of source-note basenames it was extracted
    from. kv_store_full_entities.json is per-document and pre-merge, so it
    carries every source a merged entity drew on -- see module docstring."""
    records = _read_json(storage_dir / FULL_ENTITIES_FILENAME)
    result: dict[str, set[str]] = {}
    for doc_id, record in records.items():
        file_path = doc_files[doc_id]
        for name in record["entity_names"]:
            result.setdefault(name, set()).add(file_path)
    return result


def _relation_source_files(
    storage_dir: Path, doc_files: dict[str, str]
) -> dict[frozenset[str], set[str]]:
    """{endpoint_a, endpoint_b} -> the set of source-note basenames the
    relation was extracted from. Keyed by frozenset: the graph is
    undirected and different documents can record the same pair in either
    order."""
    records = _read_json(storage_dir / FULL_RELATIONS_FILENAME)
    result: dict[frozenset[str], set[str]] = {}
    for doc_id, record in records.items():
        file_path = doc_files[doc_id]
        for a, b in record["relation_pairs"]:
            key = frozenset((a, b))
            result.setdefault(key, set()).add(file_path)
    return result


def load_graph(storage_dir: Path) -> tuple[list[ExportedEntity], list[ExportedRelation]]:
    """Read the committed graphml + KV stores directly. Deterministic
    ordering: entities sorted by name; relations sorted by (source, target)
    with each pair's two endpoints themselves sorted, so re-running never
    flips which side is "source"."""
    graph = nx.read_graphml(storage_dir / GRAPHML_FILENAME)
    doc_files = _doc_file_paths(storage_dir)
    entity_files = _entity_source_files(storage_dir, doc_files)
    relation_files = _relation_source_files(storage_dir, doc_files)

    entities = [
        ExportedEntity(
            name=name,
            type=data.get("entity_type", "UNKNOWN"),
            description=data.get("description", ""),
            degree=graph.degree(name),
            source_files=tuple(sorted(entity_files.get(name, ()))),
        )
        for name, data in graph.nodes(data=True)
    ]
    entities.sort(key=lambda entity: entity.name)

    relations = []
    for u, v, data in graph.edges(data=True):
        source, target = sorted((u, v))
        key = frozenset((u, v))
        relations.append(
            ExportedRelation(
                source=source,
                target=target,
                keywords=data.get("keywords", ""),
                description=data.get("description", ""),
                source_files=tuple(sorted(relation_files.get(key, ()))),
            )
        )
    relations.sort(key=lambda relation: (relation.source, relation.target))

    return entities, relations


def to_json_dict(
    entities: list[ExportedEntity], relations: list[ExportedRelation]
) -> dict:
    return {
        "entities": [
            {
                "name": entity.name,
                "type": entity.type,
                "description": entity.description,
                "degree": entity.degree,
                "source_files": list(entity.source_files),
            }
            for entity in entities
        ],
        "relations": [
            {
                "source": relation.source,
                "target": relation.target,
                "keywords": relation.keywords,
                "description": relation.description,
                "source_files": list(relation.source_files),
            }
            for relation in relations
        ],
    }


def write_graph_json(storage_dir: Path, output_path: Path) -> dict:
    """Read `storage_dir` and write the exported graph to `output_path` as
    pretty-printed, deterministic JSON (no timestamps, no locale-dependent
    sorting) -- byte-identical across runs against an unchanged store."""
    entities, relations = load_graph(storage_dir)
    payload = to_json_dict(entities, relations)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("storage_dir", type=Path, help="rag_storage/ directory")
    parser.add_argument("output_path", type=Path, help="output path for graph.json")
    args = parser.parse_args(argv)
    payload = write_graph_json(args.storage_dir, args.output_path)
    print(
        f"wrote {len(payload['entities'])} entities / {len(payload['relations'])} relations"
        f" to {args.output_path}"
    )


if __name__ == "__main__":
    main()
