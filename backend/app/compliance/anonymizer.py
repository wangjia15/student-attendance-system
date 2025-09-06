"""
Data Anonymizer

FERPA-compliant data anonymization tools for protecting student privacy
in reporting, analytics, and research while maintaining data utility.
"""

from typing import List, Dict, Any, Optional, Union, Callable
from datetime import datetime, timedelta
import hashlib
import secrets
import json
import re
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.user import User
from app.models.attendance import AttendanceRecord
from app.models.ferpa import DataAccessLog

import logging

logger = logging.getLogger(__name__)


class AnonymizationLevel(str, Enum):
    """Levels of data anonymization"""
    NONE = "none"
    PSEUDONYMIZATION = "pseudonymization"  # Reversible with key
    ANONYMIZATION = "anonymization"        # Irreversible
    K_ANONYMITY = "k_anonymity"           # K-anonymity compliance
    DIFFERENTIAL_PRIVACY = "differential_privacy"  # Statistical privacy


class DataAnonymizer:
    """
    Comprehensive data anonymization system for FERPA compliance
    supporting multiple privacy preservation techniques.
    """
    
    def __init__(self, db: Session, anonymization_key: str = None):
        self.db = db
        self.anonymization_key = anonymization_key or self._generate_key()
        
    # === STUDENT DATA ANONYMIZATION ===
    
    def anonymize_student_data(
        self,
        student_data: List[Dict[str, Any]],
        anonymization_level: AnonymizationLevel = AnonymizationLevel.ANONYMIZATION,
        preserve_fields: List[str] = None,
        k_value: int = 5
    ) -> Dict[str, Any]:
        """
        Anonymize student data for reporting and analytics
        """
        
        preserve_fields = preserve_fields or ['id', 'created_at', 'grade_level']
        
        anonymized_data = {
            "anonymization_metadata": {
                "level": anonymization_level.value,
                "processed_at": datetime.utcnow().isoformat(),
                "record_count": len(student_data),
                "preserved_fields": preserve_fields,
                "k_value": k_value if anonymization_level == AnonymizationLevel.K_ANONYMITY else None
            },
            "data": []
        }
        
        if anonymization_level == AnonymizationLevel.NONE:
            # Return original data with metadata
            anonymized_data["data"] = student_data
            
        elif anonymization_level == AnonymizationLevel.PSEUDONYMIZATION:
            # Reversible pseudonymization
            anonymized_data["data"] = [
                self._pseudonymize_record(record, preserve_fields)
                for record in student_data
            ]
            
        elif anonymization_level == AnonymizationLevel.ANONYMIZATION:
            # Irreversible anonymization
            anonymized_data["data"] = [
                self._anonymize_record(record, preserve_fields)
                for record in student_data
            ]
            
        elif anonymization_level == AnonymizationLevel.K_ANONYMITY:
            # K-anonymity compliance
            anonymized_data["data"] = self._apply_k_anonymity(
                student_data, k_value, preserve_fields
            )
            
        elif anonymization_level == AnonymizationLevel.DIFFERENTIAL_PRIVACY:
            # Differential privacy
            anonymized_data["data"] = self._apply_differential_privacy(
                student_data, preserve_fields
            )
        
        return anonymized_data
    
    def anonymize_attendance_data(
        self,
        attendance_records: List[Dict[str, Any]],
        aggregation_level: str = "daily",  # "hourly", "daily", "weekly", "monthly"
        remove_identifying_info: bool = True
    ) -> Dict[str, Any]:
        """
        Anonymize attendance data for reporting
        """
        
        if remove_identifying_info:
            # Remove direct identifiers
            for record in attendance_records:
                record.pop('student_id', None)
                record.pop('ip_address', None)
                record.pop('user_agent', None)
                record.pop('notes', None)
        
        # Aggregate data to reduce granularity
        aggregated_data = self._aggregate_attendance_data(
            attendance_records, aggregation_level
        )
        
        return {
            "anonymization_metadata": {
                "aggregation_level": aggregation_level,
                "identifiers_removed": remove_identifying_info,
                "processed_at": datetime.utcnow().isoformat(),
                "original_record_count": len(attendance_records),
                "aggregated_record_count": len(aggregated_data)
            },
            "data": aggregated_data
        }
    
    def create_anonymized_cohort(
        self,
        cohort_criteria: Dict[str, Any],
        min_cohort_size: int = 10,
        anonymization_level: AnonymizationLevel = AnonymizationLevel.ANONYMIZATION
    ) -> Dict[str, Any]:
        """
        Create anonymized cohort data for research and analysis
        """
        
        # Query students matching criteria
        students = self._query_students_by_criteria(cohort_criteria)
        
        if len(students) < min_cohort_size:
            return {
                "status": "rejected",
                "reason": f"Cohort size ({len(students)}) below minimum ({min_cohort_size})",
                "recommendation": "Broaden criteria or reduce minimum size"
            }
        
        # Convert to dictionaries
        student_data = [
            {
                "id": s.id,
                "username": s.username,
                "full_name": s.full_name,
                "email": s.email,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "last_login": s.last_login.isoformat() if s.last_login else None
            }
            for s in students
        ]
        
        # Anonymize the cohort
        anonymized_cohort = self.anonymize_student_data(
            student_data, anonymization_level
        )
        
        # Add cohort metadata
        anonymized_cohort["cohort_metadata"] = {
            "criteria": cohort_criteria,
            "min_size": min_cohort_size,
            "actual_size": len(students),
            "created_at": datetime.utcnow().isoformat()
        }
        
        return anonymized_cohort
    
    # === STATISTICAL ANONYMIZATION ===
    
    def generate_statistical_summary(
        self,
        data: List[Dict[str, Any]],
        metrics: List[str],
        grouping_fields: List[str] = None,
        suppress_small_counts: bool = True,
        minimum_count: int = 5
    ) -> Dict[str, Any]:
        """
        Generate statistical summary with privacy protections
        """
        
        summary = {
            "metadata": {
                "total_records": len(data),
                "metrics_calculated": metrics,
                "grouping_fields": grouping_fields or [],
                "privacy_protections": {
                    "small_count_suppression": suppress_small_counts,
                    "minimum_count_threshold": minimum_count
                },
                "generated_at": datetime.utcnow().isoformat()
            },
            "statistics": {}
        }
        
        if not grouping_fields:
            # Overall statistics
            for metric in metrics:
                if metric in ['count', 'total']:
                    value = len(data)
                    if suppress_small_counts and value < minimum_count:
                        value = f"<{minimum_count}"
                    summary["statistics"][metric] = value
                else:
                    summary["statistics"][metric] = self._calculate_metric(data, metric)
        else:
            # Grouped statistics
            grouped_data = self._group_data(data, grouping_fields)
            
            for group_key, group_data in grouped_data.items():
                if suppress_small_counts and len(group_data) < minimum_count:
                    # Suppress small groups
                    summary["statistics"][group_key] = {"suppressed": True, "reason": "Small count"}
                else:
                    group_stats = {}
                    for metric in metrics:
                        group_stats[metric] = self._calculate_metric(group_data, metric)
                    summary["statistics"][group_key] = group_stats
        
        return summary
    
    def add_statistical_noise(
        self,
        data: List[Dict[str, Any]],
        numerical_fields: List[str],
        noise_level: float = 0.1,
        method: str = "gaussian"
    ) -> List[Dict[str, Any]]:
        """
        Add statistical noise to numerical data for privacy protection
        """
        
        import random
        import numpy as np
        
        noisy_data = []
        
        for record in data:
            noisy_record = record.copy()
            
            for field in numerical_fields:
                if field in record and record[field] is not None:
                    original_value = float(record[field])
                    
                    if method == "gaussian":
                        # Add Gaussian noise
                        noise = np.random.normal(0, original_value * noise_level)
                        noisy_value = original_value + noise
                    elif method == "laplacian":
                        # Add Laplacian noise (for differential privacy)
                        scale = original_value * noise_level
                        noise = np.random.laplace(0, scale)
                        noisy_value = original_value + noise
                    else:
                        # Uniform noise
                        noise_range = original_value * noise_level
                        noise = random.uniform(-noise_range, noise_range)
                        noisy_value = original_value + noise
                    
                    # Ensure non-negative for counts/percentages
                    if field.endswith('_count') or field.endswith('_rate'):
                        noisy_value = max(0, noisy_value)
                    
                    noisy_record[field] = round(noisy_value, 2)
            
            noisy_data.append(noisy_record)
        
        return noisy_data
    
    # === FIELD-SPECIFIC ANONYMIZATION ===
    
    def anonymize_identifiers(
        self,
        data: Dict[str, Any],
        identifier_fields: List[str] = None
    ) -> Dict[str, Any]:
        """
        Anonymize specific identifier fields
        """
        
        if not identifier_fields:
            identifier_fields = [
                'student_id', 'username', 'email', 'full_name', 
                'first_name', 'last_name', 'phone', 'address'
            ]
        
        anonymized_data = data.copy()
        
        for field in identifier_fields:
            if field in anonymized_data:
                if field in ['student_id', 'username']:
                    # Generate consistent pseudonym
                    anonymized_data[field] = self._generate_pseudonym(str(data[field]))
                elif field in ['email']:
                    # Anonymize email while preserving domain structure
                    anonymized_data[field] = self._anonymize_email(data[field])
                elif field in ['full_name', 'first_name', 'last_name']:
                    # Replace with generic identifiers
                    anonymized_data[field] = f"Student_{self._generate_short_hash(str(data.get('student_id', field)))}"
                elif field in ['phone', 'address']:
                    # Remove completely
                    anonymized_data[field] = "[REDACTED]"
        
        return anonymized_data
    
    def anonymize_temporal_data(
        self,
        timestamp: datetime,
        granularity: str = "day"  # "hour", "day", "week", "month", "quarter", "year"
    ) -> str:
        """
        Reduce temporal granularity for privacy protection
        """
        
        if granularity == "hour":
            return timestamp.strftime("%Y-%m-%d %H:00:00")
        elif granularity == "day":
            return timestamp.strftime("%Y-%m-%d")
        elif granularity == "week":
            # Get Monday of the week
            monday = timestamp - timedelta(days=timestamp.weekday())
            return monday.strftime("%Y-%m-%d (Week)")
        elif granularity == "month":
            return timestamp.strftime("%Y-%m")
        elif granularity == "quarter":
            quarter = (timestamp.month - 1) // 3 + 1
            return f"{timestamp.year}-Q{quarter}"
        elif granularity == "year":
            return str(timestamp.year)
        else:
            return timestamp.isoformat()
    
    def anonymize_location_data(
        self,
        location: str,
        generalization_level: int = 1
    ) -> str:
        """
        Generalize location data for privacy protection
        """
        
        # Level 1: Remove specific room numbers
        # Level 2: Remove building names
        # Level 3: Keep only general area
        
        if generalization_level >= 1:
            # Remove room numbers
            location = re.sub(r'\d+[A-Za-z]?$', '', location).strip()
        
        if generalization_level >= 2:
            # Remove specific building names
            location = re.sub(r'Building\s+[A-Za-z0-9]+', 'Building', location)
            location = re.sub(r'Hall\s+[A-Za-z0-9]+', 'Hall', location)
        
        if generalization_level >= 3:
            # Keep only general area
            if 'classroom' in location.lower():
                return "Classroom Area"
            elif 'lab' in location.lower():
                return "Laboratory Area"
            elif 'library' in location.lower():
                return "Library Area"
            else:
                return "Campus Location"
        
        return location or "Campus Location"
    
    # === PRIVACY VALIDATION ===
    
    def validate_privacy_protection(
        self,
        original_data: List[Dict[str, Any]],
        anonymized_data: List[Dict[str, Any]],
        risk_threshold: float = 0.1
    ) -> Dict[str, Any]:
        """
        Validate that anonymized data provides adequate privacy protection
        """
        
        validation_result = {
            "privacy_score": 0.0,
            "risk_level": "unknown",
            "vulnerabilities": [],
            "recommendations": [],
            "passed": False
        }
        
        # Check for direct identifiers
        identifier_risk = self._check_identifier_risk(anonymized_data)
        validation_result["vulnerabilities"].extend(identifier_risk["vulnerabilities"])
        
        # Check for quasi-identifiers (combinations that might identify individuals)
        quasi_identifier_risk = self._check_quasi_identifier_risk(anonymized_data)
        validation_result["vulnerabilities"].extend(quasi_identifier_risk["vulnerabilities"])
        
        # Check for statistical disclosure risk
        statistical_risk = self._check_statistical_disclosure_risk(
            original_data, anonymized_data
        )
        validation_result["vulnerabilities"].extend(statistical_risk["vulnerabilities"])
        
        # Calculate overall privacy score
        total_vulnerabilities = len(validation_result["vulnerabilities"])
        high_risk_vulnerabilities = len([
            v for v in validation_result["vulnerabilities"] 
            if v.get("severity") == "high"
        ])
        
        if total_vulnerabilities == 0:
            validation_result["privacy_score"] = 1.0
        else:
            validation_result["privacy_score"] = max(0, 1.0 - (high_risk_vulnerabilities * 0.3 + (total_vulnerabilities - high_risk_vulnerabilities) * 0.1))
        
        # Determine risk level
        if validation_result["privacy_score"] >= 0.9:
            validation_result["risk_level"] = "low"
        elif validation_result["privacy_score"] >= 0.7:
            validation_result["risk_level"] = "medium"
        else:
            validation_result["risk_level"] = "high"
        
        validation_result["passed"] = validation_result["privacy_score"] >= (1.0 - risk_threshold)
        
        # Generate recommendations
        validation_result["recommendations"] = self._generate_privacy_recommendations(
            validation_result["vulnerabilities"]
        )
        
        return validation_result
    
    # === PRIVATE HELPER METHODS ===
    
    def _generate_key(self) -> str:
        """Generate anonymization key"""
        return secrets.token_hex(32)
    
    def _pseudonymize_record(
        self, 
        record: Dict[str, Any], 
        preserve_fields: List[str]
    ) -> Dict[str, Any]:
        """Apply pseudonymization to a record"""
        
        pseudonymized = {}
        
        for key, value in record.items():
            if key in preserve_fields:
                pseudonymized[key] = value
            elif key in ['student_id', 'user_id']:
                pseudonymized[key] = self._generate_pseudonym(str(value))
            elif key in ['email', 'username']:
                pseudonymized[key] = self._generate_pseudonym(str(value))
            elif key in ['full_name', 'first_name', 'last_name']:
                pseudonymized[key] = f"Student_{self._generate_short_hash(str(value))}"
            else:
                pseudonymized[key] = value
        
        return pseudonymized
    
    def _anonymize_record(
        self, 
        record: Dict[str, Any], 
        preserve_fields: List[str]
    ) -> Dict[str, Any]:
        """Apply irreversible anonymization to a record"""
        
        anonymized = {}
        
        for key, value in record.items():
            if key in preserve_fields:
                anonymized[key] = value
            elif key in ['student_id', 'user_id', 'username', 'email', 'full_name']:
                # Remove direct identifiers
                continue
            elif isinstance(value, datetime):
                # Reduce temporal granularity
                anonymized[key] = self.anonymize_temporal_data(value, "day")
            else:
                anonymized[key] = value
        
        return anonymized
    
    def _apply_k_anonymity(
        self, 
        data: List[Dict[str, Any]], 
        k: int, 
        preserve_fields: List[str]
    ) -> List[Dict[str, Any]]:
        """Apply k-anonymity to dataset"""
        
        # This is a simplified k-anonymity implementation
        # In practice, you'd use more sophisticated algorithms
        
        # Group records by quasi-identifiers
        quasi_identifiers = [field for field in data[0].keys() if field not in preserve_fields]
        groups = {}
        
        for record in data:
            # Create key from quasi-identifiers
            key_parts = []
            for qi in quasi_identifiers:
                if qi in record:
                    value = record[qi]
                    # Generalize values
                    if isinstance(value, datetime):
                        value = self.anonymize_temporal_data(value, "month")
                    elif isinstance(value, (int, float)):
                        # Round to nearest 10
                        value = round(value / 10) * 10
                    key_parts.append(str(value))
            
            group_key = "|".join(key_parts)
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(record)
        
        # Filter out groups smaller than k
        k_anonymous_data = []
        for group_records in groups.values():
            if len(group_records) >= k:
                k_anonymous_data.extend(group_records)
        
        return k_anonymous_data
    
    def _apply_differential_privacy(
        self, 
        data: List[Dict[str, Any]], 
        preserve_fields: List[str]
    ) -> List[Dict[str, Any]]:
        """Apply differential privacy techniques"""
        
        # This is a simplified implementation
        # Add noise to numerical fields
        numerical_fields = []
        for record in data[:1]:  # Check first record
            for key, value in record.items():
                if key not in preserve_fields and isinstance(value, (int, float)):
                    numerical_fields.append(key)
        
        return self.add_statistical_noise(data, numerical_fields, 0.05, "laplacian")
    
    def _generate_pseudonym(self, value: str) -> str:
        """Generate consistent pseudonym for a value"""
        
        # Use HMAC with the anonymization key
        import hmac
        
        pseudonym = hmac.new(
            self.anonymization_key.encode(),
            value.encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        
        return f"ANON_{pseudonym}"
    
    def _generate_short_hash(self, value: str) -> str:
        """Generate short hash for anonymous identifiers"""
        
        return hashlib.md5((self.anonymization_key + value).encode()).hexdigest()[:8]
    
    def _anonymize_email(self, email: str) -> str:
        """Anonymize email while preserving domain structure"""
        
        if '@' not in email:
            return "[REDACTED]"
        
        username, domain = email.split('@', 1)
        anonymous_username = self._generate_short_hash(username)
        
        return f"anon_{anonymous_username}@{domain}"
    
    def _aggregate_attendance_data(
        self, 
        records: List[Dict[str, Any]], 
        level: str
    ) -> List[Dict[str, Any]]:
        """Aggregate attendance data to specified level"""
        
        # Group by time period
        groups = {}
        
        for record in records:
            timestamp = record.get('check_in_time') or record.get('created_at')
            if not timestamp:
                continue
            
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            
            # Create grouping key based on aggregation level
            if level == "hourly":
                key = timestamp.strftime("%Y-%m-%d %H:00")
            elif level == "daily":
                key = timestamp.strftime("%Y-%m-%d")
            elif level == "weekly":
                monday = timestamp - timedelta(days=timestamp.weekday())
                key = monday.strftime("%Y-%m-%d (Week)")
            elif level == "monthly":
                key = timestamp.strftime("%Y-%m")
            else:
                key = timestamp.strftime("%Y-%m-%d")
            
            if key not in groups:
                groups[key] = {
                    "period": key,
                    "total_records": 0,
                    "present_count": 0,
                    "absent_count": 0,
                    "late_count": 0,
                    "excused_count": 0
                }
            
            groups[key]["total_records"] += 1
            
            status = record.get('status', 'unknown')
            if status == 'present':
                groups[key]["present_count"] += 1
            elif status == 'absent':
                groups[key]["absent_count"] += 1
            elif status == 'late':
                groups[key]["late_count"] += 1
            elif status == 'excused':
                groups[key]["excused_count"] += 1
        
        return list(groups.values())
    
    def _query_students_by_criteria(self, criteria: Dict[str, Any]) -> List[User]:
        """Query students matching specified criteria"""
        
        query = self.db.query(User).filter(User.role == 'student')
        
        # Apply criteria filters
        if 'grade_level' in criteria:
            # Would need grade_level field in User model
            pass
        
        if 'enrollment_date_after' in criteria:
            date_after = datetime.fromisoformat(criteria['enrollment_date_after'])
            query = query.filter(User.created_at >= date_after)
        
        if 'enrollment_date_before' in criteria:
            date_before = datetime.fromisoformat(criteria['enrollment_date_before'])
            query = query.filter(User.created_at <= date_before)
        
        return query.all()
    
    def _calculate_metric(self, data: List[Dict[str, Any]], metric: str) -> Any:
        """Calculate statistical metric on data"""
        
        if metric == 'count':
            return len(data)
        elif metric == 'attendance_rate':
            present_count = len([d for d in data if d.get('status') == 'present'])
            return (present_count / len(data)) * 100 if data else 0
        # Add more metrics as needed
        
        return None
    
    def _group_data(self, data: List[Dict[str, Any]], fields: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Group data by specified fields"""
        
        groups = {}
        
        for record in data:
            key_parts = [str(record.get(field, 'unknown')) for field in fields]
            key = "|".join(key_parts)
            
            if key not in groups:
                groups[key] = []
            groups[key].append(record)
        
        return groups
    
    def _check_identifier_risk(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Check for direct identifier risks"""
        
        vulnerabilities = []
        
        direct_identifiers = ['student_id', 'social_security', 'email', 'phone', 'address']
        
        for record in data[:5]:  # Check first few records
            for identifier in direct_identifiers:
                if identifier in record and record[identifier]:
                    vulnerabilities.append({
                        "type": "direct_identifier",
                        "field": identifier,
                        "severity": "high",
                        "description": f"Direct identifier '{identifier}' present in anonymized data"
                    })
        
        return {"vulnerabilities": vulnerabilities}
    
    def _check_quasi_identifier_risk(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Check for quasi-identifier combination risks"""
        
        vulnerabilities = []
        
        # Check for unique combinations
        combinations = {}
        quasi_identifiers = ['birth_date', 'grade_level', 'enrollment_date', 'zip_code']
        
        for record in data:
            combo_key = "|".join([
                str(record.get(qi, '')) for qi in quasi_identifiers if qi in record
            ])
            
            if combo_key not in combinations:
                combinations[combo_key] = 0
            combinations[combo_key] += 1
        
        unique_combinations = sum(1 for count in combinations.values() if count == 1)
        if unique_combinations > len(data) * 0.1:  # More than 10% unique
            vulnerabilities.append({
                "type": "quasi_identifier_uniqueness",
                "severity": "medium", 
                "description": f"{unique_combinations} unique quasi-identifier combinations found"
            })
        
        return {"vulnerabilities": vulnerabilities}
    
    def _check_statistical_disclosure_risk(
        self, 
        original_data: List[Dict[str, Any]], 
        anonymized_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Check for statistical disclosure risks"""
        
        vulnerabilities = []
        
        # Simple check: ensure anonymized dataset is different from original
        if len(original_data) == len(anonymized_data):
            # Check if any records are identical
            original_str = json.dumps(sorted(original_data, key=str), sort_keys=True)
            anonymized_str = json.dumps(sorted(anonymized_data, key=str), sort_keys=True)
            
            if original_str == anonymized_str:
                vulnerabilities.append({
                    "type": "insufficient_anonymization",
                    "severity": "high",
                    "description": "Anonymized data is identical to original data"
                })
        
        return {"vulnerabilities": vulnerabilities}
    
    def _generate_privacy_recommendations(self, vulnerabilities: List[Dict[str, Any]]) -> List[str]:
        """Generate recommendations based on vulnerabilities"""
        
        recommendations = []
        
        vulnerability_types = [v["type"] for v in vulnerabilities]
        
        if "direct_identifier" in vulnerability_types:
            recommendations.append("Remove or pseudonymize direct identifiers")
        
        if "quasi_identifier_uniqueness" in vulnerability_types:
            recommendations.append("Apply generalization to quasi-identifiers")
        
        if "insufficient_anonymization" in vulnerability_types:
            recommendations.append("Increase anonymization level or apply additional techniques")
        
        if not recommendations:
            recommendations.append("Anonymization appears adequate for current risk threshold")
        
        return recommendations