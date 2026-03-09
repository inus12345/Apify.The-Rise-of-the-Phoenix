"""Article extractor with robust parsing and configurable selectors."""
from typing import Dict, Any, Optional, List
from datetime import datetime

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
        ]
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
        }
        
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
                title = elem.get_text(strip=True)
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
                import re
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
                text = elem.get_text(strip=True)
                import re
                from datetime import datetime
                
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
        parsed = urlparse(soup.find("base").get("href") if soup.find("base") else "")
        
        url_patterns = [
            r"/(\d{4}/\d{2}/\d{2})",
            r"/(\d{8})",
        ]
        
        for pattern in url_patterns:
            import re
            match = re.search(pattern, parsed.path)
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
                    return elem["content"]
                return elem.get_text(strip=True)
        
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
    
    def _clean_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Clean and normalize extracted data."""
        # Clean title
        if result.get("title"):
            result["title"] = result["title"].strip()
        
        # Clean body
        if result.get("body"):
            # Normalize whitespace
            import re
            body = result["body"]
            body = re.sub(r"\n\s*\n", "\n\n", body)  # Multiple newlines
            body = re.sub(r"[\t ]+", " ", body)      # Tabs and spaces
            result["body"] = body.strip()
        
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