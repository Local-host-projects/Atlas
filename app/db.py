"""DB layer: SQLite locally, Postgres in production via DATABASE_URL."""
from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'atlas.db').as_posix()}")
# Heroku-style fix
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)

if IS_SQLITE:
    # WAL + busy timeout: readers never block writers, short write bursts wait instead of 500s
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models_db  # noqa: F401  (register models)
    Base.metadata.create_all(bind=engine)
