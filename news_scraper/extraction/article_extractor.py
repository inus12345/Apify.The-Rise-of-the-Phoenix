"""Article extractor with robust parsing and configurable selectors."""
from typing import Dict, Any, Optional, List
from datetime import datetime
from urllib.parse import urljoin
import re

from bs4 import BeautifulSoup

from .selector_parser import SelectorParser


class ArticleExtractor:
    """
    Advanced article extractor with configurable CSS/XPath selectors.
    
    Supports:
    - Multiple fallback selectors per field (try multiple patterns)
    - Date parsing from various formats
    - Content cleaning and normalization
    - Metadata extraction from HTML
    """
    
    DEFAULT_SELECTORS = {
        "title": ["h1", ".title", "#title", 'meta[property="og:title"]', "[itemprop='name']"],
        "date": [
            "time[datetime]",
            ".date",
            ".pub-date",
            "#publish-date",
            "[rel='publish']"
        ],
        "author": [
            ".author",
            ".byline",
            "[rel='author']",
            'meta[name="author"]'
        ],
        "content": [
            "article",
            ".content",
            ".article-content",
            "#main-content",
            "[itemprop='articleBody']"
        ],
        "image": [
            'meta[property="og:image"]',
            '.featured-image img',
            '.hero-img img',
            'img[width][height]'
        ],
        "description": [
            'meta[name="description"]',
            'meta[property="og:description"]',
            ".excerpt",
            "[itemprop='description']"
        ],
        "section": [
            'meta[property="article:section"]',
            ".section-name",
            ".article-section",
            "[data-section]"
        ],
        "tags": [
            'meta[name="keywords"]',
            ".tags a",
            ".article-tags a",
            "[rel='tag']"
        ],
    }
    
    def __init__(self, selectors: Dict[str, str] = None):
        """
        Initialize the extractor with custom selectors.
        
        Args:
            selectors: Dictionary of field -> selector string
                      Selector strings can contain pipe-separated fallbacks
                      Example: {"title": "h1|.article-title|#main-title"}
        """
        self.selectors = selectors or {}
        self.parser = SelectorParser()

    @staticmethod
    def _coerce_text(value: Any) -> str:
        """Normalize bytes/objects into a safe string."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="ignore")
        return str(value)
    
    def extract(self, url: str, html: str) -> Dict[str, Any]:
        """
        Extract article data from HTML content.
        
        Args:
            url: The source URL (for absolute link resolution)
            html: HTML content to parse
            
        Returns:
            Dictionary with extracted fields:
                - url: Source URL
                - title: Article title
                - body: Main content
                - authors: Comma-separated author names
                - date_publish: Publication date string
                - description: Article excerpt
                - image_url: Featured image URL
        """
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract all fields
        result = {
            "url": url,
            "title": self._extract_title(soup),
            "body": self._extract_content(soup),
            "authors": self._extract_authors(soup),
            "date_publish": self._extract_date(soup),
            "description": self._extract_description(soup),
            "image_url": self._extract_image(soup),
            "canonical_url": self._extract_canonical_url(soup, url),
            "section": self._extract_section(soup),
            "tags": self._extract_tags(soup),
            "extra_links": self._extract_extra_links(soup, url),
            "image_links": self._extract_image_links(soup, url),
            "language": self._extract_language(soup),
            "raw_metadata": self._extract_raw_metadata(soup),
        }

        body_text = result.get("body", "") or ""
        word_count = len(body_text.split()) if body_text else 0
        result["word_count"] = word_count if word_count > 0 else None
        result["reading_time_minutes"] = self._estimate_reading_time(word_count)

        # Clean extracted data
        result = self._clean_result(result)
        
        return result
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title from page."""
        selector_str = self.selectors.get("title", "")
        selectors = self.parser.parse_selectors(selector_str or "|".join(self.DEFAULT_SELECTORS["title"]))
        
        # Try each selector in order
        for sel in selectors:
            elem = self.parser.find_element(soup, [sel])
            if elem:
                if hasattr(elem, "get") and elem.get("content"):
                    title = self._coerce_text(elem.get("content")).strip()
                else:
                    title = self._coerce_text(elem.get_text(strip=True)).strip()
                if title and len(title) > 10:  # Avoid very short titles (likely navigation)
                    return title
        
        # Fallback: try page <title> tag
        title_tag = soup.find("title")
        if title_tag:
            text = title_tag.get_text(strip=True)
            if text and "|" not in text[:20]:  # Likely a real title, not site name
                return text
        
        return "Untitled Article"
    
    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract main article content from page."""
        selector_str = self.selectors.get("content", "")
        selectors = self.parser.parse_selectors(selector_str or "|".join(self.DEFAULT_SELECTORS["content"]))
        
        # Try each selector in order
        for sel in selectors:
            elem = self.parser.find_element(soup, [sel])
            if elem:
                content = self._extract_from_element(elem)
                if content and len(content) > 200:  # Minimum content length
                    return content

        # Structured-data fallback for script-heavy pages.
        json_ld_content = self._extract_content_from_json_ld(soup)
        if json_ld_content and len(json_ld_content) > 200:
            return json_ld_content
        
        # Fallback: try to find the largest article-like element
        body_text = self._find_largest_content(soup)
        if body_text:
            return body_text
        
        # Final fallback: all paragraphs from body
        all_p = soup.find_all("p")
        paragraphs = [p.get_text(strip=True) for p in all_p]
        content = "\n\n".join(p for p in paragraphs if len(p.strip()) > 50)
        
        return content or ""
    
    def _extract_from_element(self, elem) -> str:
        """Extract text from a content element, preserving structure."""
        # Try to preserve paragraph structure
        paragraphs = []
        
        # Find all <p> tags within the element
        for p in elem.find_all("p"):
            text = p.get_text(strip=True)
            if text and len(text) > 20:  # Skip very short lines
                paragraphs.append(text)
        
        # If no paragraphs, get all text but clean up
        if not paragraphs:
            text = elem.get_text(separator="\n\n", strip=True)
            # Split into paragraphs by double newlines or long blocks
            paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
        
        return "\n\n".join(paragraphs) if paragraphs else elem.get_text(strip=True)
    
    def _extract_authors(self, soup: BeautifulSoup) -> str:
        """Extract author names from page."""
        selector_str = self.selectors.get("author", "")
        selectors = self.parser.parse_selectors(selector_str or "|".join(self.DEFAULT_SELECTORS["author"]))
        
        for sel in selectors:
            elem = self.parser.find_element(soup, [sel])
            if elem:
                # Check for content attribute (meta tags)
                if hasattr(elem, 'get') and elem.get("content"):
                    author = elem["content"]
                else:
                    author = elem.get_text(strip=True)
                
                if author:
                    return author.replace("By", "").strip()
        
        # Fallback: look for common author patterns
        all_authors = []
        for elem in soup.find_all(["span", "div", "a"]):
            text = elem.get_text(strip=True)
            if any(pattern in text.lower() for pattern in ["by ", "author:", "written by"]):
                # Extract name after pattern
                match = re.search(r"(?:by|author[:\s]|written by)[:\s]+(.+)", text, re.IGNORECASE)
                if match:
                    all_authors.append(match.group(1).strip())
        
        return ", ".join(set(all_authors)) if all_authors else "Unknown Author"
    
    def _extract_date(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract publication date from page."""
        selector_str = self.selectors.get("date", "")
        selectors = self.parser.parse_selectors(selector_str or "|".join(self.DEFAULT_SELECTORS["date"]))
        
        for sel in selectors:
            elem = self.parser.find_element(soup, [sel])
            if elem:
                # Try datetime attribute first
                if hasattr(elem, 'get') and elem.get("datetime"):
                    return elem["datetime"]
                
                # Try to parse date from text
                date_str = self.parser.parse_date_from_element(elem)
                if date_str:
                    return date_str
                
                # Fallback: get all text
                text = self._coerce_text(elem.get_text(strip=True)).strip()
                
                patterns = [
                    (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
                    (r"(\d{1,2}/\d{1,2}/\d{4})", "%m/%d/%Y"),
                    (r"(\w+ \d{1,2}, \d{4})", "%B %d, %Y"),
                ]
                
                for pattern, fmt in patterns:
                    match = re.search(pattern, text)
                    if match:
                        try:
                            date_obj = datetime.strptime(match.group(1), fmt)
                            return date_obj.strftime("%Y-%m-%dT%H:%M:%S")
                        except ValueError:
                            continue
        
        # Check URL for date pattern
        from urllib.parse import urlparse
        base_href = ""
        base_tag = soup.find("base")
        if base_tag and hasattr(base_tag, "get"):
            base_href = self._coerce_text(base_tag.get("href")).strip()
        parsed = urlparse(base_href)
        
        url_patterns = [
            r"/(\d{4}/\d{2}/\d{2})",
            r"/(\d{8})",
        ]
        
        for pattern in url_patterns:
            path = self._coerce_text(parsed.path)
            match = re.search(pattern, path)
            if match:
                date_str = match.group(1).replace("/", "-")
                return f"{date_str[:4]}-{date_str[5:7]}-{date_str[8:10]}"
        
        # Fallback: current date
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    
    def _extract_description(self, soup: BeautifulSoup) -> str:
        """Extract article description/excerpt."""
        selector_str = self.selectors.get("description", "")
        selectors = self.parser.parse_selectors(selector_str or "|".join(self.DEFAULT_SELECTORS["description"]))
        
        for sel in selectors:
            elem = self.parser.find_element(soup, [sel])
            if elem:
                if hasattr(elem, 'get') and elem.get("content"):
                    return self._coerce_text(elem.get("content")).strip()
                return self._coerce_text(elem.get_text(strip=True)).strip()
        
        # Fallback: first paragraph
        first_p = soup.find("p")
        if first_p:
            text = first_p.get_text(strip=True)
            if len(text) > 50:
                return text[:200] + "..." if len(text) > 200 else text
        
        return ""
    
    def _extract_image(self, soup: BeautifulSoup) -> str:
        """Extract featured image URL."""
        selector_str = self.selectors.get("image", "")
        selectors = self.parser.parse_selectors(selector_str or "|".join(self.DEFAULT_SELECTORS["image"]))
        
        for sel in selectors:
            elem = self.parser.find_element(soup, [sel])
            if elem:
                # Check content attribute (meta tags)
                if hasattr(elem, 'get') and elem.get("content"):
                    return elem["content"]
                
                # Check src attribute
                if elem.name == "img":
                    return elem.get("src", "")
                
                # Find img tag within element
                img = elem.find("img")
                if img:
                    return img.get("src", "")
        
        return ""

    def _extract_canonical_url(self, soup: BeautifulSoup, page_url: str) -> str:
        """Extract canonical URL for the article."""
        canonical = soup.select_one("link[rel='canonical']")
        if canonical and canonical.get("href"):
            return urljoin(page_url, canonical.get("href"))
        return page_url

    def _extract_section(self, soup: BeautifulSoup) -> str:
        """Extract section/category of the article."""
        selector_str = self.selectors.get("section", "")
        selectors = self.parser.parse_selectors(selector_str or "|".join(self.DEFAULT_SELECTORS["section"]))

        for sel in selectors:
            elem = self.parser.find_element(soup, [sel])
            if not elem:
                continue
            if hasattr(elem, "get") and elem.get("content"):
                return elem["content"].strip()
            text = elem.get_text(strip=True)
            if text:
                return text
        return ""

    def _extract_tags(self, soup: BeautifulSoup) -> List[str]:
        """Extract article tags/topics."""
        selector_str = self.selectors.get("tags", "")
        selectors = self.parser.parse_selectors(selector_str or "|".join(self.DEFAULT_SELECTORS["tags"]))
        tags: List[str] = []

        for sel in selectors:
            for elem in soup.select(sel):
                if hasattr(elem, "get") and elem.get("content"):
                    parts = [p.strip() for p in elem["content"].split(",") if p.strip()]
                    tags.extend(parts)
                    continue
                text = elem.get_text(strip=True)
                if text:
                    tags.append(text)

        # Deduplicate while preserving order.
        return list(dict.fromkeys(tags))

    def _extract_extra_links(self, soup: BeautifulSoup, page_url: str) -> List[str]:
        """Extract article-adjacent links for downstream graph processing."""
        links: List[str] = []
        for tag in soup.find_all("a", href=True):
            href = tag.get("href", "").strip()
            if not href:
                continue
            absolute = urljoin(page_url, href)
            if absolute.startswith(("http://", "https://")):
                links.append(absolute)
        return list(dict.fromkeys(links))

    def _extract_image_links(self, soup: BeautifulSoup, page_url: str) -> List[str]:
        """Extract all image sources from the article page."""
        image_links: List[str] = []
        for img in soup.find_all("img"):
            for attr in ("src", "data-src", "data-original"):
                value = img.get(attr, "").strip()
                if value:
                    absolute = urljoin(page_url, value)
                    if absolute.startswith(("http://", "https://")):
                        image_links.append(absolute)
                    break
        return list(dict.fromkeys(image_links))

    def _extract_language(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract language from the HTML document."""
        html = soup.find("html")
        if html and html.get("lang"):
            return html.get("lang").split("-")[0].strip().lower()
        return None

    def _extract_raw_metadata(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Capture selected meta tag data for lineage and LLM review."""
        metadata: Dict[str, str] = {}
        for meta in soup.find_all("meta"):
            key = meta.get("property") or meta.get("name")
            value = meta.get("content")
            if key and value:
                metadata[str(key)] = str(value)
        return metadata

    @staticmethod
    def _estimate_reading_time(word_count: int) -> Optional[int]:
        """Estimate reading time with a 200 words/minute baseline."""
        if word_count <= 0:
            return None
        return max(1, round(word_count / 200))
    
    def _find_largest_content(self, soup: BeautifulSoup) -> Optional[str]:
        """Find the largest content block (likely the main article)."""
        candidates = []
        
        # Look for common article containers
        for elem in soup.find_all(["article", "div", "section"]):
            text = elem.get_text()
            word_count = len(text.split())
            
            if word_count > 100:  # Minimum content length
                # Score based on various factors
                score = word_count
                
                # Bonus for common article class patterns
                classes = " ".join(elem.get("class", []))
                if any(p in classes.lower() for p in ["article", "content", "post", "story"]):
                    score += 100
                
                candidates.append((score, elem))
        
        if not candidates:
            return None
        
        # Return text from highest-scoring element
        _, best_elem = max(candidates, key=lambda x: x[0])
        return self._extract_from_element(best_elem)

    def _extract_content_from_json_ld(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article body from JSON-LD when HTML body is sparse."""
        import json

        def _walk(node: Any):
            if isinstance(node, dict):
                body = node.get("articleBody")
                if isinstance(body, str) and len(body.strip()) > 200:
                    yield body
                for value in node.values():
                    yield from _walk(value)
            elif isinstance(node, list):
                for value in node:
                    yield from _walk(value)

        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = self._coerce_text(script.string or script.get_text()).strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except Exception:
                continue
            for body in _walk(parsed):
                cleaned = re.sub(r"\s+", " ", self._coerce_text(body)).strip()
                if len(cleaned) > 200:
                    return cleaned
        return None
    
    def _clean_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Clean and normalize extracted data."""
        # Clean title
        if result.get("title"):
            result["title"] = result["title"].strip()
        
        # Clean body
        if result.get("body"):
            # Normalize whitespace
            body = result["body"]
            body = re.sub(r"\n\s*\n", "\n\n", body)  # Multiple newlines
            body = re.sub(r"[\t ]+", " ", body)      # Tabs and spaces
            result["body"] = body.strip()

        # Normalize lists and empty values.
        for list_field in ("extra_links", "image_links", "tags"):
            value = result.get(list_field)
            if isinstance(value, list):
                result[list_field] = [v for v in value if v]
                if not result[list_field]:
                    result[list_field] = None

        if not result.get("section"):
            result["section"] = None

        if not result.get("raw_metadata"):
            result["raw_metadata"] = None

        return result


def extract_article(url: str, html: str, selectors: Dict[str, str] = None) -> Dict[str, Any]:
    """
    Convenience function to extract article data.
    
    Args:
        url: Source URL
        html: HTML content
        selectors: Optional custom selectors
        
    Returns:
        Dictionary with extracted fields
    """
    extractor = ArticleExtractor(selectors)
    return extractor.extract(url, html)
