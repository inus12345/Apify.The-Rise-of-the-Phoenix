"""Selector parser for XPath and CSS-based content extraction."""
from typing import List, Dict, Optional, Any
from bs4 import BeautifulSoup


class SelectorParser:
    """
    Parser for handling XPath and CSS selectors in article extraction.
    
    Supports multiple selector types:
    - CSS selectors (.class, #id, tag.class)
    - XPath-like patterns (//div[@class='content'])
    - Attribute selectors ([data-role='article'])
    - Fallback chains (selector1|selector2|selector3)
    """
    
    def __init__(self):
        self._cache: Dict[str, BeautifulSoup] = {}
    
    def parse_selectors(self, selectors_str: str) -> List[str]:
        """
        Parse a string of selectors into a list.
        
        Supports:
        - Single selector: ".article"
        - Multiple selectors (pipe-separated): ".article|div.content|#main"
        - CSS and XPath-like patterns
        
        Args:
            selectors_str: String containing one or more selectors
            
        Returns:
            List of individual selector strings
        """
        if not selectors_str:
            return []
        
        # Split by pipe for fallback chains
        selectors = [s.strip() for s in selectors_str.split("|") if s.strip()]
        return selectors
    
    def find_element(
        self,
        soup: BeautifulSoup,
        selectors: List[str],
        index: int = 0
    ) -> Optional[Any]:
        """
        Try to find an element using multiple selector strategies.
        
        Args:
            soup: BeautifulSoup parse tree
            selectors: List of selectors to try (fallback chain)
            index: Which selector in the chain to start with
            
        Returns:
            First matching element or None
        """
        for i, selector in enumerate(selectors):
            if i < index:
                continue
                
            elem = self._try_selector(soup, selector.strip())
            if elem:
                return elem
        
        return None
    
    def find_element_text(
        self,
        soup: BeautifulSoup,
        selectors: List[str],
        default: str = "",
        index: int = 0
    ) -> str:
        """
        Find element and extract its text content.
        
        Args:
            soup: BeautifulSoup parse tree
            selectors: List of selectors to try (fallback chain)
            default: Default value if no element found
            index: Which selector in the chain to start with
            
        Returns:
            Text content or default value
        """
        elem = self.find_element(soup, selectors, index)
        if elem:
            return elem.get_text(strip=True)
        return default
    
    def _try_selector(self, soup: BeautifulSoup, selector: str):
        """Try a single selector and return first match."""
        selector = selector.strip()
        
        # Handle attribute-based selectors
        if "[" in selector and "]" in selector:
            return self._try_attribute_selector(soup, selector)
        
        # Handle ID selectors (#id)
        if selector.startswith("#"):
            return soup.find(id=selector[1:])
        
        # Handle class selectors (.class)
        if selector.startswith("."):
            class_name = selector[1:]
            return soup.find(class_=class_name) or soup.select_one(selector)
        
        # Handle tag selectors (div, p, h1, etc.)
        if " " not in selector and "[" not in selector:
            return soup.find(selector)
        
        # Try CSS selector
        try:
            result = soup.select_one(selector)
            return result
        except Exception:
            pass
        
        return None
    
    def _try_attribute_selector(self, soup: BeautifulSoup, selector: str):
        """Try to find element using attribute-based selector."""
        import re
        
        # Parse [attr='value'] or [attr="value"]
        pattern = r'\[(\w+)=(["\']?)([^"\']+)\2\]'
        match = re.search(pattern, selector)
        
        if match:
            attr_name = match.group(1)
            attr_value = match.group(3)
            
            # Try to find element with matching attribute
            for elem in soup.find_all(True):
                if elem.get(attr_name) == attr_value:
                    return elem
        
        # Fallback: try as CSS selector
        try:
            return soup.select_one(selector)
        except Exception:
            return None
    
    def extract_links(
        self,
        soup: BeautifulSoup,
        link_selector: str = "a[href]"
    ) -> List[str]:
        """
        Extract all links from a page.
        
        Args:
            soup: BeautifulSoup parse tree
            link_selector: CSS selector for links
            
        Returns:
            List of href URLs found
        """
        links = []
        
        # Parse multiple selectors if provided
        selectors = self.parse_selectors(link_selector)
        
        for sel in selectors:
            for a_tag in soup.select(sel):
                href = a_tag.get("href")
                if href:
                    links.append(href)
        
        return list(set(links))  # Remove duplicates
    
    def extract_images(
        self,
        soup: BeautifulSoup,
        image_selector: str = "img[src]"
    ) -> List[str]:
        """
        Extract all image URLs from a page.
        
        Args:
            soup: BeautifulSoup parse tree
            image_selector: CSS selector for images
            
        Returns:
            List of image source URLs found
        """
        images = []
        selectors = self.parse_selectors(image_selector)
        
        for sel in selectors:
            for img_tag in soup.select(sel):
                src = img_tag.get("src")
                if src:
                    images.append(src)
        
        return list(set(images))
    
    def parse_date_from_element(self, elem) -> Optional[str]:
        """
        Try to extract a date from various date element formats.
        
        Handles:
        - <time datetime="2024-01-01"> format
        - text-based dates
        - Various common date patterns
        
        Args:
            elem: Element containing date information
            
        Returns:
            Extracted date string or None
        """
        if not elem:
            return None
        
        # Try datetime attribute first (ISO format)
        if hasattr(elem, 'get') and elem.get("datetime"):
            return elem["datetime"]
        
        # Try to find child time elements
        if hasattr(elem, 'find'):
            time_elem = elem.find("time")
            if time_elem:
                date_val = time_elem.get("datetime") or time_elem.get_text()
                if date_val:
                    return date_val
        
        # Extract from text content
        text = elem.get_text() if hasattr(elem, 'get_text') else str(elem)
        
        # Common date patterns
        import re
        
        patterns = [
            r"(\d{4}-\d{2}-\d{2})",           # YYYY-MM-DD
            r"(\d{2}/\d{2}/\d{4})",           # MM/DD/YYYY
            r"(\d{1,2}\s+\w+\s+\d{4})",       # 1 January 2024
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        
        return None


def parse_selectors(selectors_str: str) -> List[str]:
    """
    Convenience function to parse selectors string.
    
    Args:
        selectors_str: String with pipe-separated selectors
        
    Returns:
        List of individual selector strings
    """
    parser = SelectorParser()
    return parser.parse_selectors(selectors_str)
