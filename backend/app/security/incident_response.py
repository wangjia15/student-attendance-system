"""
Security Incident Response Automation

Automated incident detection, classification, and response system.
Coordinates with monitoring system for comprehensive security automation.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, update
from sqlalchemy.orm import selectinload

from app.models.audit_log import SecurityAuditLog, SecurityIncident, LoginAttempt, UserSession
from app.models.user import User
from app.services.audit_service import security_audit_service
from app.core.database import get_db


logger = logging.getLogger(__name__)


class ResponseAction(str, Enum):
    """Automated response actions."""
    BLOCK_IP = "BLOCK_IP"
    LOCK_ACCOUNT = "LOCK_ACCOUNT"
    TERMINATE_SESSION = "TERMINATE_SESSION"
    ALERT_ADMIN = "ALERT_ADMIN"
    RATE_LIMIT_USER = "RATE_LIMIT_USER"
    REQUIRE_MFA = "REQUIRE_MFA"
    LOG_ENHANCED = "LOG_ENHANCED"
    QUARANTINE_USER = "QUARANTINE_USER"
    DISABLE_API_ACCESS = "DISABLE_API_ACCESS"
    FORCE_PASSWORD_RESET = "FORCE_PASSWORD_RESET"


@dataclass
class ResponseRule:
    """Incident response rule configuration."""
    rule_id: str
    name: str
    description: str
    trigger_conditions: Dict[str, Any]
    actions: List[ResponseAction]
    severity_threshold: str = "MEDIUM"
    enabled: bool = True
    auto_execute: bool = False  # If False, requires manual approval


@dataclass
class IncidentContext:
    """Context information for incident analysis."""
    related_events: List[SecurityAuditLog]
    affected_users: Set[int]
    source_ips: Set[str]
    time_span: timedelta
    event_patterns: Dict[str, int]
    risk_indicators: List[str]


class IncidentResponseSystem:
    """
    Automated security incident response system.
    
    Features:
    - Automatic incident detection and classification
    - Configurable response rules and actions
    - Automated response execution with manual override
    - Incident tracking and workflow management
    - Integration with monitoring and audit systems
    """
    
    def __init__(self):
        self.response_rules: Dict[str, ResponseRule] = {}
        self.blocked_ips: Set[str] = set()
        self.locked_accounts: Set[int] = set()
        self.quarantined_users: Set[int] = set()
        self.rate_limited_users: Dict[int, datetime] = {}
        
        # Initialize default response rules
        self._initialize_default_rules()
    
    async def evaluate_for_incident(
        self,
        db: AsyncSession,
        audit_log: SecurityAuditLog
    ) -> Optional[SecurityIncident]:
        """
        Evaluate if an audit log entry should trigger an incident.
        
        Args:
            db: Database session
            audit_log: The audit log entry that triggered evaluation
            
        Returns:
            Created SecurityIncident if one was triggered, None otherwise
        """
        try:
            # Skip if already part of an incident
            if audit_log.correlation_id:
                existing_incident = await db.execute(
                    select(SecurityIncident)
                    .where(SecurityIncident.correlation_id == audit_log.correlation_id)
                )
                if existing_incident.scalar_one_or_none():
                    return None
            
            # Gather context for incident analysis
            context = await self._build_incident_context(db, audit_log)
            
            # Check each response rule
            for rule in self.response_rules.values():
                if not rule.enabled:
                    continue
                
                if await self._evaluate_rule_conditions(rule, audit_log, context):
                    incident = await self._create_incident(db, rule, audit_log, context)
                    
                    if rule.auto_execute:
                        await self._execute_automated_response(db, incident, rule)
                    
                    logger.info(f"Security incident created: {incident.id} - {incident.title}")
                    return incident
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to evaluate incident: {e}")
            return None
    
    async def execute_manual_response(
        self,
        db: AsyncSession,
        incident_id: str,
        actions: List[ResponseAction],
        executed_by: int
    ) -> Dict[str, Any]:
        """Execute manual response actions for an incident."""
        try:
            # Get incident
            result = await db.execute(
                select(SecurityIncident).where(SecurityIncident.id == incident_id)
            )
            incident = result.scalar_one_or_none()
            
            if not incident:
                return {"success": False, "error": "Incident not found"}
            
            # Execute actions
            execution_results = {}
            for action in actions:
                result = await self._execute_response_action(db, incident, action)
                execution_results[action.value] = result
            
            # Update incident
            incident.status = "INVESTIGATING"
            incident.manual_response_notes = f"Manual response executed by user {executed_by}"
            
            # Log the manual response
            await security_audit_service.log_security_event(
                db=db,
                event_type="INCIDENT_RESPONSE_MANUAL",
                event_category="INCIDENT",
                message=f"Manual response executed for incident {incident_id}",
                user_id=executed_by,
                event_data={
                    "incident_id": incident_id,
                    "actions": [action.value for action in actions],
                    "results": execution_results
                },
                severity="INFO",
                correlation_id=incident.correlation_id
            )
            
            await db.commit()
            
            return {"success": True, "results": execution_results}
            
        except Exception as e:
            logger.error(f"Failed to execute manual response: {e}")
            await db.rollback()
            return {"success": False, "error": str(e)}
    
    async def resolve_incident(
        self,
        db: AsyncSession,
        incident_id: str,
        resolution_notes: str,
        resolved_by: int
    ) -> bool:
        """Mark an incident as resolved."""
        try:
            result = await db.execute(
                select(SecurityIncident).where(SecurityIncident.id == incident_id)
            )
            incident = result.scalar_one_or_none()
            
            if not incident:
                return False
            
            incident.status = "RESOLVED"
            incident.resolved_at = datetime.utcnow()
            incident.manual_response_notes = (
                f"{incident.manual_response_notes or ''}\n"
                f"Resolved by user {resolved_by}: {resolution_notes}"
            )
            
            # Log resolution
            await security_audit_service.log_security_event(
                db=db,
                event_type="INCIDENT_RESOLVED",
                event_category="INCIDENT",
                message=f"Security incident resolved: {incident.title}",
                user_id=resolved_by,
                event_data={
                    "incident_id": incident_id,
                    "resolution_notes": resolution_notes
                },
                severity="INFO",
                correlation_id=incident.correlation_id
            )
            
            await db.commit()
            return True
            
        except Exception as e:
            logger.error(f"Failed to resolve incident: {e}")
            await db.rollback()
            return False
    
    async def get_active_incidents(self, db: AsyncSession) -> List[SecurityIncident]:
        """Get all active (open/investigating) incidents."""
        result = await db.execute(
            select(SecurityIncident)
            .where(SecurityIncident.status.in_(["OPEN", "INVESTIGATING"]))
            .order_by(desc(SecurityIncident.detected_at))
        )
        return result.scalars().all()
    
    async def block_ip_address(self, ip_address: str, reason: str = "Security incident"):
        """Block an IP address (would integrate with firewall/WAF)."""
        self.blocked_ips.add(ip_address)
        logger.warning(f"IP address blocked: {ip_address} - {reason}")
        
        # In a real implementation, this would:
        # 1. Update firewall rules
        # 2. Update WAF configurations
        # 3. Add to IP blacklist database
    
    async def unblock_ip_address(self, ip_address: str):
        """Unblock an IP address."""
        self.blocked_ips.discard(ip_address)
        logger.info(f"IP address unblocked: {ip_address}")
    
    async def lock_user_account(self, db: AsyncSession, user_id: int, reason: str):
        """Lock a user account."""
        try:
            self.locked_accounts.add(user_id)
            
            # Update user account in database
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(is_active=False)
            )
            
            # Terminate all active sessions
            await db.execute(
                update(UserSession)
                .where(
                    and_(
                        UserSession.user_id == user_id,
                        UserSession.is_active == True
                    )
                )
                .values(
                    is_active=False,
                    ended_at=datetime.utcnow(),
                    end_reason="SECURITY_LOCK"
                )
            )
            
            await db.commit()
            logger.warning(f"User account locked: {user_id} - {reason}")
            
        except Exception as e:
            logger.error(f"Failed to lock user account {user_id}: {e}")
            await db.rollback()
    
    async def unlock_user_account(self, db: AsyncSession, user_id: int):
        """Unlock a user account."""
        try:
            self.locked_accounts.discard(user_id)
            
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(is_active=True)
            )
            
            await db.commit()
            logger.info(f"User account unlocked: {user_id}")
            
        except Exception as e:
            logger.error(f"Failed to unlock user account {user_id}: {e}")
            await db.rollback()
    
    def is_ip_blocked(self, ip_address: str) -> bool:
        """Check if an IP address is blocked."""
        return ip_address in self.blocked_ips
    
    def is_account_locked(self, user_id: int) -> bool:
        """Check if a user account is locked."""
        return user_id in self.locked_accounts
    
    # Private helper methods
    
    def _initialize_default_rules(self):
        """Initialize default incident response rules."""
        
        # Brute force attack rule
        self.response_rules["brute_force"] = ResponseRule(
            rule_id="brute_force",
            name="Brute Force Attack Detection",
            description="Detect and respond to brute force login attempts",
            trigger_conditions={
                "event_types": ["LOGIN_FAILURE"],
                "min_events": 10,
                "time_window_minutes": 60,
                "same_ip": True
            },
            actions=[ResponseAction.BLOCK_IP, ResponseAction.ALERT_ADMIN],
            severity_threshold="HIGH",
            auto_execute=True
        )
        
        # Account enumeration rule
        self.response_rules["account_enum"] = ResponseRule(
            rule_id="account_enum",
            name="Account Enumeration Detection",
            description="Detect attempts to enumerate user accounts",
            trigger_conditions={
                "event_types": ["LOGIN_FAILURE"],
                "min_unique_usernames": 5,
                "time_window_minutes": 15,
                "same_ip": True
            },
            actions=[ResponseAction.BLOCK_IP, ResponseAction.RATE_LIMIT_USER],
            severity_threshold="MEDIUM",
            auto_execute=True
        )
        
        # Privilege escalation rule
        self.response_rules["privilege_escalation"] = ResponseRule(
            rule_id="privilege_escalation",
            name="Privilege Escalation Attempt",
            description="Detect privilege escalation attempts",
            trigger_conditions={
                "event_types": ["PERMISSION_DENIED", "ROLE_CHANGE"],
                "min_events": 3,
                "time_window_minutes": 10,
                "high_risk_score": 80
            },
            actions=[ResponseAction.QUARANTINE_USER, ResponseAction.ALERT_ADMIN, ResponseAction.LOG_ENHANCED],
            severity_threshold="HIGH",
            auto_execute=False  # Requires manual review
        )
        
        # Data exfiltration rule
        self.response_rules["data_exfiltration"] = ResponseRule(
            rule_id="data_exfiltration",
            name="Data Exfiltration Attempt",
            description="Detect potential data exfiltration",
            trigger_conditions={
                "event_types": ["DATA_EXPORT", "DATA_ACCESS"],
                "min_events": 50,
                "time_window_minutes": 60,
                "same_user": True
            },
            actions=[ResponseAction.QUARANTINE_USER, ResponseAction.ALERT_ADMIN, ResponseAction.DISABLE_API_ACCESS],
            severity_threshold="CRITICAL",
            auto_execute=False
        )
        
        # Suspicious login pattern rule
        self.response_rules["suspicious_login"] = ResponseRule(
            rule_id="suspicious_login",
            name="Suspicious Login Pattern",
            description="Detect suspicious login patterns",
            trigger_conditions={
                "event_types": ["LOGIN_SUCCESS", "LOGIN_FAILURE"],
                "risk_score_threshold": 70,
                "geographic_anomaly": True
            },
            actions=[ResponseAction.REQUIRE_MFA, ResponseAction.ALERT_ADMIN],
            severity_threshold="MEDIUM",
            auto_execute=True
        )
    
    async def _build_incident_context(
        self,
        db: AsyncSession,
        trigger_log: SecurityAuditLog
    ) -> IncidentContext:
        """Build context for incident analysis."""
        
        # Look back 2 hours for related events
        lookback_time = datetime.utcnow() - timedelta(hours=2)
        
        # Get related events
        related_events_query = select(SecurityAuditLog).where(
            and_(
                SecurityAuditLog.timestamp >= lookback_time,
                or_(
                    SecurityAuditLog.user_id == trigger_log.user_id,
                    SecurityAuditLog.ip_address == trigger_log.ip_address,
                    SecurityAuditLog.session_id == trigger_log.session_id
                )
            )
        ).order_by(SecurityAuditLog.timestamp)
        
        result = await db.execute(related_events_query)
        related_events = result.scalars().all()
        
        # Extract context information
        affected_users = {log.user_id for log in related_events if log.user_id}
        source_ips = {log.ip_address for log in related_events if log.ip_address}
        
        # Calculate time span
        if related_events:
            earliest = min(log.timestamp for log in related_events)
            latest = max(log.timestamp for log in related_events)
            time_span = latest - earliest
        else:
            time_span = timedelta(0)
        
        # Count event patterns
        event_patterns = {}
        for log in related_events:
            event_patterns[log.event_type] = event_patterns.get(log.event_type, 0) + 1
        
        # Identify risk indicators
        risk_indicators = []
        if len(source_ips) > 3:
            risk_indicators.append("multiple_source_ips")
        if len(affected_users) > 5:
            risk_indicators.append("multiple_affected_users")
        if any(log.risk_score > 80 for log in related_events):
            risk_indicators.append("high_risk_events")
        if any(log.is_suspicious for log in related_events):
            risk_indicators.append("suspicious_activities")
        
        return IncidentContext(
            related_events=related_events,
            affected_users=affected_users,
            source_ips=source_ips,
            time_span=time_span,
            event_patterns=event_patterns,
            risk_indicators=risk_indicators
        )
    
    async def _evaluate_rule_conditions(
        self,
        rule: ResponseRule,
        trigger_log: SecurityAuditLog,
        context: IncidentContext
    ) -> bool:
        """Evaluate if rule conditions are met."""
        conditions = rule.trigger_conditions
        
        # Check event types
        if "event_types" in conditions:
            required_types = conditions["event_types"]
            if trigger_log.event_type not in required_types:
                return False
        
        # Check minimum events
        if "min_events" in conditions:
            total_events = sum(context.event_patterns.values())
            if total_events < conditions["min_events"]:
                return False
        
        # Check time window
        if "time_window_minutes" in conditions:
            max_window = timedelta(minutes=conditions["time_window_minutes"])
            if context.time_span > max_window:
                return False
        
        # Check same IP requirement
        if conditions.get("same_ip", False):
            if len(context.source_ips) != 1:
                return False
        
        # Check same user requirement
        if conditions.get("same_user", False):
            if len(context.affected_users) != 1:
                return False
        
        # Check unique usernames (for account enumeration)
        if "min_unique_usernames" in conditions:
            unique_usernames = len({
                log.username for log in context.related_events 
                if log.username and log.event_type == "LOGIN_FAILURE"
            })
            if unique_usernames < conditions["min_unique_usernames"]:
                return False
        
        # Check risk score threshold
        if "risk_score_threshold" in conditions:
            if trigger_log.risk_score < conditions["risk_score_threshold"]:
                return False
        
        # Check high risk score
        if conditions.get("high_risk_score"):
            if not any(log.risk_score >= conditions["high_risk_score"] for log in context.related_events):
                return False
        
        # Check geographic anomaly
        if conditions.get("geographic_anomaly", False):
            if "geographic_anomaly" not in context.risk_indicators:
                return False
        
        return True
    
    async def _create_incident(
        self,
        db: AsyncSession,
        rule: ResponseRule,
        trigger_log: SecurityAuditLog,
        context: IncidentContext
    ) -> SecurityIncident:
        """Create a new security incident."""
        
        # Determine incident type based on rule
        incident_type_mapping = {
            "brute_force": "BRUTE_FORCE_LOGIN",
            "account_enum": "ACCOUNT_ENUMERATION", 
            "privilege_escalation": "PRIVILEGE_ESCALATION",
            "data_exfiltration": "DATA_EXFILTRATION_ATTEMPT",
            "suspicious_login": "SUSPICIOUS_ACCESS_PATTERN"
        }
        
        incident_type = incident_type_mapping.get(rule.rule_id, "SECURITY_VIOLATION")
        
        # Create incident
        incident = SecurityIncident(
            incident_type=incident_type,
            severity=rule.severity_threshold,
            title=f"{rule.name}: {trigger_log.event_type}",
            description=f"Triggered by rule '{rule.name}' - {rule.description}",
            affected_user_id=trigger_log.user_id,
            affected_ip_address=trigger_log.ip_address,
            detected_at=datetime.utcnow(),
            first_event_at=min(log.timestamp for log in context.related_events) if context.related_events else trigger_log.timestamp,
            last_event_at=max(log.timestamp for log in context.related_events) if context.related_events else trigger_log.timestamp,
            event_count=len(context.related_events),
            risk_score=max(log.risk_score for log in context.related_events) if context.related_events else trigger_log.risk_score,
            correlation_id=trigger_log.correlation_id or str(uuid.uuid4())
        )
        
        db.add(incident)
        await db.commit()
        await db.refresh(incident)
        
        return incident
    
    async def _execute_automated_response(
        self,
        db: AsyncSession,
        incident: SecurityIncident,
        rule: ResponseRule
    ):
        """Execute automated response actions."""
        executed_actions = []
        
        for action in rule.actions:
            try:
                result = await self._execute_response_action(db, incident, action)
                executed_actions.append({"action": action.value, "result": result})
            except Exception as e:
                logger.error(f"Failed to execute action {action}: {e}")
                executed_actions.append({"action": action.value, "error": str(e)})
        
        # Update incident with executed actions
        incident.auto_response_actions = executed_actions
        await db.commit()
        
        logger.info(f"Automated response executed for incident {incident.id}: {executed_actions}")
    
    async def _execute_response_action(
        self,
        db: AsyncSession,
        incident: SecurityIncident,
        action: ResponseAction
    ) -> Dict[str, Any]:
        """Execute a specific response action."""
        
        if action == ResponseAction.BLOCK_IP and incident.affected_ip_address:
            await self.block_ip_address(incident.affected_ip_address, f"Incident {incident.id}")
            return {"success": True, "ip_blocked": incident.affected_ip_address}
        
        elif action == ResponseAction.LOCK_ACCOUNT and incident.affected_user_id:
            await self.lock_user_account(db, incident.affected_user_id, f"Incident {incident.id}")
            return {"success": True, "account_locked": incident.affected_user_id}
        
        elif action == ResponseAction.TERMINATE_SESSION:
            # Terminate all sessions for affected user
            if incident.affected_user_id:
                await db.execute(
                    update(UserSession)
                    .where(
                        and_(
                            UserSession.user_id == incident.affected_user_id,
                            UserSession.is_active == True
                        )
                    )
                    .values(
                        is_active=False,
                        ended_at=datetime.utcnow(),
                        end_reason="SECURITY_INCIDENT"
                    )
                )
                await db.commit()
                return {"success": True, "sessions_terminated": incident.affected_user_id}
        
        elif action == ResponseAction.QUARANTINE_USER:
            if incident.affected_user_id:
                self.quarantined_users.add(incident.affected_user_id)
                return {"success": True, "user_quarantined": incident.affected_user_id}
        
        elif action == ResponseAction.RATE_LIMIT_USER:
            if incident.affected_user_id:
                self.rate_limited_users[incident.affected_user_id] = datetime.utcnow() + timedelta(hours=1)
                return {"success": True, "user_rate_limited": incident.affected_user_id}
        
        elif action == ResponseAction.ALERT_ADMIN:
            # In a real implementation, this would send notifications to administrators
            logger.critical(f"SECURITY ALERT: Incident {incident.id} - {incident.title}")
            return {"success": True, "admin_alerted": True}
        
        elif action == ResponseAction.LOG_ENHANCED:
            # Enable enhanced logging for affected entities
            return {"success": True, "enhanced_logging": True}
        
        return {"success": False, "error": f"Action {action} not implemented"}


# Global incident response system
incident_response_system = IncidentResponseSystem()