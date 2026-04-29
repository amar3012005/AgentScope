from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from agentscope_blaiq.runtime.config import settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_local: async_sessionmaker[AsyncSession] | None = None


def init_engine(db_url: str | None = None) -> AsyncEngine:
    global _engine, _session_local
    url = db_url or settings.database_url
    _engine = create_async_engine(url, future=True, echo=False)
    _session_local = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


async def close_engine() -> None:
    global _engine, _session_local
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_local = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_local() -> async_sessionmaker[AsyncSession]:
    global _session_local
    if _session_local is None:
        get_engine()
    assert _session_local is not None
    return _session_local


def async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Compatibility helper used by seeding/tests."""
    return get_session_local()


engine = get_engine()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session_local()() as session:
        yield session
