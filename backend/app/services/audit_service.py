"""
Comprehensive Security Audit Service

Provides immutable audit trail logging with integrity verification.
Works alongside FERPA compliance audit logging for complete coverage.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc, asc
from sqlalchemy.orm import selectinload
from fastapi import Request, HTTPException, status
import logging
from contextlib import asynccontextmanager

from app.core.database import get_db
from app.models.audit_log import SecurityAuditLog, SecurityIncident, LoginAttempt, UserSession
from app.models.user import User
from app.compliance.access_logger import AccessLogger  # Coordinate with FERPA compliance


logger = logging.getLogger(__name__)


class SecurityAuditService:
    """
    Comprehensive security audit logging with integrity verification.
    
    Features:
    - Immutable audit trail with cryptographic integrity
    - Real-time event logging for all security events
    - Chain integrity verification
    - Automated risk assessment
    - Integration with FERPA compliance logging
    """
    
    def __init__(self):
        self.compliance_logger = AccessLogger()
        self._sequence_lock = asyncio.Lock()
        self._last_hash_cache: Optional[str] = None
        
    async def log_security_event(
        self,
        db: AsyncSession,
        event_type: str,
        event_category: str,
        message: str,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        session_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        event_data: Optional[Dict[str, Any]] = None,
        severity: str = "INFO",
        correlation_id: Optional[str] = None,
        risk_score: int = 0
    ) -> SecurityAuditLog:
        """
        Log a security event with integrity verification.
        
        Args:
            db: Database session
            event_type: Type of event (LOGIN_SUCCESS, DATA_ACCESS, etc.)
            event_category: Category (AUTHENTICATION, AUTHORIZATION, etc.)
            message: Human-readable description
            user_id: User ID if applicable
            username: Username if available
            session_id: Session identifier
            ip_address: Source IP address
            user_agent: User agent string
            endpoint: API endpoint accessed
            method: HTTP method
            event_data: Additional structured data
            severity: Event severity level
            correlation_id: ID to correlate related events
            risk_score: Risk assessment (0-100)
            
        Returns:
            Created SecurityAuditLog entry
        """
        try:
            async with self._sequence_lock:
                # Get next sequence number
                sequence_number = await self._get_next_sequence_number(db)
                
                # Get previous hash for chain integrity
                previous_hash = await self._get_last_hash(db)
                
                # Create audit log entry
                audit_log = SecurityAuditLog(
                    sequence_number=sequence_number,
                    event_type=event_type,
                    event_category=event_category,
                    severity=severity,
                    user_id=user_id,
                    username=username,
                    session_id=session_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    endpoint=endpoint,
                    method=method,
                    event_data=event_data,
                    message=message,
                    timestamp=datetime.utcnow(),
                    risk_score=risk_score,
                    correlation_id=correlation_id,
                    previous_hash=previous_hash
                )
                
                # Calculate and set integrity hash
                audit_log.integrity_hash = audit_log.calculate_integrity_hash()
                
                # Perform risk assessment
                await self._assess_risk(audit_log, db)
                
                # Save to database
                db.add(audit_log)
                await db.commit()
                await db.refresh(audit_log)
                
                # Update cache
                self._last_hash_cache = audit_log.integrity_hash
                
                # If this is a FERPA-relevant event, also log to compliance system
                if await self._is_ferpa_relevant(event_type, event_data):
                    await self._log_to_compliance(
                        db, audit_log, user_id, event_data
                    )
                
                # Check for incident detection
                await self._check_incident_triggers(db, audit_log)
                
                logger.info(f"Security event logged: {event_type} (Sequence: {sequence_number})")
                return audit_log
                
        except Exception as e:
            logger.error(f"Failed to log security event: {e}")
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to log security event"
            )
    
    async def log_authentication_event(
        self,
        db: AsyncSession,
        username: str,
        success: bool,
        ip_address: str,
        user_agent: str = None,
        failure_reason: str = None,
        user_id: int = None,
        session_id: str = None,
        risk_factors: Dict[str, Any] = None
    ) -> LoginAttempt:
        """Log authentication attempt for security analysis."""
        try:
            # Create login attempt record
            login_attempt = LoginAttempt(
                username=username,
                ip_address=ip_address,
                user_agent=user_agent,
                success=success,
                failure_reason=failure_reason,
                attempted_at=datetime.utcnow(),
                risk_factors=risk_factors,
                session_id=session_id
            )
            
            # Assess if this attempt is suspicious
            await self._assess_login_risk(db, login_attempt)
            
            db.add(login_attempt)
            
            # Log corresponding security event
            event_type = "LOGIN_SUCCESS" if success else "LOGIN_FAILURE"
            event_data = {
                "username": username,
                "failure_reason": failure_reason,
                "risk_factors": risk_factors
            }
            
            await self.log_security_event(
                db=db,
                event_type=event_type,
                event_category="AUTHENTICATION",
                message=f"Login {'successful' if success else 'failed'} for user {username}",
                user_id=user_id,
                username=username,
                session_id=session_id,
                ip_address=ip_address,
                user_agent=user_agent,
                event_data=event_data,
                severity="INFO" if success else "MEDIUM",
                risk_score=login_attempt.risk_factors.get('risk_score', 0) if risk_factors else 0
            )
            
            await db.commit()
            return login_attempt
            
        except Exception as e:
            logger.error(f"Failed to log authentication event: {e}")
            await db.rollback()
            raise
    
    async def create_user_session(
        self,
        db: AsyncSession,
        user_id: int,
        username: str,
        session_id: str,
        ip_address: str,
        user_agent: str = None,
        expires_at: datetime = None,
        requires_mfa: bool = False
    ) -> UserSession:
        """Create and track a new user session."""
        try:
            if expires_at is None:
                expires_at = datetime.utcnow() + timedelta(hours=8)  # Default 8-hour session
            
            session = UserSession(
                session_id=session_id,
                user_id=user_id,
                username=username,
                ip_address=ip_address,
                user_agent=user_agent,
                started_at=datetime.utcnow(),
                last_activity=datetime.utcnow(),
                expires_at=expires_at,
                requires_mfa=requires_mfa
            )
            
            db.add(session)
            
            # Log session creation
            await self.log_security_event(
                db=db,
                event_type="SESSION_CREATED",
                event_category="AUTHENTICATION",
                message=f"New session created for user {username}",
                user_id=user_id,
                username=username,
                session_id=session_id,
                ip_address=ip_address,
                user_agent=user_agent,
                event_data={"expires_at": expires_at.isoformat(), "requires_mfa": requires_mfa}
            )
            
            await db.commit()
            return session
            
        except Exception as e:
            logger.error(f"Failed to create user session: {e}")
            await db.rollback()
            raise
    
    async def update_session_activity(
        self,
        db: AsyncSession,
        session_id: str
    ) -> Optional[UserSession]:
        """Update last activity time for a session."""
        try:
            result = await db.execute(
                select(UserSession).where(
                    and_(
                        UserSession.session_id == session_id,
                        UserSession.is_active == True
                    )
                )
            )
            session = result.scalar_one_or_none()
            
            if session:
                session.last_activity = datetime.utcnow()
                await db.commit()
                
            return session
            
        except Exception as e:
            logger.error(f"Failed to update session activity: {e}")
            return None
    
    async def end_user_session(
        self,
        db: AsyncSession,
        session_id: str,
        end_reason: str = "LOGOUT"
    ) -> Optional[UserSession]:
        """End a user session and log the event."""
        try:
            result = await db.execute(
                select(UserSession).where(UserSession.session_id == session_id)
            )
            session = result.scalar_one_or_none()
            
            if session and session.is_active:
                session.is_active = False
                session.ended_at = datetime.utcnow()
                session.end_reason = end_reason
                
                # Log session end
                await self.log_security_event(
                    db=db,
                    event_type="SESSION_ENDED",
                    event_category="AUTHENTICATION",
                    message=f"Session ended for user {session.username} ({end_reason})",
                    user_id=session.user_id,
                    username=session.username,
                    session_id=session_id,
                    ip_address=session.ip_address,
                    event_data={"end_reason": end_reason}
                )
                
                await db.commit()
                
            return session
            
        except Exception as e:
            logger.error(f"Failed to end user session: {e}")
            await db.rollback()
            return None
    
    async def verify_audit_chain_integrity(
        self,
        db: AsyncSession,
        start_sequence: int = None,
        end_sequence: int = None
    ) -> Dict[str, Any]:
        """
        Verify the integrity of the audit chain.
        
        Returns:
            Dictionary with verification results
        """
        try:
            query = select(SecurityAuditLog).order_by(asc(SecurityAuditLog.sequence_number))
            
            if start_sequence is not None:
                query = query.where(SecurityAuditLog.sequence_number >= start_sequence)
            if end_sequence is not None:
                query = query.where(SecurityAuditLog.sequence_number <= end_sequence)
                
            result = await db.execute(query)
            audit_logs = result.scalars().all()
            
            verification_result = {
                "verified": True,
                "total_entries": len(audit_logs),
                "verification_errors": [],
                "chain_breaks": [],
                "hash_mismatches": []
            }
            
            previous_hash = None
            for audit_log in audit_logs:
                # Verify individual entry integrity
                if not audit_log.verify_integrity():
                    verification_result["verified"] = False
                    verification_result["hash_mismatches"].append({
                        "sequence": audit_log.sequence_number,
                        "id": str(audit_log.id),
                        "expected_hash": audit_log.calculate_integrity_hash(),
                        "stored_hash": audit_log.integrity_hash
                    })
                
                # Verify chain integrity
                if previous_hash is not None and audit_log.previous_hash != previous_hash:
                    verification_result["verified"] = False
                    verification_result["chain_breaks"].append({
                        "sequence": audit_log.sequence_number,
                        "expected_previous_hash": previous_hash,
                        "stored_previous_hash": audit_log.previous_hash
                    })
                
                previous_hash = audit_log.integrity_hash
            
            return verification_result
            
        except Exception as e:
            logger.error(f"Failed to verify audit chain integrity: {e}")
            return {
                "verified": False,
                "error": str(e),
                "total_entries": 0,
                "verification_errors": [],
                "chain_breaks": [],
                "hash_mismatches": []
            }
    
    async def get_audit_logs(
        self,
        db: AsyncSession,
        user_id: Optional[int] = None,
        event_type: Optional[str] = None,
        event_category: Optional[str] = None,
        severity: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        ip_address: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[SecurityAuditLog]:
        """Query audit logs with filtering."""
        try:
            query = select(SecurityAuditLog)
            
            # Apply filters
            if user_id is not None:
                query = query.where(SecurityAuditLog.user_id == user_id)
            if event_type:
                query = query.where(SecurityAuditLog.event_type == event_type)
            if event_category:
                query = query.where(SecurityAuditLog.event_category == event_category)
            if severity:
                query = query.where(SecurityAuditLog.severity == severity)
            if start_time:
                query = query.where(SecurityAuditLog.timestamp >= start_time)
            if end_time:
                query = query.where(SecurityAuditLog.timestamp <= end_time)
            if ip_address:
                query = query.where(SecurityAuditLog.ip_address == ip_address)
            
            # Apply pagination and ordering
            query = query.order_by(desc(SecurityAuditLog.timestamp))
            query = query.offset(offset).limit(limit)
            
            result = await db.execute(query)
            return result.scalars().all()
            
        except Exception as e:
            logger.error(f"Failed to get audit logs: {e}")
            return []
    
    # Private helper methods
    
    async def _get_next_sequence_number(self, db: AsyncSession) -> int:
        """Get the next sequence number for audit logs."""
        result = await db.execute(
            select(func.coalesce(func.max(SecurityAuditLog.sequence_number), 0))
        )
        max_sequence = result.scalar()
        return max_sequence + 1
    
    async def _get_last_hash(self, db: AsyncSession) -> Optional[str]:
        """Get the hash of the last audit log entry for chain integrity."""
        if self._last_hash_cache:
            return self._last_hash_cache
            
        result = await db.execute(
            select(SecurityAuditLog.integrity_hash)
            .order_by(desc(SecurityAuditLog.sequence_number))
            .limit(1)
        )
        last_hash = result.scalar_one_or_none()
        
        if last_hash:
            self._last_hash_cache = last_hash
            
        return last_hash
    
    async def _assess_risk(self, audit_log: SecurityAuditLog, db: AsyncSession):
        """Assess risk level for the audit log entry."""
        risk_score = audit_log.risk_score
        
        # Additional risk assessment based on patterns
        if audit_log.event_type in ['LOGIN_FAILURE', 'PERMISSION_DENIED']:
            # Check for repeated failures
            recent_failures = await db.execute(
                select(func.count(SecurityAuditLog.id))
                .where(
                    and_(
                        SecurityAuditLog.event_type == audit_log.event_type,
                        SecurityAuditLog.ip_address == audit_log.ip_address,
                        SecurityAuditLog.timestamp >= datetime.utcnow() - timedelta(minutes=15)
                    )
                )
            )
            failure_count = recent_failures.scalar()
            
            if failure_count >= 5:
                risk_score = max(risk_score, 80)
                audit_log.is_suspicious = True
            elif failure_count >= 3:
                risk_score = max(risk_score, 60)
        
        audit_log.risk_score = risk_score
        
        if risk_score >= 70:
            audit_log.is_suspicious = True
    
    async def _is_ferpa_relevant(self, event_type: str, event_data: Dict[str, Any]) -> bool:
        """Check if event is relevant for FERPA compliance logging."""
        ferpa_relevant_events = {
            'DATA_ACCESS', 'DATA_EXPORT', 'DATA_DELETE', 'DATA_IMPORT',
            'PERMISSION_GRANTED', 'PERMISSION_DENIED'
        }
        
        return event_type in ferpa_relevant_events
    
    async def _log_to_compliance(
        self,
        db: AsyncSession,
        audit_log: SecurityAuditLog,
        user_id: Optional[int],
        event_data: Optional[Dict[str, Any]]
    ):
        """Log FERPA-relevant events to compliance system."""
        try:
            if user_id and event_data:
                await self.compliance_logger.log_access(
                    db=db,
                    user_id=user_id,
                    resource_type=event_data.get('resource_type', 'unknown'),
                    resource_id=event_data.get('resource_id'),
                    action=audit_log.event_type.lower(),
                    ip_address=audit_log.ip_address
                )
        except Exception as e:
            logger.warning(f"Failed to log to compliance system: {e}")
    
    async def _assess_login_risk(self, db: AsyncSession, login_attempt: LoginAttempt):
        """Assess risk factors for login attempt."""
        risk_factors = login_attempt.risk_factors or {}
        risk_score = 0
        
        # Check for recent failed attempts from same IP
        recent_failures = await db.execute(
            select(func.count(LoginAttempt.id))
            .where(
                and_(
                    LoginAttempt.ip_address == login_attempt.ip_address,
                    LoginAttempt.success == False,
                    LoginAttempt.attempted_at >= datetime.utcnow() - timedelta(hours=1)
                )
            )
        )
        failure_count = recent_failures.scalar()
        
        if failure_count >= 10:
            risk_score = 100
            login_attempt.is_suspicious = True
        elif failure_count >= 5:
            risk_score = 80
            login_attempt.is_suspicious = True
        elif failure_count >= 3:
            risk_score = 60
        
        risk_factors.update({
            'recent_failures': failure_count,
            'risk_score': risk_score
        })
        
        login_attempt.risk_factors = risk_factors
    
    async def _check_incident_triggers(self, db: AsyncSession, audit_log: SecurityAuditLog):
        """Check if this audit log should trigger incident creation."""
        if audit_log.is_suspicious or audit_log.risk_score >= 80:
            # Import here to avoid circular imports
            from app.security.incident_response import IncidentResponseSystem
            
            incident_system = IncidentResponseSystem()
            await incident_system.evaluate_for_incident(db, audit_log)


# Global service instance
security_audit_service = SecurityAuditService()