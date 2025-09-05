"""Notification audit trails and compliance logging service."""

import logging
import json
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import uuid

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc

from app.core.database import Base
from app.models.notifications import Notification, NotificationDelivery

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    """Types of audit events."""
    NOTIFICATION_CREATED = "notification_created"
    NOTIFICATION_SENT = "notification_sent"
    NOTIFICATION_DELIVERED = "notification_delivered"
    NOTIFICATION_FAILED = "notification_failed"
    NOTIFICATION_RETRY = "notification_retry"
    NOTIFICATION_CANCELLED = "notification_cancelled"
    PREFERENCES_UPDATED = "preferences_updated"
    CONTACT_ADDED = "contact_added"
    CONTACT_UPDATED = "contact_updated"
    CONTACT_REMOVED = "contact_removed"
    BULK_OPERATION_STARTED = "bulk_operation_started"
    BULK_OPERATION_COMPLETED = "bulk_operation_completed"
    WEBHOOK_RECEIVED = "webhook_received"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    PRIVACY_REQUEST = "privacy_request"
    DATA_EXPORT = "data_export"
    DATA_DELETION = "data_deletion"


class AuditSeverity(str, Enum):
    """Severity levels for audit events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationAuditLog(Base):
    """Comprehensive audit log for notification system activities."""
    __tablename__ = "notification_audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Event identification
    event_id = Column(String(36), unique=True, nullable=False, index=True)  # UUID
    event_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), nullable=False, index=True)
    
    # Timestamp and source
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    source_ip = Column(String(45), nullable=True)  # IPv6 support
    user_agent = Column(Text, nullable=True)
    
    # Actor information
    actor_type = Column(String(50), nullable=True)  # user, system, webhook, api
    actor_id = Column(Integer, nullable=True, index=True)  # User ID or system component ID
    actor_name = Column(String(255), nullable=True)
    
    # Target information
    target_type = Column(String(50), nullable=True)  # notification, user, contact, etc.
    target_id = Column(Integer, nullable=True, index=True)
    target_identifier = Column(String(255), nullable=True)  # Email, phone, etc.
    
    # Event details
    action = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    
    # Data payload
    event_data = Column(JSON, nullable=True)  # Structured event data
    previous_values = Column(JSON, nullable=True)  # For change tracking
    new_values = Column(JSON, nullable=True)  # For change tracking
    
    # Context information
    session_id = Column(String(255), nullable=True, index=True)
    request_id = Column(String(255), nullable=True, index=True)
    correlation_id = Column(String(255), nullable=True, index=True)  # For tracing across services
    
    # Compliance fields
    retention_until = Column(DateTime(timezone=True), nullable=True, index=True)
    is_sensitive = Column(Boolean, default=False, index=True)
    anonymized = Column(Boolean, default=False)
    
    # Integrity protection
    checksum = Column(String(64), nullable=True)  # SHA-256 of critical fields
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_audit_timestamp_type', 'timestamp', 'event_type'),
        Index('idx_audit_actor_target', 'actor_id', 'target_id'),
        Index('idx_audit_session_request', 'session_id', 'request_id'),
    )


class ComplianceReport(Base):
    """Compliance and audit reports."""
    __tablename__ = "compliance_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Report identification
    report_id = Column(String(36), unique=True, nullable=False)
    report_type = Column(String(50), nullable=False)  # gdpr_export, audit_trail, etc.
    report_name = Column(String(255), nullable=False)
    
    # Report scope
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(Integer, nullable=True)  # For user-specific reports
    
    # Report content
    summary = Column(JSON, nullable=True)  # Summary statistics
    report_data = Column(JSON, nullable=True)  # Full report data
    file_path = Column(String(500), nullable=True)  # Path to exported file
    
    # Generation info
    generated_by = Column(Integer, nullable=True)  # User ID who generated
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Status
    status = Column(String(50), default="pending")  # pending, completed, failed, expired
    error_message = Column(Text, nullable=True)


@dataclass
class AuditEvent:
    """Structured audit event."""
    event_type: AuditEventType
    action: str
    description: str
    severity: AuditSeverity = AuditSeverity.INFO
    actor_type: Optional[str] = None
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    target_identifier: Optional[str] = None
    event_data: Dict[str, Any] = field(default_factory=dict)
    previous_values: Dict[str, Any] = field(default_factory=dict)
    new_values: Dict[str, Any] = field(default_factory=dict)
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    is_sensitive: bool = False
    retention_days: Optional[int] = None


class NotificationAuditService:
    """Service for comprehensive notification system audit trails."""
    
    def __init__(self):
        # Default retention periods by event type (in days)
        self.retention_periods = {
            AuditEventType.NOTIFICATION_CREATED: 2555,  # 7 years
            AuditEventType.NOTIFICATION_SENT: 2555,
            AuditEventType.NOTIFICATION_DELIVERED: 2555,
            AuditEventType.NOTIFICATION_FAILED: 2555,
            AuditEventType.PREFERENCES_UPDATED: 2555,
            AuditEventType.CONTACT_ADDED: 2555,
            AuditEventType.CONTACT_UPDATED: 2555,
            AuditEventType.CONTACT_REMOVED: 2555,
            AuditEventType.PRIVACY_REQUEST: 3650,  # 10 years
            AuditEventType.DATA_EXPORT: 1825,     # 5 years
            AuditEventType.DATA_DELETION: 3650,   # 10 years
            AuditEventType.WEBHOOK_RECEIVED: 365,  # 1 year
            AuditEventType.RATE_LIMIT_EXCEEDED: 90,  # 90 days
            AuditEventType.BULK_OPERATION_STARTED: 1825,  # 5 years
            AuditEventType.BULK_OPERATION_COMPLETED: 1825
        }
        
        logger.info("Notification Audit Service initialized")
    
    async def log_event(
        self,
        event: AuditEvent,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Log an audit event to the database.
        
        Args:
            event: Audit event to log
            db: Database session
            
        Returns:
            Dictionary with logging result
        """
        try:
            # Generate unique event ID
            event_id = str(uuid.uuid4())
            
            # Calculate retention date
            retention_days = event.retention_days or self.retention_periods.get(
                event.event_type, 2555  # Default to 7 years
            )
            retention_until = datetime.utcnow() + timedelta(days=retention_days)
            
            # Create audit log record
            audit_log = NotificationAuditLog(
                event_id=event_id,
                event_type=event.event_type.value,
                severity=event.severity.value,
                actor_type=event.actor_type,
                actor_id=event.actor_id,
                actor_name=event.actor_name,
                target_type=event.target_type,
                target_id=event.target_id,
                target_identifier=event.target_identifier,
                action=event.action,
                description=event.description,
                event_data=event.event_data,
                previous_values=event.previous_values,
                new_values=event.new_values,
                source_ip=event.source_ip,
                user_agent=event.user_agent,
                session_id=event.session_id,
                request_id=event.request_id,
                correlation_id=event.correlation_id,
                retention_until=retention_until,
                is_sensitive=event.is_sensitive,
                anonymized=False
            )
            
            # Generate integrity checksum
            audit_log.checksum = self._generate_checksum(audit_log)
            
            db.add(audit_log)
            await db.flush()
            
            logger.debug(f"Logged audit event {event_id}: {event.action}")
            
            return {
                "success": True,
                "event_id": event_id,
                "audit_log_id": audit_log.id
            }
            
        except Exception as e:
            logger.error(f"Error logging audit event: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def log_notification_event(
        self,
        notification: Notification,
        event_type: AuditEventType,
        action: str,
        description: str,
        actor_id: Optional[int] = None,
        additional_data: Dict[str, Any] = None,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Log a notification-specific audit event."""
        event_data = {
            "notification_id": notification.id,
            "notification_type": notification.type.value,
            "priority": notification.priority.value,
            "user_id": notification.user_id,
            "title": notification.title[:100],  # Truncate for storage
            "status": notification.status.value
        }
        
        if additional_data:
            event_data.update(additional_data)
        
        event = AuditEvent(
            event_type=event_type,
            action=action,
            description=description,
            actor_type="system" if actor_id is None else "user",
            actor_id=actor_id,
            target_type="notification",
            target_id=notification.id,
            target_identifier=f"notification_{notification.id}",
            event_data=event_data,
            is_sensitive=True  # Notifications may contain PII
        )
        
        return await self.log_event(event, db)
    
    async def log_delivery_event(
        self,
        delivery: NotificationDelivery,
        event_type: AuditEventType,
        action: str,
        description: str,
        additional_data: Dict[str, Any] = None,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Log a delivery-specific audit event."""
        event_data = {
            "delivery_id": delivery.id,
            "notification_id": delivery.notification_id,
            "platform": delivery.platform.value,
            "status": delivery.status.value,
            "platform_message_id": delivery.platform_message_id
        }
        
        if additional_data:
            event_data.update(additional_data)
        
        event = AuditEvent(
            event_type=event_type,
            action=action,
            description=description,
            actor_type="system",
            target_type="delivery",
            target_id=delivery.id,
            target_identifier=f"delivery_{delivery.id}",
            event_data=event_data,
            is_sensitive=True
        )
        
        return await self.log_event(event, db)
    
    async def log_bulk_operation(
        self,
        operation_type: str,
        total_targets: int,
        actor_id: Optional[int] = None,
        job_id: Optional[str] = None,
        additional_data: Dict[str, Any] = None,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Log bulk operation events."""
        event_data = {
            "operation_type": operation_type,
            "total_targets": total_targets,
            "job_id": job_id
        }
        
        if additional_data:
            event_data.update(additional_data)
        
        event = AuditEvent(
            event_type=AuditEventType.BULK_OPERATION_STARTED,
            action=f"bulk_{operation_type}_started",
            description=f"Bulk {operation_type} operation started for {total_targets} targets",
            actor_type="user" if actor_id else "system",
            actor_id=actor_id,
            target_type="bulk_operation",
            target_identifier=job_id,
            event_data=event_data
        )
        
        return await self.log_event(event, db)
    
    async def search_audit_logs(
        self,
        filters: Dict[str, Any],
        db: AsyncSession,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Search audit logs with various filters.
        
        Args:
            filters: Dictionary of search filters
            db: Database session
            limit: Maximum number of results
            offset: Offset for pagination
            
        Returns:
            Search results with pagination info
        """
        try:
            query = select(NotificationAuditLog)
            
            # Apply filters
            if filters.get("event_type"):
                query = query.where(NotificationAuditLog.event_type == filters["event_type"])
            
            if filters.get("actor_id"):
                query = query.where(NotificationAuditLog.actor_id == filters["actor_id"])
            
            if filters.get("target_id"):
                query = query.where(NotificationAuditLog.target_id == filters["target_id"])
            
            if filters.get("target_type"):
                query = query.where(NotificationAuditLog.target_type == filters["target_type"])
            
            if filters.get("severity"):
                query = query.where(NotificationAuditLog.severity == filters["severity"])
            
            if filters.get("start_date"):
                query = query.where(NotificationAuditLog.timestamp >= filters["start_date"])
            
            if filters.get("end_date"):
                query = query.where(NotificationAuditLog.timestamp <= filters["end_date"])
            
            if filters.get("session_id"):
                query = query.where(NotificationAuditLog.session_id == filters["session_id"])
            
            if filters.get("correlation_id"):
                query = query.where(NotificationAuditLog.correlation_id == filters["correlation_id"])
            
            # Count total results
            count_query = query.with_only_columns(func.count(NotificationAuditLog.id))
            result = await db.execute(count_query)
            total_count = result.scalar()
            
            # Apply ordering, limit, and offset
            query = query.order_by(desc(NotificationAuditLog.timestamp))
            query = query.limit(limit).offset(offset)
            
            # Execute query
            result = await db.execute(query)
            logs = result.scalars().all()
            
            # Convert to dictionaries
            log_data = []
            for log in logs:
                log_dict = {
                    "id": log.id,
                    "event_id": log.event_id,
                    "event_type": log.event_type,
                    "severity": log.severity,
                    "timestamp": log.timestamp.isoformat(),
                    "actor_type": log.actor_type,
                    "actor_id": log.actor_id,
                    "actor_name": log.actor_name,
                    "target_type": log.target_type,
                    "target_id": log.target_id,
                    "target_identifier": log.target_identifier,
                    "action": log.action,
                    "description": log.description,
                    "event_data": log.event_data,
                    "source_ip": log.source_ip,
                    "session_id": log.session_id,
                    "request_id": log.request_id,
                    "correlation_id": log.correlation_id,
                    "is_sensitive": log.is_sensitive,
                    "anonymized": log.anonymized
                }
                log_data.append(log_dict)
            
            return {
                "success": True,
                "logs": log_data,
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(logs) < total_count
            }
            
        except Exception as e:
            logger.error(f"Error searching audit logs: {e}")
            return {
                "success": False,
                "error": str(e),
                "logs": [],
                "total_count": 0
            }
    
    async def generate_compliance_report(
        self,
        report_type: str,
        start_date: datetime,
        end_date: datetime,
        user_id: Optional[int] = None,
        generated_by: Optional[int] = None,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Generate compliance report for audit data."""
        try:
            report_id = str(uuid.uuid4())
            
            # Generate report based on type
            if report_type == "gdpr_export":
                report_data = await self._generate_gdpr_export(
                    user_id, start_date, end_date, db
                )
            elif report_type == "audit_trail":
                report_data = await self._generate_audit_trail_report(
                    start_date, end_date, user_id, db
                )
            elif report_type == "delivery_summary":
                report_data = await self._generate_delivery_summary_report(
                    start_date, end_date, db
                )
            else:
                return {
                    "success": False,
                    "error": f"Unsupported report type: {report_type}"
                }
            
            # Create compliance report record
            report = ComplianceReport(
                report_id=report_id,
                report_type=report_type,
                report_name=f"{report_type.replace('_', ' ').title()} Report",
                start_date=start_date,
                end_date=end_date,
                user_id=user_id,
                generated_by=generated_by,
                summary=report_data.get("summary", {}),
                report_data=report_data,
                status="completed",
                expires_at=datetime.utcnow() + timedelta(days=90)  # 90-day retention
            )
            
            db.add(report)
            await db.commit()
            
            return {
                "success": True,
                "report_id": report_id,
                "report": {
                    "id": report.id,
                    "type": report_type,
                    "generated_at": report.generated_at.isoformat(),
                    "summary": report_data.get("summary", {}),
                    "data": report_data
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating compliance report: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _generate_gdpr_export(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Generate GDPR data export for a user."""
        # Search for all audit logs related to the user
        filters = {
            "actor_id": user_id,
            "start_date": start_date,
            "end_date": end_date
        }
        
        logs_result = await self.search_audit_logs(filters, db, limit=10000)
        
        # Also search for logs where user is the target
        target_filters = {
            "target_id": user_id,
            "target_type": "user",
            "start_date": start_date,
            "end_date": end_date
        }
        
        target_logs_result = await self.search_audit_logs(target_filters, db, limit=10000)
        
        all_logs = logs_result["logs"] + target_logs_result["logs"]
        
        # Remove duplicates based on event_id
        unique_logs = {}
        for log in all_logs:
            unique_logs[log["event_id"]] = log
        
        return {
            "summary": {
                "user_id": user_id,
                "total_events": len(unique_logs),
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                },
                "export_generated": datetime.utcnow().isoformat()
            },
            "audit_events": list(unique_logs.values())
        }
    
    async def _generate_audit_trail_report(
        self,
        start_date: datetime,
        end_date: datetime,
        user_id: Optional[int],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Generate comprehensive audit trail report."""
        filters = {
            "start_date": start_date,
            "end_date": end_date
        }
        
        if user_id:
            filters["actor_id"] = user_id
        
        logs_result = await self.search_audit_logs(filters, db, limit=10000)
        
        # Generate summary statistics
        event_type_counts = {}
        severity_counts = {}
        
        for log in logs_result["logs"]:
            event_type = log["event_type"]
            severity = log["severity"]
            
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        
        return {
            "summary": {
                "total_events": logs_result["total_count"],
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                },
                "event_type_counts": event_type_counts,
                "severity_counts": severity_counts,
                "user_filter": user_id
            },
            "audit_events": logs_result["logs"]
        }
    
    async def _generate_delivery_summary_report(
        self,
        start_date: datetime,
        end_date: datetime,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Generate delivery summary report."""
        # Get delivery-related audit events
        delivery_filters = {
            "start_date": start_date,
            "end_date": end_date,
            "target_type": "delivery"
        }
        
        logs_result = await self.search_audit_logs(delivery_filters, db, limit=10000)
        
        # Analyze delivery patterns
        delivery_stats = {
            "total_deliveries": 0,
            "successful_deliveries": 0,
            "failed_deliveries": 0,
            "platform_breakdown": {},
            "failure_reasons": {}
        }
        
        for log in logs_result["logs"]:
            if log["event_type"] in ["notification_delivered", "notification_failed"]:
                delivery_stats["total_deliveries"] += 1
                
                if log["event_type"] == "notification_delivered":
                    delivery_stats["successful_deliveries"] += 1
                else:
                    delivery_stats["failed_deliveries"] += 1
                
                # Extract platform info from event data
                event_data = log.get("event_data", {})
                platform = event_data.get("platform", "unknown")
                delivery_stats["platform_breakdown"][platform] = \
                    delivery_stats["platform_breakdown"].get(platform, 0) + 1
        
        return {
            "summary": {
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                },
                "delivery_statistics": delivery_stats,
                "success_rate": (delivery_stats["successful_deliveries"] / 
                               max(delivery_stats["total_deliveries"], 1)) * 100
            },
            "detailed_events": logs_result["logs"]
        }
    
    def _generate_checksum(self, audit_log: NotificationAuditLog) -> str:
        """Generate integrity checksum for audit log."""
        # Create string of critical fields
        critical_data = f"{audit_log.event_id}{audit_log.event_type}{audit_log.timestamp}" \
                       f"{audit_log.actor_id}{audit_log.target_id}{audit_log.action}" \
                       f"{json.dumps(audit_log.event_data, sort_keys=True)}"
        
        # Generate SHA-256 hash
        return hashlib.sha256(critical_data.encode()).hexdigest()
    
    async def verify_log_integrity(
        self,
        audit_log_id: int,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Verify integrity of an audit log record."""
        try:
            result = await db.execute(
                select(NotificationAuditLog).where(
                    NotificationAuditLog.id == audit_log_id
                )
            )
            
            log = result.scalar_one_or_none()
            if not log:
                return {
                    "success": False,
                    "error": "Audit log not found"
                }
            
            # Recalculate checksum
            expected_checksum = self._generate_checksum(log)
            
            return {
                "success": True,
                "integrity_verified": log.checksum == expected_checksum,
                "stored_checksum": log.checksum,
                "calculated_checksum": expected_checksum
            }
            
        except Exception as e:
            logger.error(f"Error verifying log integrity: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def cleanup_expired_logs(self, db: AsyncSession) -> Dict[str, Any]:
        """Clean up expired audit logs based on retention policies."""
        try:
            current_time = datetime.utcnow()
            
            # Find expired logs
            result = await db.execute(
                select(NotificationAuditLog).where(
                    NotificationAuditLog.retention_until <= current_time
                )
            )
            
            expired_logs = result.scalars().all()
            deleted_count = 0
            anonymized_count = 0
            
            for log in expired_logs:
                if log.is_sensitive:
                    # Anonymize sensitive logs instead of deleting
                    log.actor_name = "[ANONYMIZED]"
                    log.target_identifier = "[ANONYMIZED]"
                    log.source_ip = None
                    log.user_agent = None
                    log.event_data = {}
                    log.anonymized = True
                    anonymized_count += 1
                else:
                    # Delete non-sensitive logs
                    await db.delete(log)
                    deleted_count += 1
            
            await db.commit()
            
            return {
                "success": True,
                "deleted_count": deleted_count,
                "anonymized_count": anonymized_count,
                "total_processed": len(expired_logs)
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up expired logs: {e}")
            await db.rollback()
            return {
                "success": False,
                "error": str(e)
            }