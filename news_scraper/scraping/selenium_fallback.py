"""Selenium-based fallback scraper for JavaScript-heavy sites."""
from typing import List, Dict, Optional
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class SeleniumScraper:
    """
    Selenium-based scraper for sites requiring JavaScript rendering.
    
    Used as fallback when the HTTPX/BeautifulSoup scraper fails or
    when a site requires dynamic content loading.
    """
    
    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30,
        wait_for_element: Optional[str] = None
    ):
        self.headless = headless
        self.timeout = timeout
        self.wait_for_element = wait_for_element
        
        self.driver: Optional[webdriver.Chrome] = None
    
    def __enter__(self):
        """Context manager entry."""
        options = Options()
        
        if self.headless:
            options.add_argument("--headless=new")
        
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        self.driver = webdriver.Chrome(options=options)
        self.driver.maximize_window()
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
    
    def _get_driver(self) -> webdriver.Chrome:
        """Get or create driver instance."""
        if self.driver is None:
            options = Options()
            if self.headless:
                options.add_argument("--headless=new")
            self.driver = webdriver.Chrome(options=options)
        return self.driver
    
    def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch a page with Selenium.
        
        Args:
            url: The URL to fetch
            
        Returns:
            HTML content as string or None if request failed
        """
        try:
            driver = self._get_driver()
            driver.get(url)
            
            # Wait for page to load
            WebDriverWait(driver, self.timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # If wait_for_element is specified, wait for it
            if self.wait_for_element:
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, self.wait_for_element))
                    )
                except Exception:
                    pass  # Continue anyway
            
            time.sleep(1)  # Allow additional JS to execute
            
            return driver.page_source
        
        except Exception as e:
            print(f"Selenium fetch error for {url}: {e}")
            return None
    
    def click_button(self, selector: str) -> bool:
        """
        Click a button using CSS selector.
        
        Args:
            selector: CSS selector for the button
            
        Returns:
            True if clicked successfully
        """
        try:
            driver = self._get_driver()
            button = driver.find_element(By.CSS_SELECTOR, selector)
            button.click()
            return True
        
        except Exception as e:
            print(f"Failed to click {selector}: {e}")
            return False
    
    def scroll_to_bottom(self) -> None:
        """Scroll to the bottom of the page."""
        try:
            driver = self._get_driver()
            last_height = driver.execute_script("return document.body.scrollHeight")
            
            while True:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
        
        except Exception as e:
            print(f"Scroll error: {e}")
    
    def extract_links(self, selector: str = "a[href]") -> List[str]:
        """
        Extract links from the current page.
        
        Args:
            selector: CSS selector for links
            
        Returns:
            List of href URLs
        """
        try:
            driver = self._get_driver()
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            
            return [el.get_attribute("href") for el in elements if el.get_attribute("href")]
        
        except Exception as e:
            print(f"Link extraction error: {e}")
            return []
    
    def extract_text(self, selector: str) -> Optional[str]:
        """
        Extract text from an element.
        
        Args:
            selector: CSS selector for the element
            
        Returns:
            Text content or None
        """
        try:
            driver = self._get_driver()
            element = driver.find_element(By.CSS_SELECTOR, selector)
            return element.text.strip()
        
        except Exception as e:
            print(f"Text extraction error: {e}")
            return None
    
    def execute_script(self, script: str) -> Optional[str]:
        """
        Execute JavaScript on the current page.
        
        Args:
            script: JavaScript code to execute
            
        Returns:
            Result of the script execution
        """
        try:
            driver = self._get_driver()
            return driver.execute_script(script)
        
        except Exception as e:
            print(f"Script execution error: {e}")
            return None


# Convenience function for quick Selenium scraping
def scrape_with_selenium(
    url: str,
    wait_selector: Optional[str] = None,
    headless: bool = True
) -> Optional[str]:
    """
    Quick helper to scrape a page with Selenium.
    
    Args:
        url: The URL to scrape
        wait_selector: Optional CSS selector to wait for
        headless: Whether to run headless
        
    Returns:
        HTML content or None
    """
    with SeleniumScraper(
        headless=headless,
        wait_for_element=wait_selector
    ) as scraper:
        return scraper.fetch_page(url)