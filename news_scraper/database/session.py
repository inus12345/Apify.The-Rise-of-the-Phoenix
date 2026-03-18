"""Database session management for simplified news scraper platform."""
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _primary_db_url() -> str:
    """Return primary DB URL."""
    return "sqlite:///./data/scraping.db"


def _spider_db_url() -> str:
    """Return spider DB URL."""
    return "sqlite:///./data/spider_tracking.db"


# Ensure parent directories exist
Path(_primary_db_url().replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
Path(_spider_db_url().replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)

# Create engines
primary_engine = create_engine(
    _primary_db_url(),
    echo=False,
    connect_args={"check_same_thread": False},
)
spider_engine = create_engine(
    _spider_db_url(),
    echo=False,
    connect_args={"check_same_thread": False},
)

# Alias for backward compatibility
engine = primary_engine

# Session factories
PrimarySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=primary_engine)
SpiderSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=spider_engine)


def get_primary_session() -> Generator:
    """Yield a primary-database session."""
    db = PrimarySessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_spider_session() -> Generator:
    """Yield a spider-database session."""
    db = SpiderSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session() -> Generator:
    """Backward-compatible alias for primary database session."""
    yield from get_primary_session()


def init_db():
    """Initialize the database by creating all tables.
    
    This function must be called before using any database operations.
    It imports models to register them with Base.metadata and creates all tables.
    """
    # Import models to register them with Base.metadata
    from .models import SiteConfig, SiteCategory  # noqa: F401
    
    with primary_engine.connect() as conn:
        # Enable foreign keys
        conn.execute(text("PRAGMA foreign_keys = ON"))
        # Create all tables
        SiteConfig.__table__.create(bind=primary_engine, checkfirst=True)
        SiteCategory.__table__.create(bind=primary_engine, checkfirst=True)
