"""
Security Middleware

Comprehensive security middleware for request interception, validation,
and automated security controls integration.
"""

import asyncio
import time
import json
from datetime import datetime, timedelta
from typing import Dict, Set, Optional, Callable
from collections import defaultdict, deque
import logging
from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import ipaddress

from app.core.database import get_db
from app.models.user import User
from app.security.audit_logger import audit_logger
from app.security.monitoring import security_monitor
from app.security.incident_response import incident_response_system
from app.security.anomaly_detector import anomaly_detector
from app.security.access_control import rbac_manager, mfa_manager
from app.services.audit_service import security_audit_service


logger = logging.getLogger(__name__)


class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Comprehensive security middleware that provides:
    - Request rate limiting and DDoS protection
    - IP-based access control and blocking
    - Session security and validation
    - Real-time threat detection
    - Automated incident response
    - Security audit logging
    """
    
    def __init__(
        self,
        app: ASGIApp,
        enable_rate_limiting: bool = True,
        enable_ip_blocking: bool = True,
        enable_anomaly_detection: bool = True,
        enable_audit_logging: bool = True
    ):
        super().__init__(app)
        
        # Feature toggles
        self.enable_rate_limiting = enable_rate_limiting
        self.enable_ip_blocking = enable_ip_blocking
        self.enable_anomaly_detection = enable_anomaly_detection
        self.enable_audit_logging = enable_audit_logging
        
        # Rate limiting configuration
        self.rate_limits = {
            "default": {"requests": 100, "window": 60},  # 100 requests per minute
            "auth": {"requests": 5, "window": 60},       # 5 auth attempts per minute
            "api": {"requests": 1000, "window": 60},     # 1000 API calls per minute
            "admin": {"requests": 50, "window": 60}      # 50 admin requests per minute
        }
        
        # Rate limiting storage (in production, use Redis)
        self.rate_limit_storage: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
        
        # IP blocking
        self.blocked_ips: Set[str] = set()
        self.suspicious_ips: Dict[str, int] = defaultdict(int)
        self.ip_whitelist: Set[str] = {"127.0.0.1", "::1"}  # Localhost
        
        # Security headers
        self.security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' https:; "
                "connect-src 'self' ws: wss:; "
                "frame-ancestors 'none';"
            ),
            "Permissions-Policy": (
                "geolocation=(), "
                "microphone=(), "
                "camera=(), "
                "payment=(), "
                "usb=(), "
                "magnetometer=(), "
                "accelerometer=()"
            )
        }
        
        # Session security
        self.session_timeout = 3600  # 1 hour
        self.active_sessions: Dict[str, Dict] = {}
        
        # Threat detection patterns
        self.threat_patterns = {
            "sql_injection": [
                r"(\%27)|(\')|(\-\-)|(\%23)|(#)",
                r"((\%3D)|(=))[^\n]*((\%27)|(\')|(\-\-)|(\%3B)|(;))",
                r"\w*((\%27)|(\'))((\%6F)|o|(\%4F))((\%72)|r|(\%52))",
            ],
            "xss": [
                r"<[^>]*script[^>]*>",
                r"javascript:",
                r"on\w+\s*=",
                r"<[^>]*iframe[^>]*>",
            ],
            "path_traversal": [
                r"\.\.\/",
                r"\.\.\\",
                r"\%2e\%2e\%2f",
                r"\%2e\%2e\%5c",
            ],
            "command_injection": [
                r"[;&|`]",
                r"\$\(.*\)",
                r"curl\s",
                r"wget\s",
            ]
        }
        
        # Initialize components
        self._initialize_security_components()
    
    def _initialize_security_components(self):
        """Initialize security components."""
        # Load blocked IPs from incident response system
        if incident_response_system:
            self.blocked_ips = incident_response_system.blocked_ips.copy()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Main middleware dispatch method."""
        start_time = time.time()
        client_ip = self._get_client_ip(request)
        
        try:
            # Pre-request security checks
            await self._pre_request_security_checks(request, client_ip)
            
            # Process request
            response = await call_next(request)
            
            # Post-request security processing
            await self._post_request_security_processing(request, response, start_time, client_ip)
            
            # Add security headers
            self._add_security_headers(response)
            
            return response
            
        except HTTPException as e:
            # Log security-related HTTP exceptions
            if e.status_code in [401, 403, 429]:
                await self._log_security_exception(request, e, client_ip)
            raise
        
        except Exception as e:
            # Log and handle unexpected errors
            logger.error(f"Security middleware error: {e}")
            await self._log_system_error(request, str(e), client_ip)
            raise
    
    async def _pre_request_security_checks(self, request: Request, client_ip: str):
        """Perform security checks before processing request."""
        
        # IP-based access control
        if self.enable_ip_blocking:
            await self._check_ip_blocking(client_ip, request)
        
        # Rate limiting
        if self.enable_rate_limiting:
            await self._check_rate_limiting(client_ip, request)
        
        # Threat detection
        await self._check_threat_patterns(request)
        
        # Session security
        await self._check_session_security(request)
        
        # Request validation
        await self._validate_request_security(request)
    
    async def _post_request_security_processing(
        self,
        request: Request,
        response: Response,
        start_time: float,
        client_ip: str
    ):
        """Perform security processing after request completion."""
        
        # Calculate request duration
        duration = time.time() - start_time
        
        # Audit logging
        if self.enable_audit_logging:
            await self._audit_log_request(request, response, duration, client_ip)
        
        # Anomaly detection
        if self.enable_anomaly_detection:
            await self._check_request_anomalies(request, response, duration, client_ip)
        
        # Update security metrics
        await self._update_security_metrics(request, response, client_ip)
    
    async def _check_ip_blocking(self, client_ip: str, request: Request):
        """Check if IP address is blocked."""
        # Check global blocked IPs
        if client_ip in self.blocked_ips:
            logger.warning(f"Blocked IP attempted access: {client_ip}")
            await self._log_blocked_ip_attempt(client_ip, request)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        # Check incident response system blocks
        if incident_response_system.is_ip_blocked(client_ip):
            logger.warning(f"Incident response blocked IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied due to security incident"
            )
        
        # Check if IP is in whitelist (skip other checks)
        if client_ip in self.ip_whitelist:
            return
        
        # Check for private/internal IP ranges accessing external endpoints
        try:
            ip = ipaddress.ip_address(client_ip)
            if ip.is_private and str(request.url.path).startswith('/api/external'):
                logger.warning(f"Private IP accessing external endpoint: {client_ip}")
                self.suspicious_ips[client_ip] += 1
        except ValueError:
            pass  # Invalid IP format
    
    async def _check_rate_limiting(self, client_ip: str, request: Request):
        """Apply rate limiting based on IP and endpoint type."""
        # Determine rate limit category
        path = str(request.url.path)
        
        if path.startswith('/auth'):
            category = "auth"
        elif path.startswith('/api/admin'):
            category = "admin"
        elif path.startswith('/api'):
            category = "api"
        else:
            category = "default"
        
        # Get rate limit configuration
        rate_config = self.rate_limits[category]
        window_size = rate_config["window"]
        max_requests = rate_config["requests"]
        
        # Clean old entries and count current requests
        current_time = time.time()
        request_times = self.rate_limit_storage[client_ip][category]
        
        # Remove requests outside the window
        while request_times and request_times[0] < current_time - window_size:
            request_times.popleft()
        
        # Check if rate limit exceeded
        if len(request_times) >= max_requests:
            logger.warning(f"Rate limit exceeded for IP {client_ip} in category {category}")
            await self._log_rate_limit_exceeded(client_ip, request, category)
            
            # Increase suspicion score
            self.suspicious_ips[client_ip] += 1
            
            # If IP is very suspicious, consider blocking
            if self.suspicious_ips[client_ip] >= 10:
                await self._escalate_suspicious_ip(client_ip, request)
            
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for {category} requests",
                headers={"Retry-After": str(window_size)}
            )
        
        # Add current request timestamp
        request_times.append(current_time)
    
    async def _check_threat_patterns(self, request: Request):
        """Check request for known threat patterns."""
        # Get request data to analyze
        url_path = str(request.url.path)
        query_params = str(request.query_params)
        
        # Check headers for threats
        headers_str = json.dumps(dict(request.headers))
        
        # Analyze all components for threat patterns
        components = [url_path, query_params, headers_str]
        
        # If request has body, include it (carefully)
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                # Note: This is a simplified example
                # In production, you'd need to handle body reading more carefully
                pass
            except Exception:
                pass
        
        detected_threats = []
        
        # Check each component against threat patterns
        for component in components:
            for threat_type, patterns in self.threat_patterns.items():
                for pattern in patterns:
                    import re
                    if re.search(pattern, component, re.IGNORECASE):
                        detected_threats.append(threat_type)
                        logger.warning(f"Threat pattern detected: {threat_type} in request from {self._get_client_ip(request)}")
        
        # If threats detected, block request and log
        if detected_threats:
            client_ip = self._get_client_ip(request)
            await self._log_threat_detection(client_ip, request, detected_threats)
            
            # Increase suspicion and potentially block
            self.suspicious_ips[client_ip] += len(detected_threats) * 2
            
            if self.suspicious_ips[client_ip] >= 5:
                await self._escalate_suspicious_ip(client_ip, request)
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request contains potentially malicious content"
            )
    
    async def _check_session_security(self, request: Request):
        """Check session security and validity."""
        # Skip session checks for auth endpoints
        if str(request.url.path).startswith('/auth'):
            return
        
        # Check for session token in headers
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return  # No session to validate
        
        # Extract session information (this would integrate with your auth system)
        # For now, we'll do basic validation
        
        # Check for session hijacking indicators
        user_agent = request.headers.get("user-agent", "")
        client_ip = self._get_client_ip(request)
        
        # Look for suspicious session patterns
        session_key = f"{client_ip}:{user_agent[:50]}"  # Truncate user agent
        
        if session_key in self.active_sessions:
            session_info = self.active_sessions[session_key]
            
            # Check for session timeout
            if time.time() - session_info["last_seen"] > self.session_timeout:
                logger.info(f"Session timeout for {client_ip}")
                del self.active_sessions[session_key]
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session expired"
                )
            
            # Update last seen
            session_info["last_seen"] = time.time()
            session_info["request_count"] += 1
            
            # Check for suspicious session activity
            if session_info["request_count"] > 1000:  # Suspicious high activity
                logger.warning(f"Suspicious session activity from {client_ip}")
                await self._log_suspicious_session(client_ip, request, session_info)
        else:
            # New session
            self.active_sessions[session_key] = {
                "created": time.time(),
                "last_seen": time.time(),
                "request_count": 1,
                "ip": client_ip,
                "user_agent": user_agent
            }
    
    async def _validate_request_security(self, request: Request):
        """Perform additional request security validation."""
        # Check request size
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > 10 * 1024 * 1024:  # 10MB limit
                    logger.warning(f"Large request from {self._get_client_ip(request)}: {size} bytes")
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Request too large"
                    )
            except ValueError:
                pass
        
        # Check for suspicious headers
        suspicious_headers = ["x-forwarded-for", "x-real-ip", "x-originating-ip"]
        for header in suspicious_headers:
            if header in request.headers:
                value = request.headers[header]
                # Log potential header spoofing attempts
                if ";" in value or "," in value:
                    logger.warning(f"Suspicious header value from {self._get_client_ip(request)}: {header}={value}")
        
        # Check for required security headers in certain endpoints
        if str(request.url.path).startswith('/api/admin'):
            # Admin endpoints should have additional security
            if not request.headers.get("x-requested-with"):
                logger.info(f"Admin access without CSRF protection from {self._get_client_ip(request)}")
    
    async def _audit_log_request(
        self,
        request: Request,
        response: Response,
        duration: float,
        client_ip: str
    ):
        """Log request for security auditing."""
        try:
            # Skip logging for certain endpoints to reduce noise
            skip_paths = ['/health', '/metrics', '/favicon.ico']
            if any(str(request.url.path).endswith(path) for path in skip_paths):
                return
            
            # Determine if this is a security-relevant request
            security_relevant = (
                response.status_code in [401, 403, 404, 429, 500] or
                str(request.url.path).startswith(('/auth', '/api/admin', '/api/security'))
            )
            
            if not security_relevant:
                return
            
            # Log through audit service
            async with get_db() as db:
                # Determine event type based on response status
                if response.status_code == 401:
                    event_type = "UNAUTHORIZED_ACCESS_ATTEMPT"
                elif response.status_code == 403:
                    event_type = "FORBIDDEN_ACCESS_ATTEMPT"
                elif response.status_code == 429:
                    event_type = "RATE_LIMIT_EXCEEDED"
                elif response.status_code >= 500:
                    event_type = "SYSTEM_ERROR"
                else:
                    event_type = "REQUEST_PROCESSED"
                
                await security_audit_service.log_security_event(
                    db=db,
                    event_type=event_type,
                    event_category="SYSTEM",
                    message=f"HTTP {request.method} {request.url.path} -> {response.status_code}",
                    ip_address=client_ip,
                    user_agent=request.headers.get("user-agent"),
                    endpoint=str(request.url.path),
                    method=request.method,
                    event_data={
                        "status_code": response.status_code,
                        "duration_ms": int(duration * 1000),
                        "content_length": request.headers.get("content-length"),
                        "referer": request.headers.get("referer")
                    },
                    severity="MEDIUM" if response.status_code in [401, 403, 429] else "INFO"
                )
                
        except Exception as e:
            logger.error(f"Failed to audit log request: {e}")
    
    async def _check_request_anomalies(
        self,
        request: Request,
        response: Response,
        duration: float,
        client_ip: str
    ):
        """Check request for anomalous patterns."""
        try:
            # Skip anomaly detection for certain requests
            if response.status_code == 200 and duration < 0.1:
                return
            
            # Create a synthetic audit log entry for anomaly detection
            # In a real implementation, this would integrate with your audit system
            pass
            
        except Exception as e:
            logger.error(f"Error in anomaly detection: {e}")
    
    async def _update_security_metrics(
        self,
        request: Request,
        response: Response,
        client_ip: str
    ):
        """Update security metrics and statistics."""
        # This would update real-time security dashboards
        # Implementation depends on your monitoring system
        pass
    
    # Helper methods
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request."""
        # Check forwarded headers first
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
    
    def _add_security_headers(self, response: Response):
        """Add security headers to response."""
        for header, value in self.security_headers.items():
            response.headers[header] = value
    
    # Logging methods
    
    async def _log_blocked_ip_attempt(self, client_ip: str, request: Request):
        """Log blocked IP access attempt."""
        try:
            async with get_db() as db:
                await security_audit_service.log_security_event(
                    db=db,
                    event_type="BLOCKED_IP_ACCESS",
                    event_category="SECURITY",
                    message=f"Blocked IP {client_ip} attempted access to {request.url.path}",
                    ip_address=client_ip,
                    user_agent=request.headers.get("user-agent"),
                    endpoint=str(request.url.path),
                    method=request.method,
                    severity="HIGH",
                    risk_score=90
                )
        except Exception as e:
            logger.error(f"Failed to log blocked IP attempt: {e}")
    
    async def _log_rate_limit_exceeded(self, client_ip: str, request: Request, category: str):
        """Log rate limit exceeded event."""
        try:
            async with get_db() as db:
                await security_audit_service.log_security_event(
                    db=db,
                    event_type="RATE_LIMIT_EXCEEDED",
                    event_category="SECURITY",
                    message=f"Rate limit exceeded for IP {client_ip} in category {category}",
                    ip_address=client_ip,
                    user_agent=request.headers.get("user-agent"),
                    endpoint=str(request.url.path),
                    method=request.method,
                    event_data={"category": category, "suspicious_score": self.suspicious_ips[client_ip]},
                    severity="MEDIUM",
                    risk_score=60
                )
        except Exception as e:
            logger.error(f"Failed to log rate limit exceeded: {e}")
    
    async def _log_threat_detection(self, client_ip: str, request: Request, threats: List[str]):
        """Log detected threat patterns."""
        try:
            async with get_db() as db:
                await security_audit_service.log_security_event(
                    db=db,
                    event_type="THREAT_PATTERN_DETECTED",
                    event_category="SECURITY",
                    message=f"Threat patterns detected from IP {client_ip}: {', '.join(threats)}",
                    ip_address=client_ip,
                    user_agent=request.headers.get("user-agent"),
                    endpoint=str(request.url.path),
                    method=request.method,
                    event_data={"threat_types": threats, "url": str(request.url)},
                    severity="HIGH",
                    risk_score=85,
                    is_suspicious=True
                )
        except Exception as e:
            logger.error(f"Failed to log threat detection: {e}")
    
    async def _log_suspicious_session(self, client_ip: str, request: Request, session_info: Dict):
        """Log suspicious session activity."""
        try:
            async with get_db() as db:
                await security_audit_service.log_security_event(
                    db=db,
                    event_type="SUSPICIOUS_SESSION_ACTIVITY",
                    event_category="SECURITY",
                    message=f"Suspicious session activity from IP {client_ip}",
                    ip_address=client_ip,
                    user_agent=request.headers.get("user-agent"),
                    endpoint=str(request.url.path),
                    method=request.method,
                    event_data={
                        "request_count": session_info["request_count"],
                        "session_duration": time.time() - session_info["created"]
                    },
                    severity="MEDIUM",
                    risk_score=70,
                    is_suspicious=True
                )
        except Exception as e:
            logger.error(f"Failed to log suspicious session: {e}")
    
    async def _log_security_exception(self, request: Request, exception: HTTPException, client_ip: str):
        """Log security-related HTTP exceptions."""
        try:
            async with get_db() as db:
                event_type_mapping = {
                    401: "UNAUTHORIZED_ACCESS",
                    403: "FORBIDDEN_ACCESS", 
                    429: "RATE_LIMIT_VIOLATION"
                }
                
                event_type = event_type_mapping.get(exception.status_code, "SECURITY_EXCEPTION")
                
                await security_audit_service.log_security_event(
                    db=db,
                    event_type=event_type,
                    event_category="SECURITY",
                    message=f"Security exception: {exception.detail}",
                    ip_address=client_ip,
                    user_agent=request.headers.get("user-agent"),
                    endpoint=str(request.url.path),
                    method=request.method,
                    event_data={
                        "status_code": exception.status_code,
                        "detail": exception.detail
                    },
                    severity="MEDIUM",
                    risk_score=50
                )
        except Exception as e:
            logger.error(f"Failed to log security exception: {e}")
    
    async def _log_system_error(self, request: Request, error_msg: str, client_ip: str):
        """Log system errors."""
        try:
            async with get_db() as db:
                await security_audit_service.log_security_event(
                    db=db,
                    event_type="SYSTEM_ERROR",
                    event_category="SYSTEM",
                    message=f"System error in security middleware: {error_msg}",
                    ip_address=client_ip,
                    user_agent=request.headers.get("user-agent"),
                    endpoint=str(request.url.path),
                    method=request.method,
                    event_data={"error": error_msg},
                    severity="HIGH",
                    risk_score=30
                )
        except Exception as e:
            logger.error(f"Failed to log system error: {e}")
    
    async def _escalate_suspicious_ip(self, client_ip: str, request: Request):
        """Escalate suspicious IP for blocking or further action."""
        try:
            # Add IP to blocked list
            self.blocked_ips.add(client_ip)
            
            # Report to incident response system
            async with get_db() as db:
                await incident_response_system.block_ip_address(
                    client_ip, 
                    f"Automatically blocked due to suspicious activity (score: {self.suspicious_ips[client_ip]})"
                )
                
                await security_audit_service.log_security_event(
                    db=db,
                    event_type="IP_AUTO_BLOCKED",
                    event_category="SECURITY",
                    message=f"IP {client_ip} automatically blocked due to suspicious activity",
                    ip_address=client_ip,
                    event_data={"suspicious_score": self.suspicious_ips[client_ip]},
                    severity="HIGH",
                    risk_score=95
                )
                
            logger.warning(f"IP {client_ip} escalated and blocked due to suspicious activity")
            
        except Exception as e:
            logger.error(f"Failed to escalate suspicious IP: {e}")


# Factory function to create middleware with configuration
def create_security_middleware(
    enable_rate_limiting: bool = True,
    enable_ip_blocking: bool = True,
    enable_anomaly_detection: bool = True,
    enable_audit_logging: bool = True
) -> SecurityMiddleware:
    """Create security middleware with configuration."""
    return SecurityMiddleware(
        app=None,  # Will be set by FastAPI
        enable_rate_limiting=enable_rate_limiting,
        enable_ip_blocking=enable_ip_blocking,
        enable_anomaly_detection=enable_anomaly_detection,
        enable_audit_logging=enable_audit_logging
    )