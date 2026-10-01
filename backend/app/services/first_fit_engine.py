"""1D First-Fit stall placement along a street segment; stalls cannot cross pillars."""
from __future__ import annotations
from dataclasses import asdict, dataclass

NO_FIT_REASON = "无连续空档可放下且不跨越挡柱"
LOCK_CONFLICT_REASON = "锁区冲突：上次已落摊锁定，新摊不得侵入"

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

@dataclass
class AllocResult:
    placements: list[Placement]
    rejected: list[Rejected]
    free_spans: list[tuple[float, float]]

def free_spans_from_pillars(width_m: float, pillars: list[dict]) -> list[tuple[float, float]]:
    """pillars: position_m, thickness_m — treated as blocked intervals."""
    blocked = []
    for p in pillars:
        half = p.get("thickness_m", 0.4) / 2.0
        lo = max(0.0, p["position_m"] - half)
        hi = min(width_m, p["position_m"] + half)
        if hi > lo:
            blocked.append((lo, hi))
    blocked.sort()
    merged = []
    for lo, hi in blocked:
        if not merged or lo > merged[-1][1]:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    spans = []
    cursor = 0.0
    for lo, hi in merged:
        if lo > cursor:
            spans.append((cursor, lo))
        cursor = hi
    if cursor < width_m:
        spans.append((cursor, width_m))
    return [(round(a, 3), round(b, 3)) for a, b in spans if b - a > 1e-6]

def _subtract_blocks(spans: list[tuple[float, float]], blocks: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Remove blocked intervals (locked stalls) from free spans."""
    blocks = sorted((lo, hi) for lo, hi in blocks if hi > lo)
    out: list[tuple[float, float]] = []
    for a, b in spans:
        cur = a
        for lo, hi in blocks:
            if hi <= cur or lo >= b:
                continue
            if lo > cur:
                out.append((cur, lo))
            cur = max(cur, hi)
        if b - cur > 1e-6:
            out.append((cur, b))
    return [(round(a, 3), round(b, 3)) for a, b in out]

def _consume(spans: list[list[float]], start: float, end: float) -> None:
    """Remove [start, end] from spans (may split a span)."""
    for i, span in enumerate(spans):
        if span[0] - 1e-9 <= start and end <= span[1] + 1e-9:
            a, b = span
            spans[i:i + 1] = [s for s in ([a, start], [end, b]) if s[1] - s[0] > 1e-6]
            return

def allocate_first_fit(width_m: float, vendors: list[dict], pillars: list[dict],
                       locked: list[dict] | None = None) -> AllocResult:
    """vendors sorted by priority ascending then id; each needs stall_width_m contiguous in one free span (no pillar cross).

    locked: placements carried over verbatim from the last successful run (start/end frozen).
    Only vendors not in the locked set are placed this round, left-filled into the spans
    that remain after subtracting locked zones; new stalls never invade locked zones.
    A vendor that fails only because of locked zones is rejected with LOCK_CONFLICT_REASON;
    one that would not fit even without locks gets NO_FIT_REASON.
    """
    spans = free_spans_from_pillars(width_m, pillars)
    locked = locked or []
    locked_ids = {l["vendor_id"] for l in locked}
    lock_blocks = [(float(l["start_m"]), float(l["end_m"])) for l in locked]
    # mutable remaining capacity per span, with locked zones subtracted
    remain = [[a, b] for a, b in _subtract_blocks(spans, lock_blocks)]
    # hypothetical capacity if locks did not exist — used only to classify rejections
    remain_unlocked = [[a, b] for a, b in spans]
    placements: list[Placement] = [
        Placement(l["vendor_id"], l["vendor_name"],
                  round(float(l["start_m"]), 3), round(float(l["end_m"]), 3),
                  round(float(l.get("width_m", float(l["end_m"]) - float(l["start_m"]))), 3),
                  True)
        for l in locked
    ]
    rejected: list[Rejected] = []
    ordered = sorted((v for v in vendors if v["id"] not in locked_ids),
                     key=lambda v: (v.get("priority", 1), v["id"]))
    for v in ordered:
        need = float(v["stall_width_m"])
        placed = False
        for span in remain:
            avail = span[1] - span[0]
            if avail + 1e-9 >= need:
                start = span[0]
                end = start + need
                placements.append(Placement(v["id"], v["name"], round(start, 3), round(end, 3), need))
                span[0] = end
                _consume(remain_unlocked, start, end)
                placed = True
                break
        if not placed:
            fits_without_locks = any(b - a + 1e-9 >= need for a, b in remain_unlocked)
            reason = LOCK_CONFLICT_REASON if fits_without_locks else NO_FIT_REASON
            rejected.append(Rejected(v["id"], v["name"], need, reason))
    if locked:
        placements.sort(key=lambda p: (p.start_m, p.vendor_id))
    free = [(round(a, 3), round(b, 3)) for a, b in remain if b - a > 1e-6]
    return AllocResult(placements, rejected, free)

def result_to_dict(r: AllocResult) -> dict:
    return {
        "placements": [asdict(p) for p in r.placements],
        "rejected": [asdict(x) for x in r.rejected],
        "free_spans": [{"start_m": a, "end_m": b} for a, b in r.free_spans],
    }
