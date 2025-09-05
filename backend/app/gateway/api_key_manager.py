"""
API Key Management and Rotation System.

This module provides secure management of API keys for external SIS providers
including automatic rotation, encryption, and comprehensive audit logging.
"""
import asyncio
import logging
import secrets
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
import json
import base64
import hashlib

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.services.api_gateway import ProviderType


logger = logging.getLogger(__name__)


class KeyStatus(str, Enum):
    """API key status states."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ROTATING = "rotating"
    EXPIRED = "expired"
    COMPROMISED = "compromised"


class KeyType(str, Enum):
    """Types of API keys."""
    PRIMARY = "primary"
    SECONDARY = "secondary"
    BACKUP = "backup"
    TESTING = "testing"


@dataclass
class APIKey:
    """Represents an API key with metadata."""
    key_id: str
    key_value: str
    provider: str
    key_type: KeyType = KeyType.PRIMARY
    status: KeyStatus = KeyStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    usage_count: int = 0
    rotation_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_expired(self) -> bool:
        """Check if key is expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    @property
    def days_until_expiry(self) -> Optional[int]:
        """Get days until expiry."""
        if not self.expires_at:
            return None
        delta = self.expires_at - datetime.utcnow()
        return max(0, delta.days)
    
    @property
    def age_days(self) -> int:
        """Get age of key in days."""
        delta = datetime.utcnow() - self.created_at
        return delta.days
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'key_id': self.key_id,
            'key_value': self.key_value,  # Will be encrypted when stored
            'provider': self.provider,
            'key_type': self.key_type.value,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'last_used': self.last_used.isoformat() if self.last_used else None,
            'usage_count': self.usage_count,
            'rotation_count': self.rotation_count,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'APIKey':
        """Create APIKey from dictionary."""
        return cls(
            key_id=data['key_id'],
            key_value=data['key_value'],
            provider=data['provider'],
            key_type=KeyType(data['key_type']),
            status=KeyStatus(data['status']),
            created_at=datetime.fromisoformat(data['created_at']),
            expires_at=datetime.fromisoformat(data['expires_at']) if data['expires_at'] else None,
            last_used=datetime.fromisoformat(data['last_used']) if data['last_used'] else None,
            usage_count=data['usage_count'],
            rotation_count=data['rotation_count'],
            metadata=data['metadata']
        )


@dataclass
class RotationConfig:
    """Configuration for automatic key rotation."""
    provider: str
    rotation_interval_days: int = 90  # Rotate every 90 days
    warning_days: int = 14  # Warn 14 days before expiry
    overlap_days: int = 7  # Keep old key active for 7 days during rotation
    auto_rotation_enabled: bool = True
    backup_key_count: int = 2
    max_key_age_days: int = 365
    
    def should_rotate(self, key: APIKey) -> bool:
        """Check if key should be rotated."""
        if not self.auto_rotation_enabled:
            return False
        
        # Check age-based rotation
        if key.age_days >= self.rotation_interval_days:
            return True
        
        # Check expiry-based rotation
        if key.days_until_expiry and key.days_until_expiry <= self.warning_days:
            return True
        
        # Check if key is compromised
        if key.status == KeyStatus.COMPROMISED:
            return True
        
        return False


@dataclass
class AuditLog:
    """Audit log entry for key operations."""
    timestamp: datetime
    operation: str
    key_id: str
    provider: str
    user_id: Optional[str] = None
    ip_address: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'operation': self.operation,
            'key_id': self.key_id,
            'provider': self.provider,
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'details': self.details,
            'success': self.success
        }


class KeyEncryption:
    """Handles encryption and decryption of API keys."""
    
    def __init__(self, encryption_key: Optional[bytes] = None):
        if encryption_key:
            self.fernet = Fernet(encryption_key)
        else:
            # Generate a new encryption key
            self.fernet = Fernet(Fernet.generate_key())
    
    @classmethod
    def from_password(cls, password: str, salt: Optional[bytes] = None) -> 'KeyEncryption':
        """Create encryption from password."""
        if salt is None:
            salt = secrets.token_bytes(16)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return cls(key)
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string."""
        return self.fernet.encrypt(plaintext.encode()).decode()
    
    def decrypt(self, encrypted_text: str) -> str:
        """Decrypt a string."""
        return self.fernet.decrypt(encrypted_text.encode()).decode()
    
    def get_key(self) -> bytes:
        """Get the encryption key."""
        return self.fernet._encryption_key


class APIKeyManager:
    """
    Comprehensive API key management system.
    
    Features:
    - Secure key storage with encryption
    - Automatic key rotation
    - Usage tracking and analytics
    - Audit logging
    - Key lifecycle management
    - Provider-specific configurations
    """
    
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        encryption_password: Optional[str] = None
    ):
        self.storage_path = storage_path or Path("keys")
        self.storage_path.mkdir(exist_ok=True)
        
        # Initialize encryption
        if encryption_password:
            self.encryption = KeyEncryption.from_password(encryption_password)
        else:
            self.encryption = KeyEncryption()
        
        # Storage
        self.keys: Dict[str, APIKey] = {}
        self.rotation_configs: Dict[str, RotationConfig] = {}
        self.audit_logs: List[AuditLog] = []
        
        # Background tasks
        self._rotation_task: Optional[asyncio.Task] = None
        self._monitoring_task: Optional[asyncio.Task] = None
        self._stop_background_tasks = False
        
        # Load existing data
        asyncio.create_task(self._load_data())
        
        logger.info("API Key Manager initialized")
    
    async def start(self):
        """Start background tasks."""
        self._stop_background_tasks = False
        
        # Start rotation monitoring
        self._rotation_task = asyncio.create_task(self._rotation_monitor())
        
        # Start key monitoring
        self._monitoring_task = asyncio.create_task(self._key_monitor())
        
        logger.info("API Key Manager background tasks started")
    
    async def stop(self):
        """Stop background tasks."""
        self._stop_background_tasks = True
        
        if self._rotation_task:
            self._rotation_task.cancel()
            
        if self._monitoring_task:
            self._monitoring_task.cancel()
        
        # Save data
        await self._save_data()
        
        logger.info("API Key Manager stopped")
    
    async def create_key(
        self,
        provider: str,
        key_value: str,
        key_type: KeyType = KeyType.PRIMARY,
        expires_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ) -> APIKey:
        """Create a new API key."""
        key_id = self._generate_key_id(provider)
        
        api_key = APIKey(
            key_id=key_id,
            key_value=key_value,
            provider=provider,
            key_type=key_type,
            expires_at=expires_at,
            metadata=metadata or {}
        )
        
        # Store the key
        self.keys[key_id] = api_key
        
        # Log the operation
        await self._log_operation(
            "key_created",
            key_id,
            provider,
            user_id=user_id,
            details={
                'key_type': key_type.value,
                'expires_at': expires_at.isoformat() if expires_at else None
            }
        )
        
        # Save to storage
        await self._save_data()
        
        logger.info(f"Created API key {key_id} for {provider}")
        return api_key
    
    async def get_active_key(self, provider: str, key_type: KeyType = KeyType.PRIMARY) -> Optional[APIKey]:
        """Get active API key for a provider."""
        for key in self.keys.values():
            if (
                key.provider == provider and
                key.key_type == key_type and
                key.status == KeyStatus.ACTIVE and
                not key.is_expired
            ):
                # Update usage
                key.last_used = datetime.utcnow()
                key.usage_count += 1
                return key
        
        return None
    
    async def get_key_by_id(self, key_id: str) -> Optional[APIKey]:
        """Get key by ID."""
        return self.keys.get(key_id)
    
    async def update_key_status(
        self,
        key_id: str,
        status: KeyStatus,
        user_id: Optional[str] = None,
        reason: Optional[str] = None
    ) -> bool:
        """Update key status."""
        key = self.keys.get(key_id)
        if not key:
            return False
        
        old_status = key.status
        key.status = status
        
        # Log the operation
        await self._log_operation(
            "key_status_updated",
            key_id,
            key.provider,
            user_id=user_id,
            details={
                'old_status': old_status.value,
                'new_status': status.value,
                'reason': reason
            }
        )
        
        await self._save_data()
        
        logger.info(f"Updated key {key_id} status: {old_status} -> {status}")
        return True
    
    async def rotate_key(
        self,
        provider: str,
        new_key_value: str,
        user_id: Optional[str] = None,
        force: bool = False
    ) -> Tuple[APIKey, Optional[APIKey]]:
        """
        Rotate API key for a provider.
        
        Returns:
            Tuple of (new_key, old_key)
        """
        # Get current active key
        old_key = await self.get_active_key(provider)
        
        if not old_key and not force:
            raise ValueError(f"No active key found for {provider}")
        
        # Create new key
        expires_at = datetime.utcnow() + timedelta(days=365)  # Default 1 year expiry
        new_key = await self.create_key(
            provider=provider,
            key_value=new_key_value,
            key_type=KeyType.PRIMARY,
            expires_at=expires_at,
            user_id=user_id
        )
        
        # Update old key status
        if old_key:
            old_key.status = KeyStatus.ROTATING
            old_key.rotation_count += 1
            
            # Schedule deactivation after overlap period
            rotation_config = self.rotation_configs.get(provider, RotationConfig(provider))
            deactivation_time = datetime.utcnow() + timedelta(days=rotation_config.overlap_days)
            
            # Store deactivation schedule in metadata
            old_key.metadata['deactivate_at'] = deactivation_time.isoformat()
        
        # Log the operation
        await self._log_operation(
            "key_rotated",
            new_key.key_id,
            provider,
            user_id=user_id,
            details={
                'old_key_id': old_key.key_id if old_key else None,
                'new_key_id': new_key.key_id
            }
        )
        
        await self._save_data()
        
        logger.info(f"Rotated key for {provider}: {old_key.key_id if old_key else None} -> {new_key.key_id}")
        return new_key, old_key
    
    async def delete_key(self, key_id: str, user_id: Optional[str] = None) -> bool:
        """Delete an API key."""
        key = self.keys.get(key_id)
        if not key:
            return False
        
        # Log before deletion
        await self._log_operation(
            "key_deleted",
            key_id,
            key.provider,
            user_id=user_id,
            details={
                'key_type': key.key_type.value,
                'status': key.status.value
            }
        )
        
        # Remove from storage
        del self.keys[key_id]
        
        await self._save_data()
        
        logger.info(f"Deleted key {key_id}")
        return True
    
    def set_rotation_config(self, provider: str, config: RotationConfig):
        """Set rotation configuration for a provider."""
        self.rotation_configs[provider] = config
        logger.info(f"Set rotation config for {provider}: {config.rotation_interval_days} days")
    
    async def check_key_health(self) -> Dict[str, Any]:
        """Check health of all keys."""
        health_report = {
            'total_keys': len(self.keys),
            'active_keys': 0,
            'expired_keys': 0,
            'rotating_keys': 0,
            'compromised_keys': 0,
            'keys_needing_rotation': 0,
            'providers': {},
            'warnings': []
        }
        
        for key in self.keys.values():
            # Count by status
            if key.status == KeyStatus.ACTIVE:
                health_report['active_keys'] += 1
            elif key.status == KeyStatus.ROTATING:
                health_report['rotating_keys'] += 1
            elif key.status == KeyStatus.COMPROMISED:
                health_report['compromised_keys'] += 1
            
            if key.is_expired:
                health_report['expired_keys'] += 1
            
            # Check if rotation needed
            rotation_config = self.rotation_configs.get(key.provider, RotationConfig(key.provider))
            if rotation_config.should_rotate(key):
                health_report['keys_needing_rotation'] += 1
            
            # Provider statistics
            if key.provider not in health_report['providers']:
                health_report['providers'][key.provider] = {
                    'total': 0,
                    'active': 0,
                    'needs_rotation': 0
                }
            
            provider_stats = health_report['providers'][key.provider]
            provider_stats['total'] += 1
            
            if key.status == KeyStatus.ACTIVE:
                provider_stats['active'] += 1
            
            if rotation_config.should_rotate(key):
                provider_stats['needs_rotation'] += 1
            
            # Generate warnings
            if key.is_expired and key.status == KeyStatus.ACTIVE:
                health_report['warnings'].append(f"Key {key.key_id} is expired but still active")
            
            if key.days_until_expiry and key.days_until_expiry <= 7:
                health_report['warnings'].append(f"Key {key.key_id} expires in {key.days_until_expiry} days")
        
        return health_report
    
    def get_usage_statistics(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """Get key usage statistics."""
        keys_to_analyze = [
            key for key in self.keys.values()
            if not provider or key.provider == provider
        ]
        
        if not keys_to_analyze:
            return {}
        
        total_usage = sum(key.usage_count for key in keys_to_analyze)
        active_keys = [key for key in keys_to_analyze if key.status == KeyStatus.ACTIVE]
        
        stats = {
            'total_keys': len(keys_to_analyze),
            'active_keys': len(active_keys),
            'total_usage': total_usage,
            'average_usage': total_usage / len(keys_to_analyze) if keys_to_analyze else 0,
            'most_used_key': None,
            'least_used_key': None,
            'usage_by_provider': {}
        }
        
        if keys_to_analyze:
            # Most and least used keys
            most_used = max(keys_to_analyze, key=lambda k: k.usage_count)
            least_used = min(keys_to_analyze, key=lambda k: k.usage_count)
            
            stats['most_used_key'] = {
                'key_id': most_used.key_id,
                'provider': most_used.provider,
                'usage_count': most_used.usage_count
            }
            
            stats['least_used_key'] = {
                'key_id': least_used.key_id,
                'provider': least_used.provider,
                'usage_count': least_used.usage_count
            }
        
        # Usage by provider
        provider_usage = {}
        for key in keys_to_analyze:
            if key.provider not in provider_usage:
                provider_usage[key.provider] = {'count': 0, 'usage': 0}
            
            provider_usage[key.provider]['count'] += 1
            provider_usage[key.provider]['usage'] += key.usage_count
        
        stats['usage_by_provider'] = provider_usage
        
        return stats
    
    def get_audit_logs(self, limit: int = 100, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get audit logs."""
        logs = self.audit_logs
        
        if provider:
            logs = [log for log in logs if log.provider == provider]
        
        # Sort by timestamp (newest first) and limit
        logs = sorted(logs, key=lambda l: l.timestamp, reverse=True)[:limit]
        
        return [log.to_dict() for log in logs]
    
    def _generate_key_id(self, provider: str) -> str:
        """Generate unique key ID."""
        timestamp = int(time.time() * 1000)
        random_part = secrets.token_hex(8)
        return f"{provider}_{timestamp}_{random_part}"
    
    async def _rotation_monitor(self):
        """Background task to monitor and perform automatic rotations."""
        while not self._stop_background_tasks:
            try:
                for key in list(self.keys.values()):
                    rotation_config = self.rotation_configs.get(key.provider, RotationConfig(key.provider))
                    
                    if rotation_config.should_rotate(key) and rotation_config.auto_rotation_enabled:
                        logger.warning(f"Key {key.key_id} needs rotation for {key.provider}")
                        
                        # In a real implementation, this would trigger an external process
                        # to generate a new key from the SIS provider
                        await self._log_operation(
                            "rotation_needed",
                            key.key_id,
                            key.provider,
                            details={'reason': 'automatic_rotation_check'}
                        )
                
                # Check every 24 hours
                await asyncio.sleep(24 * 3600)
                
            except Exception as e:
                logger.error(f"Error in rotation monitor: {e}")
                await asyncio.sleep(3600)  # Wait 1 hour on error
    
    async def _key_monitor(self):
        """Background task to monitor key health and handle deactivations."""
        while not self._stop_background_tasks:
            try:
                current_time = datetime.utcnow()
                
                for key in list(self.keys.values()):
                    # Handle scheduled deactivations
                    deactivate_at_str = key.metadata.get('deactivate_at')
                    if deactivate_at_str:
                        deactivate_at = datetime.fromisoformat(deactivate_at_str)
                        if current_time >= deactivate_at and key.status == KeyStatus.ROTATING:
                            await self.update_key_status(key.key_id, KeyStatus.INACTIVE, reason="rotation_complete")
                            del key.metadata['deactivate_at']
                    
                    # Handle expired keys
                    if key.is_expired and key.status == KeyStatus.ACTIVE:
                        await self.update_key_status(key.key_id, KeyStatus.EXPIRED, reason="automatic_expiry")
                
                # Check every hour
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"Error in key monitor: {e}")
                await asyncio.sleep(1800)  # Wait 30 minutes on error
    
    async def _log_operation(
        self,
        operation: str,
        key_id: str,
        provider: str,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True
    ):
        """Log an operation to audit log."""
        log_entry = AuditLog(
            timestamp=datetime.utcnow(),
            operation=operation,
            key_id=key_id,
            provider=provider,
            user_id=user_id,
            ip_address=ip_address,
            details=details or {},
            success=success
        )
        
        self.audit_logs.append(log_entry)
        
        # Keep only last 10000 log entries
        if len(self.audit_logs) > 10000:
            self.audit_logs = self.audit_logs[-10000:]
    
    async def _load_data(self):
        """Load keys and configurations from storage."""
        try:
            # Load keys
            keys_file = self.storage_path / "keys.json"
            if keys_file.exists():
                with open(keys_file, 'r') as f:
                    encrypted_data = json.load(f)
                
                decrypted_data = self.encryption.decrypt(encrypted_data['data'])
                keys_data = json.loads(decrypted_data)
                
                for key_data in keys_data:
                    key = APIKey.from_dict(key_data)
                    self.keys[key.key_id] = key
                
                logger.info(f"Loaded {len(self.keys)} API keys")
            
            # Load rotation configs
            config_file = self.storage_path / "rotation_configs.json"
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config_data = json.load(f)
                
                for provider, config_dict in config_data.items():
                    self.rotation_configs[provider] = RotationConfig(**config_dict)
                
                logger.info(f"Loaded rotation configs for {len(self.rotation_configs)} providers")
            
            # Load audit logs
            logs_file = self.storage_path / "audit_logs.json"
            if logs_file.exists():
                with open(logs_file, 'r') as f:
                    logs_data = json.load(f)
                
                for log_data in logs_data:
                    log_entry = AuditLog(**{
                        **log_data,
                        'timestamp': datetime.fromisoformat(log_data['timestamp'])
                    })
                    self.audit_logs.append(log_entry)
                
                logger.info(f"Loaded {len(self.audit_logs)} audit log entries")
        
        except Exception as e:
            logger.error(f"Error loading data: {e}")
    
    async def _save_data(self):
        """Save keys and configurations to storage."""
        try:
            # Save keys
            keys_data = [key.to_dict() for key in self.keys.values()]
            encrypted_data = self.encryption.encrypt(json.dumps(keys_data))
            
            keys_file = self.storage_path / "keys.json"
            with open(keys_file, 'w') as f:
                json.dump({'data': encrypted_data}, f)
            
            # Save rotation configs
            config_data = {
                provider: {
                    'provider': config.provider,
                    'rotation_interval_days': config.rotation_interval_days,
                    'warning_days': config.warning_days,
                    'overlap_days': config.overlap_days,
                    'auto_rotation_enabled': config.auto_rotation_enabled,
                    'backup_key_count': config.backup_key_count,
                    'max_key_age_days': config.max_key_age_days
                }
                for provider, config in self.rotation_configs.items()
            }
            
            config_file = self.storage_path / "rotation_configs.json"
            with open(config_file, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            # Save audit logs (last 1000 entries only)
            recent_logs = self.audit_logs[-1000:] if len(self.audit_logs) > 1000 else self.audit_logs
            logs_data = [log.to_dict() for log in recent_logs]
            
            logs_file = self.storage_path / "audit_logs.json"
            with open(logs_file, 'w') as f:
                json.dump(logs_data, f, indent=2)
        
        except Exception as e:
            logger.error(f"Error saving data: {e}")


# Global key manager instance
api_key_manager = APIKeyManager()