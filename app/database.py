"""SQLAlchemy 2.0 engine. SQLite is the local default; Postgres uses the same models."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg2" not in url and "+psycopg" not in url:
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
    module_name = type(dbapi_connection).__module__
    if module_name.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


_database_url = _normalize_database_url(settings.database_url)
_connect_args = {"check_same_thread": False} if _database_url.startswith("sqlite") else {}
engine = create_engine(_database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def init_db() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
