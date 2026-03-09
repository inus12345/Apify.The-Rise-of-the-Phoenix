"""Configuration management for the news scraper platform."""
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field
import logging


class LoggingConfig:
    """Logging configuration for the application."""
    
    @staticmethod
    def get_logging_config():
        """Return logging configuration dictionary."""
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                },
                "detailed": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": "INFO",
                    "formatter": "standard",
                    "stream": "ext://sys.stdout"
                },
                "file": {
                    "class": "logging.FileHandler",
                    "level": "DEBUG",
                    "formatter": "detailed",
                    "filename": "./data/scraping.log",
                    "mode": "a"
                }
            },
            "root": {
                "level": "INFO",
                "handlers": ["console", "file"]
            },
            "loggers": {
                "httpx": {
                    "level": "WARNING",
                    "propagate": False
                },
                "urllib3": {
                    "level": "WARNING",
                    "propagate": False
                }
            }
        }


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    APP_NAME: str = "The Rise of the Phoenix Scraper"
    VERSION: str = "0.1.0"
    
    # Database settings
    DATABASE_URL: str = Field(
        default="sqlite:///./data/scraping.db",
        description="Database URL (SQLite for MVP, PostgreSQL-ready)"
    )
    
    # Scraping settings
    DEFAULT_BATCH_SIZE: int = Field(default=20, ge=1, le=100)
    SCRAPING_TIMEOUT: int = Field(default=30, ge=5, le=300)
    MAX_RETRIES: int = Field(default=3, ge=0, le=10)
    
    # User agent for requests
    USER_AGENT: str = Field(
        default="Mozilla/5.0 (The-Rise-of-the-Phoenix/0.1; +https://github.com/inus12345/Apify.The-Rise-of-the_Phoenix)"
    )
    
    # Logging settings
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FILE: str = Field(default="./data/scraping.log")
    
    # Data directory
    DATA_DIR: Path = Field(default=Path("./data"))
    
    class Config:
        env_prefix = ""
        case_sensitive = False
        extra = "ignore"


# Initialize settings
settings = Settings()


def setup_logging():
    """Setup logging configuration from settings."""
    import logging.config
    
    # Ensure data directory exists for log file
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    config = LoggingConfig.get_logging_config()
    config["handlers"]["file"]["filename"] = settings.LOG_FILE
    
    logging.config.dictConfig(config)


# Setup logging on module import
setup_logging()


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the configured settings."""
    return logging.getLogger(name)