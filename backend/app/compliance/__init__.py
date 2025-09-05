"""
FERPA Compliance Module

This module implements FERPA (Family Educational Rights and Privacy Act) compliance
framework for protecting student educational records and ensuring data privacy.

Key Components:
- Data privacy controls for student educational records
- Consent management system for data sharing
- Access logging for all student data interactions
- Data anonymization tools for reporting
- Compliance reporting and auditing
"""

from .data_controller import DataController
from .consent_manager import ConsentManager
from .access_logger import AccessLogger
from .anonymizer import DataAnonymizer
from .audit_service import ComplianceAuditService

__all__ = [
    "DataController",
    "ConsentManager", 
    "AccessLogger",
    "DataAnonymizer",
    "ComplianceAuditService"
]