"""PROTOTYPE (ticket #16) -- naive vs mix over the question set.

Runs via `aquery_data`, not `aquery(only_need_context=True)`. Both stop before
generation, but only `aquery_data` returns the `references` list mapping
reference_id -> file_path. Under only_need_context the context carries bare
reference_ids and nothing that resolves them, so the citation footer ticket #13
specified cannot be built from it -- see RESULTS.md. This is the spike
correcting an assumption in #13, and it is why the seam should call
`aquery_data`.

Section recall is the headline metric: did the context contain every source
note the answer needs? A multi-hop question where `naive` recalls 1 of 3
sections and `mix` recalls 3 of 3 is the thesis claim, concretely.
"""

import json
import os
import re

from lightrag import QueryParam

from spike.questions import QUESTIONS, Question

MODES = ("naive", "mix")
# LightRAG basenames file_path -- the directory does not survive indexing, so
# match the leading note number of the filename itself. (Ticket #12's "the
# filename IS the citation" holds; the path around it does not.)
NOTE_PATTERN = re.compile(r"(?:^|/)(\d{2})-")


def sections_in(file_paths) -> set[str]:
    """Which source notes the returned evidence actually came from."""
    found: set[str] = set()
    for path in file_paths:
        found.update(NOTE_PATTERN.findall(path or ""))
    return found


def _recall(question: Question, found: set[str]) -> dict:
    expected = set(question.expects)
    hit = expected & found
    return {
        "expected": sorted(expected),
        "found_expected": sorted(hit),
        "missing": sorted(expected - hit),
        "recall": round(len(hit) / len(expected), 2) if expected else 0.0,
        "extra_sections": sorted(found - expected),
    }


async def run_question(rag, question: Question) -> dict:
    result: dict = {
        "qid": question.qid,
        "text": question.text,
        "hops": question.hops,
        "why": question.why,
        "chain": list(question.chain),
        "modes": {},
    }
    for mode in MODES:
        param = QueryParam(mode=mode)
        try:
            payload = await rag.aquery_data(question.text, param=param)
        except Exception as error:  # spike: record and keep going
            result["modes"][mode] = {"error": f"{type(error).__name__}: {error}"}
            continue

        data = payload.get("data") or {}
        chunks = data.get("chunks") or []
        entities = data.get("entities") or []
        relationships = data.get("relationships") or []
        references = data.get("references") or []

        # Evidence reaches the Advisor three ways; all three count as retrieval.
        # Ticket #13: relations contribute their source notes, entities do not.
        chunk_sections = sections_in(c.get("file_path", "") for c in chunks)
        relation_sections = sections_in(r.get("file_path", "") for r in relationships)
        found = chunk_sections | relation_sections

        result["modes"][mode] = {
            "chunk_count": len(chunks),
            "entity_count": len(entities),
            "relation_count": len(relationships),
            "sections": sorted(found),
            "sections_from_chunks": sorted(chunk_sections),
            "sections_from_relations": sorted(relation_sections),
            "recall": _recall(question, found),
            # Provenance (ticket #13): can we build the (อ้างอิง: ...) footer?
            "reference_count": len(references),
            "references_resolve": all(r.get("file_path") for r in references) and bool(references),
            "chunks": chunks,
            "entities": [
                {"entity_name": e.get("entity_name"), "entity_type": e.get("entity_type")}
                for e in entities
            ],
            "relationships": [
                {"src": r.get("src_id"), "tgt": r.get("tgt_id"),
                 "file_path": r.get("file_path")}
                for r in relationships
            ],
            "references": references,
        }
    return result


def _verdict(rows: list[dict]) -> dict:
    per_mode = {mode: {"recall_sum": 0.0, "n": 0} for mode in MODES}
    multi_hop = {mode: {"recall_sum": 0.0, "n": 0} for mode in MODES}
    wins = {"mix": [], "naive": [], "tie": []}

    for row in rows:
        scores = {}
        for mode in MODES:
            data = row["modes"].get(mode, {})
            if "recall" not in data:
                continue
            score = data["recall"]["recall"]
            scores[mode] = score
            per_mode[mode]["recall_sum"] += score
            per_mode[mode]["n"] += 1
            if row["hops"] > 1:
                multi_hop[mode]["recall_sum"] += score
                multi_hop[mode]["n"] += 1
        if len(scores) == 2:
            if scores["mix"] > scores["naive"]:
                wins["mix"].append(row["qid"])
            elif scores["naive"] > scores["mix"]:
                wins["naive"].append(row["qid"])
            else:
                wins["tie"].append(row["qid"])

    def mean(bucket):
        return round(bucket["recall_sum"] / bucket["n"], 3) if bucket["n"] else None

    return {
        "mean_section_recall": {mode: mean(per_mode[mode]) for mode in MODES},
        "mean_section_recall_multi_hop": {mode: mean(multi_hop[mode]) for mode in MODES},
        "wins": wins,
    }


async def write_comparison(results_dir: str) -> dict:
    from spike.rag import build_spike_rag

    rag = await build_spike_rag()
    rows = []
    for question in QUESTIONS:
        print(f"  {question.qid} ({question.hops} hop) ...", flush=True)
        rows.append(await run_question(rag, question))
    await rag.finalize_storages()

    summary = {"verdict": _verdict(rows), "questions": rows}
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "comparison.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    print(json.dumps(summary["verdict"], ensure_ascii=False, indent=2))
    return summary
