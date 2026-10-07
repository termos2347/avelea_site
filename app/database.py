from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

# check_same_thread нужен только для SQLite: FastAPI работает в разных потоках,
# а дефолтный pysqlite-драйвер это запрещает.
_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

_engine_kwargs: dict = {
    "connect_args": _connect_args,
}

if DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(
        pool_pre_ping=True,
        pool_recycle=300,
        # Размеры пула — дефолты SQLAlchemy, но здесь явно, чтобы было видно.
        pool_size=5,
        max_overflow=10,
    )

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()