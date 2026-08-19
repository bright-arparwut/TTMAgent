"""PROTOTYPE (ticket #16) -- render the run into one readable results file."""

import json
import os

MODES = ("naive", "mix")


def _corpus_chunk_count() -> int:
    path = os.path.join(os.path.dirname(__file__), "rag_storage", "kv_store_text_chunks.json")
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as handle:
        return len(json.load(handle))


def _load(results_dir: str, name: str) -> dict:
    path = os.path.join(results_dir, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _bar(value: float | None) -> str:
    if value is None:
        return "n/a"
    filled = round(value * 10)
    return f"{'█' * filled}{'░' * (10 - filled)} {value:.0%}"


def render(results_dir: str) -> str:
    graph = _load(results_dir, "graph-summary.json")
    comparison = _load(results_dir, "comparison.json")
    cost = _load(results_dir, "index-cost.json")
    verdict = comparison.get("verdict", {})

    lines: list[str] = []
    add = lines.append

    add("# Spike results — LightRAG `naive` vs `mix` on `four-elements`")
    add("")
    add("Ticket #16 · map #9 · branch `spike/lightrag-naive-vs-mix`")
    add("")

    add("## 1. The graph")
    add("")
    add(f"- **Entities**: {graph.get('entity_count', '?')}")
    add(f"- **Relations**: {graph.get('relation_count', '?')}")
    add(f"- **Relations per entity**: {graph.get('relations_per_entity', '?')}")
    add(f"- **Isolated (degree 0)**: {graph.get('isolated_count', '?')}")
    add("")
    if graph.get("entity_types"):
        add("| Entity type | Count |")
        add("| --- | ---: |")
        for name, count in graph["entity_types"].items():
            add(f"| {name} | {count} |")
        add("")
    if graph.get("top_degree_entities"):
        add("**Most connected entities**")
        add("")
        add("| Entity | Type | Degree |")
        add("| --- | --- | ---: |")
        for entity in graph["top_degree_entities"][:15]:
            add(f"| {entity['name']} | {entity['type']} | {entity['degree']} |")
        add("")

    add("## 2. Thai entity consistency")
    add("")
    duplicates = graph.get("near_duplicates", [])
    if not duplicates:
        add("No near-duplicate entity names above the 0.82 similarity threshold — "
            "the same concept is not fragmenting across spellings.")
    else:
        add(f"{len(duplicates)} pair(s) above the 0.82 character-similarity threshold. "
            "**Most are false positives** — Thai compounds that share a prefix but mean "
            "opposite things. See caveat 4 before reading this as fragmentation:")
        add("")
        add("| Similarity | A | B |")
        add("| ---: | --- | --- |")
        for pair in duplicates[:25]:
            add(f"| {pair['similarity']} | {pair['a']} | {pair['b']} |")
    add("")

    add("## 3. `naive` vs `mix` — section recall")
    add("")
    total_chunks = _corpus_chunk_count()
    naive_chunks = max(
        (row["modes"].get("naive", {}).get("chunk_count", 0)
         for row in comparison.get("questions", [])),
        default=0,
    )
    if total_chunks:
        add(f"> **Read this metric with care.** The whole corpus is **{total_chunks} chunks**, "
            f"and `naive` returns **{naive_chunks}** of them on every question — "
            f"{naive_chunks / total_chunks:.0%} of the book. Section recall is therefore close to "
            "saturated for both modes, and the near-tie below is a property of a 39-page "
            "corpus, not evidence that the graph adds nothing. See Caveats.")
        add("")
    overall = verdict.get("mean_section_recall", {})
    multi = verdict.get("mean_section_recall_multi_hop", {})
    add("| Question set | `naive` | `mix` |")
    add("| --- | --- | --- |")
    add(f"| All 10 | {_bar(overall.get('naive'))} | {_bar(overall.get('mix'))} |")
    add(f"| Multi-hop only | {_bar(multi.get('naive'))} | {_bar(multi.get('mix'))} |")
    add("")
    wins = verdict.get("wins", {})
    add(f"- `mix` better on: {', '.join(wins.get('mix', [])) or '—'}")
    add(f"- `naive` better on: {', '.join(wins.get('naive', [])) or '—'}")
    add(f"- Tied: {', '.join(wins.get('tie', [])) or '—'}")
    add("")

    add("### Per question")
    add("")
    add("| Q | hops | needs | `naive` found | `mix` found | winner |")
    add("| --- | ---: | --- | --- | --- | --- |")
    for row in comparison.get("questions", []):
        cells = {}
        for mode in MODES:
            data = row["modes"].get(mode, {})
            if "recall" not in data:
                cells[mode] = ("err", -1.0)
                continue
            recall = data["recall"]
            got = ",".join(recall["found_expected"]) or "—"
            cells[mode] = (f"{got} ({recall['recall']:.0%})", recall["recall"])
        naive_cell, naive_score = cells["naive"]
        mix_cell, mix_score = cells["mix"]
        winner = "mix" if mix_score > naive_score else ("naive" if naive_score > mix_score else "=")
        needs = ",".join(row["modes"].get("mix", {}).get("recall", {}).get("expected", []))
        add(f"| {row['qid']} | {row['hops']} | {needs} | {naive_cell} | {mix_cell} | {winner} |")
    add("")

    add("### Where the winning evidence came from")
    add("")
    add("For each multi-hop question: which sections arrived as **chunks** (flat retrieval "
        "could find these) versus as **relations** (only the graph supplies these).")
    add("")
    add("| Q | mode | via chunks | via relations | recall |")
    add("| --- | --- | ---: | ---: | ---: |")
    for row in comparison.get("questions", []):
        if row["hops"] < 2:
            continue
        for mode in MODES:
            data = row["modes"].get(mode, {})
            if "recall" not in data:
                continue
            add(f"| {row['qid']} | `{mode}` | {len(data.get('sections_from_chunks', []))} | "
                f"{len(data.get('sections_from_relations', []))} | "
                f"{data['recall']['recall']:.0%} |")
    add("")

    add("## 4. Provenance")
    add("")
    add("Can the `(อ้างอิง: …)` footer be built from what came back? Via `aquery_data`, yes:")
    add("")
    add("| mode | questions with a resolving reference list | mean references |")
    add("| --- | ---: | ---: |")
    for mode in MODES:
        rows = [row["modes"].get(mode, {}) for row in comparison.get("questions", [])]
        rows = [r for r in rows if "recall" in r]
        ok = sum(1 for r in rows if r.get("references_resolve"))
        counts = [r.get("reference_count", 0) for r in rows]
        mean_refs = round(sum(counts) / len(counts), 1) if counts else 0
        add(f"| `{mode}` | {ok}/{len(rows)} | {mean_refs} |")
    add("")
    add("Every reference carries a `file_path`, and ticket #12 made that filename the "
        "citation — so the footer is buildable. But **only through `aquery_data`**; see "
        "caveat 5.")
    add("")

    add("## 5. Caveats — read before quoting any number above")
    add("")
    total_chunks = _corpus_chunk_count()
    add(f"1. **The corpus is too small for this comparison to discriminate.** {total_chunks} "
        "chunks total; `naive` top-k returns 20 of them. Flat retrieval is handing over most "
        "of the book on every question, so both modes score near 100% and the headline "
        "near-tie is an artifact of corpus size. This answers the map's open question "
        "*'whether 42.5k tokens is enough graph to differentiate the two modes'* — **it is "
        "not.** A defensible thesis comparison needs book two, or a top-k tuned well below "
        "corpus size.")
    add("2. **The decisive result is n=1.** Only Q06 separated the modes. It separated them "
        "in exactly the predicted way, but one question is an illustration, not evidence.")
    add("3. **This measures retrieval, not answers.** No generation, no judge, no gold "
        "answers. `mix` finding the right section does not prove the Advisor writes a better "
        "reply from it. That is the map's *Thesis evaluation design* fog, still unresolved.")
    add("4. **The near-duplicate detector over-reports.** Of the pairs in section 2, most are "
        "semantically *opposite* concepts that share a Thai prefix — `ธาตุดินที่มากไป` vs "
        "`ธาตุน้ำที่มากไป` are different elements, not spelling variants. Character-similarity "
        "is the wrong tool for Thai compounds. Genuine duplicates were few: `จรราศี`/`จักรราศี` "
        "and `สังคมปัจจุบัน`/`สังคมโลกปัจจุบัน`.")
    add("5. **`only_need_context=True` does not carry provenance.** It returns bare "
        "`reference_id`s with no id→file_path map, and `include_references=True` does not "
        "change that. `aquery_data` does return the map. Ticket #13's design stands, but the "
        "seam must call **`aquery_data`**, not `aquery(only_need_context=True)`.")
    add("6. **LightRAG basenames `file_path`.** The directory does not survive indexing. "
        "Ticket #12's *'the filename IS the citation'* holds; nothing may depend on the path "
        "around it.")
    add("")

    add("## 6. EXTRACT backend cost (Claude Code headless)")
    add("")
    if cost:
        add("| Metric | Value |")
        add("| --- | ---: |")
        for key, value in cost.items():
            add(f"| {key} | {value} |")
    add("")
    return "\n".join(lines)


def write_report(results_dir: str) -> str:
    text = render(results_dir)
    path = os.path.join(results_dir, "RESULTS.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path
