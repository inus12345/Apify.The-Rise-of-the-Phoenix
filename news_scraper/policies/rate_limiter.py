"""Rate limiter for polite scraping between requests."""
import time
import threading
from typing import Dict, Optional
from collections import defaultdict


class RateLimiter:
    """
    Thread-safe rate limiter to enforce delays between requests.
    
    Features:
    - Per-domain rate limiting (different domains can be scraped in parallel)
    - Configurable delay between requests
    - Request counting and timing tracking
    - Automatic backoff on errors
    """
    
    def __init__(
        self,
        min_delay: float = 1.0,  # Minimum seconds between requests per domain
        max_requests_per_minute: Optional[int] = None,
        max_requests_per_hour: Optional[int] = None
    ):
        """
        Initialize the rate limiter.
        
        Args:
            min_delay: Minimum seconds between consecutive requests to same domain
            max_requests_per_minute: Maximum requests allowed per minute (None for unlimited)
            max_requests_per_hour: Maximum requests allowed per hour (None for unlimited)
        """
        self.min_delay = min_delay
        
        # Rate limits
        self.max_requests_per_minute = max_requests_per_minute
        self.max_requests_per_hour = max_requests_per_hour
        
        # Track last request time per domain
        self._last_request: Dict[str, float] = {}
        
        # Track request counts for time windows
        self._requests_minute: Dict[str, list] = defaultdict(list)
        self._requests_hour: Dict[str, list] = defaultdict(list)
        
        # Error tracking for exponential backoff
        self._error_counts: Dict[str, int] = defaultdict(int)
        
        # Lock for thread safety
        self._lock = threading.Lock()
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    
    def can_request(self, url: str) -> bool:
        """
        Check if a request to the given URL is allowed.
        
        Args:
            url: The URL to check
            
        Returns:
            True if request is allowed, False otherwise
        """
        domain = self._get_domain(url)
        
        with self._lock:
            # Check per-minute limit
            if self.max_requests_per_minute is not None:
                current_time = time.time()
                minute_ago = current_time - 60
                
                # Remove old requests outside the window
                self._requests_minute[domain] = [
                    t for t in self._requests_minute[domain] if t > minute_ago
                ]
                
                if len(self._requests_minute[domain]) >= self.max_requests_per_minute:
                    return False
            
            # Check per-hour limit
            if self.max_requests_per_hour is not None:
                current_time = time.time()
                hour_ago = current_time - 3600
                
                # Remove old requests outside the window
                self._requests_hour[domain] = [
                    t for t in self._requests_hour[domain] if t > hour_ago
                ]
                
                if len(self._requests_hour[domain]) >= self.max_requests_per_hour:
                    return False
        
        return True
    
    def wait_if_needed(self, url: str) -> float:
        """
        Wait if necessary to respect rate limits.
        
        Args:
            url: The URL about to be requested
            
        Returns:
            Time waited in seconds (0.0 if no wait)
        """
        domain = self._get_domain(url)
        
        with self._lock:
            current_time = time.time()
            
            # Calculate minimum delay based on error count (exponential backoff)
            base_delay = self.min_delay * (1 + 0.5 * self._error_counts[domain])
            min_delay = min(base_delay, 30.0)  # Cap at 30 seconds
            
            # Check time since last request to this domain
            if domain in self._last_request:
                elapsed = current_time - self._last_request[domain]
                wait_time = max(0, min_delay - elapsed)
                
                if wait_time > 0:
                    time.sleep(wait_time)
                    return wait_time
            
            # Record this request
            now = time.time()
            self._last_request[domain] = now
            
            # Track for rate limits
            if self.max_requests_per_minute is not None:
                self._requests_minute[domain].append(now)
            
            if self.max_requests_per_hour is not None:
                self._requests_hour[domain].append(now)
        
        return 0.0
    
    def record_success(self, url: str) -> None:
        """Record a successful request."""
        domain = self._get_domain(url)
        with self._lock:
            # Reset error count on success
            if self._error_counts[domain] > 0:
                self._error_counts[domain] = max(0, self._error_counts[domain] - 1)
    
    def record_error(self, url: str) -> None:
        """Record a failed request (increases delay for future requests)."""
        domain = self._get_domain(url)
        with self._lock:
            self._error_counts[domain] += 1
    
    def get_delay_for_url(self, url: str) -> float:
        """
        Get the recommended delay before making a request to this URL.
        
        Args:
            url: The URL to check
            
        Returns:
            Recommended delay in seconds
        """
        domain = self._get_domain(url)
        with self._lock:
            if domain not in self._last_request:
                return 0.0
            
            current_time = time.time()
            elapsed = current_time - self._last_request[domain]
            
            base_delay = self.min_delay * (1 + 0.5 * self._error_counts[domain])
            min_delay = min(base_delay, 30.0)
            
            return max(0, min_delay - elapsed)
    
    def reset_domain(self, url: str) -> None:
        """Reset rate limiting state for a specific domain."""
        domain = self._get_domain(url)
        with self._lock:
            if domain in self._last_request:
                del self._last_request[domain]
            if domain in self._requests_minute:
                del self._requests_minute[domain]
            if domain in self._requests_hour:
                del self._requests_hour[domain]
            if domain in self._error_counts:
                del self._error_counts[domain]
    
    def reset_all(self) -> None:
        """Reset all rate limiting state."""
        with self._lock:
            self._last_request.clear()
            self._requests_minute.clear()
            self._requests_hour.clear()
            self._error_counts.clear()
    
    def get_stats(self) -> Dict[str, int]:
        """
        Get current rate limiter statistics.
        
        Returns:
            Dictionary with domain -> error count mapping
        """
        with self._lock:
            return dict(self._error_counts)


class DomainThrottler(RateLimiter):
    """Specialized rate limiter that throttles based on domain."""
    
    def __init__(
        self,
        global_delay: float = 1.0,      # Delay between any requests
        per_domain_delay: float = 2.0   # Delay between requests to same domain
    ):
        super().__init__(min_delay=per_domain_delay)
        self.global_delay = global_delay
        self._global_last_request = 0.0
    
    def wait_if_needed(self, url: str) -> float:
        """
        Wait respecting both global and per-domain limits.
        
        Args:
            url: The URL about to be requested
            
        Returns:
            Total time waited in seconds
        """
        total_wait = 0.0
        
        # Check global delay first
        current_time = time.time()
        elapsed = current_time - self._global_last_request
        
        if elapsed < self.global_delay:
            wait_time = self.global_delay - elapsed
            time.sleep(wait_time)
            total_wait += wait_time
        
        # Update global timestamp
        self._global_last_request = time.time()
        
        # Also check per-domain delay (inherited from RateLimiter)
        domain_wait = super().wait_if_needed(url)
        total_wait += domain_wait
        
        return total_wait
    
    def record_success(self, url: str) -> None:
        """Record a successful request and update global timestamp."""
        self._global_last_request = time.time()
        super().record_success(url)
    
    def record_error(self, url: str) -> None:
        """Record a failed request and update global timestamp."""
        self._global_last_request = time.time()
        super().record_error(url)
