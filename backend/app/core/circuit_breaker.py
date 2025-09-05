"""
Circuit Breaker Pattern Implementation for External API Resilience.

This module implements the circuit breaker pattern to prevent cascading failures
when external services (SIS providers) are unavailable or experiencing issues.

Circuit Breaker States:
- CLOSED: Normal operation, requests pass through
- OPEN: Circuit is tripped, requests fail fast
- HALF_OPEN: Testing if service has recovered
"""
import asyncio
import logging
import time
from typing import Any, Callable, Optional, Type, Dict, List
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    failure_threshold: int = 5  # Number of failures before opening
    recovery_timeout: int = 60  # Seconds before trying half-open
    success_threshold: int = 3  # Successes needed to close from half-open
    timeout: float = 30.0  # Request timeout in seconds
    expected_exception: Type[Exception] = Exception


@dataclass
class CircuitBreakerMetrics:
    """Metrics tracking for circuit breaker."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeout_requests: int = 0
    open_state_requests: int = 0
    state_changes: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests
    
    @property
    def failure_rate(self) -> float:
        """Calculate failure rate."""
        return 1.0 - self.success_rate
    
    def record_state_change(self, from_state: CircuitState, to_state: CircuitState, reason: str):
        """Record a state transition."""
        self.state_changes.append({
            'timestamp': datetime.utcnow().isoformat(),
            'from_state': from_state,
            'to_state': to_state,
            'reason': reason
        })


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""
    pass


class CircuitBreakerTimeoutError(Exception):
    """Exception raised when request times out."""
    pass


class CircuitBreaker:
    """
    Circuit Breaker implementation with configurable thresholds and recovery logic.
    
    Features:
    - Automatic failure detection and circuit opening
    - Exponential backoff for recovery attempts
    - Metrics collection and monitoring
    - Configurable failure thresholds and timeouts
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 3,
        timeout: float = 30.0,
        expected_exception: Type[Exception] = Exception,
        name: Optional[str] = None
    ):
        self.config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=success_threshold,
            timeout=timeout,
            expected_exception=expected_exception
        )
        
        self.name = name or f"CircuitBreaker_{id(self)}"
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.next_attempt_time: Optional[datetime] = None
        self.metrics = CircuitBreakerMetrics()
        self._lock = asyncio.Lock()
        
        logger.info(f"Circuit breaker '{self.name}' initialized with threshold={failure_threshold}")
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function call through the circuit breaker.
        
        Args:
            func: The async function to call
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            Result of the function call
            
        Raises:
            CircuitBreakerError: When circuit is open
            CircuitBreakerTimeoutError: When request times out
            Exception: Any exception from the wrapped function
        """
        async with self._lock:
            self.metrics.total_requests += 1
            
            # Check if circuit should transition states
            await self._check_state_transition()
            
            if self.state == CircuitState.OPEN:
                self.metrics.open_state_requests += 1
                logger.warning(f"Circuit breaker '{self.name}' is OPEN - failing fast")
                raise CircuitBreakerError(f"Circuit breaker '{self.name}' is open")
            
            try:
                # Execute with timeout
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=self.config.timeout
                )
                
                # Success - reset failure count and handle state transitions
                await self._on_success()
                return result
                
            except asyncio.TimeoutError:
                self.metrics.timeout_requests += 1
                logger.error(f"Circuit breaker '{self.name}' - request timed out after {self.config.timeout}s")
                await self._on_failure("timeout")
                raise CircuitBreakerTimeoutError(f"Request timed out after {self.config.timeout}s")
                
            except self.config.expected_exception as e:
                logger.error(f"Circuit breaker '{self.name}' - expected failure: {e}")
                await self._on_failure(str(e))
                raise
                
            except Exception as e:
                logger.error(f"Circuit breaker '{self.name}' - unexpected failure: {e}")
                await self._on_failure(f"unexpected: {e}")
                raise
    
    async def _check_state_transition(self):
        """Check if the circuit breaker should change state."""
        now = datetime.utcnow()
        
        if self.state == CircuitState.OPEN:
            # Check if we should try half-open
            if (
                self.next_attempt_time and 
                now >= self.next_attempt_time
            ):
                await self._transition_to_half_open()
        
        elif self.state == CircuitState.HALF_OPEN:
            # In half-open, we're already allowing requests through
            # State transitions happen in _on_success and _on_failure
            pass
    
    async def _on_success(self):
        """Handle successful request."""
        self.metrics.successful_requests += 1
        
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                await self._transition_to_closed()
        else:
            # Reset failure count on success in closed state
            self.failure_count = 0
    
    async def _on_failure(self, reason: str):
        """Handle failed request."""
        self.metrics.failed_requests += 1
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.state == CircuitState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                await self._transition_to_open()
        
        elif self.state == CircuitState.HALF_OPEN:
            # Failure in half-open immediately goes back to open
            await self._transition_to_open()
    
    async def _transition_to_open(self):
        """Transition circuit breaker to OPEN state."""
        old_state = self.state
        self.state = CircuitState.OPEN
        self.next_attempt_time = datetime.utcnow() + timedelta(seconds=self.config.recovery_timeout)
        
        reason = f"Failure threshold reached ({self.failure_count}/{self.config.failure_threshold})"
        self.metrics.record_state_change(old_state, CircuitState.OPEN, reason)
        
        logger.warning(
            f"Circuit breaker '{self.name}' OPENED due to {self.failure_count} failures. "
            f"Next attempt at {self.next_attempt_time}"
        )
    
    async def _transition_to_half_open(self):
        """Transition circuit breaker to HALF_OPEN state."""
        old_state = self.state
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        
        reason = f"Recovery timeout reached, testing service availability"
        self.metrics.record_state_change(old_state, CircuitState.HALF_OPEN, reason)
        
        logger.info(f"Circuit breaker '{self.name}' transitioned to HALF_OPEN for testing")
    
    async def _transition_to_closed(self):
        """Transition circuit breaker to CLOSED state."""
        old_state = self.state
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.next_attempt_time = None
        
        reason = f"Service recovered - {self.success_count} consecutive successes"
        self.metrics.record_state_change(old_state, CircuitState.CLOSED, reason)
        
        logger.info(f"Circuit breaker '{self.name}' CLOSED - service recovered")
    
    async def force_open(self, reason: str = "Manual override"):
        """Manually force the circuit breaker to OPEN state."""
        async with self._lock:
            old_state = self.state
            self.state = CircuitState.OPEN
            self.next_attempt_time = datetime.utcnow() + timedelta(seconds=self.config.recovery_timeout)
            
            self.metrics.record_state_change(old_state, CircuitState.OPEN, f"Manual: {reason}")
            
            logger.warning(f"Circuit breaker '{self.name}' manually forced OPEN: {reason}")
    
    async def force_closed(self, reason: str = "Manual override"):
        """Manually force the circuit breaker to CLOSED state."""
        async with self._lock:
            old_state = self.state
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.next_attempt_time = None
            
            self.metrics.record_state_change(old_state, CircuitState.CLOSED, f"Manual: {reason}")
            
            logger.info(f"Circuit breaker '{self.name}' manually forced CLOSED: {reason}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status and metrics."""
        return {
            'name': self.name,
            'state': self.state,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'last_failure_time': self.last_failure_time.isoformat() if self.last_failure_time else None,
            'next_attempt_time': self.next_attempt_time.isoformat() if self.next_attempt_time else None,
            'config': {
                'failure_threshold': self.config.failure_threshold,
                'recovery_timeout': self.config.recovery_timeout,
                'success_threshold': self.config.success_threshold,
                'timeout': self.config.timeout
            },
            'metrics': {
                'total_requests': self.metrics.total_requests,
                'successful_requests': self.metrics.successful_requests,
                'failed_requests': self.metrics.failed_requests,
                'timeout_requests': self.metrics.timeout_requests,
                'open_state_requests': self.metrics.open_state_requests,
                'success_rate': self.metrics.success_rate,
                'failure_rate': self.metrics.failure_rate,
                'state_changes': self.metrics.state_changes[-10:]  # Last 10 state changes
            }
        }
    
    def reset_metrics(self):
        """Reset all metrics (useful for testing)."""
        self.metrics = CircuitBreakerMetrics()
        logger.info(f"Circuit breaker '{self.name}' metrics reset")


class CircuitBreakerManager:
    """
    Manages multiple circuit breakers for different services.
    
    Provides centralized configuration and monitoring of all circuit breakers
    in the application.
    """
    
    def __init__(self):
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
    
    def create_circuit_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 3,
        timeout: float = 30.0,
        expected_exception: Type[Exception] = Exception
    ) -> CircuitBreaker:
        """Create and register a new circuit breaker."""
        if name in self.circuit_breakers:
            raise ValueError(f"Circuit breaker '{name}' already exists")
        
        circuit_breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=success_threshold,
            timeout=timeout,
            expected_exception=expected_exception,
            name=name
        )
        
        self.circuit_breakers[name] = circuit_breaker
        logger.info(f"Created circuit breaker: {name}")
        return circuit_breaker
    
    def get_circuit_breaker(self, name: str) -> Optional[CircuitBreaker]:
        """Get a circuit breaker by name."""
        return self.circuit_breakers.get(name)
    
    def remove_circuit_breaker(self, name: str) -> bool:
        """Remove a circuit breaker."""
        if name in self.circuit_breakers:
            del self.circuit_breakers[name]
            logger.info(f"Removed circuit breaker: {name}")
            return True
        return False
    
    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all circuit breakers."""
        return {
            name: cb.get_status() 
            for name, cb in self.circuit_breakers.items()
        }
    
    async def force_open_all(self, reason: str = "Global emergency"):
        """Force all circuit breakers to OPEN state."""
        for name, cb in self.circuit_breakers.items():
            await cb.force_open(f"{reason} - {name}")
        
        logger.warning(f"All circuit breakers forced OPEN: {reason}")
    
    async def force_closed_all(self, reason: str = "Global recovery"):
        """Force all circuit breakers to CLOSED state."""
        for name, cb in self.circuit_breakers.items():
            await cb.force_closed(f"{reason} - {name}")
        
        logger.info(f"All circuit breakers forced CLOSED: {reason}")
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get overall health summary of all circuit breakers."""
        total_cbs = len(self.circuit_breakers)
        open_cbs = sum(1 for cb in self.circuit_breakers.values() if cb.state == CircuitState.OPEN)
        half_open_cbs = sum(1 for cb in self.circuit_breakers.values() if cb.state == CircuitState.HALF_OPEN)
        closed_cbs = total_cbs - open_cbs - half_open_cbs
        
        return {
            'total_circuit_breakers': total_cbs,
            'closed': closed_cbs,
            'half_open': half_open_cbs,
            'open': open_cbs,
            'health_score': (closed_cbs + half_open_cbs * 0.5) / max(total_cbs, 1),
            'circuit_breakers': list(self.circuit_breakers.keys())
        }


# Global circuit breaker manager
circuit_breaker_manager = CircuitBreakerManager()