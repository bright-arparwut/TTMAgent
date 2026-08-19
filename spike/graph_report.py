"""PROTOTYPE (ticket #16) -- what did EXTRACT actually build?

Answers the ticket's first two questions: how big is the graph, and are the
entities coherent TTM concepts or noise. The near-duplicate pass matters most:
if the same concept appears under several Thai spellings, `mix` is traversing a
fractured graph and the ontology decision needs revisiting.
"""

import difflib
import json
import os
from collections import Counter

SIMILARITY_THRESHOLD = 0.82
TTM_MARKERS = ("ธาตุ", "ราศี", "สมุนไพร", "อาการ", "สมดุล", "พลัง", "ดาว", "สุขภาพ")


def _normalise(name: str) -> str:
    return "".join(name.split()).lower()


def find_near_duplicates(names: list[str]) -> list[tuple[str, str, float]]:
    """Thai spelling drift: same concept, several surface forms."""
    pairs: list[tuple[str, str, float]] = []
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            ratio = difflib.SequenceMatcher(None, _normalise(left), _normalise(right)).ratio()
            if ratio >= SIMILARITY_THRESHOLD:
                pairs.append((left, right, round(ratio, 3)))
    return sorted(pairs, key=lambda item: -item[2])


async def collect_graph(rag) -> dict:
    graph = rag.chunk_entity_relation_graph
    labels = await graph.get_all_labels()

    entities = []
    for label in labels:
        node = await graph.get_node(label)
        if node is None:
            continue
        entities.append(
            {
                "name": label,
                "type": node.get("entity_type", "UNKNOWN"),
                "description": (node.get("description") or "")[:400],
                "file_path": node.get("file_path", ""),
                "degree": await graph.node_degree(label),
            }
        )

    # get_all_edges returns dicts carrying source/target plus edge data --
    # no per-edge round trip, and no silent empty-list fallback.
    relations = [
        {
            "source": edge.get("source"),
            "target": edge.get("target"),
            "keywords": edge.get("keywords", ""),
            "weight": edge.get("weight"),
            "description": (edge.get("description") or "")[:300],
            "file_path": edge.get("file_path", ""),
        }
        for edge in await graph.get_all_edges()
    ]

    return {"entities": entities, "relations": relations}


def summarise(graph_data: dict) -> dict:
    entities = graph_data["entities"]
    relations = graph_data["relations"]
    names = [entity["name"] for entity in entities]
    ttm_hits = [n for n in names if any(marker in n for marker in TTM_MARKERS)]
    isolated = [entity["name"] for entity in entities if entity["degree"] == 0]

    return {
        "entity_count": len(entities),
        "relation_count": len(relations),
        "relations_per_entity": round(len(relations) / len(entities), 2) if entities else 0,
        "entity_types": dict(Counter(entity["type"] for entity in entities).most_common()),
        "isolated_entities": isolated,
        "isolated_count": len(isolated),
        "ttm_flavoured_entity_count": len(ttm_hits),
        "near_duplicates": [
            {"a": a, "b": b, "similarity": score} for a, b, score in find_near_duplicates(names)
        ],
        "top_degree_entities": sorted(
            ({"name": e["name"], "type": e["type"], "degree": e["degree"]} for e in entities),
            key=lambda item: -item["degree"],
        )[:25],
    }


async def write_graph_report(results_dir: str) -> dict:
    from spike.rag import build_spike_rag

    rag = await build_spike_rag()
    graph_data = await collect_graph(rag)
    report = summarise(graph_data)
    await rag.finalize_storages()

    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "graph-raw.json"), "w", encoding="utf-8") as handle:
        json.dump(graph_data, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(results_dir, "graph-summary.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    print(json.dumps({k: v for k, v in report.items() if k != "near_duplicates"},
                     ensure_ascii=False, indent=2))
    print(f"\nnear-duplicate pairs: {len(report['near_duplicates'])}")
    for pair in report["near_duplicates"][:20]:
        print(f"   {pair['similarity']}  {pair['a']}  ~~  {pair['b']}")
    return report
