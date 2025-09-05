"""
Security Infrastructure Module

This module implements comprehensive security measures including:
- Audit logging and trails
- Security monitoring and alerting
- Access control and authentication
- Incident response automation
- Anomaly detection and analysis

Coordinates with FERPA compliance framework for educational data protection.
"""

from .audit_logger import SecurityAuditLogger
from .monitoring import SecurityMonitor
from .access_control import RBACManager, MFAManager
from .incident_response import IncidentResponseSystem
from .anomaly_detector import AnomalyDetector

__all__ = [
    "SecurityAuditLogger",
    "SecurityMonitor", 
    "RBACManager",
    "MFAManager",
    "IncidentResponseSystem",
    "AnomalyDetector"
]