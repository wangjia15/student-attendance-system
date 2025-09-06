"""
Performance and load testing suite for Student Attendance System.
Tests system capacity with 1000+ concurrent users.
"""

import asyncio
import pytest
import time
import aiohttp
import json
from typing import List, Dict, Any
from datetime import datetime
import statistics
import logging

logger = logging.getLogger(__name__)


class LoadTestResults:
    """Container for load test results."""
    
    def __init__(self):
        self.response_times: List[float] = []
        self.success_count = 0
        self.error_count = 0
        self.errors: List[Dict[str, Any]] = []
        self.start_time = 0.0
        self.end_time = 0.0
    
    @property
    def total_requests(self) -> int:
        return self.success_count + self.error_count
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return (self.success_count / self.total_requests) * 100
    
    @property
    def average_response_time(self) -> float:
        if not self.response_times:
            return 0.0
        return statistics.mean(self.response_times)
    
    @property
    def median_response_time(self) -> float:
        if not self.response_times:
            return 0.0
        return statistics.median(self.response_times)
    
    @property
    def p95_response_time(self) -> float:
        if not self.response_times:
            return 0.0
        return statistics.quantiles(self.response_times, n=20)[18]  # 95th percentile
    
    @property
    def total_duration(self) -> float:
        return self.end_time - self.start_time
    
    @property
    def requests_per_second(self) -> float:
        if self.total_duration == 0:
            return 0.0
        return self.total_requests / self.total_duration


class PerformanceTester:
    """Performance testing framework."""
    
    def __init__(self, base_url: str = "http://localhost:8000", auth_token: str = None):
        self.base_url = base_url
        self.auth_token = auth_token
        self.session: aiohttp.ClientSession = None
    
    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {}
        if self.auth_token:
            headers['Authorization'] = f'Bearer {self.auth_token}'
        
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers=headers
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def single_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Make a single HTTP request and measure response time."""
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            async with self.session.request(method, url, json=data) as response:
                end_time = time.time()
                response_time = end_time - start_time
                
                response_data = await response.json()
                
                return {
                    'success': response.status < 400,
                    'status_code': response.status,
                    'response_time': response_time,
                    'data': response_data,
                    'error': None
                }
        
        except Exception as e:
            end_time = time.time()
            response_time = end_time - start_time
            
            return {
                'success': False,
                'status_code': 0,
                'response_time': response_time,
                'data': None,
                'error': str(e)
            }
    
    async def concurrent_requests(
        self,
        method: str,
        endpoint: str,
        concurrent_users: int,
        requests_per_user: int,
        data_generator=None
    ) -> LoadTestResults:
        """
        Execute concurrent requests to simulate load.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            concurrent_users: Number of concurrent users
            requests_per_user: Requests per user
            data_generator: Function to generate request data
        
        Returns:
            LoadTestResults with performance metrics
        """
        results = LoadTestResults()
        results.start_time = time.time()
        
        logger.info(f"Starting load test: {concurrent_users} users, {requests_per_user} req/user")
        
        # Create tasks for concurrent execution
        tasks = []
        for user_id in range(concurrent_users):
            for request_id in range(requests_per_user):
                # Generate data if generator provided
                request_data = None
                if data_generator:
                    request_data = data_generator(user_id, request_id)
                
                task = asyncio.create_task(
                    self.single_request(method, endpoint, request_data)
                )
                tasks.append(task)
        
        # Execute all requests concurrently
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        results.end_time = time.time()
        
        # Process results
        for response in responses:
            if isinstance(response, Exception):
                results.error_count += 1
                results.errors.append({
                    'error': str(response),
                    'timestamp': datetime.now().isoformat()
                })
            else:
                results.response_times.append(response['response_time'])
                
                if response['success']:
                    results.success_count += 1
                else:
                    results.error_count += 1
                    results.errors.append({
                        'status_code': response['status_code'],
                        'error': response.get('error'),
                        'timestamp': datetime.now().isoformat()
                    })
        
        logger.info(f"Load test completed: {results.success_rate:.2f}% success rate")
        return results


class AttendanceSystemLoadTests:
    """Load tests specific to the attendance system."""
    
    def __init__(self, tester: PerformanceTester):
        self.tester = tester
    
    def generate_class_creation_data(self, user_id: int, request_id: int) -> Dict[str, Any]:
        """Generate data for class creation requests."""
        return {
            'class_name': f'Test Class U{user_id}R{request_id}',
            'date': datetime.now().isoformat(),
            'duration_minutes': 50,
            'location': f'Room {user_id % 100 + 1}',
            'allow_late_checkin': True,
            'require_verification': True
        }
    
    def generate_student_checkin_data(self, user_id: int, request_id: int) -> Dict[str, Any]:
        """Generate data for student check-in requests."""
        return {
            'student_id': user_id % 1000 + 1,  # Simulate 1000 students
            'verification_code': f'{user_id:04d}{request_id:02d}',
            'location': f'Building {user_id % 10 + 1}',
            'method': 'verification_code'
        }
    
    async def test_class_creation_load(
        self, 
        concurrent_teachers: int = 100,
        classes_per_teacher: int = 5
    ) -> LoadTestResults:
        """Test class creation under load."""
        return await self.tester.concurrent_requests(
            method='POST',
            endpoint='/api/v1/classes/',
            concurrent_users=concurrent_teachers,
            requests_per_user=classes_per_teacher,
            data_generator=self.generate_class_creation_data
        )
    
    async def test_student_checkin_load(
        self,
        concurrent_students: int = 1000,
        checkins_per_student: int = 1
    ) -> LoadTestResults:
        """Test student check-in under load."""
        return await self.tester.concurrent_requests(
            method='POST',
            endpoint='/api/v1/attendance/checkin',
            concurrent_users=concurrent_students,
            requests_per_user=checkins_per_student,
            data_generator=self.generate_student_checkin_data
        )
    
    async def test_websocket_connections(self, concurrent_connections: int = 500):
        """Test WebSocket connection capacity."""
        # This would test WebSocket connections concurrently
        # Implementation depends on WebSocket client library
        pass
    
    async def test_database_query_performance(self, concurrent_queries: int = 200):
        """Test database query performance under load."""
        return await self.tester.concurrent_requests(
            method='GET',
            endpoint='/api/v1/attendance/stats',
            concurrent_users=concurrent_queries,
            requests_per_user=5
        )


# Pytest test functions

@pytest.mark.asyncio
@pytest.mark.performance
async def test_api_performance_targets():
    """Test that API meets performance targets."""
    async with PerformanceTester() as tester:
        attendance_tests = AttendanceSystemLoadTests(tester)
        
        # Test class creation performance
        class_results = await attendance_tests.test_class_creation_load(
            concurrent_teachers=50,
            classes_per_teacher=2
        )
        
        # Performance assertions
        assert class_results.success_rate >= 95.0, f"Success rate too low: {class_results.success_rate}%"
        assert class_results.average_response_time <= 2.0, f"Average response time too high: {class_results.average_response_time}s"
        assert class_results.p95_response_time <= 5.0, f"95th percentile too high: {class_results.p95_response_time}s"
        
        logger.info(f"Class creation test results:")
        logger.info(f"  Success rate: {class_results.success_rate:.2f}%")
        logger.info(f"  Average response time: {class_results.average_response_time:.3f}s")
        logger.info(f"  95th percentile: {class_results.p95_response_time:.3f}s")
        logger.info(f"  Requests/second: {class_results.requests_per_second:.2f}")


@pytest.mark.asyncio
@pytest.mark.performance
async def test_student_checkin_scalability():
    """Test student check-in scalability with 1000+ concurrent users."""
    async with PerformanceTester() as tester:
        attendance_tests = AttendanceSystemLoadTests(tester)
        
        # Test with 1000 concurrent students
        checkin_results = await attendance_tests.test_student_checkin_load(
            concurrent_students=1000,
            checkins_per_student=1
        )
        
        # Scalability assertions
        assert checkin_results.success_rate >= 98.0, f"Success rate too low for scalability: {checkin_results.success_rate}%"
        assert checkin_results.average_response_time <= 1.0, f"Average response time too high: {checkin_results.average_response_time}s"
        assert checkin_results.requests_per_second >= 200, f"Throughput too low: {checkin_results.requests_per_second} req/s"
        
        logger.info(f"Student check-in scalability test results:")
        logger.info(f"  Success rate: {checkin_results.success_rate:.2f}%")
        logger.info(f"  Average response time: {checkin_results.average_response_time:.3f}s")
        logger.info(f"  Throughput: {checkin_results.requests_per_second:.2f} req/s")


@pytest.mark.asyncio
@pytest.mark.performance
async def test_database_performance_under_load():
    """Test database performance under concurrent load."""
    async with PerformanceTester() as tester:
        attendance_tests = AttendanceSystemLoadTests(tester)
        
        # Test database query performance
        db_results = await attendance_tests.test_database_query_performance(
            concurrent_queries=200
        )
        
        # Database performance assertions
        assert db_results.success_rate >= 99.0, f"Database queries failing: {db_results.success_rate}%"
        assert db_results.p95_response_time <= 0.5, f"Database queries too slow: {db_results.p95_response_time}s"
        
        logger.info(f"Database performance test results:")
        logger.info(f"  Success rate: {db_results.success_rate:.2f}%")
        logger.info(f"  95th percentile: {db_results.p95_response_time:.3f}s")


@pytest.mark.asyncio
@pytest.mark.performance
async def test_system_endurance():
    """Test system stability over extended period."""
    async with PerformanceTester() as tester:
        attendance_tests = AttendanceSystemLoadTests(tester)
        
        # Run lighter load for longer duration
        duration_minutes = 10  # 10-minute endurance test
        requests_per_minute = 60
        
        start_time = time.time()
        results_list = []
        
        while time.time() - start_time < duration_minutes * 60:
            # Execute batch of requests
            batch_results = await attendance_tests.test_student_checkin_load(
                concurrent_students=requests_per_minute,
                checkins_per_student=1
            )
            results_list.append(batch_results)
            
            # Brief pause between batches
            await asyncio.sleep(1)
        
        # Analyze endurance results
        overall_success_rate = sum(r.success_rate for r in results_list) / len(results_list)
        avg_response_time = sum(r.average_response_time for r in results_list) / len(results_list)
        
        # Endurance assertions
        assert overall_success_rate >= 95.0, f"Endurance test success rate too low: {overall_success_rate}%"
        assert avg_response_time <= 2.0, f"Response time degraded over time: {avg_response_time}s"
        
        logger.info(f"Endurance test results ({duration_minutes} minutes):")
        logger.info(f"  Overall success rate: {overall_success_rate:.2f}%")
        logger.info(f"  Average response time: {avg_response_time:.3f}s")
        logger.info(f"  Total batches: {len(results_list)}")


if __name__ == "__main__":
    # Run performance tests directly
    import sys
    
    async def run_all_tests():
        """Run all performance tests."""
        print("Starting Student Attendance System Performance Tests")
        print("=" * 60)
        
        try:
            await test_api_performance_targets()
            print("✅ API Performance Targets: PASSED")
            
            await test_student_checkin_scalability()
            print("✅ Student Check-in Scalability: PASSED")
            
            await test_database_performance_under_load()
            print("✅ Database Performance: PASSED")
            
            await test_system_endurance()
            print("✅ System Endurance: PASSED")
            
            print("\n🎉 All performance tests passed!")
            
        except AssertionError as e:
            print(f"❌ Performance test failed: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"💥 Unexpected error: {e}")
            sys.exit(1)
    
    # Run the tests
    asyncio.run(run_all_tests())