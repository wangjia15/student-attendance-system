"""
Comprehensive error handling and logging utilities for SIS integrations.
"""

import asyncio
import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable, Union
from functools import wraps
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sis_integration import SISIntegration, SISSyncOperation


# Configure SIS-specific logger
sis_logger = logging.getLogger('sis_integration')


class SISErrorSeverity:
    """Error severity levels for SIS operations."""
    LOW = "low"           # Minor issues, system continues
    MEDIUM = "medium"     # Significant issues, some functionality impacted
    HIGH = "high"         # Major issues, integration partially broken
    CRITICAL = "critical" # System-breaking issues, integration disabled


class SISErrorCategory:
    """Error categories for better classification."""
    AUTHENTICATION = "authentication"
    NETWORK = "network"
    DATA_VALIDATION = "data_validation"
    RATE_LIMITING = "rate_limiting"
    CONFIGURATION = "configuration"
    SYNC_CONFLICT = "sync_conflict"
    PROVIDER_ERROR = "provider_error"
    DATABASE_ERROR = "database_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class SISError(Exception):
    """Base exception for SIS integration errors with enhanced metadata."""
    
    def __init__(
        self,
        message: str,
        category: str = SISErrorCategory.UNKNOWN,
        severity: str = SISErrorSeverity.MEDIUM,
        provider_id: Optional[str] = None,
        integration_id: Optional[int] = None,
        operation_type: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = True,
        original_exception: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.provider_id = provider_id
        self.integration_id = integration_id
        self.operation_type = operation_type
        self.details = details or {}
        self.retryable = retryable
        self.original_exception = original_exception
        self.timestamp = datetime.utcnow()
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for logging/storage."""
        return {
            'message': self.message,
            'category': self.category,
            'severity': self.severity,
            'provider_id': self.provider_id,
            'integration_id': self.integration_id,
            'operation_type': self.operation_type,
            'details': self.details,
            'retryable': self.retryable,
            'timestamp': self.timestamp.isoformat(),
            'traceback': traceback.format_exc() if self.original_exception else None
        }


class SISAuthenticationError(SISError):
    """Authentication-related errors."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=SISErrorCategory.AUTHENTICATION,
            severity=SISErrorSeverity.HIGH,
            retryable=True,
            **kwargs
        )


class SISNetworkError(SISError):
    """Network-related errors."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=SISErrorCategory.NETWORK,
            severity=SISErrorSeverity.MEDIUM,
            retryable=True,
            **kwargs
        )


class SISRateLimitError(SISError):
    """Rate limiting errors."""
    
    def __init__(self, message: str, retry_after: Optional[int] = None, **kwargs):
        details = kwargs.get('details', {})
        details['retry_after'] = retry_after
        kwargs['details'] = details
        
        super().__init__(
            message,
            category=SISErrorCategory.RATE_LIMITING,
            severity=SISErrorSeverity.LOW,
            retryable=True,
            **kwargs
        )


class SISDataValidationError(SISError):
    """Data validation errors."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=SISErrorCategory.DATA_VALIDATION,
            severity=SISErrorSeverity.MEDIUM,
            retryable=False,
            **kwargs
        )


class SISConfigurationError(SISError):
    """Configuration-related errors."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=SISErrorCategory.CONFIGURATION,
            severity=SISErrorSeverity.HIGH,
            retryable=False,
            **kwargs
        )


class SISErrorHandler:
    """Central error handler for SIS operations."""
    
    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        self._error_log: List[Dict[str, Any]] = []
        self._max_log_entries = 1000
        
    def log_error(
        self,
        error: Union[SISError, Exception],
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log an error with full context.
        
        Args:
            error: The error to log
            context: Additional context information
        """
        if isinstance(error, SISError):
            error_dict = error.to_dict()
        else:
            # Convert regular exception to SISError format
            error_dict = {
                'message': str(error),
                'category': SISErrorCategory.UNKNOWN,
                'severity': SISErrorSeverity.MEDIUM,
                'timestamp': datetime.utcnow().isoformat(),
                'traceback': traceback.format_exc()
            }
            
        # Add context
        if context:
            error_dict.update(context)
            
        # Log to appropriate level based on severity
        severity = error_dict.get('severity', SISErrorSeverity.MEDIUM)
        log_message = f"SIS Error [{severity.upper()}]: {error_dict['message']}"
        
        if severity == SISErrorSeverity.CRITICAL:
            sis_logger.critical(log_message, extra=error_dict)
        elif severity == SISErrorSeverity.HIGH:
            sis_logger.error(log_message, extra=error_dict)
        elif severity == SISErrorSeverity.MEDIUM:
            sis_logger.warning(log_message, extra=error_dict)
        else:
            sis_logger.info(log_message, extra=error_dict)
            
        # Store in memory log (for recent errors API)
        self._error_log.append(error_dict)
        if len(self._error_log) > self._max_log_entries:
            self._error_log.pop(0)
            
    def get_recent_errors(
        self,
        limit: int = 50,
        severity_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
        provider_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent errors with optional filtering."""
        filtered_errors = self._error_log.copy()
        
        if severity_filter:
            filtered_errors = [e for e in filtered_errors if e.get('severity') == severity_filter]
            
        if category_filter:
            filtered_errors = [e for e in filtered_errors if e.get('category') == category_filter]
            
        if provider_filter:
            filtered_errors = [e for e in filtered_errors if e.get('provider_id') == provider_filter]
            
        return filtered_errors[-limit:]
        
    async def handle_integration_error(
        self,
        integration: SISIntegration,
        error: Exception,
        operation_type: str
    ) -> None:
        """
        Handle integration-specific errors and update integration status.
        
        Args:
            integration: The SIS integration
            error: The error that occurred
            operation_type: Type of operation that failed
        """
        if not isinstance(error, SISError):
            # Wrap in SISError
            error = SISError(
                message=str(error),
                provider_id=integration.provider_id,
                integration_id=integration.id,
                operation_type=operation_type,
                original_exception=error
            )
            
        # Log the error
        self.log_error(error)
        
        # Update integration based on error type
        if error.category == SISErrorCategory.AUTHENTICATION:
            integration.update_auth_failure()
        else:
            integration.update_sync_failure()
            
        # If database session is available, commit changes
        if self.db:
            try:
                await self.db.commit()
            except Exception as db_error:
                sis_logger.error(f"Failed to update integration status: {db_error}")


# Decorator for automatic error handling
def handle_sis_errors(
    operation_type: str,
    provider_id: Optional[str] = None,
    integration_id: Optional[int] = None,
    reraise: bool = True
):
    """
    Decorator for automatic SIS error handling.
    
    Args:
        operation_type: Type of operation being performed
        provider_id: SIS provider identifier
        integration_id: Integration ID
        reraise: Whether to reraise the exception after handling
    """
    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except SISError as e:
                    # Already a SIS error, just enhance with context
                    e.provider_id = e.provider_id or provider_id
                    e.integration_id = e.integration_id or integration_id
                    e.operation_type = e.operation_type or operation_type
                    
                    error_handler = SISErrorHandler()
                    error_handler.log_error(e)
                    
                    if reraise:
                        raise
                    return None
                except Exception as e:
                    # Convert to SIS error
                    sis_error = SISError(
                        message=str(e),
                        provider_id=provider_id,
                        integration_id=integration_id,
                        operation_type=operation_type,
                        original_exception=e
                    )
                    
                    error_handler = SISErrorHandler()
                    error_handler.log_error(sis_error)
                    
                    if reraise:
                        raise sis_error
                    return None
                    
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except SISError as e:
                    e.provider_id = e.provider_id or provider_id
                    e.integration_id = e.integration_id or integration_id
                    e.operation_type = e.operation_type or operation_type
                    
                    error_handler = SISErrorHandler()
                    error_handler.log_error(e)
                    
                    if reraise:
                        raise
                    return None
                except Exception as e:
                    sis_error = SISError(
                        message=str(e),
                        provider_id=provider_id,
                        integration_id=integration_id,
                        operation_type=operation_type,
                        original_exception=e
                    )
                    
                    error_handler = SISErrorHandler()
                    error_handler.log_error(sis_error)
                    
                    if reraise:
                        raise sis_error
                    return None
                    
            return sync_wrapper
            
    return decorator


@asynccontextmanager
async def error_context(
    operation_type: str,
    provider_id: Optional[str] = None,
    integration_id: Optional[int] = None,
    integration: Optional[SISIntegration] = None,
    db: Optional[AsyncSession] = None
):
    """
    Context manager for handling errors within a specific operation.
    
    Args:
        operation_type: Type of operation being performed
        provider_id: SIS provider identifier
        integration_id: Integration ID
        integration: SIS integration instance
        db: Database session for updating integration status
    """
    error_handler = SISErrorHandler(db)
    
    try:
        yield error_handler
    except SISError as e:
        # Enhance with context
        e.provider_id = e.provider_id or provider_id
        e.integration_id = e.integration_id or integration_id
        e.operation_type = e.operation_type or operation_type
        
        if integration:
            await error_handler.handle_integration_error(integration, e, operation_type)
        else:
            error_handler.log_error(e)
            
        raise
    except Exception as e:
        # Convert to SIS error
        sis_error = SISError(
            message=str(e),
            provider_id=provider_id,
            integration_id=integration_id,
            operation_type=operation_type,
            original_exception=e
        )
        
        if integration:
            await error_handler.handle_integration_error(integration, sis_error, operation_type)
        else:
            error_handler.log_error(sis_error)
            
        raise sis_error


# Retry mechanism with exponential backoff
class RetryConfig:
    """Configuration for retry attempts."""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter


async def retry_on_error(
    func: Callable,
    retry_config: RetryConfig,
    retryable_errors: tuple = (SISNetworkError, SISRateLimitError),
    *args,
    **kwargs
) -> Any:
    """
    Retry function execution on specific errors.
    
    Args:
        func: Function to retry
        retry_config: Retry configuration
        retryable_errors: Tuple of error types that should trigger retry
        *args: Arguments for function
        **kwargs: Keyword arguments for function
        
    Returns:
        Function result
    """
    import random
    
    last_exception = None
    
    for attempt in range(retry_config.max_attempts):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
                
        except retryable_errors as e:
            last_exception = e
            
            if attempt == retry_config.max_attempts - 1:
                # Last attempt, don't wait
                break
                
            # Calculate delay with exponential backoff
            delay = min(
                retry_config.base_delay * (retry_config.exponential_base ** attempt),
                retry_config.max_delay
            )
            
            # Add jitter to avoid thundering herd
            if retry_config.jitter:
                delay *= (0.5 + random.random())
                
            # Special handling for rate limit errors
            if isinstance(e, SISRateLimitError) and e.details.get('retry_after'):
                delay = max(delay, e.details['retry_after'])
                
            sis_logger.info(
                f"Retrying operation after error (attempt {attempt + 1}/{retry_config.max_attempts}): {e}"
            )
            
            await asyncio.sleep(delay)
            
        except Exception as e:
            # Non-retryable error
            raise e
            
    # All retries exhausted
    if last_exception:
        raise last_exception


# Global error handler instance
global_error_handler = SISErrorHandler()