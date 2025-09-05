"""
PowerSchool API integration client.
"""

import asyncio
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    # Create mock aiohttp for when it's not available
    class MockAiohttp:
        class ClientSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def get(self, *args, **kwargs):
                raise NotImplementedError("aiohttp not available")
            async def post(self, *args, **kwargs):
                raise NotImplementedError("aiohttp not available")
    aiohttp = MockAiohttp()
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin
import json

from app.core.sis_config import BaseSISProvider, SISProviderConfig, OAuthConfig
from app.integrations.sis.oauth_service import SISOAuthService, AuthenticationFailedError
from app.models.sis_integration import SISIntegration


logger = logging.getLogger(__name__)


class PowerSchoolAPIError(Exception):
    """PowerSchool API specific error."""
    pass


class PowerSchoolProvider(BaseSISProvider):
    """PowerSchool SIS integration provider."""
    
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
        Authenticate with PowerSchool using OAuth 2.0.
        
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
                logger.info(f"PowerSchool authentication successful for {self.integration.provider_id}")
                return True
                
            logger.warning(f"PowerSchool authentication failed for {self.integration.provider_id}")
            return False
            
        except Exception as e:
            logger.error(f"PowerSchool authentication error for {self.integration.provider_id}: {e}")
            self.integration.update_auth_failure()
            return False
            
    async def get_students(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Get student data from PowerSchool.
        
        Args:
            **kwargs: Additional parameters like page, limit, school_id
            
        Returns:
            List of student records
        """
        if not await self._ensure_authenticated():
            raise PowerSchoolAPIError("Authentication failed")
            
        # PowerSchool API parameters
        params = {
            'pagesize': kwargs.get('limit', 100),
            'page': kwargs.get('page', 1),
        }
        
        # Add school filter if provided
        if 'school_id' in kwargs:
            params['q'] = f"school_number=={kwargs['school_id']}"
            
        try:
            endpoint = f"/ws/{self.config.api_version}/district/student"
            response = await self._make_api_request('GET', endpoint, params=params)
            
            students = response.get('students', {}).get('student', [])
            if not isinstance(students, list):
                students = [students] if students else []
                
            # Transform PowerSchool format to standard format
            transformed_students = []
            for student in students:
                transformed_student = self._transform_student_data(student)
                transformed_students.append(transformed_student)
                
            logger.info(
                f"Retrieved {len(transformed_students)} students from PowerSchool "
                f"for {self.integration.provider_id}"
            )
            return transformed_students
            
        except Exception as e:
            logger.error(f"Error retrieving students from PowerSchool: {e}")
            raise PowerSchoolAPIError(f"Failed to retrieve students: {e}")
            
    async def get_enrollments(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Get enrollment data from PowerSchool.
        
        Args:
            **kwargs: Additional parameters like student_id, school_id, term_id
            
        Returns:
            List of enrollment records
        """
        if not await self._ensure_authenticated():
            raise PowerSchoolAPIError("Authentication failed")
            
        params = {
            'pagesize': kwargs.get('limit', 100),
            'page': kwargs.get('page', 1),
        }
        
        # Build query conditions
        conditions = []
        if 'student_id' in kwargs:
            conditions.append(f"studentid=={kwargs['student_id']}")
        if 'school_id' in kwargs:
            conditions.append(f"schoolid=={kwargs['school_id']}")
        if 'term_id' in kwargs:
            conditions.append(f"termid=={kwargs['term_id']}")
            
        if conditions:
            params['q'] = ';'.join(conditions)
            
        try:
            endpoint = f"/ws/{self.config.api_version}/district/section_enrollment"
            response = await self._make_api_request('GET', endpoint, params=params)
            
            enrollments = response.get('section_enrollments', {}).get('section_enrollment', [])
            if not isinstance(enrollments, list):
                enrollments = [enrollments] if enrollments else []
                
            # Transform PowerSchool format to standard format
            transformed_enrollments = []
            for enrollment in enrollments:
                transformed_enrollment = self._transform_enrollment_data(enrollment)
                transformed_enrollments.append(transformed_enrollment)
                
            logger.info(
                f"Retrieved {len(transformed_enrollments)} enrollments from PowerSchool "
                f"for {self.integration.provider_id}"
            )
            return transformed_enrollments
            
        except Exception as e:
            logger.error(f"Error retrieving enrollments from PowerSchool: {e}")
            raise PowerSchoolAPIError(f"Failed to retrieve enrollments: {e}")
            
    async def sync_student(self, student_data: Dict[str, Any]) -> bool:
        """
        Sync a single student to PowerSchool.
        
        Args:
            student_data: Student data to sync
            
        Returns:
            True if sync successful
        """
        if not await self._ensure_authenticated():
            raise PowerSchoolAPIError("Authentication failed")
            
        try:
            # Transform to PowerSchool format
            ps_student_data = self._transform_student_to_powerschool(student_data)
            
            # Check if student exists
            student_id = student_data.get('sis_student_id')
            if student_id:
                # Update existing student
                endpoint = f"/ws/{self.config.api_version}/district/student/{student_id}"
                await self._make_api_request('PATCH', endpoint, json=ps_student_data)
                logger.info(f"Updated student {student_id} in PowerSchool")
            else:
                # Create new student
                endpoint = f"/ws/{self.config.api_version}/district/student"
                response = await self._make_api_request('POST', endpoint, json=ps_student_data)
                logger.info(f"Created new student in PowerSchool: {response.get('id')}")
                
            return True
            
        except Exception as e:
            logger.error(f"Error syncing student to PowerSchool: {e}")
            return False
            
    async def health_check(self) -> bool:
        """Check PowerSchool API health."""
        try:
            if not await self._ensure_authenticated():
                return False
                
            # Test API with a simple request
            endpoint = f"/ws/{self.config.api_version}/district/school"
            await self._make_api_request('GET', endpoint, params={'pagesize': 1})
            
            logger.info(f"PowerSchool health check passed for {self.integration.provider_id}")
            return True
            
        except Exception as e:
            logger.error(f"PowerSchool health check failed for {self.integration.provider_id}: {e}")
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
        """Make authenticated API request to PowerSchool."""
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
                                raise PowerSchoolAPIError(
                                    f"API request failed: {retry_response.status} - {error_text}"
                                )
                            return await retry_response.json()
                    else:
                        raise AuthenticationFailedError("Failed to refresh authentication")
                        
                elif response.status >= 400:
                    error_text = await response.text()
                    raise PowerSchoolAPIError(
                        f"API request failed: {response.status} - {error_text}"
                    )
                    
                return await response.json()
                
        except aiohttp.ClientError as e:
            raise PowerSchoolAPIError(f"HTTP client error: {e}")
            
    def _transform_student_data(self, ps_student: Dict[str, Any]) -> Dict[str, Any]:
        """Transform PowerSchool student data to standard format."""
        return {
            'sis_student_id': str(ps_student.get('id', '')),
            'sis_student_number': ps_student.get('student_number', ''),
            'first_name': ps_student.get('first_name', ''),
            'last_name': ps_student.get('last_name', ''),
            'middle_name': ps_student.get('middle_name', ''),
            'email': ps_student.get('student_email', ''),
            'grade_level': ps_student.get('grade_level'),
            'school_id': ps_student.get('schoolid'),
            'state_id': ps_student.get('state_studentnumber', ''),
            'active': ps_student.get('enroll_status') == 0,  # 0 = active in PowerSchool
            'enrollment_date': ps_student.get('entrydate'),
            'graduation_year': ps_student.get('graduation_year'),
            'raw_data': ps_student  # Keep original data for debugging
        }
        
    def _transform_enrollment_data(self, ps_enrollment: Dict[str, Any]) -> Dict[str, Any]:
        """Transform PowerSchool enrollment data to standard format."""
        return {
            'student_id': str(ps_enrollment.get('studentid', '')),
            'section_id': str(ps_enrollment.get('sectionid', '')),
            'course_number': ps_enrollment.get('course_number', ''),
            'course_name': ps_enrollment.get('course_name', ''),
            'teacher_id': ps_enrollment.get('teacher_id', ''),
            'teacher_name': ps_enrollment.get('teacher_name', ''),
            'period': ps_enrollment.get('expression', ''),
            'room': ps_enrollment.get('room', ''),
            'term_id': ps_enrollment.get('termid'),
            'start_date': ps_enrollment.get('dateenrolled'),
            'end_date': ps_enrollment.get('dateleft'),
            'active': ps_enrollment.get('dateleft') is None,
            'raw_data': ps_enrollment
        }
        
    def _transform_student_to_powerschool(self, student_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform standard student data to PowerSchool format."""
        ps_data = {}
        
        # Map standard fields to PowerSchool fields
        field_mapping = {
            'first_name': 'first_name',
            'last_name': 'last_name',
            'middle_name': 'middle_name',
            'email': 'student_email',
            'grade_level': 'grade_level',
            'state_id': 'state_studentnumber',
        }
        
        for std_field, ps_field in field_mapping.items():
            if std_field in student_data and student_data[std_field]:
                ps_data[ps_field] = student_data[std_field]
                
        # Handle enrollment status
        if 'active' in student_data:
            ps_data['enroll_status'] = 0 if student_data['active'] else 3  # 0=active, 3=transferred
            
        return ps_data