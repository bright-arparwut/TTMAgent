"""The #36 landing check must score honestly: the tiers are the evidence a
hardening ruling reads, so each one is pinned here with synthetic entities.
"""

from spike.landing import AXES, NORMAL_TONGUE_PROBE, build_report, score_value

ENTITIES = [
    {"name": "ฝ้าขาวบาง", "type": "concept", "file_path": "006-a.md", "degree": 3},
    {"name": "ลิ้นแดงอ่อน", "type": "concept", "file_path": "007-b.md", "degree": 2},
    {"name": "สี", "type": "concept", "file_path": "008-c.md", "degree": 1},
]


def test_axes_are_the_decided_schema_keys():
    assert list(AXES) == ["color", "coating", "size", "shape", "spots"]
    assert AXES["spots"] == "จุดบนลิ้น"


def test_exact_match_ignores_whitespace_and_case():
    tier, hits, _ = score_value("ฝ้า ขาว บาง", ENTITIES)
    assert tier == "exact"
    assert hits[0]["name"] == "ฝ้าขาวบาง"


def test_node_name_inside_free_text_lands():
    tier, hits, _ = score_value("มีฝ้าขาวบางทั่วลิ้น", ENTITIES)
    assert tier == "node_in_value"
    assert hits[0]["name"] == "ฝ้าขาวบาง"


def test_value_inside_longer_node_name_lands():
    tier, hits, _ = score_value("แดงอ่อน", ENTITIES)
    assert tier == "value_in_node"
    assert hits[0]["name"] == "ลิ้นแดงอ่อน"


def test_short_node_names_do_not_containment_match():
    # "สี" (2 normalized chars) sits inside the value but is below the
    # containment floor -- it must not count as landed.
    tier, hits, _ = score_value("สีเหลืองเข้ม", ENTITIES)
    assert tier == "miss"
    assert hits == []


def test_spelling_drift_reports_near_not_landed():
    tier, hits, nearest = score_value("ฝ้าขาบาง", ENTITIES)  # dropped ว
    assert tier == "near"
    assert hits[0]["name"] == "ฝ้าขาวบาง"
    assert nearest[0]["similarity"] >= 0.82


def test_miss_still_reports_nearest_candidates():
    tier, hits, nearest = score_value("จุดแดงกระจายปลายลิ้น", ENTITIES)
    assert tier == "miss"
    assert hits == []
    assert len(nearest) == 3


def test_report_aggregates_per_axis_and_skips_empty_values():
    descriptions = [
        {"color": "แดงอ่อน", "coating": "ฝ้าขาวบาง", "spots": "  ", "quality": "clear"}
    ]
    report = build_report(descriptions, ENTITIES)
    assert set(report["axes"]) == {"color", "coating"}
    assert report["axes"]["coating"]["landed"] == 1
    assert report["axes"]["coating"]["landing_rate"] == 1.0
    assert report["axes"]["color"]["landed"] == 1  # value_in_node counts as landed
    assert all(row["axis"] != "spots" for row in report["rows"])


def test_probe_quotes_only_part_one_attested_axes():
    # Part 1 transcribes no จุดบนลิ้น vocabulary (ticket #32) -- the probe
    # must not invent one.
    assert "spots" not in NORMAL_TONGUE_PROBE
    assert set(NORMAL_TONGUE_PROBE) <= set(AXES)
