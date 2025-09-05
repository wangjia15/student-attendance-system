"""
Comprehensive test suite for API Gateway functionality.

Tests all components of the API Gateway system including routing,
rate limiting, circuit breakers, throttling, and monitoring.
"""
import asyncio
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, Any

from app.services.api_gateway import (
    APIGatewayService, GatewayRequest, GatewayResponse,
    ProviderType, RequestMethod, ProviderEndpoint
)
from app.core.circuit_breaker import CircuitBreaker, CircuitState
from app.middleware.rate_limiting import RateLimiter, TokenBucket
from app.gateway.router import GatewayRouter
from app.gateway.request_queue import RequestQueue, RequestPriority
from app.gateway.throttler import RequestThrottler, ThrottleConfig
from app.gateway.api_key_manager import APIKeyManager, APIKey, KeyType, KeyStatus
from app.gateway.coordinator import GatewayCoordinator
from app.gateway.monitoring import GatewayMonitor


class TestAPIGatewayService:
    """Test the core API Gateway Service."""
    
    @pytest.fixture
    async def gateway_service(self):
        """Create gateway service for testing."""
        service = APIGatewayService()
        await service.start()
        yield service
        await service.stop()
    
    def test_provider_endpoint_configuration(self):
        """Test provider endpoint configuration."""
        endpoint = ProviderEndpoint(
            provider=ProviderType.POWERSCHOOL,
            base_url="https://api.powerschool.com",
            timeout=30.0,
            max_retries=3,
            rate_limit_requests=1000
        )
        
        assert endpoint.provider == ProviderType.POWERSCHOOL
        assert endpoint.base_url == "https://api.powerschool.com"
        assert endpoint.timeout == 30.0
        assert endpoint.max_retries == 3
        assert endpoint.rate_limit_requests == 1000
    
    @pytest.mark.asyncio
    async def test_gateway_request_creation(self):
        """Test gateway request creation."""
        request = GatewayRequest(
            provider=ProviderType.POWERSCHOOL,
            method=RequestMethod.GET,
            path="/api/v1/students",
            params={"limit": 100},
            headers={"Accept": "application/json"}
        )
        
        assert request.provider == ProviderType.POWERSCHOOL
        assert request.method == RequestMethod.GET
        assert request.path == "/api/v1/students"
        assert request.params["limit"] == 100
        assert request.headers["Accept"] == "application/json"
    
    @pytest.mark.asyncio
    async def test_gateway_service_startup_shutdown(self, gateway_service):
        """Test gateway service startup and shutdown."""
        # Service should be started from fixture
        assert gateway_service.http_client is not None
        
        # Test health status
        health = gateway_service.get_health_status()
        assert "status" in health
        assert "metrics" in health
        assert "providers" in health
    
    @pytest.mark.asyncio
    async def test_provider_addition(self, gateway_service):
        """Test adding custom provider endpoint."""
        custom_endpoint = ProviderEndpoint(
            provider=ProviderType.CUSTOM,
            base_url="https://api.custom-sis.com",
            timeout=45.0,
            max_retries=2
        )
        
        gateway_service.add_provider(custom_endpoint)
        
        # Verify provider was added
        assert ProviderType.CUSTOM in gateway_service.providers
        assert len(gateway_service.providers[ProviderType.CUSTOM]) == 1
        assert gateway_service.providers[ProviderType.CUSTOM][0].base_url == "https://api.custom-sis.com"
    
    @pytest.mark.asyncio
    async def test_request_with_mock_response(self, gateway_service):
        """Test request processing with mocked HTTP response."""
        with patch.object(gateway_service, '_execute_request') as mock_execute:
            # Mock successful response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"students": []}
            mock_response.headers = {"Content-Type": "application/json"}
            mock_response.content = b'{"students": []}'
            mock_response.is_success = True
            mock_execute.return_value = mock_response
            
            request = GatewayRequest(
                provider=ProviderType.POWERSCHOOL,
                method=RequestMethod.GET,
                path="/api/v1/students"
            )
            
            response = await gateway_service.make_request(request)
            
            assert response.success is True
            assert response.status_code == 200
            assert response.data == {"students": []}
            assert response.provider == ProviderType.POWERSCHOOL
    
    @pytest.mark.asyncio
    async def test_request_retry_logic(self, gateway_service):
        """Test request retry logic on failure."""
        with patch.object(gateway_service, '_execute_request') as mock_execute:
            # First two calls fail, third succeeds
            mock_execute.side_effect = [
                Exception("Network error"),
                Exception("Timeout"),
                Mock(status_code=200, json=lambda: {"success": True}, 
                     headers={}, content=b'{"success": true}', is_success=True)
            ]
            
            request = GatewayRequest(
                provider=ProviderType.POWERSCHOOL,
                method=RequestMethod.GET,
                path="/api/v1/health"
            )
            
            response = await gateway_service.make_request(request)
            
            assert response.success is True
            assert response.retry_count == 2
            assert mock_execute.call_count == 3


class TestCircuitBreaker:
    """Test circuit breaker functionality."""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_states(self):
        """Test circuit breaker state transitions."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        assert cb.state == CircuitState.CLOSED
        
        # Simulate failures
        async def failing_function():
            raise Exception("Test failure")
        
        # First failure
        with pytest.raises(Exception):
            await cb.call(failing_function)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 1
        
        # Second failure - should trip circuit
        with pytest.raises(Exception):
            await cb.call(failing_function)
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 2
        
        # Subsequent calls should fail fast
        with pytest.raises(Exception):
            await cb.call(failing_function)
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        
        # Trip the circuit
        with pytest.raises(Exception):
            await cb.call(lambda: exec('raise Exception("Test")'))
        
        assert cb.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        await asyncio.sleep(0.2)
        
        # Should transition to half-open on next call
        async def success_function():
            return "success"
        
        result = await cb.call(success_function)
        assert result == "success"
        assert cb.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_manual_control(self):
        """Test manual circuit breaker control."""
        cb = CircuitBreaker()
        
        # Force open
        await cb.force_open("Manual test")
        assert cb.state == CircuitState.OPEN
        
        # Force closed
        await cb.force_closed("Manual recovery")
        assert cb.state == CircuitState.CLOSED
    
    def test_circuit_breaker_metrics(self):
        """Test circuit breaker metrics collection."""
        cb = CircuitBreaker()
        status = cb.get_status()
        
        assert 'state' in status
        assert 'failure_count' in status
        assert 'metrics' in status
        assert 'config' in status
        
        # Test metrics reset
        cb.reset_metrics()
        assert cb.metrics.total_requests == 0


class TestRateLimiter:
    """Test rate limiting functionality."""
    
    @pytest.mark.asyncio
    async def test_token_bucket_basic(self):
        """Test basic token bucket functionality."""
        bucket = TokenBucket(rate=10.0, capacity=10)
        
        # Should be able to consume all tokens initially
        for _ in range(10):
            assert await bucket.consume() is True
        
        # Should not be able to consume more
        assert await bucket.consume() is False
        
        # Wait for token refill
        await asyncio.sleep(0.2)  # 0.2s should give 2 tokens at 10 tokens/sec
        assert await bucket.consume() is True
    
    @pytest.mark.asyncio
    async def test_rate_limiter_allow_deny(self):
        """Test rate limiter allow/deny logic."""
        limiter = RateLimiter(
            max_requests=5,
            time_window=1,  # 5 requests per second
            max_queue_size=0  # No queuing for this test
        )
        await limiter.start()
        
        try:
            # Should allow first 5 requests
            for i in range(5):
                allowed = await limiter.acquire(f"req_{i}")
                assert allowed is True
            
            # 6th request should be denied (no queuing)
            allowed = await limiter.acquire("req_6")
            assert allowed is False
            
        finally:
            await limiter.stop()
    
    @pytest.mark.asyncio
    async def test_rate_limiter_queuing(self):
        """Test rate limiter queuing functionality."""
        limiter = RateLimiter(
            max_requests=2,
            time_window=1,  # 2 requests per second
            max_queue_size=5
        )
        await limiter.start()
        
        try:
            # First two should be immediate
            assert await limiter.acquire("req_1") is True
            assert await limiter.acquire("req_2") is True
            
            # Third should be queued and eventually allowed
            start_time = time.time()
            allowed = await limiter.acquire("req_3", timeout=2.0)
            elapsed = time.time() - start_time
            
            assert allowed is True
            assert elapsed > 0.3  # Should have waited for token availability
            
        finally:
            await limiter.stop()
    
    def test_rate_limiter_metrics(self):
        """Test rate limiter metrics collection."""
        limiter = RateLimiter(max_requests=10, time_window=60)
        
        # Record some metrics
        limiter.metrics.record_request(allowed=True)
        limiter.metrics.record_request(allowed=False)
        
        stats = limiter.metrics.get_stats()
        assert stats['total_requests'] == 2
        assert stats['allowed_requests'] == 1
        assert stats['denied_requests'] == 1
        assert stats['success_rate'] == 0.5


class TestGatewayRouter:
    """Test gateway routing functionality."""
    
    @pytest.fixture
    async def router_setup(self):
        """Setup router for testing."""
        gateway_service = APIGatewayService()
        await gateway_service.start()
        
        router = GatewayRouter(gateway_service)
        await router.start()
        
        yield router, gateway_service
        
        await router.stop()
        await gateway_service.stop()
    
    @pytest.mark.asyncio
    async def test_router_path_matching(self, router_setup):
        """Test router path matching logic."""
        router, _ = router_setup
        
        # Test provider matching
        assert router.match_provider("/powerschool/students") == ProviderType.POWERSCHOOL
        assert router.match_provider("/infinitecampus/enrollment") == ProviderType.INFINITE_CAMPUS
        assert router.match_provider("/skyward/grades") == ProviderType.SKYWARD
        assert router.match_provider("/unknown/path") is None
    
    @pytest.mark.asyncio
    async def test_router_health_tracking(self, router_setup):
        """Test router health tracking."""
        router, _ = router_setup
        
        # Simulate endpoint health updates
        endpoint_key = f"{ProviderType.POWERSCHOOL}_https://api.powerschool.com"
        if endpoint_key in router.endpoint_health:
            health = router.endpoint_health[endpoint_key]
            
            # Record success
            health.record_success(0.5)
            assert health.is_healthy is True
            assert health.success_count == 1
            
            # Record failures
            for _ in range(5):
                health.record_failure()
            
            assert health.is_healthy is False
            assert health.consecutive_failures == 5
    
    def test_routing_status_report(self):
        """Test routing status reporting."""
        gateway_service = APIGatewayService()
        router = GatewayRouter(gateway_service)
        
        status = router.get_routing_status()
        
        assert 'strategy' in status
        assert 'routing_rules_count' in status
        assert 'endpoint_health' in status
        assert 'active_connections' in status


class TestRequestQueue:
    """Test request queue functionality."""
    
    @pytest.fixture
    async def queue_setup(self):
        """Setup request queue for testing."""
        async def mock_processor(request):
            # Simulate processing
            await asyncio.sleep(0.1)
            return GatewayResponse(
                status_code=200,
                data={"processed": True},
                headers={},
                duration=0.1,
                provider=request.provider,
                success=True
            )
        
        queue = RequestQueue(
            max_size=100,
            processor_count=2,
            processor_callable=mock_processor
        )
        await queue.start()
        yield queue
        await queue.stop()
    
    @pytest.mark.asyncio
    async def test_queue_enqueue_and_process(self, queue_setup):
        """Test enqueueing and processing requests."""
        queue = queue_setup
        
        request = GatewayRequest(
            provider=ProviderType.POWERSCHOOL,
            method=RequestMethod.GET,
            path="/test"
        )
        
        # Enqueue and wait for processing
        response = await queue.enqueue_and_wait(
            request=request,
            priority=RequestPriority.NORMAL,
            timeout=5.0
        )
        
        assert response.success is True
        assert response.status_code == 200
        assert response.data["processed"] is True
    
    @pytest.mark.asyncio
    async def test_queue_priority_handling(self, queue_setup):
        """Test priority-based queue processing."""
        queue = queue_setup
        
        # Enqueue multiple requests with different priorities
        requests = []
        for i in range(3):
            request = GatewayRequest(
                provider=ProviderType.POWERSCHOOL,
                method=RequestMethod.GET,
                path=f"/test/{i}"
            )
            
            priority = RequestPriority.URGENT if i == 2 else RequestPriority.NORMAL
            request_id = await queue.enqueue(request, priority=priority)
            requests.append(request_id)
        
        # Allow processing
        await asyncio.sleep(0.5)
        
        # Check queue status
        status = queue.get_queue_status()
        assert status['active_requests'] == 0  # All should be processed
    
    @pytest.mark.asyncio
    async def test_queue_timeout_handling(self, queue_setup):
        """Test queue timeout handling."""
        queue = queue_setup
        
        request = GatewayRequest(
            provider=ProviderType.POWERSCHOOL,
            method=RequestMethod.GET,
            path="/test"
        )
        
        # Enqueue with very short timeout
        with pytest.raises(asyncio.TimeoutError):
            await queue.enqueue_and_wait(
                request=request,
                timeout=0.01  # Very short timeout
            )
    
    def test_queue_metrics(self, queue_setup):
        """Test queue metrics collection."""
        queue = queue_setup
        
        status = queue.get_queue_status()
        
        assert 'strategy' in status
        assert 'max_size' in status
        assert 'queue_sizes' in status
        assert 'active_requests' in status


class TestRequestThrottler:
    """Test request throttling functionality."""
    
    @pytest.mark.asyncio
    async def test_throttler_basic_functionality(self):
        """Test basic throttling functionality."""
        config = ThrottleConfig(
            provider="test",
            max_requests_per_second=2.0,
            min_interval_ms=500
        )
        
        throttler = RequestThrottler("test", config)
        
        request = GatewayRequest(
            provider=ProviderType.CUSTOM,
            method=RequestMethod.GET,
            path="/test"
        )
        
        # First request should not be throttled
        should_throttle, delay = await throttler.should_throttle(request)
        assert should_throttle is False
        assert delay == 0.0
        
        # Immediate second request should be throttled due to min_interval
        should_throttle, delay = await throttler.should_throttle(request)
        assert should_throttle is True
        assert delay > 0
    
    @pytest.mark.asyncio
    async def test_throttler_response_recording(self):
        """Test throttler response recording for adaptive behavior."""
        throttler = RequestThrottler("test")
        
        # Record successful response
        await throttler.record_response("req_1", success=True, response_time=0.5)
        assert throttler.consecutive_errors == 0
        
        # Record failed response
        await throttler.record_response("req_2", success=False, response_time=5.0)
        assert throttler.consecutive_errors == 1
    
    def test_throttler_status_report(self):
        """Test throttler status reporting."""
        throttler = RequestThrottler("test")
        
        status = throttler.get_status()
        
        assert 'provider' in status
        assert 'config' in status
        assert 'current_state' in status
        assert 'metrics' in status


class TestAPIKeyManager:
    """Test API key management functionality."""
    
    @pytest.fixture
    async def key_manager(self):
        """Create key manager for testing."""
        manager = APIKeyManager()
        await manager.start()
        yield manager
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_key_creation(self, key_manager):
        """Test API key creation."""
        key = await key_manager.create_key(
            provider="powerschool",
            key_value="test-api-key-123",
            key_type=KeyType.PRIMARY
        )
        
        assert key.provider == "powerschool"
        assert key.key_value == "test-api-key-123"
        assert key.key_type == KeyType.PRIMARY
        assert key.status == KeyStatus.ACTIVE
        assert key.key_id is not None
    
    @pytest.mark.asyncio
    async def test_active_key_retrieval(self, key_manager):
        """Test retrieving active keys."""
        # Create a key
        await key_manager.create_key(
            provider="powerschool",
            key_value="active-key-123"
        )
        
        # Retrieve active key
        active_key = await key_manager.get_active_key("powerschool")
        
        assert active_key is not None
        assert active_key.key_value == "active-key-123"
        assert active_key.status == KeyStatus.ACTIVE
        assert active_key.usage_count == 1  # Should increment on retrieval
    
    @pytest.mark.asyncio
    async def test_key_rotation(self, key_manager):
        """Test key rotation."""
        # Create initial key
        old_key = await key_manager.create_key(
            provider="powerschool",
            key_value="old-key-123"
        )
        
        # Rotate key
        new_key, rotated_old_key = await key_manager.rotate_key(
            provider="powerschool",
            new_key_value="new-key-456"
        )
        
        assert new_key.key_value == "new-key-456"
        assert new_key.status == KeyStatus.ACTIVE
        assert rotated_old_key.key_id == old_key.key_id
        assert rotated_old_key.status == KeyStatus.ROTATING
    
    @pytest.mark.asyncio
    async def test_key_status_update(self, key_manager):
        """Test key status updates."""
        key = await key_manager.create_key(
            provider="powerschool",
            key_value="test-key-123"
        )
        
        # Update status
        success = await key_manager.update_key_status(
            key.key_id,
            KeyStatus.COMPROMISED,
            reason="Security incident"
        )
        
        assert success is True
        
        # Retrieve and verify
        updated_key = await key_manager.get_key_by_id(key.key_id)
        assert updated_key.status == KeyStatus.COMPROMISED
    
    @pytest.mark.asyncio
    async def test_key_health_check(self, key_manager):
        """Test key health reporting."""
        # Create some keys with different states
        await key_manager.create_key("powerschool", "key1")
        await key_manager.create_key("infinite_campus", "key2")
        
        health_report = await key_manager.check_key_health()
        
        assert health_report['total_keys'] == 2
        assert health_report['active_keys'] == 2
        assert health_report['expired_keys'] == 0
        assert 'providers' in health_report
        assert 'warnings' in health_report


class TestGatewayCoordinator:
    """Test the main gateway coordinator."""
    
    @pytest.fixture
    async def coordinator(self):
        """Create coordinator for testing."""
        coordinator = GatewayCoordinator()
        await coordinator.start()
        yield coordinator
        await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_coordinator_startup_shutdown(self, coordinator):
        """Test coordinator startup and shutdown."""
        # Should be started from fixture
        assert coordinator.status.value in ['healthy', 'degraded']
        assert coordinator.start_time is not None
    
    @pytest.mark.asyncio
    async def test_coordinator_health_status(self, coordinator):
        """Test coordinator health status reporting."""
        health = coordinator.get_health_status()
        
        assert 'gateway_status' in health
        assert 'uptime_seconds' in health
        assert 'metrics' in health
        assert 'components' in health
        
        # Check metrics structure
        metrics = health['metrics']
        assert 'total_requests' in metrics
        assert 'success_rate' in metrics
        assert 'average_response_time' in metrics
    
    @pytest.mark.asyncio
    async def test_coordinator_request_processing(self, coordinator):
        """Test end-to-end request processing through coordinator."""
        with patch.object(coordinator.gateway_service, 'make_request') as mock_request:
            # Mock successful response
            mock_request.return_value = GatewayResponse(
                status_code=200,
                data={"test": "success"},
                headers={},
                duration=0.1,
                provider=ProviderType.POWERSCHOOL,
                success=True
            )
            
            response = await coordinator.process_request(
                provider=ProviderType.POWERSCHOOL,
                method=RequestMethod.GET,
                path="/api/v1/students",
                params={"limit": 10}
            )
            
            assert response.success is True
            assert response.status_code == 200
            assert response.data["test"] == "success"
    
    @pytest.mark.asyncio
    async def test_coordinator_admin_commands(self, coordinator):
        """Test coordinator administrative commands."""
        # Test health check command
        result = await coordinator.admin_command("health_check")
        assert 'gateway_status' in result
        
        # Test metrics reset command
        result = await coordinator.admin_command("reset_metrics")
        assert result['status'] == 'metrics_reset'
        
        # Test unknown command
        result = await coordinator.admin_command("unknown_command")
        assert 'error' in result


class TestGatewayMonitoring:
    """Test gateway monitoring functionality."""
    
    @pytest.fixture
    def monitor(self):
        """Create monitor for testing."""
        return GatewayMonitor()
    
    @pytest.mark.asyncio
    async def test_monitor_request_recording(self, monitor):
        """Test request recording in monitor."""
        response = GatewayResponse(
            status_code=200,
            data={"test": "success"},
            headers={},
            duration=0.5,
            provider=ProviderType.POWERSCHOOL,
            success=True
        )
        
        monitor.record_request(
            provider=ProviderType.POWERSCHOOL,
            method="GET",
            path="/api/v1/students",
            response=response,
            processing_time=0.1
        )
        
        # Check metrics were recorded
        assert len(monitor.response_times) == 1
        assert monitor.request_counts[ProviderType.POWERSCHOOL.value] == 1
    
    @pytest.mark.asyncio
    async def test_monitor_error_recording(self, monitor):
        """Test error recording in monitor."""
        monitor.record_error(
            provider=ProviderType.POWERSCHOOL,
            operation="sync_students",
            error="Connection timeout",
            metadata={"timeout": 30.0}
        )
        
        # Check error was logged
        recent_logs = monitor.log_aggregator.get_recent_logs(limit=10)
        assert len(recent_logs) == 1
        assert recent_logs[0]['level'] == 'ERROR'
        assert 'Connection timeout' in recent_logs[0]['message']
    
    def test_monitor_dashboard_data(self, monitor):
        """Test dashboard data generation."""
        dashboard_data = monitor.get_dashboard_data()
        
        assert 'system' in dashboard_data
        assert 'metrics' in dashboard_data
        assert 'logs' in dashboard_data
        assert 'alerts' in dashboard_data
        
        system_info = dashboard_data['system']
        assert 'uptime_seconds' in system_info
        assert 'status' in system_info


class TestIntegrationScenarios:
    """Integration tests for complex scenarios."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_request_flow(self):
        """Test complete request flow through all components."""
        # This would be a comprehensive integration test
        # that exercises the full request pipeline
        
        coordinator = GatewayCoordinator()
        await coordinator.start()
        
        try:
            with patch.object(coordinator.gateway_service, '_execute_request') as mock_execute:
                # Mock HTTP response
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"students": ["Alice", "Bob"]}
                mock_response.headers = {}
                mock_response.content = b'{"students": ["Alice", "Bob"]}'
                mock_response.is_success = True
                mock_execute.return_value = mock_response
                
                # Process request through coordinator
                response = await coordinator.process_request(
                    provider=ProviderType.POWERSCHOOL,
                    method=RequestMethod.GET,
                    path="/api/v1/students",
                    params={"grade": 9},
                    timeout=30.0
                )
                
                # Verify response
                assert response.success is True
                assert response.status_code == 200
                assert "students" in response.data
                assert len(response.data["students"]) == 2
                
        finally:
            await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_error_handling_and_recovery(self):
        """Test error handling and recovery scenarios."""
        coordinator = GatewayCoordinator()
        await coordinator.start()
        
        try:
            with patch.object(coordinator.gateway_service, '_execute_request') as mock_execute:
                # Simulate network error
                mock_execute.side_effect = Exception("Network unreachable")
                
                response = await coordinator.process_request(
                    provider=ProviderType.POWERSCHOOL,
                    method=RequestMethod.GET,
                    path="/api/v1/students"
                )
                
                # Should return error response
                assert response.success is False
                assert response.status_code == 500
                assert "error" in response.data
                
        finally:
            await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_high_load_scenario(self):
        """Test system behavior under high load."""
        coordinator = GatewayCoordinator()
        await coordinator.start()
        
        try:
            with patch.object(coordinator.gateway_service, 'make_request') as mock_request:
                # Mock fast responses
                mock_request.return_value = GatewayResponse(
                    status_code=200,
                    data={"success": True},
                    headers={},
                    duration=0.01,
                    provider=ProviderType.POWERSCHOOL,
                    success=True
                )
                
                # Send multiple concurrent requests
                tasks = []
                for i in range(50):
                    task = coordinator.process_request(
                        provider=ProviderType.POWERSCHOOL,
                        method=RequestMethod.GET,
                        path=f"/api/v1/test/{i}"
                    )
                    tasks.append(task)
                
                # Wait for all to complete
                responses = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Check results
                successful_responses = [
                    r for r in responses 
                    if hasattr(r, 'success') and r.success
                ]
                
                # Should handle most requests successfully
                assert len(successful_responses) > 40  # At least 80% success rate
                
        finally:
            await coordinator.stop()


# Utility functions for testing
def create_mock_response(status_code: int = 200, data: Any = None) -> GatewayResponse:
    """Create a mock gateway response for testing."""
    return GatewayResponse(
        status_code=status_code,
        data=data or {"mock": True},
        headers={},
        duration=0.1,
        provider=ProviderType.POWERSCHOOL,
        success=status_code < 400
    )


# Test configuration
def pytest_configure(config):
    """Configure pytest for async testing."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as asyncio coroutine"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])