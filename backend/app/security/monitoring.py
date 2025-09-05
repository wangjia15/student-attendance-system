"""
Real-time Security Monitoring and Alerting System

Provides real-time monitoring of security events, threat detection,
and automated alerting for suspicious activities.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.models.audit_log import SecurityAuditLog, SecurityIncident, LoginAttempt
from app.services.audit_service import security_audit_service
from app.core.database import get_db


logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"  
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class AlertType(str, Enum):
    """Types of security alerts."""
    BRUTE_FORCE_ATTACK = "BRUTE_FORCE_ATTACK"
    SUSPICIOUS_LOGIN_PATTERN = "SUSPICIOUS_LOGIN_PATTERN"
    MULTIPLE_FAILED_LOGINS = "MULTIPLE_FAILED_LOGINS"
    ANOMALOUS_DATA_ACCESS = "ANOMALOUS_DATA_ACCESS"
    PRIVILEGE_ESCALATION_ATTEMPT = "PRIVILEGE_ESCALATION_ATTEMPT"
    ACCOUNT_ENUMERATION = "ACCOUNT_ENUMERATION"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    GEOGRAPHIC_ANOMALY = "GEOGRAPHIC_ANOMALY"
    TIME_ANOMALY = "TIME_ANOMALY"
    SYSTEM_ERROR_SPIKE = "SYSTEM_ERROR_SPIKE"


@dataclass
class SecurityAlert:
    """Security alert data structure."""
    id: str
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    description: str
    affected_entities: Dict[str, Any]
    event_data: Dict[str, Any]
    timestamp: datetime
    correlation_id: Optional[str] = None
    auto_response_triggered: bool = False
    resolved: bool = False


class SecurityMetrics(BaseModel):
    """Real-time security metrics."""
    active_sessions: int = 0
    failed_logins_last_hour: int = 0
    suspicious_activities: int = 0
    open_incidents: int = 0
    risk_score_average: float = 0.0
    top_risk_ips: List[Dict[str, Any]] = []
    recent_alerts: List[Dict[str, Any]] = []


class SecurityMonitor:
    """
    Real-time security monitoring system.
    
    Monitors security events in real-time, detects patterns and anomalies,
    generates alerts, and coordinates with incident response system.
    """
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.alert_handlers: Dict[AlertType, List[Callable]] = {}
        self.monitoring_tasks: List[asyncio.Task] = []
        self.is_running = False
        
        # Monitoring thresholds
        self.thresholds = {
            "failed_login_attempts": 5,  # per IP per 15 minutes
            "failed_login_window": 15,   # minutes
            "suspicious_risk_threshold": 70,
            "brute_force_threshold": 10,  # attempts per IP per hour
            "data_access_rate_limit": 100,  # requests per user per hour
        }
    
    async def start_monitoring(self):
        """Start the real-time monitoring system."""
        if self.is_running:
            return
        
        self.is_running = True
        logger.info("Starting security monitoring system")
        
        # Start monitoring tasks
        self.monitoring_tasks = [
            asyncio.create_task(self._monitor_login_attempts()),
            asyncio.create_task(self._monitor_suspicious_activities()),
            asyncio.create_task(self._monitor_data_access_patterns()),
            asyncio.create_task(self._monitor_system_health()),
            asyncio.create_task(self._cleanup_expired_data())
        ]
    
    async def stop_monitoring(self):
        """Stop the monitoring system."""
        self.is_running = False
        logger.info("Stopping security monitoring system")
        
        # Cancel monitoring tasks
        for task in self.monitoring_tasks:
            task.cancel()
            
        # Wait for tasks to complete
        await asyncio.gather(*self.monitoring_tasks, return_exceptions=True)
        self.monitoring_tasks.clear()
    
    async def connect_websocket(self, websocket: WebSocket):
        """Connect a WebSocket for real-time alerts."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Active connections: {len(self.active_connections)}")
    
    def disconnect_websocket(self, websocket: WebSocket):
        """Disconnect a WebSocket."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Active connections: {len(self.active_connections)}")
    
    async def broadcast_alert(self, alert: SecurityAlert):
        """Broadcast security alert to all connected WebSocket clients."""
        if not self.active_connections:
            return
        
        alert_data = {
            "type": "security_alert",
            "data": {
                "id": alert.id,
                "alert_type": alert.alert_type.value,
                "severity": alert.severity.value,
                "title": alert.title,
                "description": alert.description,
                "timestamp": alert.timestamp.isoformat(),
                "affected_entities": alert.affected_entities,
                "correlation_id": alert.correlation_id
            }
        }
        
        # Send to all connected clients
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(alert_data))
            except WebSocketDisconnect:
                disconnected.append(connection)
            except Exception as e:
                logger.error(f"Failed to send alert to WebSocket: {e}")
                disconnected.append(connection)
        
        # Remove disconnected clients
        for connection in disconnected:
            self.disconnect_websocket(connection)
    
    async def generate_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        title: str,
        description: str,
        affected_entities: Dict[str, Any],
        event_data: Dict[str, Any] = None,
        correlation_id: str = None
    ) -> SecurityAlert:
        """Generate and broadcast a security alert."""
        alert = SecurityAlert(
            id=f"alert_{int(datetime.utcnow().timestamp())}_{hash(title) % 10000}",
            alert_type=alert_type,
            severity=severity,
            title=title,
            description=description,
            affected_entities=affected_entities,
            event_data=event_data or {},
            timestamp=datetime.utcnow(),
            correlation_id=correlation_id
        )
        
        # Log the alert
        logger.warning(f"Security Alert [{severity.value}]: {title} - {description}")
        
        # Broadcast to WebSocket clients
        await self.broadcast_alert(alert)
        
        # Trigger alert handlers
        await self._trigger_alert_handlers(alert)
        
        return alert
    
    async def get_current_metrics(self, db: AsyncSession) -> SecurityMetrics:
        """Get current security metrics."""
        now = datetime.utcnow()
        one_hour_ago = now - timedelta(hours=1)
        
        # Active sessions count
        active_sessions_result = await db.execute(
            select(func.count())
            .select_from(
                select(SecurityAuditLog.session_id)
                .where(
                    and_(
                        SecurityAuditLog.event_type == "SESSION_CREATED",
                        SecurityAuditLog.timestamp >= now - timedelta(hours=8)
                    )
                )
                .distinct()
                .subquery()
            )
        )
        active_sessions = active_sessions_result.scalar() or 0
        
        # Failed logins last hour
        failed_logins_result = await db.execute(
            select(func.count())
            .where(
                and_(
                    SecurityAuditLog.event_type == "LOGIN_FAILURE",
                    SecurityAuditLog.timestamp >= one_hour_ago
                )
            )
        )
        failed_logins = failed_logins_result.scalar() or 0
        
        # Suspicious activities
        suspicious_result = await db.execute(
            select(func.count())
            .where(
                and_(
                    SecurityAuditLog.is_suspicious == True,
                    SecurityAuditLog.timestamp >= one_hour_ago
                )
            )
        )
        suspicious_activities = suspicious_result.scalar() or 0
        
        # Open incidents
        open_incidents_result = await db.execute(
            select(func.count())
            .where(SecurityIncident.status == "OPEN")
        )
        open_incidents = open_incidents_result.scalar() or 0
        
        # Average risk score
        risk_score_result = await db.execute(
            select(func.avg(SecurityAuditLog.risk_score))
            .where(
                and_(
                    SecurityAuditLog.risk_score > 0,
                    SecurityAuditLog.timestamp >= one_hour_ago
                )
            )
        )
        risk_score_avg = float(risk_score_result.scalar() or 0)
        
        # Top risk IPs
        top_ips_result = await db.execute(
            select(
                SecurityAuditLog.ip_address,
                func.count().label('event_count'),
                func.avg(SecurityAuditLog.risk_score).label('avg_risk'),
                func.max(SecurityAuditLog.risk_score).label('max_risk')
            )
            .where(
                and_(
                    SecurityAuditLog.timestamp >= one_hour_ago,
                    SecurityAuditLog.ip_address.isnot(None),
                    SecurityAuditLog.risk_score > 0
                )
            )
            .group_by(SecurityAuditLog.ip_address)
            .order_by(desc('max_risk'))
            .limit(5)
        )
        
        top_ips = []
        for row in top_ips_result:
            top_ips.append({
                "ip_address": row.ip_address,
                "event_count": row.event_count,
                "avg_risk": float(row.avg_risk),
                "max_risk": row.max_risk
            })
        
        return SecurityMetrics(
            active_sessions=active_sessions,
            failed_logins_last_hour=failed_logins,
            suspicious_activities=suspicious_activities,
            open_incidents=open_incidents,
            risk_score_average=risk_score_avg,
            top_risk_ips=top_ips,
            recent_alerts=[]  # Would be populated from alert store
        )
    
    def register_alert_handler(self, alert_type: AlertType, handler: Callable):
        """Register a handler for specific alert types."""
        if alert_type not in self.alert_handlers:
            self.alert_handlers[alert_type] = []
        self.alert_handlers[alert_type].append(handler)
    
    # Private monitoring methods
    
    async def _monitor_login_attempts(self):
        """Monitor for suspicious login patterns."""
        while self.is_running:
            try:
                async with get_db() as db:
                    await self._check_brute_force_attacks(db)
                    await self._check_suspicious_login_patterns(db)
                
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                logger.error(f"Error in login monitoring: {e}")
                await asyncio.sleep(60)
    
    async def _monitor_suspicious_activities(self):
        """Monitor for suspicious activities and anomalies."""
        while self.is_running:
            try:
                async with get_db() as db:
                    await self._check_high_risk_events(db)
                    await self._check_privilege_escalation(db)
                
                await asyncio.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                logger.error(f"Error in suspicious activity monitoring: {e}")
                await asyncio.sleep(300)
    
    async def _monitor_data_access_patterns(self):
        """Monitor data access patterns for anomalies."""
        while self.is_running:
            try:
                async with get_db() as db:
                    await self._check_anomalous_data_access(db)
                    await self._check_data_export_patterns(db)
                
                await asyncio.sleep(600)  # Check every 10 minutes
                
            except Exception as e:
                logger.error(f"Error in data access monitoring: {e}")
                await asyncio.sleep(600)
    
    async def _monitor_system_health(self):
        """Monitor system health and error patterns."""
        while self.is_running:
            try:
                async with get_db() as db:
                    await self._check_error_spikes(db)
                
                await asyncio.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                logger.error(f"Error in system health monitoring: {e}")
                await asyncio.sleep(300)
    
    async def _cleanup_expired_data(self):
        """Clean up expired monitoring data."""
        while self.is_running:
            try:
                # Clean up old alerts and metrics
                # This would be implemented based on retention policies
                pass
                
                await asyncio.sleep(3600)  # Run every hour
                
            except Exception as e:
                logger.error(f"Error in cleanup: {e}")
                await asyncio.sleep(3600)
    
    async def _check_brute_force_attacks(self, db: AsyncSession):
        """Check for brute force login attacks."""
        threshold = self.thresholds["brute_force_threshold"]
        window = timedelta(hours=1)
        
        # Query for IPs with high failure rates
        cutoff_time = datetime.utcnow() - window
        
        result = await db.execute(
            select(
                LoginAttempt.ip_address,
                func.count().label('failure_count'),
                func.array_agg(LoginAttempt.username).label('usernames')
            )
            .where(
                and_(
                    LoginAttempt.success == False,
                    LoginAttempt.attempted_at >= cutoff_time
                )
            )
            .group_by(LoginAttempt.ip_address)
            .having(func.count() >= threshold)
        )
        
        for row in result:
            await self.generate_alert(
                alert_type=AlertType.BRUTE_FORCE_ATTACK,
                severity=AlertSeverity.HIGH,
                title=f"Brute Force Attack Detected",
                description=f"IP {row.ip_address} has {row.failure_count} failed login attempts in the last hour",
                affected_entities={
                    "ip_address": row.ip_address,
                    "failure_count": row.failure_count,
                    "targeted_usernames": row.usernames[:10]  # Limit to first 10
                }
            )
    
    async def _check_suspicious_login_patterns(self, db: AsyncSession):
        """Check for suspicious login patterns."""
        # Multiple failed attempts from same IP for different users
        cutoff_time = datetime.utcnow() - timedelta(minutes=15)
        
        result = await db.execute(
            select(
                LoginAttempt.ip_address,
                func.count(LoginAttempt.username.distinct()).label('unique_users'),
                func.count().label('total_attempts')
            )
            .where(
                and_(
                    LoginAttempt.success == False,
                    LoginAttempt.attempted_at >= cutoff_time
                )
            )
            .group_by(LoginAttempt.ip_address)
            .having(func.count(LoginAttempt.username.distinct()) >= 3)
        )
        
        for row in result:
            if row.unique_users >= 5:
                await self.generate_alert(
                    alert_type=AlertType.ACCOUNT_ENUMERATION,
                    severity=AlertSeverity.MEDIUM,
                    title=f"Account Enumeration Detected",
                    description=f"IP {row.ip_address} attempted login with {row.unique_users} different usernames",
                    affected_entities={
                        "ip_address": row.ip_address,
                        "unique_users_targeted": row.unique_users,
                        "total_attempts": row.total_attempts
                    }
                )
    
    async def _check_high_risk_events(self, db: AsyncSession):
        """Check for high-risk security events."""
        cutoff_time = datetime.utcnow() - timedelta(minutes=5)
        
        result = await db.execute(
            select(SecurityAuditLog)
            .where(
                and_(
                    SecurityAuditLog.risk_score >= self.thresholds["suspicious_risk_threshold"],
                    SecurityAuditLog.timestamp >= cutoff_time,
                    SecurityAuditLog.is_suspicious == True
                )
            )
            .order_by(desc(SecurityAuditLog.risk_score))
            .limit(10)
        )
        
        for log in result.scalars():
            await self.generate_alert(
                alert_type=AlertType.SUSPICIOUS_LOGIN_PATTERN,
                severity=AlertSeverity.MEDIUM if log.risk_score < 90 else AlertSeverity.HIGH,
                title=f"High-Risk Security Event",
                description=f"Event {log.event_type} from user {log.username} has risk score {log.risk_score}",
                affected_entities={
                    "user_id": log.user_id,
                    "username": log.username,
                    "ip_address": log.ip_address,
                    "event_type": log.event_type,
                    "risk_score": log.risk_score
                },
                correlation_id=log.correlation_id
            )
    
    async def _check_privilege_escalation(self, db: AsyncSession):
        """Check for privilege escalation attempts."""
        cutoff_time = datetime.utcnow() - timedelta(minutes=10)
        
        # Look for repeated permission denied events followed by grants
        result = await db.execute(
            select(SecurityAuditLog)
            .where(
                and_(
                    SecurityAuditLog.event_type == "PERMISSION_DENIED",
                    SecurityAuditLog.timestamp >= cutoff_time,
                    SecurityAuditLog.severity.in_(["MEDIUM", "HIGH"])
                )
            )
        )
        
        # This would implement more sophisticated logic for detecting
        # privilege escalation patterns
        pass
    
    async def _check_anomalous_data_access(self, db: AsyncSession):
        """Check for anomalous data access patterns."""
        cutoff_time = datetime.utcnow() - timedelta(hours=1)
        rate_limit = self.thresholds["data_access_rate_limit"]
        
        # Check for users exceeding data access rate limits
        result = await db.execute(
            select(
                SecurityAuditLog.user_id,
                SecurityAuditLog.username,
                func.count().label('access_count')
            )
            .where(
                and_(
                    SecurityAuditLog.event_category == "DATA",
                    SecurityAuditLog.event_type.like("%_ACCESS"),
                    SecurityAuditLog.timestamp >= cutoff_time
                )
            )
            .group_by(SecurityAuditLog.user_id, SecurityAuditLog.username)
            .having(func.count() > rate_limit)
        )
        
        for row in result:
            await self.generate_alert(
                alert_type=AlertType.ANOMALOUS_DATA_ACCESS,
                severity=AlertSeverity.MEDIUM,
                title=f"Excessive Data Access",
                description=f"User {row.username} has accessed data {row.access_count} times in the last hour",
                affected_entities={
                    "user_id": row.user_id,
                    "username": row.username,
                    "access_count": row.access_count,
                    "rate_limit": rate_limit
                }
            )
    
    async def _check_data_export_patterns(self, db: AsyncSession):
        """Check for suspicious data export patterns."""
        # Implementation would analyze data export events for suspicious patterns
        pass
    
    async def _check_error_spikes(self, db: AsyncSession):
        """Check for system error spikes."""
        cutoff_time = datetime.utcnow() - timedelta(minutes=5)
        
        result = await db.execute(
            select(func.count())
            .where(
                and_(
                    SecurityAuditLog.event_type == "SYSTEM_ERROR",
                    SecurityAuditLog.timestamp >= cutoff_time
                )
            )
        )
        
        error_count = result.scalar() or 0
        
        if error_count > 50:  # Threshold for error spike
            await self.generate_alert(
                alert_type=AlertType.SYSTEM_ERROR_SPIKE,
                severity=AlertSeverity.HIGH,
                title=f"System Error Spike",
                description=f"{error_count} system errors in the last 5 minutes",
                affected_entities={
                    "error_count": error_count,
                    "time_window": "5 minutes"
                }
            )
    
    async def _trigger_alert_handlers(self, alert: SecurityAlert):
        """Trigger registered alert handlers."""
        handlers = self.alert_handlers.get(alert.alert_type, [])
        
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
            except Exception as e:
                logger.error(f"Alert handler failed: {e}")


# Global security monitor instance
security_monitor = SecurityMonitor()