"""
FastAPI Middleware for API Gateway Integration.

This middleware intercepts API requests destined for external SIS providers
and routes them through the API Gateway for proper rate limiting, throttling,
and resilience handling.
"""
import asyncio
import json
import logging
from typing import Callable, Dict, Any, Optional, Tuple
from datetime import datetime

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.gateway.coordinator import GatewayCoordinator, gateway_coordinator
from app.services.api_gateway import ProviderType, RequestMethod, GatewayRequest
from app.gateway.request_queue import RequestPriority


logger = logging.getLogger(__name__)


class GatewayMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for API Gateway integration.
    
    Routes external API requests through the gateway infrastructure
    to provide rate limiting, throttling, circuit breaker protection,
    and comprehensive monitoring for SIS provider communications.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        coordinator: Optional[GatewayCoordinator] = None,
        enabled: bool = True
    ):
        super().__init__(app)
        self.coordinator = coordinator or gateway_coordinator
        self.enabled = enabled
        
        # Path patterns that should be routed through gateway
        self.gateway_patterns = [
            "/api/v1/sis/",
            "/api/v1/external/",
            "/api/v1/sync/",
            "/integrations/"
        ]
        
        # Provider path mappings
        self.provider_mappings = {
            "/api/v1/sis/powerschool/": ProviderType.POWERSCHOOL,
            "/api/v1/sis/infinite-campus/": ProviderType.INFINITE_CAMPUS,
            "/api/v1/sis/skyward/": ProviderType.SKYWARD,
            "/integrations/powerschool/": ProviderType.POWERSCHOOL,
            "/integrations/infinite-campus/": ProviderType.INFINITE_CAMPUS,
            "/integrations/skyward/": ProviderType.SKYWARD,
        }
        
        logger.info(f"Gateway middleware initialized (enabled={enabled})")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through middleware."""
        if not self.enabled:
            return await call_next(request)
        
        # Check if this request should go through the gateway
        should_gateway, provider, priority = self._should_route_through_gateway(request)
        
        if should_gateway and provider:
            return await self._process_through_gateway(request, provider, priority)
        
        # Normal FastAPI processing
        return await call_next(request)
    
    def _should_route_through_gateway(
        self, 
        request: Request
    ) -> Tuple[bool, Optional[ProviderType], RequestPriority]:
        """Determine if request should be routed through gateway."""
        path = str(request.url.path)
        
        # Check if path matches gateway patterns
        for pattern in self.gateway_patterns:
            if pattern in path:
                # Determine provider and priority
                provider = self._determine_provider(path)
                priority = self._determine_priority(request, path)
                
                if provider:
                    return True, provider, priority
                
                # Generic external API handling
                return True, ProviderType.CUSTOM, priority
        
        return False, None, RequestPriority.NORMAL
    
    def _determine_provider(self, path: str) -> Optional[ProviderType]:
        """Determine SIS provider from request path."""
        for path_prefix, provider in self.provider_mappings.items():
            if path.startswith(path_prefix):
                return provider
        
        return None
    
    def _determine_priority(self, request: Request, path: str) -> RequestPriority:
        """Determine request priority based on headers and path."""
        # Check for priority header
        priority_header = request.headers.get("X-Request-Priority", "").lower()
        if priority_header == "urgent":
            return RequestPriority.URGENT
        elif priority_header == "high":
            return RequestPriority.HIGH
        elif priority_header == "low":
            return RequestPriority.LOW
        
        # Path-based priority
        if "/health" in path or "/status" in path:
            return RequestPriority.HIGH
        elif "/bulk/" in path or "/import/" in path:
            return RequestPriority.LOW
        elif "/real-time/" in path or "/sync/" in path:
            return RequestPriority.HIGH
        
        return RequestPriority.NORMAL
    
    async def _process_through_gateway(
        self,
        request: Request,
        provider: ProviderType,
        priority: RequestPriority
    ) -> Response:
        """Process request through the API Gateway."""
        start_time = datetime.utcnow()
        
        try:
            # Extract request details
            method = RequestMethod(request.method)
            path = self._extract_api_path(str(request.url.path))
            params = dict(request.query_params)
            headers = self._extract_headers(request)
            
            # Extract body for POST/PUT requests
            body = None
            if method in (RequestMethod.POST, RequestMethod.PUT, RequestMethod.PATCH):
                body = await self._extract_body(request)
            
            # Determine timeout
            timeout = self._extract_timeout(request)
            
            # Process through gateway
            logger.info(f"Processing {method} {path} for {provider} through gateway")
            
            gateway_response = await self.coordinator.process_request(
                provider=provider,
                method=method,
                path=path,
                params=params,
                headers=headers,
                body=body,
                priority=priority,
                timeout=timeout
            )
            
            # Convert gateway response to FastAPI response
            return await self._convert_gateway_response(gateway_response, start_time)
            
        except Exception as e:
            logger.error(f"Error processing request through gateway: {e}")
            return await self._create_error_response(
                error=str(e),
                status_code=500,
                start_time=start_time
            )
    
    def _extract_api_path(self, full_path: str) -> str:
        """Extract the API path that should be sent to external provider."""
        # Remove our internal path prefixes to get the actual API path
        for pattern in self.provider_mappings.keys():
            if full_path.startswith(pattern):
                return full_path[len(pattern):].lstrip('/')
        
        # Fallback: use path as-is
        return full_path.lstrip('/')
    
    def _extract_headers(self, request: Request) -> Dict[str, str]:
        """Extract and filter headers for external API."""
        # Headers to exclude from external requests
        exclude_headers = {
            'host', 'content-length', 'transfer-encoding', 'connection',
            'x-request-priority', 'x-forwarded-for', 'x-real-ip'
        }
        
        filtered_headers = {}
        for name, value in request.headers.items():
            if name.lower() not in exclude_headers:
                filtered_headers[name] = value
        
        return filtered_headers
    
    async def _extract_body(self, request: Request) -> Optional[Any]:
        """Extract request body."""
        try:
            content_type = request.headers.get('content-type', '').lower()
            
            if 'application/json' in content_type:
                body_bytes = await request.body()
                if body_bytes:
                    return json.loads(body_bytes.decode())
            elif 'application/x-www-form-urlencoded' in content_type:
                form_data = await request.form()
                return dict(form_data)
            else:
                # Return raw bytes for other content types
                return await request.body()
                
        except Exception as e:
            logger.warning(f"Could not extract request body: {e}")
            return None
    
    def _extract_timeout(self, request: Request) -> float:
        """Extract timeout from request headers."""
        timeout_header = request.headers.get("X-Request-Timeout")
        if timeout_header:
            try:
                timeout = float(timeout_header)
                # Clamp timeout between 5 and 300 seconds
                return max(5.0, min(300.0, timeout))
            except (ValueError, TypeError):
                pass
        
        # Default timeout based on request type
        if request.method == "GET":
            return 30.0
        else:
            return 60.0  # POST/PUT operations may take longer
    
    async def _convert_gateway_response(
        self,
        gateway_response,
        start_time: datetime
    ) -> Response:
        """Convert gateway response to FastAPI response."""
        # Calculate processing time
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Prepare response headers
        response_headers = dict(gateway_response.headers)
        response_headers.update({
            'X-Gateway-Status': 'success' if gateway_response.success else 'failed',
            'X-Gateway-Duration': str(gateway_response.duration),
            'X-Gateway-Processing-Time': str(processing_time),
            'X-Gateway-Provider': gateway_response.provider.value,
            'X-Gateway-Retry-Count': str(gateway_response.retry_count)
        })
        
        if gateway_response.circuit_breaker_tripped:
            response_headers['X-Gateway-Circuit-Breaker'] = 'tripped'
        
        # Handle different response types
        if isinstance(gateway_response.data, dict):
            return JSONResponse(
                content=gateway_response.data,
                status_code=gateway_response.status_code,
                headers=response_headers
            )
        elif gateway_response.data is not None:
            # Try to serialize as JSON
            try:
                return JSONResponse(
                    content=gateway_response.data,
                    status_code=gateway_response.status_code,
                    headers=response_headers
                )
            except (TypeError, ValueError):
                # Return as plain text if not serializable
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse(
                    content=str(gateway_response.data),
                    status_code=gateway_response.status_code,
                    headers=response_headers
                )
        else:
            # Empty response
            return Response(
                status_code=gateway_response.status_code,
                headers=response_headers
            )
    
    async def _create_error_response(
        self,
        error: str,
        status_code: int,
        start_time: datetime
    ) -> JSONResponse:
        """Create error response."""
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        
        return JSONResponse(
            content={
                "error": error,
                "gateway_error": True,
                "timestamp": start_time.isoformat()
            },
            status_code=status_code,
            headers={
                'X-Gateway-Status': 'error',
                'X-Gateway-Processing-Time': str(processing_time)
            }
        )


class GatewayHealthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to provide gateway health endpoints.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        coordinator: Optional[GatewayCoordinator] = None,
        health_path: str = "/gateway/health",
        admin_path: str = "/gateway/admin"
    ):
        super().__init__(app)
        self.coordinator = coordinator or gateway_coordinator
        self.health_path = health_path
        self.admin_path = admin_path
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through middleware."""
        path = str(request.url.path)
        
        if path == self.health_path:
            return await self._handle_health_request()
        elif path.startswith(self.admin_path):
            return await self._handle_admin_request(request)
        
        return await call_next(request)
    
    async def _handle_health_request(self) -> JSONResponse:
        """Handle health check request."""
        try:
            health_status = self.coordinator.get_health_status()
            status_code = 200 if health_status['gateway_status'] in ['healthy', 'degraded'] else 503
            
            return JSONResponse(
                content=health_status,
                status_code=status_code
            )
        except Exception as e:
            return JSONResponse(
                content={"error": str(e), "gateway_status": "error"},
                status_code=500
            )
    
    async def _handle_admin_request(self, request: Request) -> JSONResponse:
        """Handle administrative request."""
        try:
            path_parts = str(request.url.path).split('/')
            
            if len(path_parts) >= 4 and path_parts[3] == "status":
                # /gateway/admin/status
                detailed_status = self.coordinator.get_detailed_status()
                return JSONResponse(content=detailed_status)
            
            elif len(path_parts) >= 4 and path_parts[3] == "command":
                # /gateway/admin/command/{command_name}
                if len(path_parts) >= 5:
                    command = path_parts[4]
                    
                    # Extract command parameters from query params
                    params = dict(request.query_params)
                    
                    result = await self.coordinator.admin_command(command, **params)
                    return JSONResponse(content=result)
                else:
                    return JSONResponse(
                        content={"error": "command_name_required"},
                        status_code=400
                    )
            
            else:
                return JSONResponse(
                    content={
                        "available_endpoints": [
                            f"{self.admin_path}/status",
                            f"{self.admin_path}/command/{{command_name}}"
                        ]
                    }
                )
                
        except Exception as e:
            return JSONResponse(
                content={"error": str(e)},
                status_code=500
            )


def setup_gateway_middleware(app, enable_gateway: bool = True) -> None:
    """
    Setup gateway middleware on FastAPI app.
    
    Args:
        app: FastAPI application instance
        enable_gateway: Whether to enable gateway processing
    """
    # Add health middleware first (higher priority)
    app.add_middleware(GatewayHealthMiddleware)
    
    # Add main gateway middleware
    app.add_middleware(GatewayMiddleware, enabled=enable_gateway)
    
    logger.info(f"Gateway middleware setup complete (enabled={enable_gateway})")