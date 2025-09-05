"""
Request Throttling System for API Gateway.

This module implements sophisticated throttling mechanisms to control
the flow of requests to external SIS providers, ensuring we respect
their rate limits and prevent overwhelming their systems.
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict, deque
import json

from app.services.api_gateway import ProviderType, GatewayRequest


logger = logging.getLogger(__name__)


class ThrottleStrategy(str, Enum):
    """Throttling strategies."""
    FIXED_RATE = "fixed_rate"
    ADAPTIVE = "adaptive"
    BURST_AND_SUSTAIN = "burst_and_sustain"
    PROVIDER_AWARE = "provider_aware"


@dataclass
class ThrottleConfig:
    """Configuration for request throttling."""
    provider: str
    max_requests_per_second: float = 10.0
    max_burst_size: int = 50
    burst_window_seconds: int = 60
    backoff_factor: float = 1.5
    min_interval_ms: int = 100  # Minimum time between requests
    adaptive_enabled: bool = True
    circuit_breaker_threshold: int = 5


@dataclass
class ThrottleMetrics:
    """Metrics for throttling behavior."""
    total_requests: int = 0
    throttled_requests: int = 0
    delayed_requests: int = 0
    average_delay: float = 0.0
    max_delay_recorded: float = 0.0
    current_rate: float = 0.0
    burst_count: int = 0
    circuit_trips: int = 0
    adaptive_adjustments: int = 0
    
    def record_request(self, throttled: bool, delay: float = 0.0):
        """Record request metrics."""
        self.total_requests += 1
        
        if throttled:
            self.throttled_requests += 1
        
        if delay > 0:
            self.delayed_requests += 1
            # Update rolling average delay
            if self.delayed_requests == 1:
                self.average_delay = delay
            else:
                self.average_delay = (
                    (self.average_delay * (self.delayed_requests - 1) + delay) / 
                    self.delayed_requests
                )
            
            self.max_delay_recorded = max(self.max_delay_recorded, delay)
    
    def record_burst(self):
        """Record burst occurrence."""
        self.burst_count += 1
    
    def record_circuit_trip(self):
        """Record circuit breaker trip."""
        self.circuit_trips += 1
    
    def record_adaptive_adjustment(self):
        """Record adaptive rate adjustment."""
        self.adaptive_adjustments += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        return {
            'total_requests': self.total_requests,
            'throttled_requests': self.throttled_requests,
            'delayed_requests': self.delayed_requests,
            'throttle_rate': self.throttled_requests / max(self.total_requests, 1),
            'delay_rate': self.delayed_requests / max(self.total_requests, 1),
            'average_delay': self.average_delay,
            'max_delay_recorded': self.max_delay_recorded,
            'current_rate': self.current_rate,
            'burst_count': self.burst_count,
            'circuit_trips': self.circuit_trips,
            'adaptive_adjustments': self.adaptive_adjustments
        }


class RequestThrottler:
    """
    Advanced request throttler with multiple strategies.
    
    Features:
    - Fixed rate limiting with burst allowances
    - Adaptive throttling based on server responses
    - Provider-specific configurations
    - Smooth request distribution
    - Circuit breaker integration
    - Comprehensive metrics and monitoring
    """
    
    def __init__(
        self,
        provider: str,
        config: Optional[ThrottleConfig] = None
    ):
        self.provider = provider
        self.config = config or ThrottleConfig(provider=provider)
        
        # Throttling state
        self.last_request_time = 0.0
        self.burst_tokens = self.config.max_burst_size
        self.burst_window_start = time.time()
        self.request_times: deque = deque()  # Rolling window of request times
        
        # Adaptive state
        self.current_rate = self.config.max_requests_per_second
        self.consecutive_errors = 0
        self.last_error_time = 0.0
        self.rate_adjustment_history: List[Tuple[float, float, str]] = []
        
        # Request tracking
        self.pending_requests: Set[str] = set()
        self.metrics = ThrottleMetrics()
        
        # Locks for thread safety
        self._throttle_lock = asyncio.Lock()
        
        logger.info(f"Request throttler initialized for {provider}: {self.config.max_requests_per_second} req/s")
    
    async def should_throttle(self, request: GatewayRequest) -> Tuple[bool, float]:
        """
        Check if a request should be throttled.
        
        Returns:
            Tuple of (should_throttle, delay_seconds)
        """
        async with self._throttle_lock:
            now = time.time()
            
            # Clean up old request times
            self._cleanup_request_history(now)
            
            # Check different throttling conditions
            throttle_decision = await self._evaluate_throttling(request, now)
            
            if throttle_decision[0]:  # Should throttle
                delay = throttle_decision[1]
                self.metrics.record_request(throttled=True, delay=delay)
                logger.debug(f"Throttling request for {self.provider}: delay={delay:.2f}s")
                return throttle_decision
            
            # Update request tracking
            self.last_request_time = now
            self.request_times.append(now)
            self.pending_requests.add(request.metadata.get('request_id', str(id(request))))
            
            # Update current rate
            self._update_current_rate(now)
            
            # Record metrics
            self.metrics.record_request(throttled=False)
            
            return False, 0.0
    
    async def _evaluate_throttling(self, request: GatewayRequest, now: float) -> Tuple[bool, float]:
        """Evaluate whether to throttle based on configured strategy."""
        # Check minimum interval
        min_interval = self.config.min_interval_ms / 1000.0
        time_since_last = now - self.last_request_time
        
        if time_since_last < min_interval:
            return True, min_interval - time_since_last
        
        # Strategy-specific evaluation
        if self.config.adaptive_enabled:
            return await self._adaptive_throttling_evaluation(request, now)
        else:
            return await self._fixed_throttling_evaluation(request, now)
    
    async def _fixed_throttling_evaluation(self, request: GatewayRequest, now: float) -> Tuple[bool, float]:
        """Fixed rate throttling evaluation."""
        # Check rate limit
        requests_in_window = len([t for t in self.request_times if now - t <= 1.0])
        
        if requests_in_window >= self.current_rate:
            # Calculate delay until next slot is available
            oldest_in_window = min([t for t in self.request_times if now - t <= 1.0])
            delay = 1.0 - (now - oldest_in_window)
            return True, max(delay, 0.1)  # Minimum 0.1s delay
        
        # Check burst limits
        return await self._check_burst_limits(now)
    
    async def _adaptive_throttling_evaluation(self, request: GatewayRequest, now: float) -> Tuple[bool, float]:
        """Adaptive throttling evaluation based on system feedback."""
        # Adjust rate based on recent errors
        await self._adjust_adaptive_rate(now)
        
        # Use adjusted rate for evaluation
        requests_in_window = len([t for t in self.request_times if now - t <= 1.0])
        
        if requests_in_window >= self.current_rate:
            delay = 1.0 / self.current_rate
            return True, delay
        
        # Additional adaptive checks
        return await self._check_adaptive_conditions(request, now)
    
    async def _check_burst_limits(self, now: float) -> Tuple[bool, float]:
        """Check burst limits and token bucket."""
        # Reset burst window if needed
        if now - self.burst_window_start >= self.config.burst_window_seconds:
            self.burst_window_start = now
            self.burst_tokens = self.config.max_burst_size
            self.metrics.record_burst()
        
        # Check if burst tokens available
        if self.burst_tokens <= 0:
            # Calculate delay until burst window resets
            time_until_reset = (
                self.burst_window_start + self.config.burst_window_seconds - now
            )
            return True, max(time_until_reset, 0.1)
        
        # Consume burst token
        self.burst_tokens -= 1
        return False, 0.0
    
    async def _check_adaptive_conditions(self, request: GatewayRequest, now: float) -> Tuple[bool, float]:
        """Check adaptive conditions like circuit breaker state."""
        # Circuit breaker logic
        if self.consecutive_errors >= self.config.circuit_breaker_threshold:
            time_since_error = now - self.last_error_time
            
            # Exponential backoff
            backoff_delay = min(
                self.config.backoff_factor ** self.consecutive_errors,
                60.0  # Max 60 second delay
            )
            
            if time_since_error < backoff_delay:
                self.metrics.record_circuit_trip()
                return True, backoff_delay - time_since_error
        
        return False, 0.0
    
    async def _adjust_adaptive_rate(self, now: float):
        """Adjust rate based on recent performance."""
        if not self.config.adaptive_enabled:
            return
        
        # Check if adjustment is needed (every 30 seconds)
        if (
            self.rate_adjustment_history and 
            now - self.rate_adjustment_history[-1][0] < 30.0
        ):
            return
        
        # Calculate recent error rate
        recent_errors = sum(1 for _, _, reason in self.rate_adjustment_history[-10:] if reason.startswith("error"))
        recent_adjustments = len(self.rate_adjustment_history[-10:])
        
        if recent_adjustments > 0:
            error_rate = recent_errors / recent_adjustments
            
            if error_rate > 0.1:  # More than 10% error rate
                # Reduce rate
                new_rate = self.current_rate * 0.8
                self._update_rate(new_rate, "high_error_rate", now)
            elif error_rate < 0.05 and self.current_rate < self.config.max_requests_per_second:
                # Increase rate slowly
                new_rate = min(
                    self.current_rate * 1.1,
                    self.config.max_requests_per_second
                )
                self._update_rate(new_rate, "low_error_rate", now)
    
    def _update_rate(self, new_rate: float, reason: str, timestamp: float):
        """Update the current rate and record the change."""
        old_rate = self.current_rate
        self.current_rate = max(0.1, new_rate)  # Minimum 0.1 req/s
        
        self.rate_adjustment_history.append((timestamp, new_rate, reason))
        self.metrics.record_adaptive_adjustment()
        
        logger.info(
            f"Adaptive rate adjustment for {self.provider}: "
            f"{old_rate:.2f} -> {new_rate:.2f} req/s ({reason})"
        )
    
    def _cleanup_request_history(self, now: float):
        """Clean up old request times to maintain memory efficiency."""
        # Keep only requests from last 60 seconds
        cutoff_time = now - 60.0
        while self.request_times and self.request_times[0] < cutoff_time:
            self.request_times.popleft()
        
        # Clean up rate adjustment history (keep last 100 entries)
        if len(self.rate_adjustment_history) > 100:
            self.rate_adjustment_history = self.rate_adjustment_history[-100:]
    
    def _update_current_rate(self, now: float):
        """Update current rate based on recent requests."""
        # Calculate rate over last 10 seconds
        recent_requests = [t for t in self.request_times if now - t <= 10.0]
        if recent_requests:
            self.metrics.current_rate = len(recent_requests) / 10.0
        else:
            self.metrics.current_rate = 0.0
    
    async def record_response(self, request_id: str, success: bool, response_time: float):
        """Record response feedback for adaptive throttling."""
        async with self._throttle_lock:
            # Remove from pending requests
            self.pending_requests.discard(request_id)
            
            now = time.time()
            
            if success:
                # Reset consecutive errors on success
                self.consecutive_errors = 0
            else:
                # Increment error count
                self.consecutive_errors += 1
                self.last_error_time = now
                
                # Record error for adaptive adjustment
                if self.config.adaptive_enabled:
                    self.rate_adjustment_history.append((now, self.current_rate, f"error_{response_time}"))
            
            logger.debug(f"Response recorded for {self.provider}: success={success}, time={response_time:.2f}s")
    
    async def wait_if_throttled(self, request: GatewayRequest) -> bool:
        """
        Check throttling and wait if necessary.
        
        Returns:
            True if request proceeded, False if permanently throttled
        """
        should_throttle, delay = await self.should_throttle(request)
        
        if should_throttle:
            if delay > 60.0:  # Don't wait more than 60 seconds
                logger.warning(f"Request throttled with excessive delay: {delay:.2f}s")
                return False
            
            logger.debug(f"Throttling delay for {self.provider}: {delay:.2f}s")
            await asyncio.sleep(delay)
        
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """Get current throttler status and metrics."""
        now = time.time()
        
        return {
            'provider': self.provider,
            'config': {
                'max_requests_per_second': self.config.max_requests_per_second,
                'max_burst_size': self.config.max_burst_size,
                'burst_window_seconds': self.config.burst_window_seconds,
                'adaptive_enabled': self.config.adaptive_enabled,
                'min_interval_ms': self.config.min_interval_ms
            },
            'current_state': {
                'current_rate': self.current_rate,
                'burst_tokens_remaining': self.burst_tokens,
                'consecutive_errors': self.consecutive_errors,
                'pending_requests': len(self.pending_requests),
                'requests_last_minute': len([t for t in self.request_times if now - t <= 60.0])
            },
            'metrics': self.metrics.get_stats(),
            'recent_adjustments': self.rate_adjustment_history[-5:] if self.rate_adjustment_history else []
        }
    
    def reset_metrics(self):
        """Reset all metrics."""
        self.metrics = ThrottleMetrics()
        self.rate_adjustment_history.clear()


class ThrottleManager:
    """
    Manager for multiple request throttlers.
    
    Provides centralized management and coordination of throttling
    across different SIS providers.
    """
    
    def __init__(self):
        self.throttlers: Dict[str, RequestThrottler] = {}
        self.global_throttler: Optional[RequestThrottler] = None
    
    def create_throttler(self, provider: str, config: Optional[ThrottleConfig] = None) -> RequestThrottler:
        """Create and register a new throttler."""
        if provider in self.throttlers:
            logger.warning(f"Throttler for {provider} already exists, replacing")
        
        throttler = RequestThrottler(provider, config)
        self.throttlers[provider] = throttler
        
        logger.info(f"Created throttler for provider: {provider}")
        return throttler
    
    def get_throttler(self, provider: str) -> Optional[RequestThrottler]:
        """Get throttler for a specific provider."""
        return self.throttlers.get(provider)
    
    async def should_throttle_request(self, request: GatewayRequest) -> Tuple[bool, float]:
        """Check if request should be throttled using provider-specific throttler."""
        provider = request.provider.value
        throttler = self.get_throttler(provider)
        
        if throttler:
            return await throttler.should_throttle(request)
        
        # Use global throttler if no provider-specific one
        if self.global_throttler:
            return await self.global_throttler.should_throttle(request)
        
        # No throttling configured
        return False, 0.0
    
    async def wait_if_throttled(self, request: GatewayRequest) -> bool:
        """Wait if request is throttled."""
        provider = request.provider.value
        throttler = self.get_throttler(provider)
        
        if throttler:
            return await throttler.wait_if_throttled(request)
        
        if self.global_throttler:
            return await self.global_throttler.wait_if_throttled(request)
        
        return True  # No throttling, proceed
    
    async def record_response(self, provider: str, request_id: str, success: bool, response_time: float):
        """Record response for adaptive throttling."""
        throttler = self.get_throttler(provider)
        if throttler:
            await throttler.record_response(request_id, success, response_time)
    
    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all throttlers."""
        status = {}
        
        for provider, throttler in self.throttlers.items():
            status[provider] = throttler.get_status()
        
        if self.global_throttler:
            status['global'] = self.global_throttler.get_status()
        
        return status
    
    def setup_provider_throttlers(self):
        """Setup throttlers for known SIS providers."""
        # PowerSchool - Conservative settings
        powerschool_config = ThrottleConfig(
            provider="powerschool",
            max_requests_per_second=5.0,  # Conservative rate
            max_burst_size=20,
            burst_window_seconds=60,
            adaptive_enabled=True,
            min_interval_ms=200
        )
        self.create_throttler("powerschool", powerschool_config)
        
        # Infinite Campus - Even more conservative
        infinite_campus_config = ThrottleConfig(
            provider="infinite_campus",
            max_requests_per_second=3.0,
            max_burst_size=15,
            burst_window_seconds=60,
            adaptive_enabled=True,
            min_interval_ms=300
        )
        self.create_throttler("infinite_campus", infinite_campus_config)
        
        # Skyward - More permissive
        skyward_config = ThrottleConfig(
            provider="skyward",
            max_requests_per_second=10.0,
            max_burst_size=50,
            burst_window_seconds=60,
            adaptive_enabled=True,
            min_interval_ms=100
        )
        self.create_throttler("skyward", skyward_config)
        
        logger.info("Setup throttlers for all SIS providers")


# Global throttle manager
throttle_manager = ThrottleManager()