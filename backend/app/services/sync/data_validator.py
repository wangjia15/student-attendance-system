"""
Data Validation and Integrity Service

Provides comprehensive data validation and integrity checks for sync operations,
ensuring data quality and consistency between local and external SIS systems.
"""

import logging
import re
from datetime import datetime, date
from typing import Dict, Any, List, Optional, Tuple, Union, Callable
from dataclasses import dataclass
try:
    from email_validator import validate_email, EmailNotValidError
    EMAIL_VALIDATOR_AVAILABLE = True
except ImportError:
    EMAIL_VALIDATOR_AVAILABLE = False
    class EmailNotValidError(Exception):
        pass
    def validate_email(email):
        if '@' in email:
            class MockValid:
                def __init__(self, email):
                    self.email = email
            return MockValid(email)
        else:
            raise EmailNotValidError("Invalid email")
try:
    import phonenumbers
    from phonenumbers import NumberParseException
    PHONENUMBERS_AVAILABLE = True
except ImportError:
    PHONENUMBERS_AVAILABLE = False
    class NumberParseException(Exception):
        pass
    class phonenumbers:
        @staticmethod
        def parse(*args, **kwargs):
            raise NumberParseException("phonenumbers not available")
        @staticmethod
        def is_valid_number(*args, **kwargs):
            return False
        @staticmethod
        def format_number(*args, **kwargs):
            return ""
        class PhoneNumberFormat:
            E164 = "E164"

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from app.models.sync_metadata import (
    DataValidationRule, ValidationResult, SyncOperation, DataType
)
from app.models.sis_integration import SISIntegration

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """Represents a validation error."""
    field_name: str
    error_type: str
    error_message: str
    field_value: Any
    suggested_fix: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of data validation."""
    is_valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationError]
    fixed_data: Optional[Dict[str, Any]] = None


class DataValidator:
    """
    Comprehensive data validator for sync operations.
    
    Validates data quality, format, and integrity for student demographics,
    enrollment data, and grade information.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        
        # Built-in validation functions
        self._validators = {
            'required': self._validate_required,
            'email': self._validate_email,
            'phone': self._validate_phone,
            'date': self._validate_date,
            'numeric': self._validate_numeric,
            'range': self._validate_range,
            'length': self._validate_length,
            'pattern': self._validate_pattern,
            'enum': self._validate_enum,
            'student_id': self._validate_student_id,
            'grade': self._validate_grade
        }
        
        # Data fixers
        self._fixers = {
            'trim': self._fix_trim,
            'capitalize': self._fix_capitalize,
            'phone_format': self._fix_phone_format,
            'email_lowercase': self._fix_email_lowercase,
            'default_value': self._fix_default_value
        }
    
    async def validate_student_data(
        self,
        integration_id: int,
        student_data: Dict[str, Any],
        sync_operation: Optional[SyncOperation] = None
    ) -> ValidationResult:
        """
        Validate student demographic data.
        
        Args:
            integration_id: SIS integration ID
            student_data: Student data to validate
            sync_operation: Optional sync operation for logging
            
        Returns:
            ValidationResult with validation status and errors
        """
        logger.debug(f"Validating student data for integration {integration_id}")
        
        errors = []
        warnings = []
        fixed_data = {}
        
        # Get validation rules for student data
        rules = await self._get_validation_rules(integration_id, DataType.STUDENT_DEMOGRAPHICS)
        
        for rule in rules:
            try:
                field_value = student_data.get(rule.field_name)
                
                # Validate the field
                field_result = await self._validate_field(
                    rule, field_value, student_data
                )
                
                if not field_result.is_valid:
                    errors.extend(field_result.errors)
                    warnings.extend(field_result.warnings)
                
                # Apply fixes if available and needed
                if field_result.fixed_data:
                    fixed_data.update(field_result.fixed_data)
                
                # Log validation result
                if sync_operation:
                    await self._log_validation_result(
                        rule, sync_operation, 'student',
                        str(student_data.get('id', 'unknown')),
                        field_result.is_valid, field_value,
                        field_result.errors[0].error_message if field_result.errors else None,
                        field_result.fixed_data.get(rule.field_name) if field_result.fixed_data else None
                    )
            
            except Exception as e:
                logger.error(f"Error validating field {rule.field_name}: {e}")
                errors.append(ValidationError(
                    field_name=rule.field_name,
                    error_type='validation_error',
                    error_message=f"Validation failed: {str(e)}",
                    field_value=field_value
                ))
        
        # Additional cross-field validation
        cross_field_errors = await self._validate_student_cross_fields(student_data)
        errors.extend(cross_field_errors)
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            fixed_data=fixed_data if fixed_data else None
        )
    
    async def validate_enrollment_data(
        self,
        integration_id: int,
        enrollment_data: Dict[str, Any],
        sync_operation: Optional[SyncOperation] = None
    ) -> ValidationResult:
        """
        Validate enrollment data.
        
        Args:
            integration_id: SIS integration ID
            enrollment_data: Enrollment data to validate
            sync_operation: Optional sync operation for logging
            
        Returns:
            ValidationResult with validation status and errors
        """
        logger.debug(f"Validating enrollment data for integration {integration_id}")
        
        errors = []
        warnings = []
        fixed_data = {}
        
        # Get validation rules for enrollment data
        rules = await self._get_validation_rules(integration_id, DataType.ENROLLMENT)
        
        for rule in rules:
            try:
                field_value = enrollment_data.get(rule.field_name)
                
                field_result = await self._validate_field(
                    rule, field_value, enrollment_data
                )
                
                if not field_result.is_valid:
                    errors.extend(field_result.errors)
                    warnings.extend(field_result.warnings)
                
                if field_result.fixed_data:
                    fixed_data.update(field_result.fixed_data)
                
                # Log validation result
                if sync_operation:
                    await self._log_validation_result(
                        rule, sync_operation, 'enrollment',
                        str(enrollment_data.get('id', 'unknown')),
                        field_result.is_valid, field_value,
                        field_result.errors[0].error_message if field_result.errors else None,
                        field_result.fixed_data.get(rule.field_name) if field_result.fixed_data else None
                    )
            
            except Exception as e:
                logger.error(f"Error validating enrollment field {rule.field_name}: {e}")
                errors.append(ValidationError(
                    field_name=rule.field_name,
                    error_type='validation_error',
                    error_message=f"Validation failed: {str(e)}",
                    field_value=field_value
                ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            fixed_data=fixed_data if fixed_data else None
        )
    
    async def validate_grade_data(
        self,
        integration_id: int,
        grade_data: Dict[str, Any],
        sync_operation: Optional[SyncOperation] = None
    ) -> ValidationResult:
        """
        Validate grade data.
        
        Args:
            integration_id: SIS integration ID
            grade_data: Grade data to validate
            sync_operation: Optional sync operation for logging
            
        Returns:
            ValidationResult with validation status and errors
        """
        logger.debug(f"Validating grade data for integration {integration_id}")
        
        errors = []
        warnings = []
        fixed_data = {}
        
        # Get validation rules for grade data
        rules = await self._get_validation_rules(integration_id, DataType.GRADES)
        
        for rule in rules:
            try:
                field_value = grade_data.get(rule.field_name)
                
                field_result = await self._validate_field(
                    rule, field_value, grade_data
                )
                
                if not field_result.is_valid:
                    errors.extend(field_result.errors)
                    warnings.extend(field_result.warnings)
                
                if field_result.fixed_data:
                    fixed_data.update(field_result.fixed_data)
                
                # Log validation result
                if sync_operation:
                    await self._log_validation_result(
                        rule, sync_operation, 'grade',
                        str(grade_data.get('id', 'unknown')),
                        field_result.is_valid, field_value,
                        field_result.errors[0].error_message if field_result.errors else None,
                        field_result.fixed_data.get(rule.field_name) if field_result.fixed_data else None
                    )
            
            except Exception as e:
                logger.error(f"Error validating grade field {rule.field_name}: {e}")
                errors.append(ValidationError(
                    field_name=rule.field_name,
                    error_type='validation_error',
                    error_message=f"Validation failed: {str(e)}",
                    field_value=field_value
                ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            fixed_data=fixed_data if fixed_data else None
        )
    
    async def _validate_field(
        self,
        rule: DataValidationRule,
        field_value: Any,
        full_data: Dict[str, Any]
    ) -> ValidationResult:
        """Validate a single field using the specified rule."""
        errors = []
        warnings = []
        fixed_data = {}
        
        # Get validator function
        validator = self._validators.get(rule.rule_type)
        if not validator:
            errors.append(ValidationError(
                field_name=rule.field_name,
                error_type='unknown_rule',
                error_message=f"Unknown validation rule type: {rule.rule_type}",
                field_value=field_value
            ))
            return ValidationResult(False, errors, warnings)
        
        # Apply validation
        try:
            is_valid, error_message, fixed_value = await validator(
                field_value, rule.rule_config, full_data
            )
            
            if not is_valid:
                errors.append(ValidationError(
                    field_name=rule.field_name,
                    error_type=rule.rule_type,
                    error_message=error_message,
                    field_value=field_value
                ))
            
            # Apply fix if available and needed
            if not is_valid and rule.fix_strategy and fixed_value is not None:
                fixer = self._fixers.get(rule.fix_strategy)
                if fixer:
                    try:
                        fixed_result = await fixer(field_value, rule.rule_config)
                        if fixed_result is not None:
                            fixed_data[rule.field_name] = fixed_result
                            # Convert error to warning if we can fix it
                            if errors:
                                warnings.append(errors.pop())
                    except Exception as e:
                        logger.warning(f"Failed to apply fix {rule.fix_strategy}: {e}")
            
        except Exception as e:
            errors.append(ValidationError(
                field_name=rule.field_name,
                error_type='validation_exception',
                error_message=f"Validation exception: {str(e)}",
                field_value=field_value
            ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            fixed_data=fixed_data if fixed_data else None
        )
    
    # Built-in validators
    
    async def _validate_required(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate that a field is not empty."""
        if value is None or value == '' or (isinstance(value, str) and not value.strip()):
            return False, "Field is required", None
        return True, "", None
    
    async def _validate_email(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate email format."""
        if not value:
            return True, "", None  # Empty is valid unless required
        
        try:
            valid = validate_email(str(value))
            return True, "", valid.email
        except EmailNotValidError as e:
            return False, f"Invalid email format: {str(e)}", None
    
    async def _validate_phone(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate phone number format."""
        if not value:
            return True, "", None
        
        try:
            # Try to parse with default region (US)
            region = config.get('region', 'US')
            parsed = phonenumbers.parse(str(value), region)
            
            if phonenumbers.is_valid_number(parsed):
                formatted = phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
                return True, "", formatted
            else:
                return False, "Invalid phone number", None
        
        except NumberParseException as e:
            return False, f"Invalid phone format: {str(e)}", None
    
    async def _validate_date(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate date format."""
        if not value:
            return True, "", None
        
        if isinstance(value, (date, datetime)):
            return True, "", value
        
        # Try common date formats
        date_formats = config.get('formats', [
            '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S'
        ])
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(str(value), fmt)
                return True, "", parsed_date.date()
            except ValueError:
                continue
        
        return False, f"Invalid date format. Expected formats: {date_formats}", None
    
    async def _validate_numeric(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate numeric value."""
        if not value and value != 0:
            return True, "", None
        
        try:
            if config.get('integer', False):
                num_value = int(value)
            else:
                num_value = float(value)
            return True, "", num_value
        except (ValueError, TypeError):
            return False, "Must be a numeric value", None
    
    async def _validate_range(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate value is within specified range."""
        if not value and value != 0:
            return True, "", None
        
        try:
            num_value = float(value)
            min_val = config.get('min')
            max_val = config.get('max')
            
            if min_val is not None and num_value < min_val:
                return False, f"Value must be at least {min_val}", None
            
            if max_val is not None and num_value > max_val:
                return False, f"Value must be at most {max_val}", None
            
            return True, "", num_value
        except (ValueError, TypeError):
            return False, "Must be a numeric value for range validation", None
    
    async def _validate_length(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate string length."""
        if not value:
            return True, "", None
        
        str_value = str(value)
        length = len(str_value)
        
        min_len = config.get('min')
        max_len = config.get('max')
        
        if min_len is not None and length < min_len:
            return False, f"Must be at least {min_len} characters long", None
        
        if max_len is not None and length > max_len:
            return False, f"Must be at most {max_len} characters long", None
        
        return True, "", str_value
    
    async def _validate_pattern(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate value matches regex pattern."""
        if not value:
            return True, "", None
        
        pattern = config.get('pattern')
        if not pattern:
            return False, "No pattern specified for pattern validation", None
        
        try:
            if re.match(pattern, str(value)):
                return True, "", str(value)
            else:
                return False, f"Value does not match required pattern: {pattern}", None
        except re.error as e:
            return False, f"Invalid regex pattern: {str(e)}", None
    
    async def _validate_enum(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate value is in allowed list."""
        if not value:
            return True, "", None
        
        allowed_values = config.get('values', [])
        if not allowed_values:
            return False, "No allowed values specified for enum validation", None
        
        if value in allowed_values:
            return True, "", value
        else:
            return False, f"Value must be one of: {allowed_values}", None
    
    async def _validate_student_id(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate student ID format."""
        if not value:
            return True, "", None
        
        str_value = str(value).strip()
        
        # Check minimum length
        min_len = config.get('min_length', 1)
        if len(str_value) < min_len:
            return False, f"Student ID must be at least {min_len} characters", None
        
        # Check if it should be numeric
        if config.get('numeric_only', False):
            if not str_value.isdigit():
                return False, "Student ID must be numeric", None
        
        return True, "", str_value
    
    async def _validate_grade(
        self,
        value: Any,
        config: Dict[str, Any],
        full_data: Dict[str, Any]
    ) -> Tuple[bool, str, Any]:
        """Validate grade value."""
        if not value and value != 0:
            return True, "", None
        
        try:
            grade_value = float(value)
            
            # Check grade scale
            min_grade = config.get('min_grade', 0)
            max_grade = config.get('max_grade', 100)
            
            if grade_value < min_grade or grade_value > max_grade:
                return False, f"Grade must be between {min_grade} and {max_grade}", None
            
            return True, "", grade_value
        except (ValueError, TypeError):
            return False, "Grade must be a numeric value", None
    
    # Built-in fixers
    
    async def _fix_trim(self, value: Any, config: Dict[str, Any]) -> Optional[str]:
        """Trim whitespace from string value."""
        if isinstance(value, str):
            return value.strip()
        return None
    
    async def _fix_capitalize(self, value: Any, config: Dict[str, Any]) -> Optional[str]:
        """Capitalize string value."""
        if isinstance(value, str):
            mode = config.get('mode', 'title')  # 'title', 'upper', 'lower'
            if mode == 'title':
                return value.title()
            elif mode == 'upper':
                return value.upper()
            elif mode == 'lower':
                return value.lower()
        return None
    
    async def _fix_phone_format(self, value: Any, config: Dict[str, Any]) -> Optional[str]:
        """Format phone number."""
        if not value:
            return None
        
        try:
            region = config.get('region', 'US')
            parsed = phonenumbers.parse(str(value), region)
            
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
        except NumberParseException:
            pass
        
        return None
    
    async def _fix_email_lowercase(self, value: Any, config: Dict[str, Any]) -> Optional[str]:
        """Convert email to lowercase."""
        if isinstance(value, str) and '@' in value:
            return value.lower().strip()
        return None
    
    async def _fix_default_value(self, value: Any, config: Dict[str, Any]) -> Any:
        """Set default value if field is empty."""
        if not value:
            return config.get('default')
        return None
    
    # Helper methods
    
    async def _get_validation_rules(
        self,
        integration_id: int,
        data_type: DataType
    ) -> List[DataValidationRule]:
        """Get validation rules for an integration and data type."""
        result = await self.db.execute(
            select(DataValidationRule).where(
                and_(
                    DataValidationRule.integration_id == integration_id,
                    DataValidationRule.data_type == data_type,
                    DataValidationRule.is_enabled == True
                )
            ).order_by(DataValidationRule.field_name)
        )
        return list(result.scalars().all())
    
    async def _log_validation_result(
        self,
        rule: DataValidationRule,
        sync_operation: SyncOperation,
        record_type: str,
        record_id: str,
        is_valid: bool,
        field_value: Any,
        error_message: Optional[str] = None,
        fixed_value: Optional[Any] = None
    ) -> None:
        """Log validation result to database."""
        validation_result = ValidationResult(
            validation_rule_id=rule.id,
            sync_operation_id=sync_operation.id,
            record_type=record_type,
            record_id=record_id,
            is_valid=is_valid,
            error_message=error_message,
            field_value=str(field_value) if field_value is not None else None,
            action_taken='fixed' if fixed_value is not None else ('skipped' if not is_valid else 'passed'),
            fixed_value=str(fixed_value) if fixed_value is not None else None
        )
        
        self.db.add(validation_result)
        
        # Update rule failure count
        if not is_valid:
            rule.failure_count += 1
            rule.last_failure_at = datetime.utcnow()
    
    async def _validate_student_cross_fields(
        self,
        student_data: Dict[str, Any]
    ) -> List[ValidationError]:
        """Perform cross-field validation for student data."""
        errors = []
        
        # Example: Check that first_name and last_name are both present or both absent
        first_name = student_data.get('first_name')
        last_name = student_data.get('last_name')
        
        if (first_name and not last_name) or (not first_name and last_name):
            errors.append(ValidationError(
                field_name='name',
                error_type='cross_field',
                error_message='Both first_name and last_name must be provided together',
                field_value={'first_name': first_name, 'last_name': last_name}
            ))
        
        # Add more cross-field validations as needed
        
        return errors


# Utility functions for creating common validation rules

async def create_default_validation_rules(
    db: AsyncSession,
    integration_id: int
) -> List[DataValidationRule]:
    """Create default validation rules for an integration."""
    rules = []
    
    # Student demographics rules
    student_rules = [
        {
            'name': 'Student ID Required',
            'data_type': DataType.STUDENT_DEMOGRAPHICS,
            'field_name': 'student_id',
            'rule_type': 'required',
            'rule_config': {},
            'on_failure_action': 'fail'
        },
        {
            'name': 'Email Format',
            'data_type': DataType.STUDENT_DEMOGRAPHICS,
            'field_name': 'email',
            'rule_type': 'email',
            'rule_config': {},
            'on_failure_action': 'fix',
            'fix_strategy': 'email_lowercase'
        },
        {
            'name': 'Phone Format',
            'data_type': DataType.STUDENT_DEMOGRAPHICS,
            'field_name': 'phone',
            'rule_type': 'phone',
            'rule_config': {'region': 'US'},
            'on_failure_action': 'fix',
            'fix_strategy': 'phone_format'
        },
        {
            'name': 'First Name Required',
            'data_type': DataType.STUDENT_DEMOGRAPHICS,
            'field_name': 'first_name',
            'rule_type': 'required',
            'rule_config': {},
            'on_failure_action': 'fail'
        },
        {
            'name': 'Last Name Required',
            'data_type': DataType.STUDENT_DEMOGRAPHICS,
            'field_name': 'last_name',
            'rule_type': 'required',
            'rule_config': {},
            'on_failure_action': 'fail'
        }
    ]
    
    # Grade rules
    grade_rules = [
        {
            'name': 'Grade Range',
            'data_type': DataType.GRADES,
            'field_name': 'grade',
            'rule_type': 'grade',
            'rule_config': {'min_grade': 0, 'max_grade': 100},
            'on_failure_action': 'fail'
        }
    ]
    
    all_rule_configs = student_rules + grade_rules
    
    for rule_config in all_rule_configs:
        rule = DataValidationRule(
            integration_id=integration_id,
            **rule_config
        )
        db.add(rule)
        rules.append(rule)
    
    await db.commit()
    return rules