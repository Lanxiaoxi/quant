"""SQLite 业务库会话（DESIGN.md 5.2）。

业务表（策略、回测、用户）走 SQLite；行情仍走 DuckDB（app/data/store.py）。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    f"sqlite:///{settings.sqlite_path}",
    connect_args={"check_same_thread": False},
    echo=False,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表（导入模型以注册映射）。"""
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
