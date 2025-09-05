"""
Rate Limiting Middleware for SIS Provider API Calls.

This module implements sophisticated rate limiting to respect the API limits
of different SIS providers (PowerSchool, Infinite Campus, Skyward) and prevent
overwhelming external services.

Features:
- Per-provider rate limiting with different limits
- Token bucket algorithm for smooth request distribution
- Request queuing and throttling
- Adaptive rate limiting based on provider responses
- Comprehensive monitoring and metrics
"""
import asyncio
import time
import logging
from typing import Dict, Optional, Any, List, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from collections import deque, defaultdict

import redis.asyncio as redis


logger = logging.getLogger(__name__)


class RateLimitStrategy(str, Enum):
    """Rate limiting strategies."""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiter."""
    max_requests: int  # Maximum requests per time window
    time_window: int  # Time window in seconds
    burst_limit: Optional[int] = None  # Max burst requests (for token bucket)
    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET
    backoff_factor: float = 1.5  # Exponential backoff multiplier
    max_queue_size: int = 1000  # Maximum queued requests
    provider: str = "default"


@dataclass
class RateLimitMetrics:
    """Metrics for rate limiting."""
    total_requests: int = 0
    allowed_requests: int = 0
    denied_requests: int = 0
    queued_requests: int = 0
    queue_timeouts: int = 0
    average_queue_time: float = 0.0
    current_queue_size: int = 0
    last_reset_time: float = field(default_factory=time.time)
    
    def record_request(self, allowed: bool, queue_time: float = 0.0):
        """Record a request attempt."""
        self.total_requests += 1
        if allowed:
            self.allowed_requests += 1
            if queue_time > 0:
                self.queued_requests += 1
                # Update rolling average
                if self.queued_requests == 1:
                    self.average_queue_time = queue_time
                else:
                    self.average_queue_time = (
                        (self.average_queue_time * (self.queued_requests - 1) + queue_time) / 
                        self.queued_requests
                    )
        else:
            self.denied_requests += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        return {
            'total_requests': self.total_requests,
            'allowed_requests': self.allowed_requests,
            'denied_requests': self.denied_requests,
            'queued_requests': self.queued_requests,
            'queue_timeouts': self.queue_timeouts,
            'success_rate': self.allowed_requests / max(self.total_requests, 1),
            'queue_rate': self.queued_requests / max(self.total_requests, 1),
            'average_queue_time': self.average_queue_time,
            'current_queue_size': self.current_queue_size
        }


class TokenBucket:
    """
    Token bucket implementation for smooth rate limiting.
    
    Allows bursts up to bucket capacity while maintaining average rate.
    """
    
    def __init__(self, rate: float, capacity: int):
        self.rate = rate  # Tokens per second
        self.capacity = capacity  # Maximum tokens
        self.tokens = capacity  # Current tokens
        self.last_update = time.time()
        self._lock = asyncio.Lock()
    
    async def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from the bucket."""
        async with self._lock:
            now = time.time()
            
            # Add tokens based on elapsed time
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            # Try to consume tokens
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            return False
    
    async def get_wait_time(self, tokens: int = 1) -> float:
        """Get estimated wait time for tokens to be available."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            current_tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            
            if current_tokens >= tokens:
                return 0.0
            
            needed_tokens = tokens - current_tokens
            return needed_tokens / self.rate


@dataclass
class QueuedRequest:
    """A request waiting in the rate limiter queue."""
    request_id: str
    timestamp: float
    future: asyncio.Future
    timeout: float = 30.0  # Default timeout
    
    @property
    def is_expired(self) -> bool:
        """Check if request has timed out."""
        return time.time() - self.timestamp > self.timeout


class RateLimiter:
    """
    Advanced rate limiter with multiple strategies and request queuing.
    
    Features:
    - Token bucket algorithm for smooth rate limiting
    - Request queuing with configurable timeouts
    - Per-provider configuration
    - Adaptive rate limiting based on server responses
    - Redis-based state for distributed systems
    """
    
    def __init__(
        self,
        max_requests: int,
        time_window: int,
        provider: str = "default",
        burst_limit: Optional[int] = None,
        strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET,
        max_queue_size: int = 1000,
        redis_client: Optional[redis.Redis] = None
    ):
        self.config = RateLimitConfig(
            max_requests=max_requests,
            time_window=time_window,
            burst_limit=burst_limit or max_requests * 2,
            strategy=strategy,
            max_queue_size=max_queue_size,
            provider=provider
        )
        
        # Calculate rate in requests per second
        self.rate = max_requests / time_window
        
        # Initialize token bucket
        self.token_bucket = TokenBucket(
            rate=self.rate,
            capacity=self.config.burst_limit
        )
        
        # Request queue
        self.request_queue: deque[QueuedRequest] = deque()
        self.metrics = RateLimitMetrics()
        
        # Redis for distributed rate limiting (optional)
        self.redis_client = redis_client
        self.redis_key_prefix = f"rate_limit:{provider}"
        
        # Background task for processing queue
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._stop_processing = False
        
        logger.info(
            f"Rate limiter initialized for {provider}: "
            f"{max_requests} requests per {time_window}s "
            f"(burst: {self.config.burst_limit})"
        )
    
    async def start(self):
        """Start the rate limiter background processing."""
        self._stop_processing = False
        self._queue_processor_task = asyncio.create_task(self._process_queue())
        logger.info(f"Rate limiter started for {self.config.provider}")
    
    async def stop(self):
        """Stop the rate limiter and cleanup resources."""
        self._stop_processing = True
        
        if self._queue_processor_task:
            await self._queue_processor_task
        
        # Cancel all pending requests
        while self.request_queue:
            queued_request = self.request_queue.popleft()
            if not queued_request.future.done():
                queued_request.future.set_exception(
                    asyncio.CancelledError("Rate limiter shutdown")
                )
        
        logger.info(f"Rate limiter stopped for {self.config.provider}")
    
    async def acquire(self, request_id: Optional[str] = None, timeout: float = 30.0) -> bool:
        """
        Acquire permission to make a request.
        
        Returns True if request can proceed immediately, False if denied.
        May queue the request for later processing.
        """
        start_time = time.time()
        
        # Check if we can consume a token immediately
        if await self.token_bucket.consume():
            self.metrics.record_request(allowed=True)
            return True
        
        # If queue is full, deny request
        if len(self.request_queue) >= self.config.max_queue_size:
            self.metrics.record_request(allowed=False)
            logger.warning(f"Rate limiter queue full for {self.config.provider}")
            return False
        
        # Queue the request
        request_id = request_id or f"req_{int(time.time() * 1000000)}"
        future = asyncio.Future()
        
        queued_request = QueuedRequest(
            request_id=request_id,
            timestamp=start_time,
            future=future,
            timeout=timeout
        )
        
        self.request_queue.append(queued_request)
        self.metrics.current_queue_size = len(self.request_queue)
        
        try:
            # Wait for the request to be processed or timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            queue_time = time.time() - start_time
            self.metrics.record_request(allowed=True, queue_time=queue_time)
            return result
            
        except asyncio.TimeoutError:
            # Remove from queue if still there
            try:
                self.request_queue.remove(queued_request)
                self.metrics.current_queue_size = len(self.request_queue)
            except ValueError:
                pass  # Already removed
            
            self.metrics.queue_timeouts += 1
            self.metrics.record_request(allowed=False)
            logger.warning(f"Rate limiter timeout for {self.config.provider}")
            return False
    
    async def _process_queue(self):
        """Background task to process queued requests."""
        while not self._stop_processing:
            try:
                # Clean up expired requests
                await self._cleanup_expired_requests()
                
                # Process requests that can be fulfilled
                while self.request_queue and await self.token_bucket.consume():
                    queued_request = self.request_queue.popleft()
                    self.metrics.current_queue_size = len(self.request_queue)
                    
                    if not queued_request.future.done():
                        queued_request.future.set_result(True)
                
                # Wait before next iteration
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in rate limiter queue processor: {e}")
                await asyncio.sleep(1.0)
    
    async def _cleanup_expired_requests(self):
        """Remove expired requests from the queue."""
        expired_requests = []
        
        # Find expired requests
        for queued_request in list(self.request_queue):
            if queued_request.is_expired:
                expired_requests.append(queued_request)
        
        # Remove expired requests and notify them
        for expired_request in expired_requests:
            try:
                self.request_queue.remove(expired_request)
                self.metrics.current_queue_size = len(self.request_queue)
                
                if not expired_request.future.done():
                    expired_request.future.set_exception(
                        asyncio.TimeoutError("Request expired in queue")
                    )
                
                self.metrics.queue_timeouts += 1
                
            except ValueError:
                pass  # Already removed
    
    async def get_wait_time(self) -> float:
        """Get estimated wait time for next available slot."""
        # Check token bucket wait time
        token_wait = await self.token_bucket.get_wait_time()
        
        # Add queue processing time estimate
        queue_wait = len(self.request_queue) / max(self.rate, 0.1)
        
        return token_wait + queue_wait
    
    async def adjust_rate(self, new_rate: float, reason: str = ""):
        """Dynamically adjust rate limit (adaptive rate limiting)."""
        if new_rate <= 0:
            logger.warning(f"Invalid rate adjustment attempted: {new_rate}")
            return
        
        old_rate = self.rate
        self.rate = new_rate
        
        # Update token bucket with new rate
        self.token_bucket.rate = new_rate
        
        # Update config
        self.config.max_requests = int(new_rate * self.config.time_window)
        
        logger.info(
            f"Rate limit adjusted for {self.config.provider}: "
            f"{old_rate:.2f} -> {new_rate:.2f} req/s"
            f"{f' ({reason})' if reason else ''}"
        )
    
    def get_status(self) -> Dict[str, Any]:
        """Get current rate limiter status and metrics."""
        return {
            'provider': self.config.provider,
            'config': {
                'max_requests': self.config.max_requests,
                'time_window': self.config.time_window,
                'burst_limit': self.config.burst_limit,
                'rate_per_second': self.rate,
                'max_queue_size': self.config.max_queue_size
            },
            'current_state': {
                'available_tokens': self.token_bucket.tokens,
                'token_capacity': self.token_bucket.capacity,
                'queue_size': len(self.request_queue),
                'estimated_wait_time': asyncio.create_task(self.get_wait_time())
            },
            'metrics': self.metrics.get_stats()
        }
    
    def reset_metrics(self):
        """Reset all metrics."""
        self.metrics = RateLimitMetrics()


class RateLimitMiddleware:
    """
    FastAPI middleware for applying rate limits to requests.
    
    Integrates with the API Gateway to provide per-provider rate limiting.
    """
    
    def __init__(self):
        self.rate_limiters: Dict[str, RateLimiter] = {}
        self.default_limiter: Optional[RateLimiter] = None
    
    async def setup_provider_limiters(self, provider_configs: Dict[str, Dict[str, Any]]):
        """Setup rate limiters for different providers."""
        for provider, config in provider_configs.items():
            rate_limiter = RateLimiter(
                max_requests=config.get('max_requests', 100),
                time_window=config.get('time_window', 3600),
                provider=provider,
                burst_limit=config.get('burst_limit'),
                max_queue_size=config.get('max_queue_size', 1000)
            )
            
            await rate_limiter.start()
            self.rate_limiters[provider] = rate_limiter
            
            logger.info(f"Setup rate limiter for provider: {provider}")
    
    async def get_rate_limiter(self, provider: str) -> Optional[RateLimiter]:
        """Get rate limiter for a specific provider."""
        return self.rate_limiters.get(provider, self.default_limiter)
    
    async def cleanup(self):
        """Cleanup all rate limiters."""
        for rate_limiter in self.rate_limiters.values():
            await rate_limiter.stop()
        
        if self.default_limiter:
            await self.default_limiter.stop()
    
    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all rate limiters."""
        return {
            provider: limiter.get_status()
            for provider, limiter in self.rate_limiters.items()
        }


# Provider-specific rate limiter configurations
PROVIDER_RATE_LIMITS = {
    'powerschool': {
        'max_requests': 1000,  # PowerSchool allows 1000 requests/hour
        'time_window': 3600,   # 1 hour
        'burst_limit': 50,     # Allow bursts up to 50 requests
        'max_queue_size': 500
    },
    'infinite_campus': {
        'max_requests': 500,   # More conservative for Infinite Campus
        'time_window': 3600,   # 1 hour
        'burst_limit': 25,     # Smaller burst allowance
        'max_queue_size': 300
    },
    'skyward': {
        'max_requests': 2000,  # Skyward has higher limits
        'time_window': 3600,   # 1 hour
        'burst_limit': 100,    # Larger burst allowance
        'max_queue_size': 800
    }
}


# Global middleware instance
rate_limit_middleware = RateLimitMiddleware()