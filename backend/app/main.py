from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.seed import seed_if_empty


def _ensure_schema():
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    if "allocation_runs" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("allocation_runs")}
        if "keep_placed" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE allocation_runs ADD COLUMN keep_placed BOOLEAN NOT NULL DEFAULT FALSE"
                ))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _ensure_schema()
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="StallSpan", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
