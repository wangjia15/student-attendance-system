"""
Skyward API integration client.
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin
import json

from app.core.sis_config import BaseSISProvider, SISProviderConfig, OAuthConfig
from app.integrations.sis.oauth_service import SISOAuthService, AuthenticationFailedError
from app.models.sis_integration import SISIntegration


logger = logging.getLogger(__name__)


class SkywardAPIError(Exception):
    """Skyward API specific error."""
    pass


class SkywardProvider(BaseSISProvider):
    """Skyward SIS integration provider."""
    
    def __init__(self, config: SISProviderConfig, integration: SISIntegration, oauth_service: SISOAuthService):
        super().__init__(config)
        self.integration = integration
        self.oauth_service = oauth_service
        self._http_session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        """Async context manager entry."""
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        self._http_session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                'User-Agent': 'Student-Attendance-System/1.0',
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None
            
    async def authenticate(self) -> bool:
        """
        Authenticate with Skyward using OAuth 2.0.
        
        Returns:
            True if authentication successful
        """
        try:
            if not self.config.oauth_config:
                raise AuthenticationFailedError("OAuth configuration not found")
                
            token = await self.oauth_service.get_valid_token(
                self.integration,
                self.config.oauth_config
            )
            
            if token:
                self._authenticated = True
                self._token_expires_at = token.expires_at
                logger.info(f"Skyward authentication successful for {self.integration.provider_id}")
                return True
                
            logger.warning(f"Skyward authentication failed for {self.integration.provider_id}")
            return False
            
        except Exception as e:
            logger.error(f"Skyward authentication error for {self.integration.provider_id}: {e}")
            self.integration.update_auth_failure()
            return False
            
    async def get_students(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Get student data from Skyward.
        
        Args:
            **kwargs: Additional parameters like page, page_size, school_id
            
        Returns:
            List of student records
        """
        if not await self._ensure_authenticated():
            raise SkywardAPIError("Authentication failed")
            
        # Skyward API parameters
        params = {
            'PageSize': kwargs.get('limit', 100),
            'PageNumber': kwargs.get('page', 1),
        }
        
        # Add school filter if provided
        if 'school_id' in kwargs:
            params['SchoolId'] = kwargs['school_id']
            
        # Add active status filter
        if 'active_only' in kwargs:
            params['ActiveOnly'] = kwargs['active_only']
        else:
            params['ActiveOnly'] = True  # Default to active students only
            
        try:
            endpoint = f"/api/{self.config.api_version}/students"
            response = await self._make_api_request('GET', endpoint, params=params)
            
            students = response.get('Data', [])
            
            # Transform Skyward format to standard format
            transformed_students = []
            for student in students:
                transformed_student = self._transform_student_data(student)
                transformed_students.append(transformed_student)
                
            logger.info(
                f"Retrieved {len(transformed_students)} students from Skyward "
                f"for {self.integration.provider_id}"
            )
            return transformed_students
            
        except Exception as e:
            logger.error(f"Error retrieving students from Skyward: {e}")
            raise SkywardAPIError(f"Failed to retrieve students: {e}")
            
    async def get_enrollments(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Get enrollment data from Skyward.
        
        Args:
            **kwargs: Additional parameters like student_id, school_id, term_id
            
        Returns:
            List of enrollment records
        """
        if not await self._ensure_authenticated():
            raise SkywardAPIError("Authentication failed")
            
        params = {
            'PageSize': kwargs.get('limit', 100),
            'PageNumber': kwargs.get('page', 1),
        }
        
        # Add filters
        if 'student_id' in kwargs:
            params['StudentId'] = kwargs['student_id']
        if 'school_id' in kwargs:
            params['SchoolId'] = kwargs['school_id']
        if 'term_id' in kwargs:
            params['TermId'] = kwargs['term_id']
            
        # Add active status filter
        if 'active_only' in kwargs:
            params['ActiveOnly'] = kwargs['active_only']
        else:
            params['ActiveOnly'] = True
            
        try:
            endpoint = f"/api/{self.config.api_version}/enrollments"
            response = await self._make_api_request('GET', endpoint, params=params)
            
            enrollments = response.get('Data', [])
            
            # Transform Skyward format to standard format
            transformed_enrollments = []
            for enrollment in enrollments:
                transformed_enrollment = self._transform_enrollment_data(enrollment)
                transformed_enrollments.append(transformed_enrollment)
                
            logger.info(
                f"Retrieved {len(transformed_enrollments)} enrollments from Skyward "
                f"for {self.integration.provider_id}"
            )
            return transformed_enrollments
            
        except Exception as e:
            logger.error(f"Error retrieving enrollments from Skyward: {e}")
            raise SkywardAPIError(f"Failed to retrieve enrollments: {e}")
            
    async def sync_student(self, student_data: Dict[str, Any]) -> bool:
        """
        Sync a single student to Skyward.
        
        Args:
            student_data: Student data to sync
            
        Returns:
            True if sync successful
        """
        if not await self._ensure_authenticated():
            raise SkywardAPIError("Authentication failed")
            
        try:
            # Transform to Skyward format
            skyward_student_data = self._transform_student_to_skyward(student_data)
            
            # Check if student exists
            student_id = student_data.get('sis_student_id')
            if student_id:
                # Update existing student
                endpoint = f"/api/{self.config.api_version}/students/{student_id}"
                await self._make_api_request('PUT', endpoint, json=skyward_student_data)
                logger.info(f"Updated student {student_id} in Skyward")
            else:
                # Create new student
                endpoint = f"/api/{self.config.api_version}/students"
                response = await self._make_api_request('POST', endpoint, json=skyward_student_data)
                logger.info(f"Created new student in Skyward: {response.get('StudentId')}")
                
            return True
            
        except Exception as e:
            logger.error(f"Error syncing student to Skyward: {e}")
            return False
            
    async def health_check(self) -> bool:
        """Check Skyward API health."""
        try:
            if not await self._ensure_authenticated():
                return False
                
            # Test API with a simple request
            endpoint = f"/api/{self.config.api_version}/schools"
            await self._make_api_request('GET', endpoint, params={'PageSize': 1})
            
            logger.info(f"Skyward health check passed for {self.integration.provider_id}")
            return True
            
        except Exception as e:
            logger.error(f"Skyward health check failed for {self.integration.provider_id}: {e}")
            return False
            
    async def _ensure_authenticated(self) -> bool:
        """Ensure we have valid authentication."""
        if self.is_authenticated:
            return True
        return await self.authenticate()
        
    async def _make_api_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json: Optional[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make authenticated API request to Skyward."""
        if not self._http_session:
            raise RuntimeError("HTTP session not initialized")
            
        # Get access token
        token = await self.oauth_service.get_valid_token(
            self.integration,
            self.config.oauth_config
        )
        
        if not token:
            raise AuthenticationFailedError("No valid token available")
            
        access_token = await self.oauth_service.get_decrypted_token(token)
        
        # Build request URL
        url = urljoin(self.config.base_url, endpoint)
        
        # Set authorization header
        headers = kwargs.get('headers', {})
        headers['Authorization'] = f"Bearer {access_token}"
        
        # Track API call
        self.integration.total_api_calls += 1
        
        try:
            async with self._http_session.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                **{k: v for k, v in kwargs.items() if k != 'headers'}
            ) as response:
                
                if response.status == 401:
                    # Token might be invalid, try to refresh
                    self._authenticated = False
                    if await self.authenticate():
                        # Retry the request once
                        token = await self.oauth_service.get_valid_token(
                            self.integration,
                            self.config.oauth_config
                        )
                        access_token = await self.oauth_service.get_decrypted_token(token)
                        headers['Authorization'] = f"Bearer {access_token}"
                        
                        async with self._http_session.request(
                            method,
                            url,
                            params=params,
                            json=json,
                            headers=headers,
                            **{k: v for k, v in kwargs.items() if k != 'headers'}
                        ) as retry_response:
                            if retry_response.status >= 400:
                                error_text = await retry_response.text()
                                raise SkywardAPIError(
                                    f"API request failed: {retry_response.status} - {error_text}"
                                )
                            return await retry_response.json()
                    else:
                        raise AuthenticationFailedError("Failed to refresh authentication")
                        
                elif response.status >= 400:
                    error_text = await response.text()
                    raise SkywardAPIError(
                        f"API request failed: {response.status} - {error_text}"
                    )
                    
                return await response.json()
                
        except aiohttp.ClientError as e:
            raise SkywardAPIError(f"HTTP client error: {e}")
            
    def _transform_student_data(self, skyward_student: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Skyward student data to standard format."""
        return {
            'sis_student_id': str(skyward_student.get('StudentId', '')),
            'sis_student_number': str(skyward_student.get('StudentNumber', '')),
            'first_name': skyward_student.get('FirstName', ''),
            'last_name': skyward_student.get('LastName', ''),
            'middle_name': skyward_student.get('MiddleName', ''),
            'email': skyward_student.get('Email', ''),
            'grade_level': skyward_student.get('GradeLevel'),
            'school_id': skyward_student.get('SchoolId'),
            'state_id': skyward_student.get('StateId', ''),
            'active': skyward_student.get('IsActive', False),
            'enrollment_date': skyward_student.get('EnrollmentDate'),
            'graduation_year': skyward_student.get('GraduationYear'),
            'birth_date': skyward_student.get('BirthDate'),
            'gender': skyward_student.get('Gender'),
            'home_phone': skyward_student.get('HomePhone'),
            'address': {
                'street': skyward_student.get('Address', ''),
                'city': skyward_student.get('City', ''),
                'state': skyward_student.get('State', ''),
                'zip': skyward_student.get('ZipCode', '')
            },
            'raw_data': skyward_student  # Keep original data for debugging
        }
        
    def _transform_enrollment_data(self, skyward_enrollment: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Skyward enrollment data to standard format."""
        return {
            'student_id': str(skyward_enrollment.get('StudentId', '')),
            'section_id': str(skyward_enrollment.get('SectionId', '')),
            'course_number': skyward_enrollment.get('CourseNumber', ''),
            'course_name': skyward_enrollment.get('CourseName', ''),
            'teacher_id': str(skyward_enrollment.get('TeacherId', '')),
            'teacher_name': skyward_enrollment.get('TeacherName', ''),
            'period': skyward_enrollment.get('Period', ''),
            'room': skyward_enrollment.get('Room', ''),
            'term_id': skyward_enrollment.get('TermId'),
            'start_date': skyward_enrollment.get('StartDate'),
            'end_date': skyward_enrollment.get('EndDate'),
            'active': skyward_enrollment.get('IsActive', False),
            'credit_hours': skyward_enrollment.get('CreditHours'),
            'department': skyward_enrollment.get('Department', ''),
            'raw_data': skyward_enrollment
        }
        
    def _transform_student_to_skyward(self, student_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform standard student data to Skyward format."""
        skyward_data = {}
        
        # Map standard fields to Skyward fields
        field_mapping = {
            'first_name': 'FirstName',
            'last_name': 'LastName',
            'middle_name': 'MiddleName',
            'email': 'Email',
            'grade_level': 'GradeLevel',
            'state_id': 'StateId',
            'active': 'IsActive',
            'enrollment_date': 'EnrollmentDate',
            'graduation_year': 'GraduationYear',
            'birth_date': 'BirthDate',
            'gender': 'Gender',
            'home_phone': 'HomePhone'
        }
        
        for std_field, skyward_field in field_mapping.items():
            if std_field in student_data and student_data[std_field] is not None:
                skyward_data[skyward_field] = student_data[std_field]
                
        # Handle address fields
        if 'address' in student_data and student_data['address']:
            address = student_data['address']
            if isinstance(address, dict):
                skyward_data['Address'] = address.get('street', '')
                skyward_data['City'] = address.get('city', '')
                skyward_data['State'] = address.get('state', '')
                skyward_data['ZipCode'] = address.get('zip', '')
            elif isinstance(address, str):
                skyward_data['Address'] = address
                
        # Handle student number
        if 'sis_student_number' in student_data and student_data['sis_student_number']:
            skyward_data['StudentNumber'] = student_data['sis_student_number']
            
        # Handle school ID
        if 'school_id' in student_data and student_data['school_id']:
            skyward_data['SchoolId'] = student_data['school_id']
            
        return skyward_data