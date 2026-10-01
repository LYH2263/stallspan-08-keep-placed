import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import AllocationRun, Pillar, Segment, Vendor
from app.services.first_fit_engine import allocate_first_fit, result_to_dict
router = APIRouter(prefix="/allocate", tags=["allocate"])


def _latest_run(db: Session, segment_id: int) -> AllocationRun | None:
    return db.scalars(select(AllocationRun).where(AllocationRun.segment_id == segment_id)
                      .order_by(AllocationRun.id.desc())).first()


def _run_payload(run: AllocationRun) -> dict:
    data = json.loads(run.result_json)
    return {"id": run.id, "keep_placed": run.keep_placed,
            "created_at": run.created_at.isoformat() if run.created_at else None, **data}


@router.post("/run")
def run_allocate(segment_id: int = 1, keep_placed: bool = False, db: Session = Depends(get_db)):
    seg = db.get(Segment, segment_id)
    if not seg: raise HTTPException(404, "街段不存在")
    pillars = [{"position_m": p.position_m, "thickness_m": p.thickness_m}
               for p in db.scalars(select(Pillar).where(Pillar.segment_id == segment_id)).all()]
    vendors = [{"id": v.id, "name": v.name, "stall_width_m": v.stall_width_m, "priority": v.priority}
               for v in db.scalars(select(Vendor).where(Vendor.market_day_id == seg.market_day_id)).all()]
    locked: list[dict] = []
    if keep_placed:
        prev = _latest_run(db, segment_id)
        if not prev:
            # 尚无成功运行：拒绝且不落库，图与放不下保持不变
            raise HTTPException(409, "尚无成功运行，无法保留已落摊")
        prev_data = json.loads(prev.result_json)
        current_ids = {v["id"] for v in vendors}
        locked = [p for p in prev_data.get("placements", []) if p["vendor_id"] in current_ids]
    result = result_to_dict(allocate_first_fit(seg.width_m, vendors, pillars, locked=locked))
    result["segment"] = {"id": seg.id, "name": seg.name, "width_m": seg.width_m}
    result["pillars"] = pillars
    run = AllocationRun(segment_id=segment_id, created_at=datetime.utcnow(), keep_placed=keep_placed,
                        result_json=json.dumps(result, ensure_ascii=False))
    db.add(run); db.commit(); db.refresh(run)
    return _run_payload(run)


@router.get("/latest")
def latest(segment_id: int = 1, db: Session = Depends(get_db)):
    run = _latest_run(db, segment_id)
    if not run:
        return run_allocate(segment_id=segment_id, db=db)
    return _run_payload(run)


@router.get("/runs")
def list_runs(segment_id: int = 1, db: Session = Depends(get_db)):
    runs = db.scalars(select(AllocationRun).where(AllocationRun.segment_id == segment_id)
                      .order_by(AllocationRun.id.desc())).all()
    out = []
    for r in runs:
        data = json.loads(r.result_json)
        placements = data.get("placements", [])
        out.append({
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "keep_placed": r.keep_placed,
            "placed": len(placements),
            "locked": sum(1 for p in placements if p.get("locked")),
            "rejected": len(data.get("rejected", [])),
        })
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(AllocationRun, run_id)
    if not run: raise HTTPException(404, "运行不存在")
    return _run_payload(run)
