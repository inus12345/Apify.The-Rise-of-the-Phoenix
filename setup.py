# Setup script for The Rise of the Phoenix News Scraper Platform
# Allows installation as Python package via: pip install -e .

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="news_scraper",
    version="2.0.0",
    author="The Rise of the Phoenix Team",
    description="Global news scraper platform using scrapling with fallback engines",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "httpx>=0.24.0",
        "beautifulsoup4>=4.12.0",
        "lxml>=4.9.0",
        "pydantic>=2.7.0",
        "python-dateutil>=2.8.0",
        "apify>=1.9.0",
        "scrapling>=0.2.0",
        "pydoll-python>=2.2.0",
        "selenium>=4.10.0",
        "flask>=3.0.0",
    ],
    extras_require={
        "dev": ["pytest>=7.4.0", "pytest-cov>=4.1.0"],
        "llm": ["openai>=1.0.0", "anthropic>=0.3.0"],
    },
    entry_points={
        "console_scripts": [
            "news-scraper=news_scraper.__main__:main",
        ],
    },
)
