import io
import json
from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient
from PIL import Image

from app.config import Settings
from app.models.schemas import TongueDescription
from scripts.redescribe_photos import (
    AXES,
    MongoUnavailableError,
    _fetch_photo_docs,
    format_report,
    load_graph_node_names,
    match_kind,
    redescribe_and_report,
)


def _settings(**overrides) -> Settings:
    return Settings(line_channel_secret="test", line_channel_access_token="test", **overrides)


# ---------------------------------------------------------------------------
# match_kind -- exact / substring / near-variant / miss (issue #36's rule)
# ---------------------------------------------------------------------------


def test_match_kind_exact_when_value_equals_a_node_name():
    assert match_kind("แดง", frozenset({"แดง", "ฝ้าขาว"})) == "exact"


def test_match_kind_exact_is_whitespace_insensitive():
    # "แดง และ ชื้น" (the book's own row spacing) should still count exact
    # against a node name that differs only in whitespace.
    assert match_kind("แดง  และ ชื้น", frozenset({"แดงและชื้น"})) == "exact"


def test_match_kind_substring_when_value_contained_in_a_node_name():
    assert match_kind("แดง", frozenset({"ลิ้นสีแดงเข้ม"})) == "substring"


def test_match_kind_substring_when_node_name_contained_in_value():
    assert match_kind("ลิ้นสีแดงเข้มมาก", frozenset({"แดงเข้ม"})) == "substring"


def test_match_kind_near_variant_for_a_paraphrase():
    # Same characteristic, one synonym swapped near the end -- close enough
    # (ratio ~0.91) to count as a near-variant, but not a substring either
    # way (issue #36's "trivial composition variant" category).
    assert match_kind("ฝ้าขาวหนาเหนียวและเลี่ยน", frozenset({"ฝ้าขาวหนาเหนียวและลื่น"})) == "near_variant"


def test_match_kind_miss_when_nothing_is_close():
    assert match_kind("สีเขียวสด", frozenset({"ลิ้นผอมเล็ก", "ฝ้าเหลือง"})) == "miss"


def test_match_kind_miss_for_empty_value():
    assert match_kind("", frozenset({"แดง"})) == "miss"


def test_match_kind_miss_against_empty_node_set():
    assert match_kind("แดง", frozenset()) == "miss"


# ---------------------------------------------------------------------------
# load_graph_node_names
# ---------------------------------------------------------------------------


def test_load_graph_node_names_collects_only_the_given_book(tmp_path: Path):
    store = {
        "tongue-100-001": {"entity_names": ["แดง", "ฝ้าขาว"]},
        "tongue-100-002": {"entity_names": ["ฝ้าขาว", "ลิ้นยาว"]},
        "four-elements-01": {"entity_names": ["ธาตุไฟ"]},
    }
    kv_path = tmp_path / "kv_store_full_entities.json"
    kv_path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")

    names = load_graph_node_names(tmp_path, book_id="tongue-100")

    assert names == frozenset({"แดง", "ฝ้าขาว", "ลิ้นยาว"})


# ---------------------------------------------------------------------------
# redescribe_and_report -- per-axis tallying over a batch of photo docs
# ---------------------------------------------------------------------------


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 60, 60)).save(buffer, format="JPEG")
    return buffer.getvalue()


async def test_redescribe_and_report_tallies_each_axis_independently():
    photo_docs = [{"photo_id": "P1", "image": _jpeg_bytes()}]
    node_names = frozenset({"แดง", "ฝ้าขาว", "ปกติ", "ไม่มีจุด"})

    async def fake_describe(image: Image.Image) -> TongueDescription:
        return TongueDescription(
            color="แดง",  # exact
            coating="ฝ้าขาวหนามาก",  # substring (node contained in value)
            size="เขียวสดใสทั้งลิ้น",  # miss -- unrelated to every node name
            shape="ปกติ",  # exact
            spots="ไม่มีจุด",  # exact
            quality="clear",
        )

    tallies = await redescribe_and_report(photo_docs, fake_describe, node_names)

    assert tallies["color"]["exact"] == 1
    assert tallies["coating"]["substring"] == 1
    assert tallies["size"]["miss"] == 1
    assert tallies["shape"]["exact"] == 1
    assert tallies["spots"]["exact"] == 1
    assert set(tallies.keys()) == set(AXES)


async def test_redescribe_and_report_skips_a_photo_whose_describe_call_fails():
    photo_docs = [
        {"photo_id": "BAD", "image": _jpeg_bytes()},
        {"photo_id": "OK", "image": _jpeg_bytes()},
    ]
    node_names = frozenset({"แดง"})
    calls = []

    async def flaky_describe(image: Image.Image) -> TongueDescription:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("describer outage")
        return TongueDescription(
            color="แดง", coating="x", size="x", shape="x", spots="x", quality="clear"
        )

    tallies = await redescribe_and_report(photo_docs, flaky_describe, node_names)

    # only the second photo's axis values were tallied
    assert sum(tallies["color"].values()) == 1
    assert tallies["color"]["exact"] == 1


async def test_redescribe_and_report_on_empty_input_yields_empty_tallies():
    tallies = await redescribe_and_report([], lambda image: None, frozenset({"แดง"}))

    assert all(sum(counter.values()) == 0 for counter in tallies.values())


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


async def test_format_report_includes_landing_rate_per_axis():
    node_names = frozenset({"แดง"})

    async def fake_describe(image: Image.Image) -> TongueDescription:
        return TongueDescription(
            color="แดง", coating="ไม่เกี่ยวข้องเลย", size="x", shape="x", spots="x", quality="clear"
        )

    tallies = await redescribe_and_report(
        [{"photo_id": "P1", "image": _jpeg_bytes()}], fake_describe, node_names
    )
    report = format_report(tallies)

    assert "สี" in report
    assert "100%" in report  # color landed exactly
    assert "0%" in report  # coating missed entirely


def test_format_report_handles_zero_photos_without_dividing_by_zero():
    empty_tallies = {axis: __import__("collections").Counter() for axis in AXES}

    report = format_report(empty_tallies)

    assert "n/a" in report


def test_mongo_unavailable_error_is_a_plain_exception():
    with pytest.raises(MongoUnavailableError):
        raise MongoUnavailableError("no mongo here")


# ---------------------------------------------------------------------------
# _fetch_photo_docs -- Mongo I/O, exercised against mongomock (no real DB)
# ---------------------------------------------------------------------------


async def test_fetch_photo_docs_reads_stored_photos_from_mongo(monkeypatch):
    import motor.motor_asyncio as motor_asyncio

    fake_client = AsyncMongoMockClient()
    monkeypatch.setattr(motor_asyncio, "AsyncIOMotorClient", lambda *a, **k: fake_client)
    settings = _settings(mongodb_db_name="test_db")

    await fake_client["test_db"]["tongue_photos"].insert_one(
        {"photo_id": "P1", "image": _jpeg_bytes(), "passed_gate": True}
    )
    await fake_client["test_db"]["tongue_photos"].insert_one(
        {"photo_id": "P2", "image": _jpeg_bytes(), "passed_gate": True}
    )

    docs = await _fetch_photo_docs(settings, limit=None)

    assert {doc["photo_id"] for doc in docs} == {"P1", "P2"}


async def test_fetch_photo_docs_filters_to_gate_passed_photos_only(monkeypatch):
    """Only gate-passed photos should be fetched (ADR 0007: production
    dispatcher never sends below-gate crops to describer, so acceptance script
    must not re-describe them either, or the landing rate will be skewed)."""
    import motor.motor_asyncio as motor_asyncio

    fake_client = AsyncMongoMockClient()
    monkeypatch.setattr(motor_asyncio, "AsyncIOMotorClient", lambda *a, **k: fake_client)
    settings = _settings(mongodb_db_name="test_db_gate")

    # Insert both gate-passed and below-gate photos
    await fake_client["test_db_gate"]["tongue_photos"].insert_one(
        {"photo_id": "PASSED", "image": _jpeg_bytes(), "passed_gate": True}
    )
    await fake_client["test_db_gate"]["tongue_photos"].insert_one(
        {"photo_id": "FAILED", "image": _jpeg_bytes(), "passed_gate": False}
    )

    docs = await _fetch_photo_docs(settings, limit=None)

    # Only the gate-passed photo should be returned
    assert len(docs) == 1
    assert docs[0]["photo_id"] == "PASSED"


async def test_fetch_photo_docs_respects_the_limit(monkeypatch):
    import motor.motor_asyncio as motor_asyncio

    fake_client = AsyncMongoMockClient()
    monkeypatch.setattr(motor_asyncio, "AsyncIOMotorClient", lambda *a, **k: fake_client)
    settings = _settings(mongodb_db_name="test_db_limit")

    for photo_id in ("P1", "P2", "P3"):
        await fake_client["test_db_limit"]["tongue_photos"].insert_one(
            {"photo_id": photo_id, "image": _jpeg_bytes(), "passed_gate": True}
        )

    docs = await _fetch_photo_docs(settings, limit=2)

    assert len(docs) == 2


async def test_fetch_photo_docs_on_empty_collection_returns_empty_list(monkeypatch):
    import motor.motor_asyncio as motor_asyncio

    fake_client = AsyncMongoMockClient()
    monkeypatch.setattr(motor_asyncio, "AsyncIOMotorClient", lambda *a, **k: fake_client)
    settings = _settings(mongodb_db_name="test_db_empty")

    docs = await _fetch_photo_docs(settings, limit=None)

    assert docs == []


async def test_fetch_photo_docs_raises_mongo_unavailable_when_ping_fails(monkeypatch):
    import motor.motor_asyncio as motor_asyncio
    from pymongo.errors import PyMongoError

    class _DeadAdmin:
        async def command(self, *args, **kwargs):
            raise PyMongoError("connection refused")

    class _DeadClient:
        admin = _DeadAdmin()

        def close(self) -> None:
            pass

    monkeypatch.setattr(motor_asyncio, "AsyncIOMotorClient", lambda *a, **k: _DeadClient())
    settings = _settings()

    with pytest.raises(MongoUnavailableError):
        await _fetch_photo_docs(settings, limit=None)
