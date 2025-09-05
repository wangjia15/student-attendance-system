"""
Security Anomaly Detection System

Machine learning and rule-based system for detecting anomalous user behavior
and potential security threats based on data access patterns.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Set, Tuple, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
import statistics
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, distinct

from app.models.audit_log import SecurityAuditLog, LoginAttempt, UserSession
from app.models.user import User
from app.security.monitoring import security_monitor, AlertType, AlertSeverity
from app.services.audit_service import security_audit_service


logger = logging.getLogger(__name__)


class AnomalyType(str, Enum):
    """Types of anomalies that can be detected."""
    TEMPORAL_ANOMALY = "temporal_anomaly"          # Unusual timing patterns
    GEOGRAPHIC_ANOMALY = "geographic_anomaly"      # Unusual location access
    BEHAVIORAL_ANOMALY = "behavioral_anomaly"      # Unusual user behavior
    ACCESS_PATTERN_ANOMALY = "access_pattern_anomaly"  # Unusual data access
    VOLUME_ANOMALY = "volume_anomaly"             # Unusual activity volume
    SEQUENTIAL_ANOMALY = "sequential_anomaly"      # Unusual action sequences


@dataclass
class UserProfile:
    """User behavior profile for anomaly detection."""
    user_id: int
    username: str
    
    # Temporal patterns
    typical_login_hours: Set[int] = field(default_factory=set)
    typical_login_days: Set[int] = field(default_factory=set)  # 0=Monday, 6=Sunday
    average_session_duration: float = 0.0
    
    # Geographic patterns
    common_ip_addresses: Set[str] = field(default_factory=set)
    common_locations: Set[str] = field(default_factory=set)  # Could be inferred from IP
    
    # Access patterns
    typical_endpoints: Dict[str, int] = field(default_factory=dict)
    typical_resources: Set[str] = field(default_factory=set)
    average_requests_per_session: float = 0.0
    
    # Behavioral metrics
    failed_login_rate: float = 0.0
    typical_user_agents: Set[str] = field(default_factory=set)
    
    # Profile metadata
    profile_created: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    confidence_score: float = 0.0  # How well-established this profile is


@dataclass
class AnomalyScore:
    """Anomaly score with details."""
    anomaly_type: AnomalyType
    score: float  # 0-1, where 1 is most anomalous
    confidence: float  # 0-1, confidence in the anomaly detection
    description: str
    contributing_factors: List[str] = field(default_factory=list)
    severity: str = "MEDIUM"


@dataclass
class DetectionResult:
    """Result of anomaly detection analysis."""
    user_id: int
    event_id: str
    timestamp: datetime
    anomaly_scores: List[AnomalyScore]
    overall_risk_score: float
    is_anomalous: bool
    recommended_actions: List[str] = field(default_factory=list)


class AnomalyDetector:
    """
    Advanced anomaly detection system for security monitoring.
    
    Uses statistical analysis and behavioral profiling to detect
    unusual patterns that may indicate security threats.
    """
    
    def __init__(self):
        self.user_profiles: Dict[int, UserProfile] = {}
        self.detection_thresholds = {
            "anomaly_threshold": 0.7,  # Score above which to flag as anomalous
            "confidence_threshold": 0.6,  # Minimum confidence to act
            "profile_min_events": 50,  # Minimum events needed for reliable profile
            "lookback_days": 30,  # Days to look back for profile building
        }
        
        # Statistical parameters
        self.statistical_params = {
            "temporal_std_multiplier": 2.0,  # Standard deviations for temporal anomalies
            "volume_std_multiplier": 2.5,    # Standard deviations for volume anomalies
            "geographic_similarity_threshold": 0.8,  # IP similarity threshold
        }
        
        self.is_running = False
        self.analysis_tasks: List[asyncio.Task] = []
    
    async def start_detection(self):
        """Start the anomaly detection system."""
        if self.is_running:
            return
        
        self.is_running = True
        logger.info("Starting anomaly detection system")
        
        # Start background tasks
        self.analysis_tasks = [
            asyncio.create_task(self._profile_building_task()),
            asyncio.create_task(self._real_time_detection_task()),
            asyncio.create_task(self._periodic_analysis_task())
        ]
    
    async def stop_detection(self):
        """Stop the anomaly detection system."""
        self.is_running = False
        logger.info("Stopping anomaly detection system")
        
        # Cancel background tasks
        for task in self.analysis_tasks:
            task.cancel()
        
        await asyncio.gather(*self.analysis_tasks, return_exceptions=True)
        self.analysis_tasks.clear()
    
    async def analyze_event(
        self,
        db: AsyncSession,
        audit_log: SecurityAuditLog
    ) -> Optional[DetectionResult]:
        """
        Analyze a single security event for anomalies.
        
        Args:
            db: Database session
            audit_log: The audit log event to analyze
            
        Returns:
            DetectionResult if anomalies detected, None otherwise
        """
        try:
            if not audit_log.user_id:
                return None  # Can't analyze without user context
            
            # Get or build user profile
            user_profile = await self._get_or_build_user_profile(db, audit_log.user_id)
            
            if not user_profile:
                return None  # Not enough data for analysis
            
            # Perform anomaly detection
            anomaly_scores = []
            
            # Temporal anomaly detection
            temporal_score = await self._detect_temporal_anomaly(audit_log, user_profile)
            if temporal_score:
                anomaly_scores.append(temporal_score)
            
            # Geographic anomaly detection
            geographic_score = await self._detect_geographic_anomaly(audit_log, user_profile)
            if geographic_score:
                anomaly_scores.append(geographic_score)
            
            # Behavioral anomaly detection
            behavioral_score = await self._detect_behavioral_anomaly(db, audit_log, user_profile)
            if behavioral_score:
                anomaly_scores.append(behavioral_score)
            
            # Access pattern anomaly detection
            access_score = await self._detect_access_pattern_anomaly(db, audit_log, user_profile)
            if access_score:
                anomaly_scores.append(access_score)
            
            # Volume anomaly detection
            volume_score = await self._detect_volume_anomaly(db, audit_log, user_profile)
            if volume_score:
                anomaly_scores.append(volume_score)
            
            if not anomaly_scores:
                return None
            
            # Calculate overall risk score
            overall_risk = self._calculate_overall_risk(anomaly_scores)
            
            # Determine if anomalous
            is_anomalous = (
                overall_risk >= self.detection_thresholds["anomaly_threshold"] and
                max(score.confidence for score in anomaly_scores) >= self.detection_thresholds["confidence_threshold"]
            )
            
            if not is_anomalous:
                return None
            
            # Generate recommended actions
            recommended_actions = self._generate_recommendations(anomaly_scores, overall_risk)
            
            # Create detection result
            result = DetectionResult(
                user_id=audit_log.user_id,
                event_id=str(audit_log.id),
                timestamp=audit_log.timestamp,
                anomaly_scores=anomaly_scores,
                overall_risk_score=overall_risk,
                is_anomalous=is_anomalous,
                recommended_actions=recommended_actions
            )
            
            # Log the anomaly detection
            await self._log_anomaly_detection(db, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing event for anomalies: {e}")
            return None
    
    async def build_user_profile(
        self,
        db: AsyncSession,
        user_id: int,
        lookback_days: int = None
    ) -> Optional[UserProfile]:
        """Build or update user behavior profile."""
        try:
            lookback_days = lookback_days or self.detection_thresholds["lookback_days"]
            cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
            
            # Get user information
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            
            if not user:
                return None
            
            # Get historical audit logs for the user
            logs_result = await db.execute(
                select(SecurityAuditLog)
                .where(
                    and_(
                        SecurityAuditLog.user_id == user_id,
                        SecurityAuditLog.timestamp >= cutoff_date
                    )
                )
                .order_by(SecurityAuditLog.timestamp)
            )
            
            logs = logs_result.scalars().all()
            
            if len(logs) < self.detection_thresholds["profile_min_events"]:
                logger.info(f"Insufficient data to build profile for user {user_id} ({len(logs)} events)")
                return None
            
            # Build profile
            profile = UserProfile(user_id=user_id, username=user.username)
            
            # Extract temporal patterns
            login_hours = []
            login_days = []
            session_durations = []
            
            for log in logs:
                if log.timestamp:
                    login_hours.append(log.timestamp.hour)
                    login_days.append(log.timestamp.weekday())
                
                if log.event_type == "SESSION_CREATED" and log.event_data:
                    # Try to calculate session duration if available
                    pass
            
            profile.typical_login_hours = set(self._find_common_values(login_hours))
            profile.typical_login_days = set(self._find_common_values(login_days))
            
            # Extract geographic patterns
            ip_addresses = [log.ip_address for log in logs if log.ip_address]
            profile.common_ip_addresses = set(self._find_common_values(ip_addresses, threshold=0.05))
            
            # Extract access patterns
            endpoints = [log.endpoint for log in logs if log.endpoint]
            profile.typical_endpoints = self._count_frequencies(endpoints)
            
            # Extract behavioral patterns
            user_agents = [log.user_agent for log in logs if log.user_agent]
            profile.typical_user_agents = set(self._find_common_values(user_agents, threshold=0.1))
            
            # Calculate confidence score based on data quality
            profile.confidence_score = min(1.0, len(logs) / (self.detection_thresholds["profile_min_events"] * 2))
            profile.last_updated = datetime.utcnow()
            
            # Store profile
            self.user_profiles[user_id] = profile
            
            logger.info(f"Built profile for user {user_id} with {len(logs)} events (confidence: {profile.confidence_score:.2f})")
            return profile
            
        except Exception as e:
            logger.error(f"Error building user profile for {user_id}: {e}")
            return None
    
    # Private detection methods
    
    async def _detect_temporal_anomaly(
        self,
        audit_log: SecurityAuditLog,
        user_profile: UserProfile
    ) -> Optional[AnomalyScore]:
        """Detect temporal anomalies (unusual timing patterns)."""
        if not audit_log.timestamp:
            return None
        
        current_hour = audit_log.timestamp.hour
        current_day = audit_log.timestamp.weekday()
        
        anomaly_factors = []
        score = 0.0
        
        # Check if login hour is unusual
        if user_profile.typical_login_hours and current_hour not in user_profile.typical_login_hours:
            score += 0.4
            anomaly_factors.append(f"Unusual login hour: {current_hour}")
        
        # Check if login day is unusual
        if user_profile.typical_login_days and current_day not in user_profile.typical_login_days:
            score += 0.3
            anomaly_factors.append(f"Unusual login day: {current_day}")
        
        # Check for very early/late access (2-6 AM typically unusual)
        if 2 <= current_hour <= 6:
            score += 0.3
            anomaly_factors.append(f"Very early/late access: {current_hour}:00")
        
        if score > 0:
            return AnomalyScore(
                anomaly_type=AnomalyType.TEMPORAL_ANOMALY,
                score=min(score, 1.0),
                confidence=user_profile.confidence_score,
                description="Unusual timing pattern detected",
                contributing_factors=anomaly_factors,
                severity="MEDIUM" if score < 0.7 else "HIGH"
            )
        
        return None
    
    async def _detect_geographic_anomaly(
        self,
        audit_log: SecurityAuditLog,
        user_profile: UserProfile
    ) -> Optional[AnomalyScore]:
        """Detect geographic anomalies (unusual location access)."""
        if not audit_log.ip_address:
            return None
        
        current_ip = audit_log.ip_address
        
        # Check if IP is completely new
        if (user_profile.common_ip_addresses and 
            current_ip not in user_profile.common_ip_addresses):
            
            # Calculate IP similarity (simple heuristic)
            similarity_scores = []
            for known_ip in user_profile.common_ip_addresses:
                similarity = self._calculate_ip_similarity(current_ip, known_ip)
                similarity_scores.append(similarity)
            
            max_similarity = max(similarity_scores) if similarity_scores else 0.0
            
            # If IP is very different from known IPs
            if max_similarity < self.statistical_params["geographic_similarity_threshold"]:
                return AnomalyScore(
                    anomaly_type=AnomalyType.GEOGRAPHIC_ANOMALY,
                    score=1.0 - max_similarity,
                    confidence=user_profile.confidence_score,
                    description=f"New IP address: {current_ip}",
                    contributing_factors=[f"IP not in typical set", f"Max similarity: {max_similarity:.2f}"],
                    severity="HIGH" if max_similarity < 0.5 else "MEDIUM"
                )
        
        return None
    
    async def _detect_behavioral_anomaly(
        self,
        db: AsyncSession,
        audit_log: SecurityAuditLog,
        user_profile: UserProfile
    ) -> Optional[AnomalyScore]:
        """Detect behavioral anomalies."""
        anomaly_factors = []
        score = 0.0
        
        # Check user agent anomaly
        if (audit_log.user_agent and user_profile.typical_user_agents and
            audit_log.user_agent not in user_profile.typical_user_agents):
            score += 0.3
            anomaly_factors.append("Unusual user agent")
        
        # Check for rapid successive actions (within 1 second)
        if audit_log.user_id:
            one_second_ago = audit_log.timestamp - timedelta(seconds=1)
            recent_result = await db.execute(
                select(func.count())
                .where(
                    and_(
                        SecurityAuditLog.user_id == audit_log.user_id,
                        SecurityAuditLog.timestamp >= one_second_ago,
                        SecurityAuditLog.timestamp < audit_log.timestamp
                    )
                )
            )
            
            recent_count = recent_result.scalar() or 0
            if recent_count > 10:  # More than 10 actions in 1 second
                score += 0.5
                anomaly_factors.append(f"Rapid successive actions: {recent_count}")
        
        if score > 0:
            return AnomalyScore(
                anomaly_type=AnomalyType.BEHAVIORAL_ANOMALY,
                score=min(score, 1.0),
                confidence=user_profile.confidence_score,
                description="Unusual behavioral pattern",
                contributing_factors=anomaly_factors,
                severity="MEDIUM" if score < 0.7 else "HIGH"
            )
        
        return None
    
    async def _detect_access_pattern_anomaly(
        self,
        db: AsyncSession,
        audit_log: SecurityAuditLog,
        user_profile: UserProfile
    ) -> Optional[AnomalyScore]:
        """Detect access pattern anomalies."""
        if not audit_log.endpoint:
            return None
        
        score = 0.0
        anomaly_factors = []
        
        # Check if accessing unusual endpoint
        if (user_profile.typical_endpoints and 
            audit_log.endpoint not in user_profile.typical_endpoints):
            score += 0.4
            anomaly_factors.append(f"Unusual endpoint: {audit_log.endpoint}")
        
        # Check for suspicious endpoint patterns
        sensitive_patterns = ['/admin', '/api/export', '/api/delete', '/config']
        if any(pattern in audit_log.endpoint for pattern in sensitive_patterns):
            score += 0.3
            anomaly_factors.append("Access to sensitive endpoint")
        
        if score > 0:
            return AnomalyScore(
                anomaly_type=AnomalyType.ACCESS_PATTERN_ANOMALY,
                score=min(score, 1.0),
                confidence=user_profile.confidence_score,
                description="Unusual access pattern",
                contributing_factors=anomaly_factors,
                severity="HIGH" if any('admin' in factor.lower() for factor in anomaly_factors) else "MEDIUM"
            )
        
        return None
    
    async def _detect_volume_anomaly(
        self,
        db: AsyncSession,
        audit_log: SecurityAuditLog,
        user_profile: UserProfile
    ) -> Optional[AnomalyScore]:
        """Detect volume anomalies (unusual activity volume)."""
        if not audit_log.user_id:
            return None
        
        # Count recent activity
        one_hour_ago = audit_log.timestamp - timedelta(hours=1)
        recent_result = await db.execute(
            select(func.count())
            .where(
                and_(
                    SecurityAuditLog.user_id == audit_log.user_id,
                    SecurityAuditLog.timestamp >= one_hour_ago,
                    SecurityAuditLog.timestamp <= audit_log.timestamp
                )
            )
        )
        
        recent_count = recent_result.scalar() or 0
        
        # Compare with typical volume
        if user_profile.average_requests_per_session > 0:
            expected_hourly = user_profile.average_requests_per_session
            if recent_count > expected_hourly * 3:  # 3x typical volume
                score = min(1.0, recent_count / (expected_hourly * 5))
                
                return AnomalyScore(
                    anomaly_type=AnomalyType.VOLUME_ANOMALY,
                    score=score,
                    confidence=user_profile.confidence_score,
                    description=f"Unusually high activity volume: {recent_count} events in 1 hour",
                    contributing_factors=[f"Recent events: {recent_count}", f"Expected: ~{expected_hourly}"],
                    severity="HIGH" if score > 0.8 else "MEDIUM"
                )
        
        # Static threshold for very high volume
        elif recent_count > 100:  # More than 100 events per hour is unusual
            return AnomalyScore(
                anomaly_type=AnomalyType.VOLUME_ANOMALY,
                score=min(1.0, recent_count / 200),
                confidence=0.8,
                description=f"Very high activity volume: {recent_count} events in 1 hour",
                contributing_factors=[f"Recent events: {recent_count}"],
                severity="HIGH"
            )
        
        return None
    
    # Background tasks
    
    async def _profile_building_task(self):
        """Background task to build and update user profiles."""
        while self.is_running:
            try:
                from app.core.database import get_db
                
                async with get_db() as db:
                    # Get users who need profile updates
                    users_result = await db.execute(
                        select(User.id).where(User.is_active == True)
                    )
                    user_ids = [row[0] for row in users_result]
                    
                    # Update profiles for active users
                    for user_id in user_ids[:10]:  # Limit to avoid overload
                        if user_id not in self.user_profiles:
                            await self.build_user_profile(db, user_id)
                        elif (datetime.utcnow() - self.user_profiles[user_id].last_updated).days >= 7:
                            await self.build_user_profile(db, user_id)
                        
                        await asyncio.sleep(1)  # Rate limiting
                
                await asyncio.sleep(3600)  # Run every hour
                
            except Exception as e:
                logger.error(f"Error in profile building task: {e}")
                await asyncio.sleep(3600)
    
    async def _real_time_detection_task(self):
        """Background task for real-time anomaly detection on new events."""
        while self.is_running:
            try:
                from app.core.database import get_db
                
                async with get_db() as db:
                    # Get recent high-risk events
                    cutoff_time = datetime.utcnow() - timedelta(minutes=5)
                    
                    recent_events = await db.execute(
                        select(SecurityAuditLog)
                        .where(
                            and_(
                                SecurityAuditLog.timestamp >= cutoff_time,
                                SecurityAuditLog.user_id.isnot(None),
                                or_(
                                    SecurityAuditLog.risk_score > 50,
                                    SecurityAuditLog.is_suspicious == True
                                )
                            )
                        )
                        .order_by(desc(SecurityAuditLog.timestamp))
                        .limit(20)
                    )
                    
                    for event in recent_events.scalars():
                        result = await self.analyze_event(db, event)
                        
                        if result and result.is_anomalous:
                            # Trigger alert through monitoring system
                            await self._trigger_anomaly_alert(result)
                
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                logger.error(f"Error in real-time detection task: {e}")
                await asyncio.sleep(60)
    
    async def _periodic_analysis_task(self):
        """Background task for periodic deep analysis."""
        while self.is_running:
            try:
                # Perform more comprehensive analysis periodically
                # This could include trend analysis, correlation analysis, etc.
                await asyncio.sleep(1800)  # Run every 30 minutes
                
            except Exception as e:
                logger.error(f"Error in periodic analysis task: {e}")
                await asyncio.sleep(1800)
    
    # Helper methods
    
    async def _get_or_build_user_profile(
        self,
        db: AsyncSession,
        user_id: int
    ) -> Optional[UserProfile]:
        """Get existing profile or build new one."""
        if user_id in self.user_profiles:
            profile = self.user_profiles[user_id]
            # Check if profile needs update
            if (datetime.utcnow() - profile.last_updated).days >= 7:
                return await self.build_user_profile(db, user_id)
            return profile
        else:
            return await self.build_user_profile(db, user_id)
    
    def _find_common_values(self, values: List, threshold: float = 0.2) -> List:
        """Find values that appear frequently (above threshold)."""
        if not values:
            return []
        
        value_counts = defaultdict(int)
        for value in values:
            value_counts[value] += 1
        
        total = len(values)
        common_values = []
        
        for value, count in value_counts.items():
            if count / total >= threshold:
                common_values.append(value)
        
        return common_values
    
    def _count_frequencies(self, values: List) -> Dict:
        """Count frequencies of values."""
        frequencies = defaultdict(int)
        for value in values:
            frequencies[value] += 1
        return dict(frequencies)
    
    def _calculate_ip_similarity(self, ip1: str, ip2: str) -> float:
        """Calculate similarity between two IP addresses (simple heuristic)."""
        try:
            parts1 = ip1.split('.')
            parts2 = ip2.split('.')
            
            if len(parts1) != 4 or len(parts2) != 4:
                return 0.0
            
            matches = sum(1 for p1, p2 in zip(parts1, parts2) if p1 == p2)
            return matches / 4.0
            
        except Exception:
            return 0.0
    
    def _calculate_overall_risk(self, anomaly_scores: List[AnomalyScore]) -> float:
        """Calculate overall risk score from individual anomaly scores."""
        if not anomaly_scores:
            return 0.0
        
        # Weight different types of anomalies
        weights = {
            AnomalyType.GEOGRAPHIC_ANOMALY: 0.9,
            AnomalyType.BEHAVIORAL_ANOMALY: 0.8,
            AnomalyType.ACCESS_PATTERN_ANOMALY: 0.8,
            AnomalyType.VOLUME_ANOMALY: 0.7,
            AnomalyType.TEMPORAL_ANOMALY: 0.6,
            AnomalyType.SEQUENTIAL_ANOMALY: 0.7
        }
        
        weighted_scores = []
        for score in anomaly_scores:
            weight = weights.get(score.anomaly_type, 0.5)
            weighted_score = score.score * score.confidence * weight
            weighted_scores.append(weighted_score)
        
        # Use maximum weighted score as overall risk
        return max(weighted_scores)
    
    def _generate_recommendations(
        self,
        anomaly_scores: List[AnomalyScore],
        overall_risk: float
    ) -> List[str]:
        """Generate recommended actions based on anomaly detection."""
        recommendations = []
        
        if overall_risk >= 0.9:
            recommendations.extend([
                "Consider temporarily suspending user account",
                "Require immediate MFA verification",
                "Alert security team for manual investigation"
            ])
        elif overall_risk >= 0.7:
            recommendations.extend([
                "Require additional authentication",
                "Enable enhanced monitoring for user",
                "Review recent user activities"
            ])
        else:
            recommendations.extend([
                "Monitor user activity closely",
                "Log additional details for future analysis"
            ])
        
        # Add specific recommendations based on anomaly types
        for score in anomaly_scores:
            if score.anomaly_type == AnomalyType.GEOGRAPHIC_ANOMALY:
                recommendations.append("Verify user location through alternative means")
            elif score.anomaly_type == AnomalyType.ACCESS_PATTERN_ANOMALY:
                recommendations.append("Review data access permissions")
            elif score.anomaly_type == AnomalyType.VOLUME_ANOMALY:
                recommendations.append("Implement rate limiting for user")
        
        return list(set(recommendations))  # Remove duplicates
    
    async def _log_anomaly_detection(self, db: AsyncSession, result: DetectionResult):
        """Log the anomaly detection result."""
        await security_audit_service.log_security_event(
            db=db,
            event_type="ANOMALY_DETECTED",
            event_category="SECURITY",
            message=f"Anomaly detected for user {result.user_id} (risk score: {result.overall_risk_score:.2f})",
            user_id=result.user_id,
            event_data={
                "anomaly_types": [score.anomaly_type.value for score in result.anomaly_scores],
                "overall_risk_score": result.overall_risk_score,
                "anomaly_details": [
                    {
                        "type": score.anomaly_type.value,
                        "score": score.score,
                        "confidence": score.confidence,
                        "factors": score.contributing_factors
                    }
                    for score in result.anomaly_scores
                ],
                "recommendations": result.recommended_actions
            },
            severity="HIGH" if result.overall_risk_score > 0.8 else "MEDIUM",
            risk_score=int(result.overall_risk_score * 100)
        )
    
    async def _trigger_anomaly_alert(self, result: DetectionResult):
        """Trigger alert through monitoring system."""
        severity_mapping = {
            "HIGH": AlertSeverity.HIGH,
            "MEDIUM": AlertSeverity.MEDIUM,
            "LOW": AlertSeverity.LOW
        }
        
        max_severity = max(score.severity for score in result.anomaly_scores)
        alert_severity = severity_mapping.get(max_severity, AlertSeverity.MEDIUM)
        
        await security_monitor.generate_alert(
            alert_type=AlertType.ANOMALY_DETECTION,
            severity=alert_severity,
            title=f"User Behavior Anomaly Detected",
            description=f"Anomalous behavior detected for user {result.user_id} with risk score {result.overall_risk_score:.2f}",
            affected_entities={
                "user_id": result.user_id,
                "risk_score": result.overall_risk_score,
                "anomaly_types": [score.anomaly_type.value for score in result.anomaly_scores]
            },
            event_data={
                "recommendations": result.recommended_actions,
                "anomaly_details": [
                    {
                        "type": score.anomaly_type.value,
                        "score": score.score,
                        "description": score.description
                    }
                    for score in result.anomaly_scores
                ]
            }
        )


# Global anomaly detector instance
anomaly_detector = AnomalyDetector()