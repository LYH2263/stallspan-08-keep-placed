import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import AllocationRun, Pillar, Segment, Vendor
from app.services.first_fit_engine import allocate_first_fit, result_to_dict
router = APIRouter(prefix="/allocate", tags=["allocate"])

def _latest_run(segment_id: int, db: Session) -> AllocationRun | None:
    return db.scalars(select(AllocationRun).where(AllocationRun.segment_id == segment_id)
                      .order_by(AllocationRun.id.desc())).first()

def _compute(seg: Segment, vendors: list[dict], pillars: list[dict],
             preserve: bool, baseline: AllocationRun | None) -> dict:
    locked = []
    baseline_id = None
    if preserve:
        # 基线存在性由调用方保证；锁区取上一次成功运行的已落摊起止。
        baseline_data = json.loads(baseline.result_json)
        locked = [dict(p) for p in baseline_data.get("placements", [])]
        baseline_id = baseline.id
    result = result_to_dict(allocate_first_fit(seg.width_m, vendors, pillars, locked=locked))
    result["segment"] = {"id": seg.id, "name": seg.name, "width_m": seg.width_m}
    result["pillars"] = pillars
    # 口径标记随结果快照持久化：保留/非保留结果各自独立，禁止混用缓存。
    result["preserve"] = preserve
    result["baseline_run_id"] = baseline_id
    return result

@router.post("/run")
def run_allocate(segment_id: int = 1, preserve: bool = False, db: Session = Depends(get_db)):
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "街段不存在")
    baseline = _latest_run(segment_id, db)
    if preserve and baseline is None:
        # 尚无成功运行可保留：整次拒绝，不产生半成功运行，图与放不下维持原状。
        raise HTTPException(409, "尚无成功运行可保留：请先取消保留完成一次整段分配")
    pillars = [{"position_m": p.position_m, "thickness_m": p.thickness_m}
               for p in db.scalars(select(Pillar).where(Pillar.segment_id == segment_id)).all()]
    vendors = [{"id": v.id, "name": v.name, "stall_width_m": v.stall_width_m, "priority": v.priority}
               for v in db.scalars(select(Vendor).where(Vendor.market_day_id == seg.market_day_id)).all()]
    result = _compute(seg, vendors, pillars, preserve, baseline)
    run = AllocationRun(segment_id=segment_id, created_at=datetime.utcnow(),
                        result_json=json.dumps(result, ensure_ascii=False))
    db.add(run); db.commit(); db.refresh(run)
    return {"id": run.id, **result}

@router.get("/latest")
def latest(segment_id: int = 1, db: Session = Depends(get_db)):
    run = _latest_run(segment_id, db)
    if not run:
        # 与绿仓一致：无任何运行时按非保留整段重算并落一条成功运行。
        return run_allocate(segment_id=segment_id, preserve=False, db=db)
    data = json.loads(run.result_json)
    return {"id": run.id, **data}

@router.get("/runs")
def list_runs(segment_id: int = 1, db: Session = Depends(get_db)):
    runs = db.scalars(select(AllocationRun).where(AllocationRun.segment_id == segment_id)
                      .order_by(AllocationRun.id.desc())).all()
    out = []
    for r in runs:
        data = json.loads(r.result_json)
        out.append({
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "preserve": bool(data.get("preserve", False)),
            "baseline_run_id": data.get("baseline_run_id"),
            "placed_count": len(data.get("placements", [])),
            "locked_count": sum(1 for p in data.get("placements", []) if p.get("locked")),
            "rejected_count": len(data.get("rejected", [])),
            "lock_conflict_count": sum(1 for x in data.get("rejected", []) if x.get("lock_conflict")),
        })
    return out

@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(AllocationRun, run_id)
    if not run:
        raise HTTPException(404, "运行不存在")
    data = json.loads(run.result_json)
    return {"id": run.id, "created_at": run.created_at.isoformat(), **data}
