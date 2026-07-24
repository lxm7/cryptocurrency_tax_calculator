"""Declarative base for all ORM models (SQLAlchemy 2.0, typed)."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
