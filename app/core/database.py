from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import DATABASE_URL

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

_engine_kwargs: dict = {"connect_args": _connect_args}

if DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(
        pool_pre_ping=True,
        pool_recycle=300,
        # Для витрины на облачном Postgres (free-tier часто 5–20 conn):
        pool_size=3,
        max_overflow=5,
        pool_timeout=30,
    )
    # Защита от зависших запросов — Postgres убьёт по таймауту.
    _connect_args.setdefault("options", "-c statement_timeout=30000")

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()