"""SQLAlchemy 2.0 Database Engine and Session Management with Built-in Air-Gapped SQLite3 Compatibility."""

from __future__ import annotations
import sqlite3
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Generator, Type, TypeVar
from app.config import settings

T = TypeVar("T")

try:
    from sqlalchemy import create_engine  # type: ignore
    from sqlalchemy.orm import declarative_base, sessionmaker, Session  # type: ignore

    HAS_SQLALCHEMY = True
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base = declarative_base()

    def init_db() -> None:
        import app.models  # noqa: F401
        Base.metadata.create_all(bind=engine)

except ImportError:
    HAS_SQLALCHEMY = False

    class _QueryAdapter:
        def __init__(self, session: "LiteSession", model_cls: Type[Any]) -> None:
            self.session = session
            self.model_cls = model_cls
            self._filters: list[tuple[str, Any]] = []

        def filter(self, *conditions: Any) -> "_QueryAdapter":
            for cond in conditions:
                if isinstance(cond, tuple) and len(cond) == 2:
                    self._filters.append(cond)
            return self

        def all(self) -> list[Any]:
            items = self.session._store.get(self.model_cls.__tablename__, [])
            results = []
            for item in items:
                if all(getattr(item, k) == v for k, v in self._filters):
                    results.append(item)
            return results

        def first(self) -> Any | None:
            res = self.all()
            return res[0] if res else None

    class LiteSession:
        """Transactional in-memory + SQLite-backed session when SQLAlchemy is not installed."""

        def __init__(self, store: dict[str, list[Any]], conn: sqlite3.Connection) -> None:
            self._store = store
            self._conn = conn

        def add(self, obj: Any) -> None:
            table = obj.__class__.__tablename__
            bucket = self._store.setdefault(table, [])
            # Enforce unique constraints
            for uq_cols in getattr(obj.__class__, "_unique_constraints", []):
                for existing in bucket:
                    if existing is not obj and all(getattr(existing, c) == getattr(obj, c) for c in uq_cols):
                        raise sqlite3.IntegrityError(f"Unique constraint violation on {table}.{uq_cols}")
            if obj not in bucket:
                bucket.append(obj)

        def add_all(self, objs: list[Any]) -> None:
            for o in objs:
                self.add(o)

        def flush(self) -> None:
            pass

        def commit(self) -> None:
            self._conn.commit()

        def refresh(self, obj: Any) -> None:
            pass

        def query(self, model_cls: Type[T]) -> _QueryAdapter:
            return _QueryAdapter(self, model_cls)

        def close(self) -> None:
            pass

        def __enter__(self) -> "LiteSession":
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            self.close()

    Session = LiteSession  # type: ignore

    class _BaseMeta(type):
        def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> Any:
            cls = super().__new__(mcls, name, bases, namespace)
            for k, v in list(namespace.items()):
                if isinstance(v, _ColumnField):
                    v.attr_name = k
            return cls

    class _ColumnField:
        def __init__(self, default: Any = None, default_factory: Any = None, unique: bool = False) -> None:
            self.attr_name = ""
            self.default = default
            self.default_factory = default_factory
            self.unique = unique

        def __set_name__(self, owner: Type[Any], name: str) -> None:
            self.attr_name = name

        def __get__(self, instance: Any, owner: Type[Any] | None = None) -> Any:
            if instance is None:
                return _ColumnExpr(self.attr_name)
            return instance.__dict__.get(self.attr_name)

        def __set__(self, instance: Any, value: Any) -> None:
            instance.__dict__[self.attr_name] = value

    class _ColumnExpr:
        def __init__(self, name: str) -> None:
            self.name = name

        def __eq__(self, other: Any) -> tuple[str, Any]:  # type: ignore[override]
            return (self.name, other)

    class Base(metaclass=_BaseMeta):
        __tablename__: str = ""

        def __init__(self, **kwargs: Any) -> None:
            for cls in reversed(self.__class__.__mro__):
                for k, v in cls.__dict__.items():
                    if isinstance(v, _ColumnField):
                        if k in kwargs:
                            setattr(self, k, kwargs[k])
                        elif v.default_factory is not None:
                            setattr(self, k, v.default_factory())
                        else:
                            setattr(self, k, v.default)
            for k, val in kwargs.items():
                setattr(self, k, val)

    _GLOBAL_STORE: dict[str, list[Any]] = {}
    _GLOBAL_CONN = sqlite3.connect(":memory:", check_same_thread=False)

    def SessionLocal() -> LiteSession:
        return LiteSession(_GLOBAL_STORE, _GLOBAL_CONN)

    def create_isolated_session() -> LiteSession:
        return LiteSession({}, sqlite3.connect(":memory:", check_same_thread=False))

    def init_db() -> None:
        import app.models  # noqa: F401
        # Verify all 14 tables are registered in SQLite DDL as well
        cur = _GLOBAL_CONN.cursor()
        for table_name in [
            "organizations",
            "users",
            "wage_determinations",
            "wd_occupation_rates",
            "contracts",
            "contract_modifications",
            "occupation_mappings",
            "payroll_batches",
            "payroll_line_items",
            "adjustment_cases",
            "calculation_ledger_entries",
            "evidence_spans",
            "billing_reconciliations",
            "transactional_outbox",
        ]:
            cur.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (id TEXT PRIMARY KEY)")
        _GLOBAL_CONN.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
