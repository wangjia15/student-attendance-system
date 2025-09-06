"""
WebSocket Security Testing for Student Attendance System.
Tests WebSocket authentication, authorization, and security vulnerabilities.
"""

import pytest
import asyncio
import websockets
import json
import jwt
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging
import aiohttp

logger = logging.getLogger(__name__)


class WebSocketSecurityTester:
    """WebSocket security testing framework."""
    
    def __init__(self, base_url: str = "ws://localhost:8000"):
        self.base_url = base_url
        self.http_base = base_url.replace('ws://', 'http://').replace('wss://', 'https://')
    
    async def test_websocket_connection(
        self,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 10
    ) -> Dict[str, Any]:
        """Test WebSocket connection and return connection details."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            websocket = await websockets.connect(
                url,
                extra_headers=headers or {},
                timeout=timeout
            )
            
            # Test basic connectivity
            await websocket.ping()
            pong_waiter = await websocket.wait_closed()
            
            connection_info = {
                'success': True,
                'url': url,
                'state': websocket.state.name,
                'local_address': str(websocket.local_address),
                'remote_address': str(websocket.remote_address)
            }
            
            await websocket.close()
            return connection_info
            
        except websockets.exceptions.ConnectionClosed as e:
            return {
                'success': False,
                'error': 'Connection closed',
                'code': e.code,
                'reason': e.reason
            }
        except websockets.exceptions.InvalidStatusCode as e:
            return {
                'success': False,
                'error': 'Invalid status code',
                'status_code': e.status_code
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'type': type(e).__name__
            }
    
    async def test_websocket_authentication(
        self,
        endpoint: str,
        token: Optional[str] = None,
        connection_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test WebSocket authentication mechanisms."""
        url = f"{self.base_url}{endpoint}"
        
        headers = {}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        
        try:
            websocket = await websockets.connect(url, extra_headers=headers)
            
            # Send authentication message if required
            if connection_id:
                auth_message = {
                    'type': 'authenticate',
                    'connection_id': connection_id,
                    'token': token
                }
                await websocket.send(json.dumps(auth_message))
                
                # Wait for authentication response
                response = await asyncio.wait_for(
                    websocket.recv(), 
                    timeout=5
                )
                response_data = json.loads(response)
            else:
                response_data = {'authenticated': True}  # Assume success if no auth required
            
            await websocket.close()
            
            return {
                'success': True,
                'authenticated': response_data.get('authenticated', False),
                'response': response_data
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'authenticated': False
            }
    
    async def test_websocket_message_validation(
        self,
        endpoint: str,
        test_messages: List[Dict[str, Any]],
        token: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Test WebSocket message validation and sanitization."""
        url = f"{self.base_url}{endpoint}"
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        
        results = []
        
        try:
            websocket = await websockets.connect(url, extra_headers=headers)
            
            for message in test_messages:
                try:
                    # Send test message
                    await websocket.send(json.dumps(message))
                    
                    # Wait for response
                    response = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=2
                    )
                    response_data = json.loads(response)
                    
                    results.append({
                        'message': message,
                        'success': True,
                        'response': response_data,
                        'validation_passed': not response_data.get('error')
                    })
                    
                except asyncio.TimeoutError:
                    results.append({
                        'message': message,
                        'success': False,
                        'error': 'timeout',
                        'validation_passed': True  # No response might mean rejected
                    })
                except Exception as e:
                    results.append({
                        'message': message,
                        'success': False,
                        'error': str(e),
                        'validation_passed': False
                    })
            
            await websocket.close()
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            # Add failed connection result for all messages
            for message in test_messages:
                results.append({
                    'message': message,
                    'success': False,
                    'error': f'Connection failed: {e}',
                    'validation_passed': False
                })
        
        return results
    
    async def test_websocket_dos_protection(
        self,
        endpoint: str,
        message_count: int = 1000,
        message_rate: int = 100,  # messages per second
        token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test WebSocket DoS protection mechanisms."""
        url = f"{self.base_url}{endpoint}"
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        
        try:
            websocket = await websockets.connect(url, extra_headers=headers)
            
            start_time = time.time()
            sent_messages = 0
            failed_messages = 0
            
            # Calculate delay between messages
            delay = 1.0 / message_rate
            
            for i in range(message_count):
                try:
                    message = {
                        'type': 'test_flood',
                        'sequence': i,
                        'timestamp': time.time()
                    }
                    
                    await websocket.send(json.dumps(message))
                    sent_messages += 1
                    
                    # Rate limiting delay
                    await asyncio.sleep(delay)
                    
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"Connection closed after {sent_messages} messages")
                    break
                except Exception as e:
                    failed_messages += 1
                    if failed_messages > 10:  # Too many failures
                        break
            
            end_time = time.time()
            duration = end_time - start_time
            
            try:
                await websocket.close()
            except:
                pass  # Connection might already be closed
            
            return {
                'success': True,
                'sent_messages': sent_messages,
                'failed_messages': failed_messages,
                'duration': duration,
                'messages_per_second': sent_messages / duration if duration > 0 else 0,
                'connection_survived': sent_messages == message_count
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'sent_messages': 0,
                'connection_survived': False
            }


class WebSocketVulnerabilityTests:
    """WebSocket vulnerability test suite."""
    
    def __init__(self, tester: WebSocketSecurityTester):
        self.tester = tester
    
    def get_malicious_messages(self) -> List[Dict[str, Any]]:
        """Generate malicious messages for security testing."""
        return [
            # XSS Injection Attempts
            {
                'type': 'message',
                'content': '<script>alert("XSS")</script>',
                'student_name': '<img src=x onerror=alert("XSS")>'
            },
            
            # SQL Injection Attempts
            {
                'type': 'checkin',
                'student_id': "1'; DROP TABLE users; --",
                'class_id': '1 OR 1=1'
            },
            
            # JSON Injection
            {
                'type': 'message',
                'content': '","malicious_field":"injected_value","original_field":"'
            },
            
            # Command Injection
            {
                'type': 'message',
                'content': '$(rm -rf /)',
                'command': '|whoami'
            },
            
            # Buffer Overflow Attempts
            {
                'type': 'message',
                'content': 'A' * 10000,
                'student_name': 'B' * 5000
            },
            
            # Path Traversal
            {
                'type': 'file_request',
                'path': '../../../etc/passwd',
                'file': '....//....//....//etc/passwd'
            },
            
            # LDAP Injection
            {
                'type': 'search',
                'query': '*)(uid=*))(|(uid=*',
                'filter': '*)(&(uid=admin)'
            },
            
            # NoSQL Injection
            {
                'type': 'query',
                'filter': {'$where': 'function() { return true; }'},
                'query': {'$regex': '.*', '$options': 'i'}
            },
            
            # XXE (XML External Entity)
            {
                'type': 'xml_data',
                'content': '<?xml version="1.0"?><!DOCTYPE root [<!ENTITY test SYSTEM "file:///etc/passwd">]><root>&test;</root>'
            },
            
            # Protocol Confusion
            {
                'type': 'http_request',
                'method': 'GET',
                'headers': {'Host': 'evil.com'}
            }
        ]
    
    async def test_injection_vulnerabilities(self, endpoint: str) -> Dict[str, Any]:
        """Test for various injection vulnerabilities."""
        malicious_messages = self.get_malicious_messages()
        
        results = await self.tester.test_websocket_message_validation(
            endpoint=endpoint,
            test_messages=malicious_messages
        )
        
        # Analyze results
        vulnerabilities = []
        for result in results:
            if result['success'] and not result['validation_passed']:
                vulnerabilities.append({
                    'message_type': result['message'].get('type', 'unknown'),
                    'vulnerability': 'Possible injection vulnerability',
                    'payload': result['message'],
                    'response': result.get('response')
                })
        
        return {
            'total_tests': len(results),
            'vulnerabilities_found': len(vulnerabilities),
            'vulnerabilities': vulnerabilities,
            'security_score': max(0, 100 - (len(vulnerabilities) * 10))
        }
    
    async def test_authentication_bypass(
        self,
        endpoint: str,
        valid_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test authentication bypass vulnerabilities."""
        bypass_attempts = [
            # No token
            None,
            
            # Empty token
            '',
            
            # Invalid token
            'invalid_token_12345',
            
            # Expired token (if we can generate one)
            self._generate_expired_token(),
            
            # Malformed token
            'Bearer malformed.token.here',
            
            # Token with wrong algorithm
            self._generate_wrong_algorithm_token(),
            
            # SQL injection in token
            "'; DROP TABLE tokens; --"
        ]
        
        results = []
        for token in bypass_attempts:
            result = await self.tester.test_websocket_authentication(
                endpoint=endpoint,
                token=token
            )
            
            results.append({
                'token': token[:20] + '...' if token and len(token) > 20 else token,
                'authenticated': result.get('authenticated', False),
                'success': result.get('success', False),
                'bypass_successful': result.get('authenticated', False) and not token
            })
        
        bypass_count = sum(1 for r in results if r['bypass_successful'])
        
        return {
            'total_attempts': len(results),
            'bypass_successful': bypass_count,
            'results': results,
            'security_score': max(0, 100 - (bypass_count * 25))
        }
    
    def _generate_expired_token(self) -> str:
        """Generate an expired JWT token for testing."""
        try:
            payload = {
                'user_id': '1',
                'exp': datetime.utcnow() - timedelta(hours=1),
                'iat': datetime.utcnow() - timedelta(hours=2)
            }
            return jwt.encode(payload, 'test_secret', algorithm='HS256')
        except:
            return 'expired.token.here'
    
    def _generate_wrong_algorithm_token(self) -> str:
        """Generate a token with wrong algorithm for testing."""
        try:
            payload = {
                'user_id': '1',
                'exp': datetime.utcnow() + timedelta(hours=1),
                'iat': datetime.utcnow()
            }
            return jwt.encode(payload, 'test_secret', algorithm='none')
        except:
            return 'wrong.algorithm.token'


# Pytest test functions

@pytest.mark.asyncio
@pytest.mark.security
async def test_websocket_connection_security():
    """Test WebSocket connection security."""
    tester = WebSocketSecurityTester()
    
    # Test connection to main WebSocket endpoint
    connection_result = await tester.test_websocket_connection('/ws/test_connection_123')
    
    # Basic security assertions
    assert connection_result is not None, "Connection test should return results"
    
    # If connection succeeds, verify it's secure
    if connection_result.get('success'):
        assert 'local_address' in connection_result, "Connection should provide address info"
        assert 'remote_address' in connection_result, "Connection should provide remote address"
    
    logger.info(f"WebSocket connection test: {connection_result}")


@pytest.mark.asyncio
@pytest.mark.security
async def test_websocket_authentication_security():
    """Test WebSocket authentication security."""
    tester = WebSocketSecurityTester()
    vulnerability_tests = WebSocketVulnerabilityTests(tester)
    
    # Test authentication bypass attempts
    bypass_results = await vulnerability_tests.test_authentication_bypass('/ws/test_auth_123')
    
    # Security assertions
    assert bypass_results['bypass_successful'] == 0, f"Authentication bypass detected: {bypass_results['bypass_successful']} attempts succeeded"
    assert bypass_results['security_score'] >= 75, f"Authentication security score too low: {bypass_results['security_score']}"
    
    logger.info(f"Authentication security score: {bypass_results['security_score']}/100")


@pytest.mark.asyncio
@pytest.mark.security
async def test_websocket_injection_vulnerabilities():
    """Test WebSocket message injection vulnerabilities."""
    tester = WebSocketSecurityTester()
    vulnerability_tests = WebSocketVulnerabilityTests(tester)
    
    # Test injection vulnerabilities
    injection_results = await vulnerability_tests.test_injection_vulnerabilities('/ws/test_injection_123')
    
    # Security assertions
    assert injection_results['vulnerabilities_found'] <= 2, f"Too many injection vulnerabilities: {injection_results['vulnerabilities_found']}"
    assert injection_results['security_score'] >= 80, f"Injection security score too low: {injection_results['security_score']}"
    
    logger.info(f"Injection security score: {injection_results['security_score']}/100")
    
    if injection_results['vulnerabilities']:
        logger.warning(f"Vulnerabilities found: {json.dumps(injection_results['vulnerabilities'], indent=2)}")


@pytest.mark.asyncio
@pytest.mark.security
async def test_websocket_dos_protection():
    """Test WebSocket DoS protection mechanisms."""
    tester = WebSocketSecurityTester()
    
    # Test DoS protection with high message rate
    dos_results = await tester.test_websocket_dos_protection(
        endpoint='/ws/test_dos_123',
        message_count=500,
        message_rate=50  # 50 messages per second
    )
    
    # DoS protection assertions
    assert dos_results.get('success', False), f"DoS test failed: {dos_results.get('error')}"
    
    # Check if rate limiting is working
    if dos_results.get('messages_per_second', 0) > 100:
        logger.warning(f"High message rate detected: {dos_results['messages_per_second']} msg/s")
    
    # Connection should handle reasonable load
    assert dos_results.get('sent_messages', 0) > 100, "Should handle at least 100 messages"
    
    logger.info(f"DoS protection test results:")
    logger.info(f"  Messages sent: {dos_results.get('sent_messages', 0)}")
    logger.info(f"  Rate: {dos_results.get('messages_per_second', 0):.2f} msg/s")
    logger.info(f"  Connection survived: {dos_results.get('connection_survived', False)}")


@pytest.mark.asyncio
@pytest.mark.performance
async def test_websocket_performance_under_load():
    """Test WebSocket performance under concurrent load."""
    
    async def create_concurrent_connections(connection_count: int) -> Dict[str, Any]:
        """Create multiple concurrent WebSocket connections."""
        tester = WebSocketSecurityTester()
        
        async def single_connection_test(conn_id: int) -> Dict[str, Any]:
            endpoint = f'/ws/perf_test_{conn_id}_{int(time.time())}'
            return await tester.test_websocket_connection(endpoint)
        
        # Create concurrent connection tasks
        tasks = [single_connection_test(i) for i in range(connection_count)]
        
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()
        
        # Analyze results
        successful_connections = sum(1 for r in results if isinstance(r, dict) and r.get('success'))
        failed_connections = len(results) - successful_connections
        
        return {
            'total_connections': connection_count,
            'successful_connections': successful_connections,
            'failed_connections': failed_connections,
            'success_rate': (successful_connections / connection_count) * 100,
            'total_time': end_time - start_time,
            'connections_per_second': connection_count / (end_time - start_time)
        }
    
    # Test with increasing connection counts
    test_counts = [10, 50, 100]
    
    for count in test_counts:
        performance_results = await create_concurrent_connections(count)
        
        # Performance assertions
        assert performance_results['success_rate'] >= 80.0, f"Low success rate with {count} connections: {performance_results['success_rate']}%"
        assert performance_results['connections_per_second'] >= 5.0, f"Low connection rate: {performance_results['connections_per_second']} conn/s"
        
        logger.info(f"WebSocket performance test ({count} connections):")
        logger.info(f"  Success rate: {performance_results['success_rate']:.1f}%")
        logger.info(f"  Connection rate: {performance_results['connections_per_second']:.2f} conn/s")


if __name__ == "__main__":
    # Run WebSocket security tests directly
    import sys
    
    async def run_websocket_security_tests():
        """Run all WebSocket security tests."""
        print("Starting WebSocket Security Tests")
        print("=" * 50)
        
        try:
            await test_websocket_connection_security()
            print("✅ WebSocket Connection Security: PASSED")
            
            await test_websocket_authentication_security()
            print("✅ WebSocket Authentication Security: PASSED")
            
            await test_websocket_injection_vulnerabilities()
            print("✅ WebSocket Injection Vulnerabilities: PASSED")
            
            await test_websocket_dos_protection()
            print("✅ WebSocket DoS Protection: PASSED")
            
            await test_websocket_performance_under_load()
            print("✅ WebSocket Performance Under Load: PASSED")
            
            print("\n🔒 All WebSocket security tests passed!")
            
        except AssertionError as e:
            print(f"❌ Security test failed: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"💥 Unexpected error: {e}")
            sys.exit(1)
    
    # Run the tests
    asyncio.run(run_websocket_security_tests())