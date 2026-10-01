"""1D First-Fit stall placement along a street segment; stalls cannot cross pillars.

保留模式（preserve）下，上一次成功运行中已落摊的 [start_m, end_m] 作为锁区：
锁区起止在本轮锁定，本轮其余摊位只在剩余空档内从左填，不得侵入锁区；
因锁区阻挡而放不下的摊位记为“锁区冲突”，与“空档不够（跨挡柱/街段不足）”严格区分。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass

NO_SPACE_REASON = "无连续空档可放下且不跨越挡柱"
LOCK_CONFLICT_REASON = "锁区冲突：可容纳位置与保留锁定的已落摊重叠，不得顶挪锁摊起止"

@dataclass
class Placement:
    vendor_id: int
    vendor_name: str
    start_m: float
    end_m: float
    width_m: float
    locked: bool = False

@dataclass
class Rejected:
    vendor_id: int
    vendor_name: str
    width_m: float
    reason: str
    lock_conflict: bool = False

@dataclass
class AllocResult:
    placements: list[Placement]
    rejected: list[Rejected]
    free_spans: list[tuple[float, float]]

def _pillar_intervals(width_m: float, pillars: list[dict]) -> list[tuple[float, float]]:
    """挡柱（或任意阻断）在街段上的合并阻断区间。"""
    blocked = []
    for p in pillars:
        half = p.get("thickness_m", 0.4) / 2.0
        lo = max(0.0, p["position_m"] - half)
        hi = min(width_m, p["position_m"] + half)
        if hi > lo:
            blocked.append((lo, hi))
    return _merge_intervals(blocked)

def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted(intervals)
    merged: list[list[float]] = []
    for lo, hi in ordered:
        if not merged or lo > merged[-1][1]:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    return [(a, b) for a, b in merged]

def _free_spans(width_m: float, blocked: list[tuple[float, float]]) -> list[tuple[float, float]]:
    spans = []
    cursor = 0.0
    for lo, hi in _merge_intervals(blocked):
        if lo > cursor:
            spans.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < width_m:
        spans.append((cursor, width_m))
    return [(round(a, 3), round(b, 3)) for a, b in spans if b - a > 1e-6]

def free_spans_from_pillars(width_m: float, pillars: list[dict]) -> list[tuple[float, float]]:
    """pillars: position_m, thickness_m — treated as blocked intervals."""
    return _free_spans(width_m, _pillar_intervals(width_m, pillars))

def _fits_ignoring_locks(width_m: float, need: float,
                         pillar_blocked: list[tuple[float, float]],
                         new_occupied: list[tuple[float, float]]) -> bool:
    """假设没有锁区（挡柱与本轮已放置的新摊仍占用），该宽度是否放得下。"""
    return any(b - a + 1e-9 >= need
               for a, b in _free_spans(width_m, pillar_blocked + new_occupied))

def allocate_first_fit(width_m: float, vendors: list[dict], pillars: list[dict],
                       locked: list[dict] | None = None) -> AllocResult:
    """vendors sorted by priority ascending then id; each needs stall_width_m contiguous in one free span (no pillar cross).

    locked: 上一次成功运行中要保留的已落摊 [{vendor_id, vendor_name, start_m, end_m, ...}]。
    锁摊起止原样锁定并直接落位，本轮不再参与分配；其余摊位只在扣除挡柱与锁区后的空档内
    从左填，禁止侵入锁区。放不下时：若去掉锁区即可放下，记锁区冲突；否则记空档不够。
    """
    pillar_blocked = _pillar_intervals(width_m, pillars)
    locked = sorted(locked or [], key=lambda x: (float(x["start_m"]), x["vendor_id"]))

    lock_intervals: list[tuple[float, float]] = []
    locked_placements: list[Placement] = []
    locked_ids: set[int] = set()
    for L in locked:
        lo = max(0.0, min(width_m, float(L["start_m"])))
        hi = max(0.0, min(width_m, float(L["end_m"])))
        if hi - lo <= 1e-9:
            continue
        lock_intervals.append((lo, hi))
        locked_ids.add(L["vendor_id"])
        locked_placements.append(Placement(
            L["vendor_id"], L["vendor_name"], round(lo, 3), round(hi, 3),
            round(hi - lo, 3), True))

    # 扣除挡柱与锁区后的剩余空档；锁区在本轮不可被侵入。
    remain = [[a, b] for a, b in _free_spans(width_m, pillar_blocked + lock_intervals)]
    ordered = sorted((v for v in vendors if v["id"] not in locked_ids),
                     key=lambda v: (v.get("priority", 1), v["id"]))
    placements: list[Placement] = list(locked_placements)
    rejected: list[Rejected] = []
    new_occupied: list[tuple[float, float]] = []
    for v in ordered:
        need = float(v["stall_width_m"])
        placed = False
        for span in remain:
            avail = span[1] - span[0]
            if avail + 1e-9 >= need:
                start = span[0]
                end = start + need
                placements.append(Placement(v["id"], v["name"], round(start, 3), round(end, 3), need, False))
                new_occupied.append((start, end))
                span[0] = end
                placed = True
                break
        if not placed:
            # 无锁区（仅有挡柱与本轮已落新摊）能放下 → 是锁区顶摊冲突；不得改写为空档不够。
            is_lock_conflict = _fits_ignoring_locks(width_m, need, pillar_blocked, new_occupied)
            reason = LOCK_CONFLICT_REASON if is_lock_conflict else NO_SPACE_REASON
            rejected.append(Rejected(v["id"], v["name"], need, reason, is_lock_conflict))
    free = [(round(a, 3), round(b, 3)) for a, b in remain if b - a > 1e-6]
    return AllocResult(placements, rejected, free)

def result_to_dict(r: AllocResult) -> dict:
    return {
        "placements": [asdict(p) for p in r.placements],
        "rejected": [asdict(x) for x in r.rejected],
        "free_spans": [{"start_m": a, "end_m": b} for a, b in r.free_spans],
    }
