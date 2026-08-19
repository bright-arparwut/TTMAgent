from scripts.build_client_record_demo import build_states


def test_four_consultations_in_order():
    states = build_states()
    assert [state["index"] for state in states] == [1, 2, 3, 4]
    assert [state["date"] for state in states] == [
        "2026-05-02",
        "2026-05-20",
        "2026-06-15",
        "2026-07-08",
    ]


def test_first_consultation_fills_an_empty_folder():
    first = build_states()[0]
    assert "ยังไม่มีข้อมูล" in first["rendered_before"]
    assert "ข้อมูลที่ยังขาด" in first["rendered_before"]
    assert "อายุ 28 ปี" in first["rendered_after"]
    assert "ธาตุเจ้าเรือน: ไฟ" in first["rendered_after"]
    assert first["changed"]["added"] == ["h1", "o1"]


def test_tongue_photo_consultation_is_the_only_one_with_an_assessment():
    states = build_states()
    with_tongue = [s for s in states if s["entry"] and s["entry"]["tongue"]]
    assert [s["index"] for s in with_tongue] == [2]
    assert with_tongue[0]["entry"]["tongue"]["description"]["body_color"] == "แดง"
    assert with_tongue[0]["changed"] == {
        "added": ["a1"],
        "updated": ["o1"],
        "removed": [],
    }


def test_discarded_consultation_writes_nothing():
    third = build_states()[2]
    assert third["gate"]["has_health_content"] is False
    assert third["entry"] is None
    assert third["ops"] == []
    assert third["profile_before"] == third["profile_after"]
    assert third["changed"] == {"added": [], "updated": [], "removed": []}


def test_resolved_complaint_is_removed_but_its_id_is_never_reused():
    final = build_states()[-1]
    assert final["profile_after"]["ongoing_complaints"] == []
    assert final["profile_after"]["id_counters"]["ongoing_complaints"] == 1
    assert final["changed"]["removed"] == ["o1"]
    assert final["changed"]["updated"] == ["h1"]
    assert sorted(final["changed"]["added"]) == ["c1", "m1"]
