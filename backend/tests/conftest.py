from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import MarketDay, Pillar, Segment, Vendor


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def seeded(db_session):
    """与 services.seed 一致的种子数据：30m 街段、两根挡柱、含 12m 未落宽摊。"""
    day = MarketDay(name="周末夜市", day=date(2026, 9, 20))
    db_session.add(day)
    db_session.flush()
    seg = Segment(market_day_id=day.id, name="东街段", width_m=30.0)
    db_session.add(seg)
    db_session.flush()
    db_session.add(Pillar(segment_id=seg.id, position_m=10.0, thickness_m=0.5, label="灯柱A"))
    db_session.add(Pillar(segment_id=seg.id, position_m=20.0, thickness_m=0.5, label="灯柱B"))
    vendors = [
        ("阿强烧烤", 4.0, 1), ("林记糖水", 3.0, 1), ("老周水果", 5.0, 2),
        ("小美饰品", 2.5, 2), ("大碗面", 6.0, 1), ("手作皮具", 3.5, 3),
        ("巨型舞台车", 12.0, 9),
    ]
    ids = {}
    for name, wdt, pri in vendors:
        v = Vendor(market_day_id=day.id, name=name, stall_width_m=wdt, priority=pri)
        db_session.add(v)
        db_session.flush()
        ids[name] = v.id
    db_session.commit()
    return {"segment_id": seg.id, "market_day_id": day.id, "vendor_ids": ids}
