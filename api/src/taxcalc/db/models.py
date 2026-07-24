"""Persisted schema — deliberately minimal (ephemeral-free data model).

Only NON-user-specific data lives in Postgres:
- ``price_snapshots`` — a shared valuation cache (asset/quote at a point in time),
  keyed for idempotent upserts. Not user data.
- ``users`` — account identity for the save/paid tier (auth fields land in a
  later slice).

Per-user tax data (transactions, disposals, pool state) is held in Redis with a
TTL and never persisted here for the free tier; the paid tier adds encrypted
persistence later. See CONTEXT.md → data-model decision.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from taxcalc.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PriceSnapshot(Base):
    """A single shared valuation point: 1 unit of ``asset`` in ``quote`` at ``as_of``.

    Unique on (asset, quote, as_of, source) so backfill/ingest can upsert without
    duplicating. ``price`` is exact Numeric — the engine consumes it as ``Decimal``.
    """

    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint("asset", "quote", "as_of", "source", name="uq_price_point"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    quote: Mapped[str] = mapped_column(String(8), nullable=False)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
