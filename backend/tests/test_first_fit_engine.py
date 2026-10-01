from app.services.first_fit_engine import (
    LOCK_CONFLICT_REASON,
    NO_SPACE_REASON,
    allocate_first_fit,
    free_spans_from_pillars,
)


def test_free_spans_with_pillars():
    spans = free_spans_from_pillars(30.0, [{"position_m": 10.0, "thickness_m": 0.5}, {"position_m": 20.0, "thickness_m": 0.5}])
    assert len(spans) == 3
    assert spans[0][0] == 0.0


def test_first_fit_no_cross_pillar():
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 12.0, "priority": 1},
    ]
    pillars = [{"position_m": 10.0, "thickness_m": 0.5}]
    r = allocate_first_fit(30.0, vendors, pillars)
    assert any(p.vendor_name == "A" for p in r.placements)
    # 12m may fit in a free span after first placement depending on remainders
    assert len(r.placements) + len(r.rejected) == 2


def test_reject_oversized():
    vendors = [{"id": 1, "name": "Huge", "stall_width_m": 25.0, "priority": 1}]
    pillars = [{"position_m": 10.0, "thickness_m": 0.5}, {"position_m": 20.0, "thickness_m": 0.5}]
    r = allocate_first_fit(30.0, vendors, pillars)
    assert len(r.rejected) == 1
    assert r.rejected[0].vendor_name == "Huge"


def _baseline_layout():
    """街段 20 无挡柱：P@0-8、B@8-14、Q@14-20 全部落满。"""
    return [
        {"vendor_id": 1, "vendor_name": "P", "start_m": 0.0, "end_m": 8.0},
        {"vendor_id": 2, "vendor_name": "B", "start_m": 8.0, "end_m": 14.0},
        {"vendor_id": 3, "vendor_name": "Q", "start_m": 14.0, "end_m": 20.0},
    ]


def test_preserve_locks_coordinates_and_fills_remaining_from_left():
    # 本轮只有中间的 B 保留；新摊 C 宽 7 只能落锁区左侧 0-8 空档（从左填）。
    locked = [_baseline_layout()[1]]
    vendors = [
        {"id": 2, "name": "B", "stall_width_m": 6.0, "priority": 2},
        {"id": 4, "name": "C", "stall_width_m": 7.0, "priority": 1},
    ]
    r = allocate_first_fit(20.0, vendors, [], locked=locked)
    b = next(p for p in r.placements if p.vendor_id == 2)
    c = next(p for p in r.placements if p.vendor_id == 4)
    assert (b.start_m, b.end_m, b.locked) == (8.0, 14.0, True)
    assert (c.start_m, c.end_m, c.locked) == (0.0, 7.0, False)
    # 剩余空档：0-7 用掉后 7-8，以及 14-20。
    assert r.free_spans == [(7.0, 8.0), (14.0, 20.0)]
    assert r.rejected == []


def test_low_priority_cannot_displace_high_priority_locked_stall():
    # 高优先 H(1) 已锁 0-8；低优先 L(9) 宽 8 只剩 8-12(4m)，不得顶挪锁摊。
    locked = [{"vendor_id": 1, "vendor_name": "H", "start_m": 0.0, "end_m": 8.0}]
    vendors = [
        {"id": 1, "name": "H", "stall_width_m": 8.0, "priority": 1},
        {"id": 9, "name": "L", "stall_width_m": 8.0, "priority": 9},
    ]
    r = allocate_first_fit(12.0, vendors, [], locked=locked)
    assert len(r.placements) == 1
    h = r.placements[0]
    assert (h.vendor_id, h.start_m, h.end_m, h.locked) == (1, 0.0, 8.0, True)
    assert len(r.rejected) == 1
    rej = r.rejected[0]
    assert rej.vendor_id == 9
    # 必须是锁区冲突，不得改写成空档不够。
    assert rej.lock_conflict is True
    assert rej.reason == LOCK_CONFLICT_REASON


def test_lock_conflict_distinct_from_genuinely_no_space():
    # 比整段还宽的摊：即使没有锁区也放不下，必须记空档不够而非锁区冲突。
    locked = [{"vendor_id": 1, "vendor_name": "H", "start_m": 0.0, "end_m": 4.0}]
    vendors = [
        {"id": 1, "name": "H", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "Huge", "stall_width_m": 12.0, "priority": 1},
    ]
    r = allocate_first_fit(10.0, vendors, [], locked=locked)
    assert len(r.rejected) == 1
    rej = r.rejected[0]
    assert rej.vendor_id == 2
    assert rej.lock_conflict is False
    assert rej.reason == NO_SPACE_REASON


def test_two_consecutive_preserve_runs_do_not_drift():
    locked = [_baseline_layout()[1]]  # B 锁 8-14
    vendors = [
        {"id": 2, "name": "B", "stall_width_m": 6.0, "priority": 2},
        {"id": 4, "name": "C", "stall_width_m": 10.0, "priority": 1},
    ]
    first = allocate_first_fit(20.0, vendors, [], locked=locked)
    # 第一次：C 宽 10，两侧空档 8 与 6 均不够 → 锁区冲突；B 起止不动。
    assert len(first.rejected) == 1 and first.rejected[0].lock_conflict is True
    b1 = next(p for p in first.placements if p.vendor_id == 2)
    assert (b1.start_m, b1.end_m) == (8.0, 14.0)

    # 第二次保留以上一次结果为基线：B 仍锁 8-14，结论一致，锁摊色块坐标不漂移。
    second_locked = [{"vendor_id": p.vendor_id, "vendor_name": p.vendor_name,
                      "start_m": p.start_m, "end_m": p.end_m} for p in first.placements]
    second = allocate_first_fit(20.0, vendors, [], locked=second_locked)
    b2 = next(p for p in second.placements if p.vendor_id == 2)
    assert (b2.start_m, b2.end_m) == (8.0, 14.0)
    assert len(second.rejected) == 1 and second.rejected[0].lock_conflict is True
    assert second.rejected[0].vendor_id == 4


def test_narrowing_unplaced_stall_keeps_locked_coords_only_free_changes():
    locked = [_baseline_layout()[1]]  # B 锁 8-14
    # 宽摊 C=10 首轮放不下（锁区冲突）。
    wide = [
        {"id": 2, "name": "B", "stall_width_m": 6.0, "priority": 2},
        {"id": 4, "name": "C", "stall_width_m": 10.0, "priority": 1},
    ]
    first = allocate_first_fit(20.0, wide, [], locked=locked)
    assert [x.vendor_id for x in first.rejected] == [4]

    # C 改窄为 7 后勾保留重跑：已锁 B 坐标保持，C 落入左侧空档，放不下名单不再点名任何已锁摊。
    narrow = [dict(v) for v in wide]
    narrow[1]["stall_width_m"] = 7.0
    second = allocate_first_fit(20.0, narrow, [], locked=locked)
    b = next(p for p in second.placements if p.vendor_id == 2)
    c = next(p for p in second.placements if p.vendor_id == 4)
    assert (b.start_m, b.end_m, b.locked) == (8.0, 14.0, True)
    assert (c.start_m, c.end_m, c.locked) == (0.0, 7.0, False)
    assert second.rejected == []
    assert second.free_spans == [(7.0, 8.0), (14.0, 20.0)]


def test_non_preserve_recomputes_whole_segment_greenfield():
    # locked=None 与绿仓行为一致：所有摊重新从左填，没有任何 locked 标志。
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 4.0, "priority": 1},
    ]
    r = allocate_first_fit(12.0, vendors, [], locked=None)
    assert [(p.vendor_id, p.start_m, p.end_m, p.locked) for p in r.placements] == [
        (1, 0.0, 4.0, False),
        (2, 4.0, 8.0, False),
    ]
