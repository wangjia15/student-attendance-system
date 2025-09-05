"""
API Gateway Coordinator Service.

This service coordinates all gateway components to provide a unified
API gateway interface with comprehensive SIS integration capabilities.
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from app.services.api_gateway import (
    APIGatewayService, GatewayRequest, GatewayResponse, 
    ProviderType, RequestMethod, gateway_service
)
from app.gateway.router import GatewayRouter
from app.gateway.request_queue import RequestQueue, RequestPriority
from app.gateway.throttler import RequestThrottler, ThrottleManager, throttle_manager
from app.gateway.api_key_manager import APIKeyManager, api_key_manager
from app.middleware.rate_limiting import RateLimitMiddleware, rate_limit_middleware
from app.core.circuit_breaker import CircuitBreakerManager, circuit_breaker_manager


logger = logging.getLogger(__name__)


class GatewayStatus(str, Enum):
    """Gateway operational status."""
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    SHUTDOWN = "shutdown"


@dataclass
class GatewayMetrics:
    """Consolidated gateway metrics."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_response_time: float = 0.0
    requests_per_second: float = 0.0
    active_connections: int = 0
    queue_size: int = 0
    circuit_breakers_open: int = 0
    rate_limited_requests: int = 0


class GatewayCoordinator:
    """
    Unified API Gateway Coordinator.
    
    Coordinates all gateway components to provide comprehensive
    SIS integration capabilities with resilience and monitoring.
    
    Features:
    - Unified request processing pipeline
    - Component health monitoring
    - Automatic failover and recovery
    - Comprehensive metrics collection
    - Administrative control interface
    """
    
    def __init__(self):
        # Core components
        self.gateway_service = gateway_service
        self.router: Optional[GatewayRouter] = None
        self.request_queue: Optional[RequestQueue] = None
        self.throttle_manager = throttle_manager
        self.api_key_manager = api_key_manager
        self.rate_limit_middleware = rate_limit_middleware
        self.circuit_breaker_manager = circuit_breaker_manager
        
        # Coordinator state
        self.status = GatewayStatus.SHUTDOWN
        self.start_time: Optional[datetime] = None
        self.metrics = GatewayMetrics()
        
        # Background tasks
        self._monitoring_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        self._stop_background_tasks = False
        
        logger.info("API Gateway Coordinator initialized")
    
    async def start(self):
        """Start all gateway components."""
        try:
            self.status = GatewayStatus.STARTING
            self.start_time = datetime.utcnow()
            
            logger.info("Starting API Gateway components...")
            
            # Start core gateway service
            await self.gateway_service.start()
            
            # Initialize and start router
            self.router = GatewayRouter(self.gateway_service)
            await self.router.start()
            
            # Initialize and start request queue
            self.request_queue = RequestQueue(
                max_size=10000,
                processor_count=20,
                processor_callable=self._process_queued_request
            )
            await self.request_queue.start()
            
            # Setup throttling for providers
            self.throttle_manager.setup_provider_throttlers()
            
            # Setup rate limiting for providers
            from app.middleware.rate_limiting import PROVIDER_RATE_LIMITS
            await self.rate_limit_middleware.setup_provider_limiters(PROVIDER_RATE_LIMITS)
            
            # Start API key manager
            await self.api_key_manager.start()
            
            # Start background monitoring
            self._stop_background_tasks = False
            self._monitoring_task = asyncio.create_task(self._health_monitor())
            self._metrics_task = asyncio.create_task(self._metrics_collector())
            
            self.status = GatewayStatus.HEALTHY
            logger.info("API Gateway Coordinator started successfully")
            
        except Exception as e:
            self.status = GatewayStatus.UNHEALTHY
            logger.error(f"Failed to start API Gateway Coordinator: {e}")
            raise
    
    async def stop(self):
        """Stop all gateway components."""
        try:
            logger.info("Stopping API Gateway Coordinator...")
            self.status = GatewayStatus.SHUTDOWN
            
            # Stop background tasks
            self._stop_background_tasks = True
            
            if self._monitoring_task:
                self._monitoring_task.cancel()
            if self._metrics_task:
                self._metrics_task.cancel()
            
            # Stop components in reverse order
            if self.api_key_manager:
                await self.api_key_manager.stop()
            
            if self.rate_limit_middleware:
                await self.rate_limit_middleware.cleanup()
            
            if self.request_queue:
                await self.request_queue.stop()
            
            if self.router:
                await self.router.stop()
            
            await self.gateway_service.stop()
            
            logger.info("API Gateway Coordinator stopped")
            
        except Exception as e:
            logger.error(f"Error stopping API Gateway Coordinator: {e}")
    
    async def process_request(
        self,
        provider: ProviderType,
        method: RequestMethod,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[Any] = None,
        priority: RequestPriority = RequestPriority.NORMAL,
        timeout: float = 30.0
    ) -> GatewayResponse:
        """
        Process a request through the complete gateway pipeline.
        
        This is the main entry point for external API requests.
        """
        if self.status != GatewayStatus.HEALTHY:
            return GatewayResponse(
                status_code=503,
                data={"error": f"Gateway unavailable: {self.status}"},
                headers={},
                duration=0.0,
                provider=provider,
                success=False,
                error=f"Gateway status: {self.status}"
            )
        
        # Create gateway request
        request = GatewayRequest(
            provider=provider,
            method=method,
            path=path,
            params=params or {},
            headers=headers or {},
            body=body,
            timeout=timeout,
            metadata={
                'request_id': f"req_{int(asyncio.get_event_loop().time() * 1000000)}",
                'priority': priority.value,
                'submitted_at': datetime.utcnow().isoformat()
            }
        )
        
        try:
            # Process through request queue for proper throttling and ordering
            if self.request_queue:
                response = await self.request_queue.enqueue_and_wait(
                    request=request,
                    priority=priority,
                    timeout=timeout
                )
            else:
                # Direct processing if queue not available
                response = await self._process_request_direct(request)
            
            # Update metrics
            self._update_metrics(response)
            
            return response
            
        except Exception as e:
            logger.error(f"Error processing request: {e}")
            error_response = GatewayResponse(
                status_code=500,
                data={"error": str(e)},
                headers={},
                duration=0.0,
                provider=provider,
                success=False,
                error=str(e)
            )
            self._update_metrics(error_response)
            return error_response
    
    async def _process_queued_request(self, request: GatewayRequest) -> GatewayResponse:
        """Process a request from the queue."""
        return await self._process_request_direct(request)
    
    async def _process_request_direct(self, request: GatewayRequest) -> GatewayResponse:
        """Process request through the gateway pipeline."""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Step 1: Throttling check
            throttler = self.throttle_manager.get_throttler(request.provider.value)
            if throttler:
                proceed = await throttler.wait_if_throttled(request)
                if not proceed:
                    return GatewayResponse(
                        status_code=429,
                        data={"error": "Request throttled"},
                        headers={"Retry-After": "60"},
                        duration=asyncio.get_event_loop().time() - start_time,
                        provider=request.provider,
                        success=False,
                        error="Throttled"
                    )
            
            # Step 2: Rate limiting check
            rate_limiter = await self.rate_limit_middleware.get_rate_limiter(request.provider.value)
            if rate_limiter:
                allowed = await rate_limiter.acquire(
                    request_id=request.metadata.get('request_id'),
                    timeout=request.timeout or 30.0
                )
                if not allowed:
                    return GatewayResponse(
                        status_code=429,
                        data={"error": "Rate limit exceeded"},
                        headers={"Retry-After": "60"},
                        duration=asyncio.get_event_loop().time() - start_time,
                        provider=request.provider,
                        success=False,
                        error="Rate limited"
                    )
            
            # Step 3: API key injection
            await self._inject_api_key(request)
            
            # Step 4: Route through gateway
            if self.router:
                response = await self.router.route_request(request)
            else:
                response = await self.gateway_service.make_request(request)
            
            # Step 5: Record response for adaptive systems
            if throttler:
                await throttler.record_response(
                    request.metadata.get('request_id', ''),
                    response.success,
                    response.duration
                )
            
            return response
            
        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            logger.error(f"Error in request pipeline: {e}")
            return GatewayResponse(
                status_code=500,
                data={"error": str(e)},
                headers={},
                duration=duration,
                provider=request.provider,
                success=False,
                error=str(e)
            )
    
    async def _inject_api_key(self, request: GatewayRequest):
        """Inject appropriate API key into request headers."""
        try:
            api_key = await self.api_key_manager.get_active_key(request.provider.value)
            if api_key:
                # Different providers use different authentication headers
                if request.provider == ProviderType.POWERSCHOOL:
                    request.headers["Authorization"] = f"Bearer {api_key.key_value}"
                elif request.provider == ProviderType.INFINITE_CAMPUS:
                    request.headers["X-API-Key"] = api_key.key_value
                elif request.provider == ProviderType.SKYWARD:
                    request.headers["Authorization"] = f"ApiKey {api_key.key_value}"
                else:
                    request.headers["X-API-Key"] = api_key.key_value
                
                logger.debug(f"Injected API key for {request.provider}")
            else:
                logger.warning(f"No active API key found for {request.provider}")
        
        except Exception as e:
            logger.error(f"Error injecting API key: {e}")
    
    def _update_metrics(self, response: GatewayResponse):
        """Update gateway metrics."""
        self.metrics.total_requests += 1
        
        if response.success:
            self.metrics.successful_requests += 1
        else:
            self.metrics.failed_requests += 1
            
            if response.status_code == 429:
                self.metrics.rate_limited_requests += 1
        
        # Update rolling averages
        if self.metrics.total_requests == 1:
            self.metrics.average_response_time = response.duration
        else:
            self.metrics.average_response_time = (
                (self.metrics.average_response_time * (self.metrics.total_requests - 1) + response.duration) /
                self.metrics.total_requests
            )
    
    async def _health_monitor(self):
        """Background task to monitor component health."""
        while not self._stop_background_tasks:
            try:
                # Check component health
                unhealthy_components = []
                
                # Check circuit breakers
                cb_health = self.circuit_breaker_manager.get_health_summary()
                if cb_health['open'] > 0:
                    unhealthy_components.append(f"Circuit breakers open: {cb_health['open']}")
                
                # Check request queue
                if self.request_queue:
                    queue_status = self.request_queue.get_queue_status()
                    if queue_status['queue_sizes']['priority_queue'] > 1000:
                        unhealthy_components.append("Request queue backing up")
                
                # Update gateway status
                if unhealthy_components:
                    if self.status == GatewayStatus.HEALTHY:
                        self.status = GatewayStatus.DEGRADED
                        logger.warning(f"Gateway degraded: {'; '.join(unhealthy_components)}")
                else:
                    if self.status == GatewayStatus.DEGRADED:
                        self.status = GatewayStatus.HEALTHY
                        logger.info("Gateway health restored")
                
                await asyncio.sleep(30)  # Health check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in health monitor: {e}")
                await asyncio.sleep(10)
    
    async def _metrics_collector(self):
        """Background task to collect and update metrics."""
        while not self._stop_background_tasks:
            try:
                # Update derived metrics
                if self.start_time:
                    uptime = (datetime.utcnow() - self.start_time).total_seconds()
                    if uptime > 0:
                        self.metrics.requests_per_second = self.metrics.total_requests / uptime
                
                # Update queue size
                if self.request_queue:
                    queue_status = self.request_queue.get_queue_status()
                    self.metrics.queue_size = queue_status['active_requests']
                
                # Update circuit breaker count
                cb_status = self.circuit_breaker_manager.get_all_status()
                self.metrics.circuit_breakers_open = sum(
                    1 for cb in cb_status.values() 
                    if cb.get('state') == 'open'
                )
                
                await asyncio.sleep(10)  # Collect metrics every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in metrics collector: {e}")
                await asyncio.sleep(10)
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get comprehensive health status."""
        uptime = None
        if self.start_time:
            uptime = (datetime.utcnow() - self.start_time).total_seconds()
        
        return {
            'gateway_status': self.status.value,
            'uptime_seconds': uptime,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'metrics': {
                'total_requests': self.metrics.total_requests,
                'successful_requests': self.metrics.successful_requests,
                'failed_requests': self.metrics.failed_requests,
                'success_rate': (
                    self.metrics.successful_requests / max(self.metrics.total_requests, 1)
                ),
                'average_response_time': self.metrics.average_response_time,
                'requests_per_second': self.metrics.requests_per_second,
                'active_connections': self.metrics.active_connections,
                'queue_size': self.metrics.queue_size,
                'circuit_breakers_open': self.metrics.circuit_breakers_open,
                'rate_limited_requests': self.metrics.rate_limited_requests
            },
            'components': {
                'gateway_service': 'healthy',
                'router': 'healthy' if self.router else 'not_initialized',
                'request_queue': 'healthy' if self.request_queue else 'not_initialized',
                'throttle_manager': 'healthy',
                'api_key_manager': 'healthy',
                'rate_limit_middleware': 'healthy',
                'circuit_breaker_manager': 'healthy'
            }
        }
    
    def get_detailed_status(self) -> Dict[str, Any]:
        """Get detailed status of all components."""
        status = {
            'gateway': self.get_health_status(),
            'api_gateway_service': self.gateway_service.get_health_status(),
            'circuit_breakers': self.circuit_breaker_manager.get_all_status(),
            'throttlers': self.throttle_manager.get_all_status(),
            'rate_limiters': self.rate_limit_middleware.get_all_status(),
        }
        
        if self.router:
            status['router'] = self.router.get_routing_status()
        
        if self.request_queue:
            status['request_queue'] = self.request_queue.get_queue_status()
        
        return status
    
    async def admin_command(self, command: str, **kwargs) -> Dict[str, Any]:
        """Execute administrative commands."""
        try:
            if command == "health_check":
                return self.get_health_status()
            
            elif command == "detailed_status":
                return self.get_detailed_status()
            
            elif command == "reset_metrics":
                self.metrics = GatewayMetrics()
                return {"status": "metrics_reset"}
            
            elif command == "force_circuit_breaker_open":
                provider = kwargs.get("provider")
                if provider:
                    cb = self.circuit_breaker_manager.get_circuit_breaker(f"{provider}_circuit_breaker")
                    if cb:
                        await cb.force_open("Admin command")
                        return {"status": f"circuit_breaker_opened_{provider}"}
                return {"error": "provider_not_specified"}
            
            elif command == "force_circuit_breaker_closed":
                provider = kwargs.get("provider")
                if provider:
                    cb = self.circuit_breaker_manager.get_circuit_breaker(f"{provider}_circuit_breaker")
                    if cb:
                        await cb.force_closed("Admin command")
                        return {"status": f"circuit_breaker_closed_{provider}"}
                return {"error": "provider_not_specified"}
            
            elif command == "clear_request_queue":
                if self.request_queue:
                    await self.request_queue.stop()
                    self.request_queue = RequestQueue(
                        max_size=10000,
                        processor_count=20,
                        processor_callable=self._process_queued_request
                    )
                    await self.request_queue.start()
                    return {"status": "request_queue_cleared"}
                return {"error": "request_queue_not_available"}
            
            else:
                return {"error": f"unknown_command_{command}"}
                
        except Exception as e:
            logger.error(f"Error executing admin command {command}: {e}")
            return {"error": str(e)}


# Global gateway coordinator instance
gateway_coordinator = GatewayCoordinator()