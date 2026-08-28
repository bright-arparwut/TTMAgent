"""PROTOTYPE (ticket #36) -- do TongueDescription's free-Thai values land on
the graph's node names?

#31 fixed the five axis values (สี, ฝ้า, ขนาด, รูปร่าง, จุดบนลิ้น) as free Thai
text, steered by the describer prompt rather than enforced by enum, and
deferred the hardening question to #36's post-#30 check. This is that check:
score sampled Tongue Description axis values against the graph's actual
entity names and report, per axis, how many land.

"Landing" is lexical, deliberately: the tongue turn renders the description
as Thai text (#31 decision 6) and that text IS the retrieval query, so the
KEYWORD role can only surface a node name that is literally present. Tiers:

    exact          value == node name (whitespace/case normalized)
    node_in_value  a node name appears inside the free-text value
    value_in_node  the value appears inside a longer node name
    near           best fuzzy ratio >= graph_report's near-duplicate
                   threshold -- spelling drift, the evidence a hardening
                   ruling needs
    miss           nothing close

The first three count as landed. Thai has no word boundaries, so containment
can false-positive on short names; names under MIN_CONTAINMENT_CHARS are
excluded from containment and every hit reports the node behind it so a
human can audit the tier, not just the rate. Matched nodes carry their
source-note `file_path`, which is what answers #36's "which vocabulary"
sub-question (ch. 6-10 entry names vs ch. 12 synthesis terms) once those
chapters are transcribed (#32/#33) and indexed (#30).

Run it:

    uv run python -m spike landing
    uv run python -m spike landing --descriptions photos.json --out report.json

`--descriptions` takes one JSON TongueDescription object or a list of them,
keyed by #31's decided schema (color, coating, size, shape, spots; other
keys ignored). Without it, the built-in probe runs: the book's own
normal-tongue baseline quoted from the Part 1 transcription. Against the
current four-elements-only graph the probe is a negative control -- landing
should be ~zero until #30 indexes the tongue book.
"""

import argparse
import difflib
import json
import os

from spike.graph_report import SIMILARITY_THRESHOLD, _normalise

GRAPH_RAW_DEFAULT = os.path.join(os.path.dirname(__file__), "results", "graph-raw.json")

# #31's decided schema keys -> the ch. 12 axis names (CONTEXT.md -> Tongue Description).
AXES = {
    "color": "สี",
    "coating": "ฝ้า",
    "size": "ขนาด",
    "shape": "รูปร่าง",
    "spots": "จุดบนลิ้น",
}

MIN_CONTAINMENT_CHARS = 3

LANDED_TIERS = ("exact", "node_in_value", "value_in_node")

# The book's own normal-tongue baseline, quoted from the Part 1 transcription
# (corpus/tongue-100 notes 002 and 010). A smoke probe for the harness -- not
# described-photo data. Part 1 attests no จุดบนลิ้น value at all (the spots
# vocabulary starts with ch. 6-10, ticket #32), so the probe carries four axes.
NORMAL_TONGUE_PROBE = {
    "color": "แดงอ่อน",  # 010: "ลิ้นปกติมีสีแดงอ่อน"
    "coating": "ฝ้าสีขาวบาง",  # 010: "มีฝ้าสีขาวบาง"
    "size": "ไม่หนาหรือบางเกินไป",  # 010: "รูปร่างไม่หนาหรือบางเกินไป"
    "shape": "ไม่เบี้ยวไปด้านหนึ่งด้านใด",  # 002: the normal-tongue paragraph
}


def score_value(value: str, entities: list[dict]) -> tuple[str, list[dict], list[dict]]:
    """One axis value against every entity name -> (tier, hits, nearest-3)."""
    norm_value = _normalise(value)
    tiers: dict[str, list[dict]] = {tier: [] for tier in LANDED_TIERS}
    scored: list[tuple[float, dict]] = []

    for entity in entities:
        norm_node = _normalise(entity["name"])
        if not norm_node:
            continue
        if norm_node == norm_value:
            tiers["exact"].append(entity)
        elif len(norm_node) >= MIN_CONTAINMENT_CHARS and norm_node in norm_value:
            tiers["node_in_value"].append(entity)
        elif len(norm_value) >= MIN_CONTAINMENT_CHARS and norm_value in norm_node:
            tiers["value_in_node"].append(entity)
        ratio = difflib.SequenceMatcher(None, norm_value, norm_node).ratio()
        scored.append((ratio, entity))

    scored.sort(key=lambda item: -item[0])
    nearest = [
        {"name": entity["name"], "similarity": round(ratio, 3)} for ratio, entity in scored[:3]
    ]
    for tier in LANDED_TIERS:
        if tiers[tier]:
            return tier, tiers[tier], nearest
    if scored and scored[0][0] >= SIMILARITY_THRESHOLD:
        return "near", [scored[0][1]], nearest
    return "miss", [], nearest


def build_report(descriptions: list[dict], entities: list[dict]) -> dict:
    rows = []
    for index, description in enumerate(descriptions):
        for key, label in AXES.items():
            value = (description.get(key) or "").strip()
            if not value:
                continue
            tier, hits, nearest = score_value(value, entities)
            rows.append(
                {
                    "description": index,
                    "axis": key,
                    "axis_label": label,
                    "value": value,
                    "tier": tier,
                    "landed": tier in LANDED_TIERS,
                    "matched": [
                        {
                            "name": hit["name"],
                            "type": hit.get("type", ""),
                            "file_path": hit.get("file_path", ""),
                        }
                        for hit in hits
                    ],
                    "nearest": nearest,
                }
            )

    axes = {}
    for key, label in AXES.items():
        axis_rows = [row for row in rows if row["axis"] == key]
        if not axis_rows:
            continue
        landed = sum(row["landed"] for row in axis_rows)
        near = sum(row["tier"] == "near" for row in axis_rows)
        axes[key] = {
            "axis_label": label,
            "values": len(axis_rows),
            "landed": landed,
            "near": near,
            "missed": len(axis_rows) - landed - near,
            "landing_rate": round(landed / len(axis_rows), 3),
        }

    return {
        "entity_count": len(entities),
        "description_count": len(descriptions),
        "axes": axes,
        "rows": rows,
    }


def render(report: dict, source: str) -> str:
    lines = [
        "LANDING -- ticket #36 check",
        f"graph entities: {report['entity_count']}",
        f"descriptions:   {report['description_count']} from {source}",
        "",
        f"{'axis':<24}{'values':>7}{'landed':>8}{'near':>6}{'miss':>6}{'rate':>7}",
    ]
    for key, axis in report["axes"].items():
        label = f"{axis['axis_label']} ({key})"
        lines.append(
            f"{label:<24}{axis['values']:>7}{axis['landed']:>8}"
            f"{axis['near']:>6}{axis['missed']:>6}{axis['landing_rate']:>7.2f}"
        )
    lines.append("")
    for row in report["rows"]:
        if row["matched"]:
            hit = row["matched"][0]
            where = f" <- {hit['file_path']}" if hit["file_path"] else ""
            detail = f"{hit['name']}{where}"
        else:
            detail = ", ".join(
                f"{item['name']} ({item['similarity']})" for item in row["nearest"]
            )
            detail = f"nearest: {detail}" if detail else "graph is empty"
        lines.append(f"[{row['tier']}] {row['axis_label']}: \"{row['value']}\" -> {detail}")
    return "\n".join(lines)


def run_cli(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(
        prog="python -m spike landing",
        description="Score Tongue Description axis values against graph entity names (#36).",
    )
    parser.add_argument("--graph", default=GRAPH_RAW_DEFAULT, help="graph-raw.json dump")
    parser.add_argument(
        "--descriptions", help="JSON file: one TongueDescription object or a list of them"
    )
    parser.add_argument("--out", help="write the full report JSON here")
    args = parser.parse_args(argv)

    with open(args.graph, encoding="utf-8") as handle:
        entities = json.load(handle)["entities"]

    if args.descriptions:
        with open(args.descriptions, encoding="utf-8") as handle:
            data = json.load(handle)
        descriptions = data if isinstance(data, list) else [data]
        source = args.descriptions
    else:
        descriptions = [NORMAL_TONGUE_PROBE]
        source = "built-in normal-tongue probe (corpus notes 002/010)"

    report = build_report(descriptions, entities)
    report["graph"] = args.graph
    report["source"] = source
    print(render(report, source))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        print(f"\nreport written to {args.out}")
    return report
