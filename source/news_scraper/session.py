"""Database session management for The Rise of the Phoenix news scraper platform.

This module provides database connectivity and session management. It supports both
SQLite (local development) and PostgreSQL/MySQL (production) databases.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Sequence, Iterator, Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker


def get_database_url(db_name: str = "DATABASE_URL") -> str:
    """Get database URL from environment variable.
    
    Args:
        db_name: Environment variable name for database URL
        
    Returns:
        Database URL string (defaults to SQLite for local development)
    """
    url = os.environ.get(db_name)
    # Default to SQLite database file at the project root for local development
    if not url:
        return "sqlite:///database.db"
    return url.strip()


def _connect_args(db_url: str) -> Dict[str, object]:
    """Get connection arguments for SQLite databases."""
    if db_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _build_engine(db_url: str) -> Engine:
    """Build a SQLAlchemy engine for the given database URL."""
    return create_engine(
        db_url,
        echo=False,
        connect_args=_connect_args(db_url),
    )


# Primary DB: websites/source metadata + scraper strategy + articles/story data.
primary_engine = _build_engine(get_database_url("DATABASE_URL"))

# Spider DB: categories/page tracking + spider diagrams (same as primary by default)
spider_engine = primary_engine


# Session factories for both databases
PrimarySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=primary_engine)
SpiderSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=spider_engine)

# Base classes (single base since we're using one database now)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def get_session() -> Iterator:
    """Yield a primary-database session."""
    db = PrimarySessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_primary_session() -> Iterator:
    """Yield a primary-database session (alias for get_session)."""
    yield from get_session()


def get_spider_session() -> Iterator:
    """Yield a spider-database session."""
    db = SpiderSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Init/reset functions
# ---------------------------------------------------------------------------

def _ensure_sqlite_parent_dir(db_url: str) -> None:
    """Create parent directory for SQLite DB files."""
    if not db_url.startswith("sqlite"):
        return

    db_path = db_url.replace("sqlite:///", "")
    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)


def init_db():
    """Initialize the database by creating all tables.
    
    This function creates all tables defined in models.py. Call this before
    attempting to use the database for the first time.
    """
    _ensure_sqlite_parent_dir(primary_engine.url.render_as_string())

    from . import models

    _ = models
    Base.metadata.create_all(bind=primary_engine)


def reset_db():
    """Drop and recreate all tables (use with caution)."""
    from . import models

    _ = models
    Base.metadata.drop_all(bind=primary_engine)
    Base.metadata.create_all(bind=primary_engine)


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def test_connection() -> bool:
    """Test database connectivity.
    
    Returns:
        True if connection is successful, False otherwise
    """
    try:
        with primary_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Backward-compatible aliases
# ---------------------------------------------------------------------------

engine = primary_engine