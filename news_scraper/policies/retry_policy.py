"""Retry policy with exponential backoff for robust error handling."""
import time
import random
from typing import Callable, Optional, TypeVar, Union
from functools import wraps


T = TypeVar("T")


class RetryPolicy:
    """
    Policy for retrying operations with exponential backoff.
    
    Features:
    - Configurable maximum retries
    - Exponential backoff (base_delay * 2^attempt)
    - Jitter to prevent thundering herd
    - Customizable error handling
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,      # Base delay in seconds
        max_delay: float = 60.0,      # Maximum delay cap
        jitter_range: float = 0.5,    # Jitter as fraction of delay (e.g., 0.5 = +/- 50%)
        retryable_exceptions: tuple = (Exception,)
    ):
        """
        Initialize the retry policy.
        
        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay before first retry
            max_delay: Maximum delay cap
            jitter_range: Random jitter as fraction of delay (0.0 to 1.0)
            retryable_exceptions: Tuple of exception types that should trigger retry
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter_range = min(max(jitter_range, 0.0), 1.0)  # Clamp to [0, 1]
        self.retryable_exceptions = retryable_exceptions
    
    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate the delay for a given retry attempt.
        
        Uses exponential backoff with jitter.
        
        Args:
            attempt: The retry attempt number (0-indexed)
            
        Returns:
            Delay in seconds
        """
        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay * (2 ** attempt)
        
        # Apply jitter: random value in [delay * (1 - jitter), delay * (1 + jitter)]
        if self.jitter_range > 0:
            jitter = delay * self.jitter_range * (random.random() * 2 - 1)
            delay += jitter
        
        # Cap at maximum delay
        return min(delay, self.max_delay)
    
    def should_retry(self, exception: Exception) -> bool:
        """
        Check if an exception is retryable.
        
        Args:
            exception: The exception that was raised
            
        Returns:
            True if the operation should be retried
        """
        return isinstance(exception, self.retryable_exceptions)
    
    def execute(
        self,
        func: Callable[[], T],
        on_retry: Optional[Callable[[int, float, Exception], None]] = None,
        **kwargs
    ) -> Union[T, None]:
        """
        Execute a function with retry logic.
        
        Args:
            func: The function to execute (no-argument callable)
            on_retry: Optional callback called before each retry (attempt, delay, exception)
            **kwargs: Additional kwargs passed to the function
            
        Returns:
            Result of the function if successful, None if all retries failed
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(**kwargs) if kwargs else func()
            
            except self.retryable_exceptions as e:
                last_exception = e
                
                # Check if we have retries left
                if attempt >= self.max_retries:
                    break
                
                # Calculate delay
                delay = self.calculate_delay(attempt)
                
                # Call retry callback if provided
                if on_retry:
                    try:
                        on_retry(attempt, delay, e)
                    except Exception:
                        pass  # Ignore callback errors
                
                # Wait before retry
                time.sleep(delay)
        
        raise last_exception
    
    def execute_with_callback(
        self,
        func: Callable[..., T],
        *args,
        **kwargs
    ) -> Union[T, None]:
        """
        Execute a function with retry logic and automatic logging.
        
        Args:
            func: The function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments (includes 'name' for logging)
            
        Returns:
            Result of the function if successful, None if all retries failed
        """
        name = kwargs.pop("name", "operation")
        on_retry = kwargs.pop("on_retry", None)
        
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            
            except self.retryable_exceptions as e:
                last_exception = e
                
                if attempt >= self.max_retries:
                    break
                
                delay = self.calculate_delay(attempt)
                
                # Log retry
                print(f"Retry {attempt + 1}/{self.max_retries} for {name} "
                      f"in {delay:.2f}s: {e}")
                
                if on_retry:
                    try:
                        on_retry(attempt, delay, e)
                    except Exception:
                        pass
                
                time.sleep(delay)
        
        raise last_exception


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_range: float = 0.5
) -> Callable:
    """
    Decorator to add retry logic to a function.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay before first retry
        max_delay: Maximum delay cap
        jitter_range: Random jitter as fraction of delay
        
    Returns:
        Decorated function with retry logic
    """
    policy = RetryPolicy(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        jitter_range=jitter_range
    )
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return policy.execute_with_callback(func, *args, **kwargs)
        
        return wrapper
    
    return decorator


class RetryTracker:
    """Track retry statistics for analysis."""
    
    def __init__(self):
        self.total_attempts = 0
        self.successful_first_try = 0
        self.retries_needed: dict[int, int] = {}  # attempts -> count
        self.total_retries = 0
    
    def record_attempt(self, success_on_first: bool, retries: int) -> None:
        """
        Record an execution result.
        
        Args:
            success_on_first: Whether it succeeded on first try
            retries: Number of retries needed (0 if first try succeeded)
        """
        self.total_attempts += 1
        
        if success_on_first:
            self.successful_first_try += 1
            return
        
        self.total_retries += retries
        self.retries_needed[retries] = self.retries_needed.get(retries, 0) + 1
    
    def get_stats(self) -> dict:
        """
        Get retry statistics.
        
        Returns:
            Dictionary with statistics
        """
        avg_retries = (
            self.total_retries / (self.total_attempts - self.successful_first_try)
            if self.total_attempts > self.successful_first_try else 0.0
        )
        
        return {
            "total_attempts": self.total_attempts,
            "successful_first_try": self.successful_first_try,
            "retries_needed": dict(self.retries_needed),
            "avg_retries": round(avg_retries, 2),
            "success_rate": round(
                self.successful_first_try / self.total_attempts * 100, 1
            ) if self.total_attempts > 0 else 0.0,
        }
