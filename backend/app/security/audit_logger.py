"""
Security Audit Logger

High-level interface for logging security events throughout the application.
Provides context managers and decorators for easy integration.
"""

import functools
import asyncio
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, Callable, Union
from fastapi import Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
import logging

from app.services.audit_service import security_audit_service
from app.core.database import get_db


logger = logging.getLogger(__name__)


class SecurityAuditLogger:
    """
    High-level security audit logging interface.
    
    Provides convenient methods and decorators for logging security events
    throughout the application with consistent formatting and correlation.
    """
    
    def __init__(self):
        self.audit_service = security_audit_service
    
    async def log_user_action(
        self,
        db: AsyncSession,
        user_id: int,
        username: str,
        action: str,
        resource: str,
        request: Request = None,
        additional_data: Dict[str, Any] = None,
        severity: str = "INFO"
    ) -> str:
        """
        Log a user action with automatic context extraction.
        
        Args:
            db: Database session
            user_id: ID of the user performing the action
            username: Username of the user
            action: Action being performed (CREATE, READ, UPDATE, DELETE)
            resource: Resource being accessed (attendance, class, user, etc.)
            request: FastAPI request object for context
            additional_data: Additional structured data
            severity: Event severity
            
        Returns:
            Correlation ID for tracking related events
        """
        correlation_id = str(uuid.uuid4())
        
        # Extract request context
        ip_address = None
        user_agent = None
        endpoint = None
        method = None
        
        if request:
            ip_address = self._get_client_ip(request)
            user_agent = request.headers.get("user-agent")
            endpoint = str(request.url.path)
            method = request.method
        
        # Determine event type and category
        event_type = f"{action}_{resource.upper()}"
        event_category = "DATA" if action in ["READ", "export", "import"] else "AUTHORIZATION"
        
        # Prepare event data
        event_data = {
            "action": action,
            "resource": resource,
            "resource_id": additional_data.get("resource_id") if additional_data else None
        }
        
        if additional_data:
            event_data.update(additional_data)
        
        # Log the event
        await self.audit_service.log_security_event(
            db=db,
            event_type=event_type,
            event_category=event_category,
            message=f"User {username} performed {action} on {resource}",
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            user_agent=user_agent,
            endpoint=endpoint,
            method=method,
            event_data=event_data,
            severity=severity,
            correlation_id=correlation_id
        )
        
        return correlation_id
    
    async def log_authentication_event(
        self,
        db: AsyncSession,
        event_type: str,
        username: str,
        request: Request = None,
        user_id: int = None,
        session_id: str = None,
        additional_data: Dict[str, Any] = None,
        success: bool = True,
        failure_reason: str = None
    ) -> str:
        """Log authentication-related events."""
        correlation_id = str(uuid.uuid4())
        
        # Extract request context
        ip_address = self._get_client_ip(request) if request else None
        user_agent = request.headers.get("user-agent") if request else None
        
        # Log authentication attempt in dedicated table
        if event_type in ["LOGIN_SUCCESS", "LOGIN_FAILURE"]:
            await self.audit_service.log_authentication_event(
                db=db,
                username=username,
                success=success,
                ip_address=ip_address,
                user_agent=user_agent,
                failure_reason=failure_reason,
                user_id=user_id,
                session_id=session_id
            )
        
        # Prepare event data
        event_data = {
            "success": success,
            "failure_reason": failure_reason
        }
        
        if additional_data:
            event_data.update(additional_data)
        
        # Log security event
        await self.audit_service.log_security_event(
            db=db,
            event_type=event_type,
            event_category="AUTHENTICATION",
            message=f"Authentication event: {event_type} for user {username}",
            user_id=user_id,
            username=username,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            event_data=event_data,
            severity="INFO" if success else "MEDIUM",
            correlation_id=correlation_id
        )
        
        return correlation_id
    
    async def log_authorization_event(
        self,
        db: AsyncSession,
        user_id: int,
        username: str,
        permission: str,
        resource: str,
        granted: bool,
        request: Request = None,
        additional_data: Dict[str, Any] = None
    ) -> str:
        """Log authorization decisions."""
        correlation_id = str(uuid.uuid4())
        
        # Extract request context
        ip_address = self._get_client_ip(request) if request else None
        user_agent = request.headers.get("user-agent") if request else None
        endpoint = str(request.url.path) if request else None
        method = request.method if request else None
        
        event_type = "PERMISSION_GRANTED" if granted else "PERMISSION_DENIED"
        event_data = {
            "permission": permission,
            "resource": resource,
            "granted": granted
        }
        
        if additional_data:
            event_data.update(additional_data)
        
        await self.audit_service.log_security_event(
            db=db,
            event_type=event_type,
            event_category="AUTHORIZATION",
            message=f"Permission {permission} for {resource} {'granted' if granted else 'denied'} to user {username}",
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            user_agent=user_agent,
            endpoint=endpoint,
            method=method,
            event_data=event_data,
            severity="INFO" if granted else "MEDIUM",
            correlation_id=correlation_id
        )
        
        return correlation_id
    
    async def log_system_event(
        self,
        db: AsyncSession,
        event_type: str,
        message: str,
        severity: str = "INFO",
        additional_data: Dict[str, Any] = None,
        correlation_id: str = None
    ) -> str:
        """Log system-level security events."""
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        
        event_data = additional_data or {}
        
        await self.audit_service.log_security_event(
            db=db,
            event_type=event_type,
            event_category="SYSTEM",
            message=message,
            event_data=event_data,
            severity=severity,
            correlation_id=correlation_id
        )
        
        return correlation_id
    
    async def log_security_incident(
        self,
        db: AsyncSession,
        incident_type: str,
        description: str,
        affected_user_id: int = None,
        affected_ip: str = None,
        severity: str = "MEDIUM",
        additional_data: Dict[str, Any] = None
    ) -> str:
        """Log security incidents for investigation."""
        correlation_id = str(uuid.uuid4())
        
        event_data = {
            "incident_type": incident_type,
            "affected_user_id": affected_user_id,
            "affected_ip": affected_ip
        }
        
        if additional_data:
            event_data.update(additional_data)
        
        await self.audit_service.log_security_event(
            db=db,
            event_type="SECURITY_VIOLATION",
            event_category="SECURITY",
            message=f"Security incident: {description}",
            user_id=affected_user_id,
            ip_address=affected_ip,
            event_data=event_data,
            severity=severity,
            correlation_id=correlation_id,
            risk_score=80 if severity in ["HIGH", "CRITICAL"] else 60
        )
        
        return correlation_id
    
    @asynccontextmanager
    async def audit_context(
        self,
        db: AsyncSession,
        user_id: int,
        username: str,
        action: str,
        resource: str,
        request: Request = None,
        auto_log_errors: bool = True
    ):
        """
        Context manager for auditing operations.
        
        Automatically logs start and completion of operations,
        and handles errors with appropriate security event logging.
        """
        correlation_id = str(uuid.uuid4())
        start_time = datetime.utcnow()
        
        # Log operation start
        await self.log_user_action(
            db=db,
            user_id=user_id,
            username=username,
            action=f"{action}_START",
            resource=resource,
            request=request,
            additional_data={"correlation_id": correlation_id, "start_time": start_time.isoformat()},
            severity="INFO"
        )
        
        try:
            yield correlation_id
            
            # Log successful completion
            end_time = datetime.utcnow()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            
            await self.log_user_action(
                db=db,
                user_id=user_id,
                username=username,
                action=f"{action}_SUCCESS",
                resource=resource,
                request=request,
                additional_data={
                    "correlation_id": correlation_id,
                    "duration_ms": duration_ms,
                    "end_time": end_time.isoformat()
                },
                severity="INFO"
            )
            
        except Exception as e:
            if auto_log_errors:
                # Log operation failure
                end_time = datetime.utcnow()
                duration_ms = int((end_time - start_time).total_seconds() * 1000)
                
                await self.log_user_action(
                    db=db,
                    user_id=user_id,
                    username=username,
                    action=f"{action}_FAILURE",
                    resource=resource,
                    request=request,
                    additional_data={
                        "correlation_id": correlation_id,
                        "duration_ms": duration_ms,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "end_time": end_time.isoformat()
                    },
                    severity="HIGH"
                )
            
            raise
    
    def audit_operation(
        self,
        action: str,
        resource: str,
        severity: str = "INFO"
    ):
        """
        Decorator for automatically auditing function operations.
        
        Usage:
        @audit_logger.audit_operation("CREATE", "attendance")
        async def create_attendance(db: AsyncSession, user: User, data: dict):
            # Function implementation
            pass
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                # Extract common parameters
                db = None
                user = None
                request = None
                
                # Try to find db, user, and request in arguments
                for arg in args:
                    if hasattr(arg, 'execute'):  # AsyncSession
                        db = arg
                    elif hasattr(arg, 'id') and hasattr(arg, 'username'):  # User
                        user = arg
                    elif hasattr(arg, 'method') and hasattr(arg, 'url'):  # Request
                        request = arg
                
                # Check keyword arguments
                if 'db' in kwargs:
                    db = kwargs['db']
                if 'current_user' in kwargs:
                    user = kwargs['current_user']
                if 'request' in kwargs:
                    request = kwargs['request']
                
                if db and user:
                    async with self.audit_context(
                        db=db,
                        user_id=user.id,
                        username=user.username,
                        action=action,
                        resource=resource,
                        request=request
                    ) as correlation_id:
                        # Add correlation_id to kwargs for function use
                        kwargs['correlation_id'] = correlation_id
                        return await func(*args, **kwargs)
                else:
                    # If we can't audit, just run the function
                    return await func(*args, **kwargs)
            
            return wrapper
        return decorator
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request."""
        # Check for forwarded headers first
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fallback to client host
        return request.client.host if request.client else "unknown"


# Global audit logger instance
audit_logger = SecurityAuditLogger()