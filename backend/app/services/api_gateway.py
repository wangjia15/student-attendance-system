"""
API Gateway Service for routing external API requests with monitoring and resilience.

This service provides:
- Request routing to external SIS providers
- Load balancing and failover capabilities
- Request/response transformation
- Monitoring and metrics collection
- Integration with rate limiting and circuit breaker
"""
import asyncio
import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx
from pydantic import BaseModel

from app.core.circuit_breaker import CircuitBreaker
from app.middleware.rate_limiting import RateLimiter


logger = logging.getLogger(__name__)


class ProviderType(str, Enum):
    """Supported SIS provider types."""
    POWERSCHOOL = "powerschool"
    INFINITE_CAMPUS = "infinite_campus"
    SKYWARD = "skyward"
    CUSTOM = "custom"


class RequestMethod(str, Enum):
    """HTTP methods supported by gateway."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


@dataclass
class ProviderEndpoint:
    """Configuration for a provider endpoint."""
    provider: ProviderType
    base_url: str
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60
    rate_limit_requests: int = 100
    rate_limit_window: int = 60
    headers: Dict[str, str] = field(default_factory=dict)
    auth_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GatewayRequest:
    """Internal representation of a gateway request."""
    provider: ProviderType
    method: RequestMethod
    path: str
    params: Dict[str, Any] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[Any] = None
    timeout: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GatewayResponse:
    """Response from gateway including metrics."""
    status_code: int
    data: Any
    headers: Dict[str, str]
    duration: float
    provider: ProviderType
    success: bool
    error: Optional[str] = None
    retry_count: int = 0
    circuit_breaker_tripped: bool = False


class GatewayMetrics:
    """Metrics collector for gateway operations."""
    
    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.total_duration = 0.0
        self.provider_stats: Dict[ProviderType, Dict[str, Any]] = {}
        self.start_time = time.time()
    
    def record_request(self, provider: ProviderType, duration: float, success: bool):
        """Record metrics for a request."""
        self.request_count += 1
        self.total_duration += duration
        
        if not success:
            self.error_count += 1
        
        if provider not in self.provider_stats:
            self.provider_stats[provider] = {
                'requests': 0,
                'errors': 0,
                'total_duration': 0.0,
                'avg_duration': 0.0
            }
        
        stats = self.provider_stats[provider]
        stats['requests'] += 1
        stats['total_duration'] += duration
        stats['avg_duration'] = stats['total_duration'] / stats['requests']
        
        if not success:
            stats['errors'] += 1
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics summary."""
        uptime = time.time() - self.start_time
        return {
            'uptime': uptime,
            'request_count': self.request_count,
            'error_count': self.error_count,
            'error_rate': self.error_count / max(self.request_count, 1),
            'avg_duration': self.total_duration / max(self.request_count, 1),
            'requests_per_second': self.request_count / max(uptime, 1),
            'provider_stats': self.provider_stats
        }


class APIGatewayService:
    """
    API Gateway service for external SIS provider requests.
    
    Provides:
    - Request routing and load balancing
    - Rate limiting integration
    - Circuit breaker pattern
    - Request/response monitoring
    - Retry mechanisms with exponential backoff
    """
    
    def __init__(self):
        self.providers: Dict[ProviderType, List[ProviderEndpoint]] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.rate_limiters: Dict[ProviderType, RateLimiter] = {}
        self.metrics = GatewayMetrics()
        self.http_client: Optional[httpx.AsyncClient] = None
        self._setup_default_providers()
    
    def _setup_default_providers(self):
        """Setup default provider configurations."""
        # PowerSchool configuration
        powerschool_config = ProviderEndpoint(
            provider=ProviderType.POWERSCHOOL,
            base_url="https://api.powerschool.com",
            timeout=30.0,
            max_retries=3,
            rate_limit_requests=1000,  # PowerSchool allows 1000 requests/hour
            rate_limit_window=3600,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        )
        
        # Infinite Campus configuration
        infinite_campus_config = ProviderEndpoint(
            provider=ProviderType.INFINITE_CAMPUS,
            base_url="https://api.infinitecampus.com",
            timeout=45.0,
            max_retries=2,
            rate_limit_requests=500,  # More conservative rate limit
            rate_limit_window=3600,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        )
        
        # Skyward configuration
        skyward_config = ProviderEndpoint(
            provider=ProviderType.SKYWARD,
            base_url="https://api.skyward.com",
            timeout=30.0,
            max_retries=3,
            rate_limit_requests=2000,  # Higher rate limit
            rate_limit_window=3600,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        )
        
        self.providers[ProviderType.POWERSCHOOL] = [powerschool_config]
        self.providers[ProviderType.INFINITE_CAMPUS] = [infinite_campus_config]
        self.providers[ProviderType.SKYWARD] = [skyward_config]
        
        # Initialize circuit breakers and rate limiters
        for provider_type, endpoints in self.providers.items():
            for endpoint in endpoints:
                cb_key = f"{provider_type}_{endpoint.base_url}"
                self.circuit_breakers[cb_key] = CircuitBreaker(
                    failure_threshold=endpoint.circuit_breaker_threshold,
                    recovery_timeout=endpoint.circuit_breaker_timeout,
                    expected_exception=httpx.RequestError
                )
                
                self.rate_limiters[provider_type] = RateLimiter(
                    max_requests=endpoint.rate_limit_requests,
                    time_window=endpoint.rate_limit_window,
                    provider=provider_type.value
                )
    
    async def start(self):
        """Initialize the gateway service."""
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
        )
        logger.info("API Gateway service started")
    
    async def stop(self):
        """Cleanup gateway resources."""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("API Gateway service stopped")
    
    def add_provider(self, endpoint: ProviderEndpoint):
        """Add a new provider endpoint configuration."""
        if endpoint.provider not in self.providers:
            self.providers[endpoint.provider] = []
        
        self.providers[endpoint.provider].append(endpoint)
        
        # Initialize circuit breaker and rate limiter
        cb_key = f"{endpoint.provider}_{endpoint.base_url}"
        self.circuit_breakers[cb_key] = CircuitBreaker(
            failure_threshold=endpoint.circuit_breaker_threshold,
            recovery_timeout=endpoint.circuit_breaker_timeout,
            expected_exception=httpx.RequestError
        )
        
        self.rate_limiters[endpoint.provider] = RateLimiter(
            max_requests=endpoint.rate_limit_requests,
            time_window=endpoint.rate_limit_window,
            provider=endpoint.provider.value
        )
        
        logger.info(f"Added provider endpoint: {endpoint.provider} -> {endpoint.base_url}")
    
    def _select_endpoint(self, provider: ProviderType) -> Optional[ProviderEndpoint]:
        """Select the best available endpoint for a provider."""
        endpoints = self.providers.get(provider, [])
        if not endpoints:
            return None
        
        # Simple round-robin selection for now
        # TODO: Implement smart load balancing based on health and response times
        available_endpoints = []
        
        for endpoint in endpoints:
            cb_key = f"{provider}_{endpoint.base_url}"
            circuit_breaker = self.circuit_breakers.get(cb_key)
            
            if circuit_breaker and circuit_breaker.state == "open":
                continue
                
            available_endpoints.append(endpoint)
        
        return available_endpoints[0] if available_endpoints else None
    
    async def make_request(self, request: GatewayRequest) -> GatewayResponse:
        """
        Make a request through the gateway.
        
        Applies rate limiting, circuit breaking, and retry logic.
        """
        start_time = time.time()
        
        # Check rate limiting
        rate_limiter = self.rate_limiters.get(request.provider)
        if rate_limiter and not await rate_limiter.acquire():
            return GatewayResponse(
                status_code=429,
                data={"error": "Rate limit exceeded"},
                headers={},
                duration=time.time() - start_time,
                provider=request.provider,
                success=False,
                error="Rate limit exceeded"
            )
        
        endpoint = self._select_endpoint(request.provider)
        if not endpoint:
            return GatewayResponse(
                status_code=503,
                data={"error": "No available endpoints"},
                headers={},
                duration=time.time() - start_time,
                provider=request.provider,
                success=False,
                error="No available endpoints"
            )
        
        cb_key = f"{request.provider}_{endpoint.base_url}"
        circuit_breaker = self.circuit_breakers.get(cb_key)
        
        retry_count = 0
        last_error = None
        
        for attempt in range(endpoint.max_retries + 1):
            try:
                if circuit_breaker:
                    response = await circuit_breaker.call(
                        self._execute_request, endpoint, request
                    )
                else:
                    response = await self._execute_request(endpoint, request)
                
                duration = time.time() - start_time
                self.metrics.record_request(request.provider, duration, True)
                
                return GatewayResponse(
                    status_code=response.status_code,
                    data=response.json() if response.content else None,
                    headers=dict(response.headers),
                    duration=duration,
                    provider=request.provider,
                    success=response.is_success,
                    retry_count=retry_count
                )
                
            except Exception as e:
                last_error = str(e)
                retry_count += 1
                
                if attempt < endpoint.max_retries:
                    delay = endpoint.retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{endpoint.max_retries + 1}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    break
        
        # All retries failed
        duration = time.time() - start_time
        self.metrics.record_request(request.provider, duration, False)
        
        circuit_breaker_tripped = (
            circuit_breaker and circuit_breaker.state == "open"
        ) if circuit_breaker else False
        
        return GatewayResponse(
            status_code=503,
            data={"error": last_error or "Request failed"},
            headers={},
            duration=duration,
            provider=request.provider,
            success=False,
            error=last_error,
            retry_count=retry_count,
            circuit_breaker_tripped=circuit_breaker_tripped
        )
    
    async def _execute_request(self, endpoint: ProviderEndpoint, request: GatewayRequest) -> httpx.Response:
        """Execute the actual HTTP request."""
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")
        
        url = f"{endpoint.base_url.rstrip('/')}/{request.path.lstrip('/')}"
        timeout = request.timeout or endpoint.timeout
        
        # Merge headers
        headers = {**endpoint.headers, **request.headers}
        
        # Add authentication if configured
        if endpoint.auth_config:
            headers.update(self._build_auth_headers(endpoint.auth_config))
        
        response = await self.http_client.request(
            method=request.method.value,
            url=url,
            params=request.params,
            headers=headers,
            json=request.body if request.body else None,
            timeout=timeout
        )
        
        return response
    
    def _build_auth_headers(self, auth_config: Dict[str, Any]) -> Dict[str, str]:
        """Build authentication headers from configuration."""
        headers = {}
        
        auth_type = auth_config.get("type", "").lower()
        
        if auth_type == "bearer":
            token = auth_config.get("token")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            key_name = auth_config.get("key_name", "X-API-Key")
            api_key = auth_config.get("api_key")
            if api_key:
                headers[key_name] = api_key
        elif auth_type == "basic":
            import base64
            username = auth_config.get("username", "")
            password = auth_config.get("password", "")
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
        
        return headers
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get gateway health status and metrics."""
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": self.metrics.get_metrics(),
            "providers": {},
            "circuit_breakers": {}
        }
        
        # Provider status
        for provider_type, endpoints in self.providers.items():
            health_status["providers"][provider_type] = {
                "endpoint_count": len(endpoints),
                "endpoints": [
                    {
                        "base_url": ep.base_url,
                        "timeout": ep.timeout,
                        "max_retries": ep.max_retries
                    }
                    for ep in endpoints
                ]
            }
        
        # Circuit breaker status
        for cb_key, cb in self.circuit_breakers.items():
            health_status["circuit_breakers"][cb_key] = {
                "state": cb.state,
                "failure_count": cb.failure_count,
                "last_failure_time": cb.last_failure_time.isoformat() if cb.last_failure_time else None
            }
        
        return health_status
    
    async def test_provider_connection(self, provider: ProviderType) -> Dict[str, Any]:
        """Test connection to a specific provider."""
        endpoint = self._select_endpoint(provider)
        if not endpoint:
            return {
                "provider": provider,
                "status": "error",
                "message": "No available endpoints"
            }
        
        try:
            test_request = GatewayRequest(
                provider=provider,
                method=RequestMethod.GET,
                path="/health",  # Assume health check endpoint
                timeout=10.0
            )
            
            response = await self.make_request(test_request)
            
            return {
                "provider": provider,
                "status": "healthy" if response.success else "unhealthy",
                "response_time": response.duration,
                "status_code": response.status_code,
                "circuit_breaker_tripped": response.circuit_breaker_tripped
            }
            
        except Exception as e:
            return {
                "provider": provider,
                "status": "error",
                "message": str(e)
            }


# Global gateway instance
gateway_service = APIGatewayService()