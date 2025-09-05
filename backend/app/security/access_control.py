"""
Role-Based Access Control (RBAC) and Multi-Factor Authentication (MFA)

Comprehensive access control system with granular permissions and MFA support.
"""

import secrets
import qrcode
import io
import base64
import pyotp
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, update
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from pydantic import BaseModel

from app.models.user import User, UserRole
from app.models.audit_log import SecurityAuditLog
from app.services.audit_service import security_audit_service
from app.security.audit_logger import audit_logger


logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """System permissions with granular access control."""
    
    # User management
    VIEW_USERS = "view_users"
    CREATE_USERS = "create_users"
    UPDATE_USERS = "update_users"
    DELETE_USERS = "delete_users"
    MANAGE_USER_ROLES = "manage_user_roles"
    
    # Attendance management  
    VIEW_ATTENDANCE = "view_attendance"
    CREATE_ATTENDANCE = "create_attendance"
    UPDATE_ATTENDANCE = "update_attendance"
    DELETE_ATTENDANCE = "delete_attendance"
    EXPORT_ATTENDANCE = "export_attendance"
    
    # Class management
    VIEW_CLASSES = "view_classes"
    CREATE_CLASSES = "create_classes"
    UPDATE_CLASSES = "update_classes"
    DELETE_CLASSES = "delete_classes"
    MANAGE_CLASS_SESSIONS = "manage_class_sessions"
    
    # Analytics and reporting
    VIEW_ANALYTICS = "view_analytics"
    EXPORT_REPORTS = "export_reports"
    VIEW_SYSTEM_METRICS = "view_system_metrics"
    
    # Security and audit
    VIEW_AUDIT_LOGS = "view_audit_logs"
    MANAGE_SECURITY_SETTINGS = "manage_security_settings"
    VIEW_INCIDENTS = "view_incidents"
    MANAGE_INCIDENTS = "manage_incidents"
    
    # System administration
    MANAGE_SYSTEM_CONFIG = "manage_system_config"
    VIEW_SYSTEM_HEALTH = "view_system_health"
    MANAGE_INTEGRATIONS = "manage_integrations"
    PERFORM_MAINTENANCE = "perform_maintenance"
    
    # Data privacy and compliance
    VIEW_FERPA_LOGS = "view_ferpa_logs"
    MANAGE_DATA_RETENTION = "manage_data_retention"
    EXPORT_USER_DATA = "export_user_data"
    DELETE_USER_DATA = "delete_user_data"


class Resource(str, Enum):
    """System resources that can be protected."""
    USER = "user"
    ATTENDANCE = "attendance"  
    CLASS = "class"
    REPORT = "report"
    AUDIT_LOG = "audit_log"
    SECURITY_INCIDENT = "security_incident"
    SYSTEM_CONFIG = "system_config"
    INTEGRATION = "integration"


@dataclass
class AccessPolicy:
    """Access control policy definition."""
    resource: Resource
    permissions: Set[Permission]
    conditions: Dict[str, Any] = field(default_factory=dict)
    
    def allows(self, permission: Permission, context: Dict[str, Any] = None) -> bool:
        """Check if policy allows a specific permission."""
        if permission not in self.permissions:
            return False
        
        # Apply conditional logic if present
        if self.conditions and context:
            return self._evaluate_conditions(context)
        
        return True
    
    def _evaluate_conditions(self, context: Dict[str, Any]) -> bool:
        """Evaluate conditional access rules."""
        # Owner condition - user can only access their own resources
        if "owner_only" in self.conditions:
            return context.get("resource_owner") == context.get("user_id")
        
        # IP restriction condition
        if "allowed_ips" in self.conditions:
            client_ip = context.get("client_ip")
            return client_ip in self.conditions["allowed_ips"]
        
        # Time-based restrictions
        if "allowed_hours" in self.conditions:
            current_hour = datetime.now().hour
            allowed_hours = self.conditions["allowed_hours"]
            return current_hour in allowed_hours
        
        # MFA requirement
        if "requires_mfa" in self.conditions:
            return context.get("mfa_verified", False)
        
        return True


class MFAMethod(str, Enum):
    """Multi-factor authentication methods."""
    TOTP = "totp"  # Time-based One-Time Password (Google Authenticator, etc.)
    SMS = "sms"    # SMS verification codes
    EMAIL = "email"  # Email verification codes
    BACKUP_CODES = "backup_codes"  # Single-use backup codes


@dataclass
class MFASecret:
    """MFA secret and configuration."""
    user_id: int
    method: MFAMethod
    secret: str
    backup_codes: List[str] = field(default_factory=list)
    verified: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used: Optional[datetime] = None


class RBACManager:
    """
    Role-Based Access Control Manager.
    
    Provides granular permission management with context-aware access policies.
    """
    
    def __init__(self):
        self.role_policies: Dict[UserRole, List[AccessPolicy]] = {}
        self._initialize_default_policies()
    
    def _initialize_default_policies(self):
        """Initialize default access policies for each role."""
        
        # Student permissions
        self.role_policies[UserRole.STUDENT] = [
            AccessPolicy(
                resource=Resource.ATTENDANCE,
                permissions={Permission.VIEW_ATTENDANCE},
                conditions={"owner_only": True}  # Students can only view their own attendance
            ),
            AccessPolicy(
                resource=Resource.CLASS,
                permissions={Permission.VIEW_CLASSES}
            )
        ]
        
        # Teacher permissions
        self.role_policies[UserRole.TEACHER] = [
            AccessPolicy(
                resource=Resource.USER,
                permissions={Permission.VIEW_USERS}
            ),
            AccessPolicy(
                resource=Resource.ATTENDANCE,
                permissions={
                    Permission.VIEW_ATTENDANCE,
                    Permission.CREATE_ATTENDANCE,
                    Permission.UPDATE_ATTENDANCE,
                    Permission.EXPORT_ATTENDANCE
                }
            ),
            AccessPolicy(
                resource=Resource.CLASS,
                permissions={
                    Permission.VIEW_CLASSES,
                    Permission.CREATE_CLASSES,
                    Permission.UPDATE_CLASSES,
                    Permission.MANAGE_CLASS_SESSIONS
                }
            ),
            AccessPolicy(
                resource=Resource.REPORT,
                permissions={Permission.VIEW_ANALYTICS, Permission.EXPORT_REPORTS}
            )
        ]
        
        # Admin permissions (all permissions)
        admin_permissions = set(Permission)
        self.role_policies[UserRole.ADMIN] = [
            AccessPolicy(
                resource=resource,
                permissions=admin_permissions
            ) for resource in Resource
        ]
    
    async def check_permission(
        self,
        db: AsyncSession,
        user: User,
        permission: Permission,
        resource: Resource,
        resource_id: Optional[str] = None,
        context: Dict[str, Any] = None
    ) -> bool:
        """
        Check if user has permission for a specific resource.
        
        Args:
            db: Database session
            user: User requesting access
            permission: Permission being requested
            resource: Resource being accessed
            resource_id: Specific resource ID (optional)
            context: Additional context for conditional access
            
        Returns:
            True if access is granted, False otherwise
        """
        try:
            # Get policies for user's role
            policies = self.role_policies.get(user.role, [])
            
            # Build context
            access_context = context or {}
            access_context.update({
                "user_id": user.id,
                "user_role": user.role.value,
                "resource_id": resource_id
            })
            
            # Check each policy
            for policy in policies:
                if policy.resource == resource and policy.allows(permission, access_context):
                    # Log successful permission grant
                    await audit_logger.log_authorization_event(
                        db=db,
                        user_id=user.id,
                        username=user.username,
                        permission=permission.value,
                        resource=f"{resource.value}:{resource_id}" if resource_id else resource.value,
                        granted=True,
                        additional_data={"context": access_context}
                    )
                    return True
            
            # Log permission denial
            await audit_logger.log_authorization_event(
                db=db,
                user_id=user.id,
                username=user.username,
                permission=permission.value,
                resource=f"{resource.value}:{resource_id}" if resource_id else resource.value,
                granted=False,
                additional_data={"context": access_context}
            )
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking permission: {e}")
            return False
    
    def require_permission(
        self,
        permission: Permission,
        resource: Resource,
        resource_id_param: str = None
    ):
        """
        Decorator to require specific permissions for API endpoints.
        
        Usage:
        @rbac_manager.require_permission(Permission.VIEW_USERS, Resource.USER)
        async def get_users(current_user: User = Depends(get_current_user)):
            ...
        """
        def decorator(func):
            async def wrapper(*args, **kwargs):
                # Extract database session and current user
                db = None
                current_user = None
                resource_id = None
                
                # Find db and user in function arguments
                for key, value in kwargs.items():
                    if key == 'db' and hasattr(value, 'execute'):
                        db = value
                    elif key == 'current_user' and hasattr(value, 'id'):
                        current_user = value
                    elif key == resource_id_param:
                        resource_id = str(value)
                
                if not db or not current_user:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Cannot verify permissions"
                    )
                
                # Check permission
                has_permission = await self.check_permission(
                    db=db,
                    user=current_user,
                    permission=permission,
                    resource=resource,
                    resource_id=resource_id
                )
                
                if not has_permission:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Permission denied: {permission.value} on {resource.value}"
                    )
                
                # Call the original function
                return await func(*args, **kwargs)
            
            return wrapper
        return decorator
    
    async def assign_role_permissions(
        self,
        role: UserRole,
        resource: Resource,
        permissions: Set[Permission],
        conditions: Dict[str, Any] = None
    ):
        """Dynamically assign permissions to a role."""
        if role not in self.role_policies:
            self.role_policies[role] = []
        
        # Remove existing policy for this resource
        self.role_policies[role] = [
            policy for policy in self.role_policies[role]
            if policy.resource != resource
        ]
        
        # Add new policy
        new_policy = AccessPolicy(
            resource=resource,
            permissions=permissions,
            conditions=conditions or {}
        )
        
        self.role_policies[role].append(new_policy)
    
    def get_user_permissions(self, user_role: UserRole) -> Dict[Resource, Set[Permission]]:
        """Get all permissions for a user role."""
        role_permissions = {}
        
        for policy in self.role_policies.get(user_role, []):
            if policy.resource not in role_permissions:
                role_permissions[policy.resource] = set()
            role_permissions[policy.resource].update(policy.permissions)
        
        return role_permissions


class MFAManager:
    """
    Multi-Factor Authentication Manager.
    
    Supports TOTP, SMS, and backup codes for enhanced security.
    """
    
    def __init__(self):
        self.mfa_secrets: Dict[int, MFASecret] = {}  # In production, store in database
        self.pending_verifications: Dict[str, Dict[str, Any]] = {}
    
    async def enable_mfa_totp(
        self,
        db: AsyncSession,
        user: User,
        app_name: str = "Student Attendance System"
    ) -> Tuple[str, str]:
        """
        Enable TOTP-based MFA for a user.
        
        Returns:
            Tuple of (secret_key, qr_code_data_url)
        """
        try:
            # Generate TOTP secret
            secret = pyotp.random_base32()
            
            # Create TOTP provisioning URI
            totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
                name=user.email,
                issuer_name=app_name
            )
            
            # Generate QR code
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(totp_uri)
            qr.make(fit=True)
            
            qr_image = qr.make_image(fill_color="black", back_color="white")
            
            # Convert QR code to base64 data URL
            buffer = io.BytesIO()
            qr_image.save(buffer, format='PNG')
            qr_code_data = base64.b64encode(buffer.getvalue()).decode()
            qr_code_url = f"data:image/png;base64,{qr_code_data}"
            
            # Generate backup codes
            backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]
            
            # Store MFA secret (not yet verified)
            mfa_secret = MFASecret(
                user_id=user.id,
                method=MFAMethod.TOTP,
                secret=secret,
                backup_codes=backup_codes,
                verified=False
            )
            
            self.mfa_secrets[user.id] = mfa_secret
            
            # Log MFA setup initiation
            await audit_logger.log_authentication_event(
                db=db,
                event_type="MFA_SETUP_INITIATED",
                username=user.username,
                user_id=user.id,
                additional_data={"method": "TOTP"},
                success=True
            )
            
            return secret, qr_code_url
            
        except Exception as e:
            logger.error(f"Failed to enable MFA TOTP for user {user.id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to enable MFA"
            )
    
    async def verify_mfa_setup(
        self,
        db: AsyncSession,
        user: User,
        verification_code: str
    ) -> Dict[str, Any]:
        """Verify MFA setup with initial code."""
        try:
            if user.id not in self.mfa_secrets:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="MFA setup not initiated"
                )
            
            mfa_secret = self.mfa_secrets[user.id]
            
            # Verify TOTP code
            if mfa_secret.method == MFAMethod.TOTP:
                totp = pyotp.TOTP(mfa_secret.secret)
                if not totp.verify(verification_code, valid_window=1):
                    await audit_logger.log_authentication_event(
                        db=db,
                        event_type="MFA_SETUP_VERIFICATION_FAILED",
                        username=user.username,
                        user_id=user.id,
                        additional_data={"method": "TOTP"},
                        success=False,
                        failure_reason="INVALID_CODE"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid verification code"
                    )
            
            # Mark as verified
            mfa_secret.verified = True
            
            # Log successful MFA setup
            await audit_logger.log_authentication_event(
                db=db,
                event_type="MFA_SETUP_COMPLETED",
                username=user.username,
                user_id=user.id,
                additional_data={"method": mfa_secret.method.value},
                success=True
            )
            
            return {
                "success": True,
                "backup_codes": mfa_secret.backup_codes,
                "message": "MFA successfully enabled"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to verify MFA setup for user {user.id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to verify MFA setup"
            )
    
    async def verify_mfa_code(
        self,
        db: AsyncSession,
        user: User,
        verification_code: str,
        session_id: str = None
    ) -> bool:
        """Verify MFA code for authentication."""
        try:
            if user.id not in self.mfa_secrets:
                return False
            
            mfa_secret = self.mfa_secrets[user.id]
            
            if not mfa_secret.verified:
                return False
            
            # Try TOTP verification
            if mfa_secret.method == MFAMethod.TOTP:
                totp = pyotp.TOTP(mfa_secret.secret)
                if totp.verify(verification_code, valid_window=1):
                    mfa_secret.last_used = datetime.utcnow()
                    
                    await audit_logger.log_authentication_event(
                        db=db,
                        event_type="MFA_SUCCESS",
                        username=user.username,
                        user_id=user.id,
                        session_id=session_id,
                        additional_data={"method": "TOTP"},
                        success=True
                    )
                    return True
            
            # Try backup codes
            if verification_code.upper() in mfa_secret.backup_codes:
                # Remove used backup code
                mfa_secret.backup_codes.remove(verification_code.upper())
                mfa_secret.last_used = datetime.utcnow()
                
                await audit_logger.log_authentication_event(
                    db=db,
                    event_type="MFA_SUCCESS",
                    username=user.username,
                    user_id=user.id,
                    session_id=session_id,
                    additional_data={"method": "BACKUP_CODE"},
                    success=True
                )
                return True
            
            # Log failed verification
            await audit_logger.log_authentication_event(
                db=db,
                event_type="MFA_FAILURE",
                username=user.username,
                user_id=user.id,
                session_id=session_id,
                additional_data={"method": mfa_secret.method.value},
                success=False,
                failure_reason="INVALID_CODE"
            )
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to verify MFA code for user {user.id}: {e}")
            return False
    
    async def disable_mfa(
        self,
        db: AsyncSession,
        user: User,
        confirmation_code: str = None
    ) -> bool:
        """Disable MFA for a user (with verification)."""
        try:
            if user.id not in self.mfa_secrets:
                return True  # Already disabled
            
            # If confirmation code provided, verify it first
            if confirmation_code:
                if not await self.verify_mfa_code(db, user, confirmation_code):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid confirmation code"
                    )
            
            # Remove MFA secret
            del self.mfa_secrets[user.id]
            
            # Log MFA disable
            await audit_logger.log_authentication_event(
                db=db,
                event_type="MFA_DISABLED",
                username=user.username,
                user_id=user.id,
                success=True
            )
            
            return True
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to disable MFA for user {user.id}: {e}")
            return False
    
    def is_mfa_enabled(self, user_id: int) -> bool:
        """Check if MFA is enabled for a user."""
        return (user_id in self.mfa_secrets and 
                self.mfa_secrets[user_id].verified)
    
    def requires_mfa(self, user: User) -> bool:
        """Check if user requires MFA based on role and policies."""
        # Require MFA for admin users
        if user.role == UserRole.ADMIN:
            return True
        
        # Can be extended with more complex policies
        return self.is_mfa_enabled(user.id)
    
    async def generate_backup_codes(
        self,
        db: AsyncSession,
        user: User,
        count: int = 10
    ) -> List[str]:
        """Generate new backup codes for a user."""
        try:
            if user.id not in self.mfa_secrets:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="MFA not enabled"
                )
            
            mfa_secret = self.mfa_secrets[user.id]
            
            # Generate new backup codes
            new_codes = [secrets.token_hex(4).upper() for _ in range(count)]
            mfa_secret.backup_codes = new_codes
            
            # Log backup code regeneration
            await audit_logger.log_authentication_event(
                db=db,
                event_type="MFA_BACKUP_CODES_GENERATED",
                username=user.username,
                user_id=user.id,
                additional_data={"count": count},
                success=True
            )
            
            return new_codes
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to generate backup codes for user {user.id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate backup codes"
            )


# Global instances
rbac_manager = RBACManager()
mfa_manager = MFAManager()