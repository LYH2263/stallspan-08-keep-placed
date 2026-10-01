from dataclasses import asdict

from app.services.first_fit_engine import (
    LOCK_CONFLICT_REASON,
    NO_FIT_REASON,
    allocate_first_fit,
)

PILLARS = [{"position_m": 10.0, "thickness_m": 0.5}, {"position_m": 20.0, "thickness_m": 0.5}]


def _coords(r):
    return {p.vendor_id: (p.start_m, p.end_m) for p in r.placements}


def test_locked_carried_verbatim_and_left_fill():
    locked = [{"vendor_id": 1, "vendor_name": "A", "start_m": 0.0, "end_m": 4.0, "width_m": 4.0}]
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 3.0, "priority": 1},
    ]
    r = allocate_first_fit(30.0, vendors, PILLARS, locked=locked)
    pa = next(p for p in r.placements if p.vendor_id == 1)
    assert (pa.start_m, pa.end_m) == (0.0, 4.0)
    assert pa.locked is True
    pb = next(p for p in r.placements if p.vendor_id == 2)
    # 其余摊从锁区右缘继续从左填
    assert (pb.start_m, pb.end_m) == (4.0, 7.0)
    assert pb.locked is False
    # 锁区不出现在剩余空档
    assert all(b <= 0.0 or a >= 4.0 for a, b in r.free_spans)


def test_new_stall_never_invades_locked_zone():
    locked = [{"vendor_id": 1, "vendor_name": "A", "start_m": 5.0, "end_m": 9.0, "width_m": 4.0}]
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 6.0, "priority": 1},
    ]
    r = allocate_first_fit(30.0, vendors, [], locked=locked)
    pb = next(p for p in r.placements if p.vendor_id == 2)
    # [0,5] 放不下 6m，不得侵入 [5,9] 锁区，只能落到 [9,15]
    assert pb.start_m >= 9.0
    for p in r.placements:
        if p.vendor_id == 2:
            assert p.end_m <= 5.0 or p.start_m >= 9.0


def test_lock_conflict_reason_not_rewritten_as_no_fit():
    locked = [{"vendor_id": 1, "vendor_name": "A", "start_m": 0.0, "end_m": 28.0, "width_m": 28.0}]
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 28.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 5.0, "priority": 2},   # 无锁能放 → 锁区冲突
        {"id": 3, "name": "C", "stall_width_m": 35.0, "priority": 3},  # 无锁也放不下 → 空档不够
    ]
    r = allocate_first_fit(30.0, vendors, [], locked=locked)
    reasons = {x.vendor_id: x.reason for x in r.rejected}
    assert reasons[2] == LOCK_CONFLICT_REASON
    assert "锁区冲突" in reasons[2]
    assert "空档" not in reasons[2]
    assert reasons[3] == NO_FIT_REASON
    # 整次不得静默挪锁摊起止
    pa = next(p for p in r.placements if p.vendor_id == 1)
    assert (pa.start_m, pa.end_m) == (0.0, 28.0)


def test_low_priority_cannot_displace_locked_stall():
    # 低优先宽摊试图顶掉高优先已锁摊：必须失败并进锁区冲突
    locked = [{"vendor_id": 1, "vendor_name": "高优先老摊", "start_m": 0.0, "end_m": 9.5, "width_m": 9.5}]
    vendors = [
        {"id": 1, "name": "高优先老摊", "stall_width_m": 9.5, "priority": 1},
        {"id": 2, "name": "低优先新摊", "stall_width_m": 8.0, "priority": 9},
    ]
    r = allocate_first_fit(10.0, vendors, [], locked=locked)
    assert len(r.rejected) == 1
    assert r.rejected[0].vendor_id == 2
    assert r.rejected[0].reason == LOCK_CONFLICT_REASON
    pa = next(p for p in r.placements if p.vendor_id == 1)
    assert (pa.start_m, pa.end_m) == (0.0, 9.5)


def test_consecutive_keep_placed_rounds_are_stable():
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 3.0, "priority": 1},
        {"id": 3, "name": "C", "stall_width_m": 6.0, "priority": 1},
        {"id": 4, "name": "D", "stall_width_m": 12.0, "priority": 9},
    ]
    r1 = allocate_first_fit(30.0, vendors, PILLARS)
    r2 = allocate_first_fit(30.0, vendors, PILLARS, locked=[asdict(p) for p in r1.placements])
    assert _coords(r2) == _coords(r1)  # 第一次已落起止不变
    r3 = allocate_first_fit(30.0, vendors, PILLARS, locked=[asdict(p) for p in r2.placements])
    assert _coords(r3) == _coords(r2)  # 连续两次保留不漂移


def test_empty_locked_matches_full_recompute():
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 12.0, "priority": 1},
    ]
    fresh = allocate_first_fit(30.0, vendors, PILLARS)
    empty = allocate_first_fit(30.0, vendors, PILLARS, locked=[])
    assert _coords(fresh) == _coords(empty)
    assert [(x.vendor_id, x.reason) for x in fresh.rejected] == \
           [(x.vendor_id, x.reason) for x in empty.rejected]
    assert fresh.free_spans == empty.free_spans
    assert all(not p.locked for p in empty.placements)
