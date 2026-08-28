"""Phase 3 acceptance check (issue #36, decision 4; docs/adr/0010).

Re-describes a sample of stored Tongue Photos through the new five-axis
`DESCRIBE_PROMPT` and reports, per axis, whether the emitted Thai value
lands on the committed tongue-100 graph's node names -- exact, substring,
or near-variant match, the same three-way rule ticket #36's steering-
vocabulary check used (see spike/graph_report.py's near-duplicate pass for
the precedent). A poor landing rate reopens the Literal-hardening question
(see .superpowers/sdd/phase-3-brief.md); this script only measures and
reports -- it never fails the build.

Reads photos directly off the `tongue_photos` Mongo collection, bypassing
TonguePhotoRepository on purpose: that repository deliberately has no
listing method (ADR 0007 -- the capability URL is the only read path for
application code), but this is a one-off research script, not a request
handler.

Usage:
    uv run python scripts/redescribe_photos.py [--limit N]

Needs a reachable MongoDB (MONGODB_URI) holding the `tongue_photos`
collection, and a working Vision Describer slot (DESCRIBER_* in .env).
When either is unavailable, this prints an honest explanation instead of
fabricating numbers.
"""

import argparse
import asyncio
import difflib
import io
import json
import logging
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path

from PIL import Image

# Allow `import app.*` when run as `python scripts/redescribe_photos.py`
# (script dir, not repo root, is sys.path[0] otherwise) -- see scripts/chat.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings, get_settings  # noqa: E402
from app.models.schemas import TongueDescription  # noqa: E402
from app.vision.describer import VisionDescriber  # noqa: E402

logger = logging.getLogger(__name__)

# The five schema axes, in the same order as the schema and the dispatcher's
# Thai-label render (app/pipeline/dispatcher.py:_render_tongue_description).
AXES: tuple[str, ...] = ("color", "coating", "size", "shape", "spots")
AXIS_LABELS: dict[str, str] = {
    "color": "สี",
    "coating": "ฝ้า",
    "size": "ขนาด",
    "shape": "รูปร่าง",
    "spots": "จุดบนลิ้น",
}

# Matches spike/graph_report.py's near-duplicate pass (SIMILARITY_THRESHOLD),
# reused here as the "near-variant" bar so both checks agree on what counts
# as the same concept under Thai spelling/composition drift.
NEAR_VARIANT_THRESHOLD = 0.82

MongoDoc = dict


class MongoUnavailableError(Exception):
    """Raised when the `tongue_photos` collection cannot be reached -- a
    distinct, honestly-reported outcome from "reachable but empty"."""


def _normalise(text: str) -> str:
    """Whitespace-insensitive comparison key -- book rows and node names
    disagree on spacing around "และ" far more often than on substance
    (e.g. "แดง และ ชื้น" vs "แดงและชื้น")."""
    return "".join(text.split())


def match_kind(value: str, node_names: frozenset[str]) -> str:
    """Ticket #36's three-way landing rule for one axis value against the
    committed graph's node names: "exact" (verbatim, whitespace aside),
    "substring" (either direction), "near_variant" (a close paraphrase),
    else "miss". Mirrors the table issue #36's resolution reported for the
    steering vocabulary itself; this applies the same rule to the
    Describer's actual output.
    """
    normalised_value = _normalise(value)
    if not normalised_value or not node_names:
        return "miss"

    normalised_names = {name: _normalise(name) for name in node_names}

    if any(normalised_value == normalised_name for normalised_name in normalised_names.values()):
        return "exact"

    if any(
        normalised_value in normalised_name or normalised_name in normalised_value
        for normalised_name in normalised_names.values()
    ):
        return "substring"

    best_ratio = max(
        difflib.SequenceMatcher(None, normalised_value, normalised_name).ratio()
        for normalised_name in normalised_names.values()
    )
    return "near_variant" if best_ratio >= NEAR_VARIANT_THRESHOLD else "miss"


def load_graph_node_names(rag_storage_dir: Path, book_id: str = "tongue-100") -> frozenset[str]:
    """The committed graph's node names for one book, read straight off
    LightRAG's own per-doc extraction record (`kv_store_full_entities.json`
    -- doc_id -> {entity_names: [...]}), the same source issue #36's
    resolution measured against (1,141 unique tongue-100 names, 139 docs).
    """
    kv_path = rag_storage_dir / "kv_store_full_entities.json"
    with kv_path.open(encoding="utf-8") as handle:
        entities_by_doc: dict = json.load(handle)

    names: set[str] = set()
    prefix = f"{book_id}-"
    for doc_id, doc in entities_by_doc.items():
        if not doc_id.startswith(prefix):
            continue
        names.update(doc.get("entity_names", []))
    return frozenset(names)


DescribeFn = Callable[[Image.Image], Awaitable[TongueDescription]]


async def redescribe_and_report(
    photo_docs: list[MongoDoc],
    describe: DescribeFn,
    node_names: frozenset[str],
) -> dict[str, Counter]:
    """Re-describe every photo doc's stored JPEG and tally each axis
    value's landing against `node_names`. A single photo's describe
    failure is logged and skipped -- one bad crop must not sink the whole
    sample's numbers."""
    tallies: dict[str, Counter] = {axis: Counter() for axis in AXES}

    for doc in photo_docs:
        image = Image.open(io.BytesIO(bytes(doc["image"])))
        try:
            description = await describe(image)
        except Exception:
            logger.exception("Re-describe failed for photo %s", doc.get("photo_id", "?"))
            continue

        for axis in AXES:
            value = getattr(description, axis)
            tallies[axis][match_kind(value, node_names)] += 1

    return tallies


def format_report(tallies: dict[str, Counter]) -> str:
    header = (
        f"{'axis':<20} {'n':>4} {'exact':>6} {'substring':>10} "
        f"{'near_variant':>13} {'miss':>5} {'landing':>8}"
    )
    lines = [header, "-" * len(header)]
    for axis in AXES:
        counts = tallies[axis]
        total = sum(counts.values())
        landed = total - counts["miss"]
        rate = f"{landed / total:.0%}" if total else "n/a"
        label = f"{AXIS_LABELS[axis]} ({axis})"
        lines.append(
            f"{label:<20} {total:>4} {counts['exact']:>6} {counts['substring']:>10} "
            f"{counts['near_variant']:>13} {counts['miss']:>5} {rate:>8}"
        )
    return "\n".join(lines)


async def _fetch_photo_docs(settings: Settings, limit: int | None) -> list[MongoDoc]:
    """Direct Mongo read of `tongue_photos` (image + photo_id only --
    descriptions are re-derived, never trusted from the old run). Raises
    MongoUnavailableError rather than letting a raw connection traceback
    stand in for an honest report."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import PyMongoError

    client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
    except PyMongoError as exc:
        client.close()
        raise MongoUnavailableError(
            "Could not reach MongoDB at the configured MONGODB_URI "
            f"(db={settings.mongodb_db_name}): {type(exc).__name__}: {exc}"
        ) from exc

    try:
        cursor = client[settings.mongodb_db_name]["tongue_photos"].find(
            {}, {"image": 1, "photo_id": 1}
        )
        if limit is not None:
            cursor = cursor.limit(limit)
        return [doc async for doc in cursor]
    finally:
        client.close()


async def main(limit: int | None) -> None:
    settings = get_settings()

    try:
        photo_docs = await _fetch_photo_docs(settings, limit)
    except MongoUnavailableError as exc:
        print(f"Acceptance check could not run: {exc}")
        print(
            "No landing numbers were produced -- honestly reporting rather than fabricating them."
        )
        return

    if not photo_docs:
        print(
            f"No stored Tongue Photos found in the `tongue_photos` collection "
            f"(db={settings.mongodb_db_name}) -- nothing to re-describe."
        )
        return

    node_names = load_graph_node_names(Path(settings.rag_storage_dir))
    describer = VisionDescriber(settings)
    tallies = await redescribe_and_report(photo_docs, describer.describe, node_names)

    print(
        f"Re-described {len(photo_docs)} stored Tongue Photo(s) against "
        f"{len(node_names)} tongue-100 graph node names:\n"
    )
    print(format_report(tallies))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None, help="Re-describe at most N stored photos"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(args.limit))
