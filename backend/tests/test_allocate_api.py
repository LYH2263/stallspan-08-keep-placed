import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import AllocationRun, MarketDay, Pillar, Segment, Vendor


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c, TestSession
    app.dependency_overrides.clear()


def _seed(session_factory, width=20.0):
    with session_factory() as db:
        day = MarketDay(name="测试夜市", day=date(2026, 9, 30))
        db.add(day); db.flush()
        seg = Segment(market_day_id=day.id, name="东街段", width_m=width)
        db.add(seg); db.flush()
        # P 高优先 8m、B 低优先 6m、Q 低优先 6m → 0-8 / 8-14 / 14-20
        for name, wdt, pri in [("P", 8.0, 1), ("B", 6.0, 9), ("Q", 6.0, 9)]:
            db.add(Vendor(market_day_id=day.id, name=name, stall_width_m=wdt, priority=pri))
        db.commit()
        return seg.id


def _run_count(session_factory):
    with session_factory() as db:
        return db.scalar(select(func.count()).select_from(AllocationRun))


def test_preserve_without_any_run_is_rejected_no_half_success(client):
    c, sf = client
    seg_id = _seed(sf)
    resp = c.post(f"/api/allocate/run?segment_id={seg_id}&preserve=true")
    assert resp.status_code == 409
    # 禁止半成功：不写入任何运行，图与放不下维持原状。
    assert _run_count(sf) == 0
    latest = c.get(f"/api/allocate/latest?segment_id={seg_id}").json()
    assert latest["preserve"] is False
    assert all(p["locked"] is False for p in latest["placements"])


def test_preserve_retains_coords_and_fills_remaining(client):
    c, sf = client
    seg_id = _seed(sf)
    with sf() as db:
        # 首跑只保留高优先 P(8m)：落 0-8，8-20 为空档。
        for name in ("B", "Q"):
            db.query(Vendor).filter_by(name=name).delete()
        db.commit()
    first = c.post(f"/api/allocate/run?segment_id={seg_id}&preserve=false").json()
    assert first["preserve"] is False and first["baseline_run_id"] is None
    assert {p["vendor_name"]: (p["start_m"], p["end_m"]) for p in first["placements"]} == {"P": (0.0, 8.0)}

    # 新增摊 N(5m) 后勾保留重跑：P 起止锁定，N 只能在剩余空档从左填（8 起），不得侵入锁区。
    with sf() as db:
        day_id = db.get(Segment, seg_id).market_day_id
        db.add(Vendor(market_day_id=day_id, name="N", stall_width_m=5.0, priority=5))
        db.commit()
    second = c.post(f"/api/allocate/run?segment_id={seg_id}&preserve=true").json()
    assert second["preserve"] is True
    assert second["baseline_run_id"] == first["id"]
    p = next(x for x in second["placements"] if x["vendor_name"] == "P")
    assert (p["start_m"], p["end_m"], p["locked"]) == (0.0, 8.0, True)
    n = next(x for x in second["placements"] if x["vendor_name"] == "N")
    assert (n["start_m"], n["end_m"], n["locked"]) == (8.0, 13.0, False)
    assert all(x["end_m"] <= p["start_m"] + 1e-9 or x["start_m"] >= p["end_m"] - 1e-9
               for x in second["placements"] if not x["locked"])


def test_low_priority_locked_stall_conflict_is_recorded_as_lock_conflict(client):
    c, sf = client
    seg_id = _seed(sf, width=12.0)  # P 8m 落 0-8；B/Q 各 6m，剩 8-12 仅 4m
    with sf() as db:
        db.query(Vendor).filter_by(name="Q").delete()
        db.commit()
    c.post(f"/api/allocate/run?segment_id={seg_id}&preserve=false")
    resp = c.post(f"/api/allocate/run?segment_id={seg_id}&preserve=true").json()
    rejected = {(r["vendor_name"], r["lock_conflict"]) for r in resp["rejected"]}
    # B 宽 6 在无锁区时整段 12m 放得下 → 必须记锁区冲突，不是空档不够。
    assert ("B", True) in rejected
    p = next(x for x in resp["placements"] if x["vendor_name"] == "P")
    assert (p["start_m"], p["end_m"]) == (0.0, 8.0)  # 锁摊起止未被静默挪动


def test_true_and_false_results_do_not_share_lock_cache(client):
    c, sf = client
    seg_id = _seed(sf)
    r_false_1 = c.post(f"/api/allocate/run?segment_id={seg_id}&preserve=false").json()
    r_true = c.post(f"/api/allocate/run?segment_id={seg_id}&preserve=true").json()
    # 勾真跑出的色块带锁
    assert all(p["locked"] for p in r_true["placements"])
    # 勾假后整段重算：没有任何色块可被当成锁区
    r_false_2 = c.post(f"/api/allocate/run?segment_id={seg_id}&preserve=false").json()
    assert r_false_2["preserve"] is False
    assert all(not p["locked"] for p in r_false_2["placements"])
    # 最新结果即为非保留，/latest 不把保留结果的锁区带出来
    latest = c.get(f"/api/allocate/latest?segment_id={seg_id}").json()
    assert latest["id"] == r_false_2["id"]
    assert all(not p["locked"] for p in latest["placements"])
    # 反之：勾真结果的历史快照仍保留其锁区标记，不被后续假结果覆盖
    snap_true = c.get(f"/api/allocate/runs/{r_true['id']}").json()
    assert snap_true["preserve"] is True and all(p["locked"] for p in snap_true["placements"])


def test_old_non_preserve_run_snapshot_not_polluted(client):
    c, sf = client
    seg_id = _seed(sf)
    old = c.post(f"/api/allocate/run?segment_id={seg_id}&preserve=false").json()
    c.post(f"/api/allocate/run?segment_id={seg_id}&preserve=true")
    snap = c.get(f"/api/allocate/runs/{old['id']}").json()
    assert snap["preserve"] is False
    assert all(not p["locked"] for p in snap["placements"])
    # 抽屉列表口径：保留/非保留各自计数
    items = c.get(f"/api/allocate/runs?segment_id={seg_id}").json()
    assert items[0]["preserve"] is True and items[0]["locked_count"] == 3
    assert any(i["id"] == old["id"] and i["preserve"] is False and i["locked_count"] == 0
               for i in items)
