"""Async engine + session factory (SQLAlchemy 2.0 + asyncpg)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from taxcalc.web.config import get_settings

# Neon pooled endpoint runs PgBouncer in transaction mode: asyncpg's prepared
# statements break there, so disable the statement cache. SSL is required by Neon
# and passed here because the sslmode/channel_binding query params are stripped
# from DATABASE_URL (asyncpg rejects them).
engine = create_async_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    connect_args={"ssl": "require", "statement_cache_size": 0},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with SessionLocal() as session:
        yield session
