"""
Infinite Campus API integration client.
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


class InfiniteCampusAPIError(Exception):
    """Infinite Campus API specific error."""
    pass


class InfiniteCampusProvider(BaseSISProvider):
    """Infinite Campus SIS integration provider."""
    
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
        Authenticate with Infinite Campus using OAuth 2.0.
        
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
                logger.info(f"Infinite Campus authentication successful for {self.integration.provider_id}")
                return True
                
            logger.warning(f"Infinite Campus authentication failed for {self.integration.provider_id}")
            return False
            
        except Exception as e:
            logger.error(f"Infinite Campus authentication error for {self.integration.provider_id}: {e}")
            self.integration.update_auth_failure()
            return False
            
    async def get_students(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Get student data from Infinite Campus.
        
        Args:
            **kwargs: Additional parameters like page, limit, school_year
            
        Returns:
            List of student records
        """
        if not await self._ensure_authenticated():
            raise InfiniteCampusAPIError("Authentication failed")
            
        # Infinite Campus API parameters
        params = {
            'limit': kwargs.get('limit', 100),
            'offset': kwargs.get('offset', 0),
        }
        
        # Add school year filter if provided
        if 'school_year' in kwargs:
            params['schoolYear'] = kwargs['school_year']
        else:
            # Default to current school year
            current_year = datetime.now().year
            school_year = current_year if datetime.now().month >= 7 else current_year - 1
            params['schoolYear'] = school_year
            
        # Add school filter if provided
        if 'school_id' in kwargs:
            params['schoolID'] = kwargs['school_id']
            
        try:
            endpoint = f"/campus/api/{self.config.api_version}/students"
            response = await self._make_api_request('GET', endpoint, params=params)
            
            students = response.get('students', [])
            
            # Transform Infinite Campus format to standard format
            transformed_students = []
            for student in students:
                transformed_student = self._transform_student_data(student)
                transformed_students.append(transformed_student)
                
            logger.info(
                f"Retrieved {len(transformed_students)} students from Infinite Campus "
                f"for {self.integration.provider_id}"
            )
            return transformed_students
            
        except Exception as e:
            logger.error(f"Error retrieving students from Infinite Campus: {e}")
            raise InfiniteCampusAPIError(f"Failed to retrieve students: {e}")
            
    async def get_enrollments(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Get enrollment data from Infinite Campus.
        
        Args:
            **kwargs: Additional parameters like student_id, school_id, term_id
            
        Returns:
            List of enrollment records
        """
        if not await self._ensure_authenticated():
            raise InfiniteCampusAPIError("Authentication failed")
            
        params = {
            'limit': kwargs.get('limit', 100),
            'offset': kwargs.get('offset', 0),
        }
        
        # Add filters
        if 'student_id' in kwargs:
            params['studentID'] = kwargs['student_id']
        if 'school_id' in kwargs:
            params['schoolID'] = kwargs['school_id']
        if 'term_id' in kwargs:
            params['termID'] = kwargs['term_id']
            
        # Add school year
        if 'school_year' in kwargs:
            params['schoolYear'] = kwargs['school_year']
        else:
            current_year = datetime.now().year
            school_year = current_year if datetime.now().month >= 7 else current_year - 1
            params['schoolYear'] = school_year
            
        try:
            endpoint = f"/campus/api/{self.config.api_version}/sections/enrollments"
            response = await self._make_api_request('GET', endpoint, params=params)
            
            enrollments = response.get('enrollments', [])
            
            # Transform Infinite Campus format to standard format
            transformed_enrollments = []
            for enrollment in enrollments:
                transformed_enrollment = self._transform_enrollment_data(enrollment)
                transformed_enrollments.append(transformed_enrollment)
                
            logger.info(
                f"Retrieved {len(transformed_enrollments)} enrollments from Infinite Campus "
                f"for {self.integration.provider_id}"
            )
            return transformed_enrollments
            
        except Exception as e:
            logger.error(f"Error retrieving enrollments from Infinite Campus: {e}")
            raise InfiniteCampusAPIError(f"Failed to retrieve enrollments: {e}")
            
    async def sync_student(self, student_data: Dict[str, Any]) -> bool:
        """
        Sync a single student to Infinite Campus.
        
        Args:
            student_data: Student data to sync
            
        Returns:
            True if sync successful
        """
        if not await self._ensure_authenticated():
            raise InfiniteCampusAPIError("Authentication failed")
            
        try:
            # Transform to Infinite Campus format
            ic_student_data = self._transform_student_to_infinite_campus(student_data)
            
            # Check if student exists
            student_id = student_data.get('sis_student_id')
            if student_id:
                # Update existing student
                endpoint = f"/campus/api/{self.config.api_version}/students/{student_id}"
                await self._make_api_request('PUT', endpoint, json=ic_student_data)
                logger.info(f"Updated student {student_id} in Infinite Campus")
            else:
                # Create new student
                endpoint = f"/campus/api/{self.config.api_version}/students"
                response = await self._make_api_request('POST', endpoint, json=ic_student_data)
                logger.info(f"Created new student in Infinite Campus: {response.get('personID')}")
                
            return True
            
        except Exception as e:
            logger.error(f"Error syncing student to Infinite Campus: {e}")
            return False
            
    async def health_check(self) -> bool:
        """Check Infinite Campus API health."""
        try:
            if not await self._ensure_authenticated():
                return False
                
            # Test API with a simple request
            endpoint = f"/campus/api/{self.config.api_version}/districts"
            await self._make_api_request('GET', endpoint, params={'limit': 1})
            
            logger.info(f"Infinite Campus health check passed for {self.integration.provider_id}")
            return True
            
        except Exception as e:
            logger.error(f"Infinite Campus health check failed for {self.integration.provider_id}: {e}")
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
        """Make authenticated API request to Infinite Campus."""
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
                                raise InfiniteCampusAPIError(
                                    f"API request failed: {retry_response.status} - {error_text}"
                                )
                            return await retry_response.json()
                    else:
                        raise AuthenticationFailedError("Failed to refresh authentication")
                        
                elif response.status >= 400:
                    error_text = await response.text()
                    raise InfiniteCampusAPIError(
                        f"API request failed: {response.status} - {error_text}"
                    )
                    
                return await response.json()
                
        except aiohttp.ClientError as e:
            raise InfiniteCampusAPIError(f"HTTP client error: {e}")
            
    def _transform_student_data(self, ic_student: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Infinite Campus student data to standard format."""
        identity = ic_student.get('identity', {})
        enrollment = ic_student.get('enrollment', {})
        
        return {
            'sis_student_id': str(ic_student.get('personID', '')),
            'sis_student_number': str(ic_student.get('studentNumber', '')),
            'first_name': identity.get('firstName', ''),
            'last_name': identity.get('lastName', ''),
            'middle_name': identity.get('middleName', ''),
            'email': identity.get('email', ''),
            'grade_level': enrollment.get('grade'),
            'school_id': enrollment.get('schoolID'),
            'state_id': ic_student.get('stateID', ''),
            'active': enrollment.get('active', False),
            'enrollment_date': enrollment.get('startDate'),
            'graduation_year': enrollment.get('graduationYear'),
            'birth_date': identity.get('birthDate'),
            'gender': identity.get('gender'),
            'raw_data': ic_student  # Keep original data for debugging
        }
        
    def _transform_enrollment_data(self, ic_enrollment: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Infinite Campus enrollment data to standard format."""
        section = ic_enrollment.get('section', {})
        course = section.get('course', {})
        teacher = section.get('teacher', {})
        
        return {
            'student_id': str(ic_enrollment.get('personID', '')),
            'section_id': str(section.get('sectionID', '')),
            'course_number': course.get('courseNumber', ''),
            'course_name': course.get('courseName', ''),
            'teacher_id': str(teacher.get('personID', '')),
            'teacher_name': f"{teacher.get('firstName', '')} {teacher.get('lastName', '')}".strip(),
            'period': section.get('period', ''),
            'room': section.get('roomNumber', ''),
            'term_id': section.get('termID'),
            'start_date': ic_enrollment.get('startDate'),
            'end_date': ic_enrollment.get('endDate'),
            'active': ic_enrollment.get('active', False),
            'credit_hours': course.get('creditHours'),
            'raw_data': ic_enrollment
        }
        
    def _transform_student_to_infinite_campus(self, student_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform standard student data to Infinite Campus format."""
        ic_data = {
            'identity': {},
            'enrollment': {}
        }
        
        # Map identity fields
        identity_mapping = {
            'first_name': 'firstName',
            'last_name': 'lastName',
            'middle_name': 'middleName',
            'email': 'email',
            'birth_date': 'birthDate',
            'gender': 'gender'
        }
        
        for std_field, ic_field in identity_mapping.items():
            if std_field in student_data and student_data[std_field]:
                ic_data['identity'][ic_field] = student_data[std_field]
                
        # Map enrollment fields
        enrollment_mapping = {
            'grade_level': 'grade',
            'school_id': 'schoolID',
            'active': 'active',
            'enrollment_date': 'startDate',
            'graduation_year': 'graduationYear'
        }
        
        for std_field, ic_field in enrollment_mapping.items():
            if std_field in student_data and student_data[std_field] is not None:
                ic_data['enrollment'][ic_field] = student_data[std_field]
                
        # Handle state ID
        if 'state_id' in student_data and student_data['state_id']:
            ic_data['stateID'] = student_data['state_id']
            
        # Handle student number
        if 'sis_student_number' in student_data and student_data['sis_student_number']:
            ic_data['studentNumber'] = student_data['sis_student_number']
            
        return ic_data