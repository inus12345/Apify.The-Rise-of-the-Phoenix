# Database Session Management - The Rise of the Phoenix
# Simplified single SQLite database for all site configuration data

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()


def get_database_url(db_name="DATABASE_URL"):
    """Get database URL from environment variable"""
    return os.getenv(db_name)


def get_session():
    """Get database session with tables auto-created"""
    url = get_database_url()
    
    if not url:
        raise ValueError(f"{db_name} environment variable is not set")
    
    engine = create_engine(url, echo=False)
    Base.metadata.create_all(bind=engine)
    
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return SessionLocal()


def get_engine():
    """Get database engine (singleton pattern)"""
    url = get_database_url()
    if not url:
        raise ValueError(f"{db_name} environment variable is not set")
    
    engine = create_engine(url, echo=False)
    Base.metadata.create_all(bind=engine)
    return engine


def cleanup_db():
    """Drop all tables (use with caution!)"""
    url = get_database_url()
    if not url:
        raise ValueError(f"{db_name} environment variable is not set")
    
    engine = create_engine(url, echo=False)
    Base.metadata.drop_all(bind=engine)
    print("All tables dropped.")


def init_db():
    """Initialize database - creates all 4 core tables"""
    url = get_database_url()
    if not url:
        raise ValueError(f"{db_name} environment variable is not set")
    
    engine = create_engine(url, echo=False)
    Base.metadata.create_all(bind=engine)
    print("Database initialized with 4 core tables!")