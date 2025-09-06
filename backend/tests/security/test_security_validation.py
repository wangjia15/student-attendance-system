"""
Security validation tests for Student Attendance System.
Tests OWASP Top 10 vulnerabilities and FERPA compliance requirements.
"""

import pytest
import asyncio
import aiohttp
import json
import jwt
import base64
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class SecurityTester:
    """Security testing framework."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session: aiohttp.ClientSession = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_endpoint(
        self, 
        method: str, 
        endpoint: str, 
        headers: Dict[str, str] = None,
        data: Any = None,
        params: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """Test an endpoint and return response details."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            async with self.session.request(
                method, 
                url, 
                headers=headers or {},
                json=data,
                params=params
            ) as response:
                try:
                    response_data = await response.json()
                except:
                    response_data = await response.text()
                
                return {
                    'status_code': response.status,
                    'headers': dict(response.headers),
                    'data': response_data,
                    'success': True
                }
        
        except Exception as e:
            return {
                'status_code': 0,
                'headers': {},
                'data': str(e),
                'success': False,
                'error': str(e)
            }


class OWASPSecurityTests:
    """Test for OWASP Top 10 vulnerabilities."""
    
    def __init__(self, tester: SecurityTester):
        self.tester = tester
    
    async def test_sql_injection(self) -> Dict[str, Any]:
        """Test for SQL injection vulnerabilities."""
        results = {
            'test_name': 'SQL Injection',
            'vulnerabilities_found': [],
            'tests_passed': 0,
            'tests_failed': 0
        }
        
        # Common SQL injection payloads
        sql_payloads = [
            "' OR '1'='1",
            "'; DROP TABLE users; --",
            "' UNION SELECT * FROM users --",
            "1' AND (SELECT COUNT(*) FROM users) > 0 --",
            "admin'--",
            "' OR 1=1#",
        ]
        
        # Test endpoints that might be vulnerable
        test_endpoints = [
            ('/api/v1/auth/login', 'POST', {'username': '', 'password': ''}),
            ('/api/v1/users/search', 'GET', None),
            ('/api/v1/students/search', 'GET', None),
        ]
        
        for endpoint, method, base_data in test_endpoints:
            for payload in sql_payloads:
                try:
                    # Test in different parameters
                    test_cases = []
                    
                    if method == 'GET':
                        test_cases.append(({}, {'q': payload}))
                        test_cases.append(({}, {'search': payload}))
                    elif method == 'POST' and base_data:
                        for field in base_data.keys():
                            data_with_payload = base_data.copy()
                            data_with_payload[field] = payload
                            test_cases.append((data_with_payload, {}))
                    
                    for data, params in test_cases:
                        response = await self.tester.test_endpoint(
                            method, endpoint, data=data, params=params
                        )
                        
                        # Check for indicators of successful injection
                        if response['success']:
                            response_text = str(response['data']).lower()
                            
                            # Look for database error messages
                            error_indicators = [
                                'sql syntax error',
                                'mysql error',
                                'postgresql error',
                                'sqlite error',
                                'ora-00',  # Oracle errors
                                'sqlstate',
                                'syntax error at or near',
                                'quoted string not properly terminated'
                            ]
                            
                            for indicator in error_indicators:
                                if indicator in response_text:
                                    results['vulnerabilities_found'].append({
                                        'endpoint': endpoint,
                                        'method': method,
                                        'payload': payload,
                                        'vulnerability': 'SQL Injection',
                                        'evidence': indicator,
                                        'response_code': response['status_code']
                                    })
                                    results['tests_failed'] += 1
                                    break
                            else:
                                results['tests_passed'] += 1
                        else:
                            results['tests_passed'] += 1
                
                except Exception as e:
                    logger.error(f"SQL injection test error: {e}")
        
        return results
    
    async def test_xss_vulnerabilities(self) -> Dict[str, Any]:
        """Test for Cross-Site Scripting vulnerabilities."""
        results = {
            'test_name': 'Cross-Site Scripting (XSS)',
            'vulnerabilities_found': [],
            'tests_passed': 0,
            'tests_failed': 0
        }
        
        # XSS payloads
        xss_payloads = [
            '<script>alert("XSS")</script>',
            '"><script>alert("XSS")</script>',
            "javascript:alert('XSS')",
            '<img src=x onerror=alert("XSS")>',
            '<svg onload=alert("XSS")>',
            '{{7*7}}',  # Template injection
            '${7*7}',   # Expression injection
        ]
        
        # Test endpoints
        test_endpoints = [
            ('/api/v1/classes/', 'POST', {'class_name': '', 'location': ''}),
            ('/api/v1/students/', 'POST', {'first_name': '', 'last_name': ''}),
        ]
        
        for endpoint, method, base_data in test_endpoints:
            for payload in xss_payloads:
                try:
                    # Test payload in different fields
                    for field in base_data.keys():
                        data_with_payload = base_data.copy()
                        data_with_payload[field] = payload
                        
                        response = await self.tester.test_endpoint(
                            method, endpoint, data=data_with_payload
                        )
                        
                        if response['success']:
                            response_text = str(response['data'])
                            
                            # Check if payload is reflected without sanitization
                            if payload in response_text and '<script>' in response_text:
                                results['vulnerabilities_found'].append({
                                    'endpoint': endpoint,
                                    'field': field,
                                    'payload': payload,
                                    'vulnerability': 'Reflected XSS',
                                    'evidence': 'Payload reflected in response'
                                })
                                results['tests_failed'] += 1
                            else:
                                results['tests_passed'] += 1
                        else:
                            results['tests_passed'] += 1
                
                except Exception as e:
                    logger.error(f"XSS test error: {e}")
        
        return results
    
    async def test_authentication_bypass(self) -> Dict[str, Any]:
        """Test for authentication bypass vulnerabilities."""
        results = {
            'test_name': 'Authentication Bypass',
            'vulnerabilities_found': [],
            'tests_passed': 0,
            'tests_failed': 0
        }
        
        # Protected endpoints that should require authentication
        protected_endpoints = [
            '/api/v1/classes/',
            '/api/v1/attendance/checkin',
            '/api/v1/students/',
            '/api/v1/users/profile',
        ]
        
        for endpoint in protected_endpoints:
            try:
                # Test without authentication
                response = await self.tester.test_endpoint('GET', endpoint)
                
                if response['status_code'] == 200:
                    results['vulnerabilities_found'].append({
                        'endpoint': endpoint,
                        'vulnerability': 'Authentication Bypass',
                        'evidence': 'Endpoint accessible without authentication',
                        'response_code': response['status_code']
                    })
                    results['tests_failed'] += 1
                else:
                    results['tests_passed'] += 1
                
                # Test with invalid token
                invalid_headers = {'Authorization': 'Bearer invalid_token_here'}
                response = await self.tester.test_endpoint('GET', endpoint, headers=invalid_headers)
                
                if response['status_code'] == 200:
                    results['vulnerabilities_found'].append({
                        'endpoint': endpoint,
                        'vulnerability': 'Invalid Token Acceptance',
                        'evidence': 'Endpoint accessible with invalid token',
                        'response_code': response['status_code']
                    })
                    results['tests_failed'] += 1
                else:
                    results['tests_passed'] += 1
            
            except Exception as e:
                logger.error(f"Authentication test error: {e}")
        
        return results
    
    async def test_sensitive_data_exposure(self) -> Dict[str, Any]:
        """Test for sensitive data exposure."""
        results = {
            'test_name': 'Sensitive Data Exposure',
            'vulnerabilities_found': [],
            'tests_passed': 0,
            'tests_failed': 0
        }
        
        # Test endpoints that might expose sensitive data
        test_endpoints = [
            '/api/v1/users/',
            '/api/v1/students/',
            '/api/v1/classes/',
        ]
        
        sensitive_fields = [
            'password',
            'password_hash',
            'api_key',
            'secret',
            'token',
            'ssn',
            'social_security_number',
        ]
        
        for endpoint in test_endpoints:
            try:
                response = await self.tester.test_endpoint('GET', endpoint)
                
                if response['success'] and response['data']:
                    response_text = str(response['data']).lower()
                    
                    for field in sensitive_fields:
                        if field in response_text:
                            results['vulnerabilities_found'].append({
                                'endpoint': endpoint,
                                'vulnerability': 'Sensitive Data Exposure',
                                'sensitive_field': field,
                                'evidence': f'Response contains {field} field'
                            })
                            results['tests_failed'] += 1
                            break
                    else:
                        results['tests_passed'] += 1
            
            except Exception as e:
                logger.error(f"Sensitive data test error: {e}")
        
        return results
    
    async def test_rate_limiting(self) -> Dict[str, Any]:
        """Test rate limiting implementation."""
        results = {
            'test_name': 'Rate Limiting',
            'vulnerabilities_found': [],
            'tests_passed': 0,
            'tests_failed': 0
        }
        
        # Test login endpoint for rate limiting
        login_endpoint = '/api/v1/auth/login'
        
        try:
            # Send many requests quickly
            tasks = []
            for i in range(20):  # 20 rapid requests
                task = asyncio.create_task(
                    self.tester.test_endpoint(
                        'POST', 
                        login_endpoint,
                        data={'username': f'test{i}', 'password': 'wrongpassword'}
                    )
                )
                tasks.append(task)
            
            responses = await asyncio.gather(*tasks)
            
            # Check if any requests were rate limited
            rate_limited_count = sum(1 for r in responses if r['status_code'] == 429)
            
            if rate_limited_count == 0:
                results['vulnerabilities_found'].append({
                    'endpoint': login_endpoint,
                    'vulnerability': 'No Rate Limiting',
                    'evidence': f'All {len(responses)} rapid requests were accepted'
                })
                results['tests_failed'] += 1
            else:
                results['tests_passed'] += 1
        
        except Exception as e:
            logger.error(f"Rate limiting test error: {e}")
        
        return results


class FERPAComplianceTests:
    """Test FERPA compliance requirements."""
    
    def __init__(self, tester: SecurityTester):
        self.tester = tester
    
    async def test_student_data_access_controls(self) -> Dict[str, Any]:
        """Test access controls for student educational records."""
        results = {
            'test_name': 'FERPA Access Controls',
            'violations_found': [],
            'tests_passed': 0,
            'tests_failed': 0
        }
        
        # Test student data endpoints
        student_endpoints = [
            '/api/v1/students/',
            '/api/v1/attendance/student/',
            '/api/v1/grades/student/',
        ]
        
        for endpoint in student_endpoints:
            try:
                # Test without proper authorization
                response = await self.tester.test_endpoint('GET', endpoint)
                
                # Should not return student data without proper authorization
                if response['success'] and response['status_code'] == 200:
                    results['violations_found'].append({
                        'endpoint': endpoint,
                        'violation': 'Unauthorized student data access',
                        'evidence': 'Student data accessible without proper authorization'
                    })
                    results['tests_failed'] += 1
                else:
                    results['tests_passed'] += 1
            
            except Exception as e:
                logger.error(f"FERPA access control test error: {e}")
        
        return results
    
    async def test_audit_logging_requirements(self) -> Dict[str, Any]:
        """Test audit logging for student data access."""
        results = {
            'test_name': 'FERPA Audit Logging',
            'violations_found': [],
            'tests_passed': 0,
            'tests_failed': 0
        }
        
        # Check if audit endpoints exist and require authentication
        audit_endpoints = [
            '/api/v1/audit/student-access',
            '/api/v1/compliance/audit-logs',
        ]
        
        for endpoint in audit_endpoints:
            try:
                response = await self.tester.test_endpoint('GET', endpoint)
                
                # Audit endpoints should exist and be protected
                if response['status_code'] == 404:
                    results['violations_found'].append({
                        'endpoint': endpoint,
                        'violation': 'Missing audit logging endpoint',
                        'evidence': 'Audit endpoint not found'
                    })
                    results['tests_failed'] += 1
                elif response['status_code'] == 401 or response['status_code'] == 403:
                    results['tests_passed'] += 1
                else:
                    results['violations_found'].append({
                        'endpoint': endpoint,
                        'violation': 'Unprotected audit endpoint',
                        'evidence': 'Audit endpoint not properly protected'
                    })
                    results['tests_failed'] += 1
            
            except Exception as e:
                logger.error(f"FERPA audit test error: {e}")
        
        return results
    
    async def test_data_anonymization(self) -> Dict[str, Any]:
        """Test data anonymization capabilities."""
        results = {
            'test_name': 'FERPA Data Anonymization',
            'violations_found': [],
            'tests_passed': 0,
            'tests_failed': 0
        }
        
        # Test anonymization endpoints
        anonymization_endpoints = [
            '/api/v1/compliance/anonymize',
            '/api/v1/reports/anonymous',
        ]
        
        for endpoint in anonymization_endpoints:
            try:
                response = await self.tester.test_endpoint('POST', endpoint)
                
                if response['status_code'] == 404:
                    results['violations_found'].append({
                        'endpoint': endpoint,
                        'violation': 'Missing anonymization capability',
                        'evidence': 'Anonymization endpoint not found'
                    })
                    results['tests_failed'] += 1
                else:
                    results['tests_passed'] += 1
            
            except Exception as e:
                logger.error(f"FERPA anonymization test error: {e}")
        
        return results


# Pytest test functions

@pytest.mark.asyncio
@pytest.mark.security
async def test_owasp_top_10():
    """Test for OWASP Top 10 vulnerabilities."""
    async with SecurityTester() as tester:
        owasp_tests = OWASPSecurityTests(tester)
        
        # Run security tests
        sql_results = await owasp_tests.test_sql_injection()
        xss_results = await owasp_tests.test_xss_vulnerabilities()
        auth_results = await owasp_tests.test_authentication_bypass()
        data_results = await owasp_tests.test_sensitive_data_exposure()
        rate_results = await owasp_tests.test_rate_limiting()
        
        # Collect all results
        all_results = [sql_results, xss_results, auth_results, data_results, rate_results]
        
        # Report results
        total_vulnerabilities = sum(len(r['vulnerabilities_found']) for r in all_results)
        
        for result in all_results:
            logger.info(f"{result['test_name']}: {result['tests_passed']} passed, {result['tests_failed']} failed")
            for vuln in result['vulnerabilities_found']:
                logger.error(f"🚨 {vuln['vulnerability']}: {vuln['endpoint']} - {vuln['evidence']}")
        
        # Assert no critical vulnerabilities
        assert total_vulnerabilities == 0, f"Found {total_vulnerabilities} security vulnerabilities"


@pytest.mark.asyncio
@pytest.mark.security
async def test_ferpa_compliance():
    """Test FERPA compliance requirements."""
    async with SecurityTester() as tester:
        ferpa_tests = FERPAComplianceTests(tester)
        
        # Run FERPA tests
        access_results = await ferpa_tests.test_student_data_access_controls()
        audit_results = await ferpa_tests.test_audit_logging_requirements()
        anonym_results = await ferpa_tests.test_data_anonymization()
        
        # Collect all results
        all_results = [access_results, audit_results, anonym_results]
        
        # Report results
        total_violations = sum(len(r['violations_found']) for r in all_results)
        
        for result in all_results:
            logger.info(f"{result['test_name']}: {result['tests_passed']} passed, {result['tests_failed']} failed")
            for violation in result['violations_found']:
                logger.error(f"⚖️ FERPA Violation: {violation['violation']} - {violation['evidence']}")
        
        # Assert FERPA compliance
        assert total_violations == 0, f"Found {total_violations} FERPA compliance violations"


@pytest.mark.asyncio
@pytest.mark.security
async def test_security_headers():
    """Test security headers implementation."""
    async with SecurityTester() as tester:
        response = await tester.test_endpoint('GET', '/')
        
        required_headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': ['DENY', 'SAMEORIGIN'],
            'X-XSS-Protection': '1; mode=block',
            'Strict-Transport-Security': 'max-age=',
            'Content-Security-Policy': 'default-src'
        }
        
        missing_headers = []
        
        for header, expected in required_headers.items():
            if header not in response['headers']:
                missing_headers.append(header)
            else:
                header_value = response['headers'][header]
                if isinstance(expected, list):
                    if not any(exp in header_value for exp in expected):
                        missing_headers.append(f"{header} (invalid value)")
                elif isinstance(expected, str) and expected not in header_value:
                    missing_headers.append(f"{header} (invalid value)")
        
        assert not missing_headers, f"Missing security headers: {missing_headers}"


if __name__ == "__main__":
    # Run security tests directly
    import sys
    
    async def run_security_tests():
        """Run all security tests."""
        print("Starting Student Attendance System Security Tests")
        print("=" * 60)
        
        try:
            await test_owasp_top_10()
            print("✅ OWASP Top 10 Security Tests: PASSED")
            
            await test_ferpa_compliance()
            print("✅ FERPA Compliance Tests: PASSED")
            
            await test_security_headers()
            print("✅ Security Headers Tests: PASSED")
            
            print("\n🔒 All security tests passed!")
            
        except AssertionError as e:
            print(f"❌ Security test failed: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"💥 Unexpected error: {e}")
            sys.exit(1)
    
    # Run the tests
    asyncio.run(run_security_tests())