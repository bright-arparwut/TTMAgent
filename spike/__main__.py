"""PROTOTYPE (ticket #16) -- one command to run the spike.

    uv run python -m spike index      # build the graph (Claude Code EXTRACT)
    uv run python -m spike graph      # report what the graph actually contains
    uv run python -m spike compare    # naive vs mix over the question set

Analysis modules are imported lazily so `index` runs before they exist.
"""

import asyncio
import json
import os
import sys

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


async def _index() -> None:
    from spike.claude_code_llm import METER
    from spike.index_corpus import index_corpus, load_source_notes
    from spike.rag import build_spike_rag

    rag = await build_spike_rag()
    notes = load_source_notes()
    print(f"indexing {len(notes)} notes, {sum(len(n.content) for n in notes)} chars", flush=True)
    await index_corpus(rag, notes)
    await rag.finalize_storages()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    meter = METER.as_dict()
    with open(os.path.join(RESULTS_DIR, "index-cost.json"), "w") as handle:
        json.dump(meter, handle, indent=2)
    print("EXTRACT backend cost:", json.dumps(meter, indent=2), flush=True)


async def _graph() -> None:
    from spike.graph_report import write_graph_report

    await write_graph_report(RESULTS_DIR)


async def _compare() -> None:
    from spike.compare import write_comparison

    await write_comparison(RESULTS_DIR)


COMMANDS = {"index": _index, "graph": _graph, "compare": _compare}


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in COMMANDS:
        print(f"usage: python -m spike [{'|'.join(COMMANDS)}]")
        raise SystemExit(2)
    asyncio.run(COMMANDS[command]())


main()
