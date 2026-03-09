"""Database session management and engine configuration."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from ..core.config import settings


# Create SQLAlchemy engine
engine = create_engine(
    settings.DATABASE_URL,
    echo=False,  # Set to True for SQL logging
    connect_args={
        "check_same_thread": False if "sqlite" in settings.DATABASE_URL else {}
    },
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_session():
    """Get a new database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize the database by creating all tables."""
    import os
    from pathlib import Path
    
    # Ensure data directory exists for SQLite
    db_url = settings.DATABASE_URL
    if "sqlite" in db_url:
        # Extract path from sqlite:///path/to/db
        db_path = db_url.replace("sqlite:///", "")
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
    
    from .models import (
        SiteConfig,
        SiteCategory,
        ScrapedArticle,
        ScrapeRun,
        ValidationRun,
        ScrapeLog
    )
    Base.metadata.create_all(bind=engine)


def reset_db():
    """Drop and recreate all tables (use with caution!)."""
    from .models import (
        SiteConfig,
        SiteCategory,
        ScrapedArticle,
        ScrapeRun,
        ValidationRun,
        ScrapeLog
    )
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


# Test connection function
def test_connection() -> bool:
    """Test database connection."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False