"""
Gateway Router for intelligent request routing to SIS providers.

This module handles request routing decisions, load balancing,
and failover logic for external SIS provider APIs.
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
import random

from app.services.api_gateway import (
    ProviderType, GatewayRequest, GatewayResponse, 
    ProviderEndpoint, APIGatewayService
)


logger = logging.getLogger(__name__)


class RoutingStrategy(str, Enum):
    """Request routing strategies."""
    ROUND_ROBIN = "round_robin"
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
    LEAST_CONNECTIONS = "least_connections"
    FASTEST_RESPONSE = "fastest_response"
    RANDOM = "random"


@dataclass
class EndpointHealth:
    """Health status of an endpoint."""
    endpoint_url: str
    is_healthy: bool = True
    last_check: datetime = field(default_factory=datetime.utcnow)
    response_time: float = 0.0
    error_count: int = 0
    success_count: int = 0
    consecutive_failures: int = 0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.error_count
        return self.success_count / max(total, 1)
    
    def record_success(self, response_time: float):
        """Record a successful request."""
        self.success_count += 1
        self.consecutive_failures = 0
        self.response_time = response_time
        self.is_healthy = True
        self.last_check = datetime.utcnow()
    
    def record_failure(self):
        """Record a failed request."""
        self.error_count += 1
        self.consecutive_failures += 1
        self.last_check = datetime.utcnow()
        
        # Mark as unhealthy after 3 consecutive failures
        if self.consecutive_failures >= 3:
            self.is_healthy = False


@dataclass 
class RoutingRule:
    """Rule for routing requests to specific providers."""
    path_pattern: str
    provider: ProviderType
    method: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    priority: int = 1
    conditions: Dict[str, Any] = field(default_factory=dict)


class GatewayRouter:
    """
    Intelligent router for API gateway requests.
    
    Features:
    - Multiple routing strategies (round-robin, weighted, etc.)
    - Health-based routing decisions
    - Automatic failover to backup endpoints
    - Request path matching and transformation
    - Performance-aware routing
    """
    
    def __init__(self, gateway_service: APIGatewayService):
        self.gateway_service = gateway_service
        self.routing_strategy = RoutingStrategy.WEIGHTED_ROUND_ROBIN
        
        # Health tracking
        self.endpoint_health: Dict[str, EndpointHealth] = {}
        
        # Routing state
        self.round_robin_counters: Dict[ProviderType, int] = {}
        self.connection_counts: Dict[str, int] = {}
        
        # Routing rules
        self.routing_rules: List[RoutingRule] = []
        
        # Health check task
        self._health_check_task: Optional[asyncio.Task] = None
        self._stop_health_checks = False
        
        self._initialize_default_rules()
        logger.info("Gateway router initialized")
    
    def _initialize_default_rules(self):
        """Initialize default routing rules for SIS providers."""
        default_rules = [
            # PowerSchool routes
            RoutingRule(
                path_pattern="/powerschool/*",
                provider=ProviderType.POWERSCHOOL,
                priority=1
            ),
            RoutingRule(
                path_pattern="/api/v1/students",
                provider=ProviderType.POWERSCHOOL,
                method="GET",
                priority=2
            ),
            
            # Infinite Campus routes
            RoutingRule(
                path_pattern="/infinitecampus/*",
                provider=ProviderType.INFINITE_CAMPUS,
                priority=1
            ),
            RoutingRule(
                path_pattern="/api/v1/enrollment",
                provider=ProviderType.INFINITE_CAMPUS,
                priority=2
            ),
            
            # Skyward routes
            RoutingRule(
                path_pattern="/skyward/*",
                provider=ProviderType.SKYWARD,
                priority=1
            ),
            RoutingRule(
                path_pattern="/api/v1/grades",
                provider=ProviderType.SKYWARD,
                priority=2
            )
        ]
        
        self.routing_rules.extend(default_rules)
    
    async def start(self):
        """Start the router with health checking."""
        # Initialize health tracking for all endpoints
        for provider_type, endpoints in self.gateway_service.providers.items():
            for endpoint in endpoints:
                endpoint_key = f"{provider_type}_{endpoint.base_url}"
                self.endpoint_health[endpoint_key] = EndpointHealth(
                    endpoint_url=endpoint.base_url
                )
                self.connection_counts[endpoint_key] = 0
        
        # Start health check task
        self._stop_health_checks = False
        self._health_check_task = asyncio.create_task(self._run_health_checks())
        
        logger.info("Gateway router started with health checking")
    
    async def stop(self):
        """Stop the router and cleanup resources."""
        self._stop_health_checks = True
        
        if self._health_check_task:
            await self._health_check_task
        
        logger.info("Gateway router stopped")
    
    def add_routing_rule(self, rule: RoutingRule):
        """Add a new routing rule."""
        self.routing_rules.append(rule)
        self.routing_rules.sort(key=lambda r: r.priority, reverse=True)
        logger.info(f"Added routing rule: {rule.path_pattern} -> {rule.provider}")
    
    def match_provider(self, path: str, method: str = "GET") -> Optional[ProviderType]:
        """Match a request path to a provider using routing rules."""
        for rule in self.routing_rules:
            # Check method match
            if rule.method and rule.method.upper() != method.upper():
                continue
            
            # Check path pattern match
            if self._match_path_pattern(path, rule.path_pattern):
                return rule.provider
        
        return None
    
    def _match_path_pattern(self, path: str, pattern: str) -> bool:
        """Check if path matches pattern (supports wildcards)."""
        if pattern.endswith("/*"):
            prefix = pattern[:-2]
            return path.startswith(prefix)
        
        return path == pattern
    
    async def route_request(self, request: GatewayRequest) -> GatewayResponse:
        """
        Route a request using the configured strategy.
        
        Handles endpoint selection, health checking, and failover.
        """
        provider = request.provider
        
        # Get healthy endpoints for provider
        healthy_endpoints = self._get_healthy_endpoints(provider)
        
        if not healthy_endpoints:
            logger.error(f"No healthy endpoints available for {provider}")
            return GatewayResponse(
                status_code=503,
                data={"error": f"No healthy endpoints available for {provider}"},
                headers={},
                duration=0.0,
                provider=provider,
                success=False,
                error="No healthy endpoints"
            )
        
        # Select endpoint based on strategy
        selected_endpoint = await self._select_endpoint(
            healthy_endpoints, 
            provider, 
            self.routing_strategy
        )
        
        # Track connection
        endpoint_key = f"{provider}_{selected_endpoint.base_url}"
        self.connection_counts[endpoint_key] += 1
        
        try:
            # Make the request
            original_request = request
            request.provider = provider  # Ensure provider is set
            
            response = await self.gateway_service.make_request(request)
            
            # Update health tracking
            if endpoint_key in self.endpoint_health:
                if response.success:
                    self.endpoint_health[endpoint_key].record_success(response.duration)
                else:
                    self.endpoint_health[endpoint_key].record_failure()
            
            return response
            
        except Exception as e:
            # Update health tracking for failures
            if endpoint_key in self.endpoint_health:
                self.endpoint_health[endpoint_key].record_failure()
            
            logger.error(f"Request routing failed: {e}")
            return GatewayResponse(
                status_code=500,
                data={"error": str(e)},
                headers={},
                duration=0.0,
                provider=provider,
                success=False,
                error=str(e)
            )
            
        finally:
            # Release connection
            if endpoint_key in self.connection_counts:
                self.connection_counts[endpoint_key] -= 1
    
    def _get_healthy_endpoints(self, provider: ProviderType) -> List[ProviderEndpoint]:
        """Get list of healthy endpoints for a provider."""
        endpoints = self.gateway_service.providers.get(provider, [])
        healthy_endpoints = []
        
        for endpoint in endpoints:
            endpoint_key = f"{provider}_{endpoint.base_url}"
            health = self.endpoint_health.get(endpoint_key)
            
            if health and health.is_healthy:
                healthy_endpoints.append(endpoint)
            elif not health:
                # If no health info, assume healthy initially
                healthy_endpoints.append(endpoint)
        
        return healthy_endpoints
    
    async def _select_endpoint(
        self, 
        endpoints: List[ProviderEndpoint], 
        provider: ProviderType,
        strategy: RoutingStrategy
    ) -> ProviderEndpoint:
        """Select an endpoint based on routing strategy."""
        if len(endpoints) == 1:
            return endpoints[0]
        
        if strategy == RoutingStrategy.ROUND_ROBIN:
            return self._round_robin_selection(endpoints, provider)
        
        elif strategy == RoutingStrategy.WEIGHTED_ROUND_ROBIN:
            return self._weighted_round_robin_selection(endpoints, provider)
        
        elif strategy == RoutingStrategy.LEAST_CONNECTIONS:
            return self._least_connections_selection(endpoints, provider)
        
        elif strategy == RoutingStrategy.FASTEST_RESPONSE:
            return self._fastest_response_selection(endpoints, provider)
        
        elif strategy == RoutingStrategy.RANDOM:
            return random.choice(endpoints)
        
        else:
            # Default to round-robin
            return self._round_robin_selection(endpoints, provider)
    
    def _round_robin_selection(
        self, 
        endpoints: List[ProviderEndpoint], 
        provider: ProviderType
    ) -> ProviderEndpoint:
        """Simple round-robin endpoint selection."""
        if provider not in self.round_robin_counters:
            self.round_robin_counters[provider] = 0
        
        index = self.round_robin_counters[provider] % len(endpoints)
        self.round_robin_counters[provider] += 1
        
        return endpoints[index]
    
    def _weighted_round_robin_selection(
        self, 
        endpoints: List[ProviderEndpoint], 
        provider: ProviderType
    ) -> ProviderEndpoint:
        """Weighted round-robin based on endpoint health."""
        # Calculate weights based on success rate and response time
        weights = []
        for endpoint in endpoints:
            endpoint_key = f"{provider}_{endpoint.base_url}"
            health = self.endpoint_health.get(endpoint_key)
            
            if health:
                # Weight based on success rate and inverse response time
                success_weight = health.success_rate
                speed_weight = 1.0 / max(health.response_time, 0.001)  # Avoid division by zero
                weight = success_weight * speed_weight
            else:
                weight = 1.0  # Default weight
            
            weights.append(weight)
        
        # Select based on weighted probability
        total_weight = sum(weights)
        if total_weight == 0:
            return random.choice(endpoints)
        
        rand_value = random.uniform(0, total_weight)
        cumulative_weight = 0
        
        for i, weight in enumerate(weights):
            cumulative_weight += weight
            if rand_value <= cumulative_weight:
                return endpoints[i]
        
        return endpoints[-1]  # Fallback
    
    def _least_connections_selection(
        self, 
        endpoints: List[ProviderEndpoint], 
        provider: ProviderType
    ) -> ProviderEndpoint:
        """Select endpoint with fewest active connections."""
        min_connections = float('inf')
        selected_endpoint = endpoints[0]
        
        for endpoint in endpoints:
            endpoint_key = f"{provider}_{endpoint.base_url}"
            connections = self.connection_counts.get(endpoint_key, 0)
            
            if connections < min_connections:
                min_connections = connections
                selected_endpoint = endpoint
        
        return selected_endpoint
    
    def _fastest_response_selection(
        self, 
        endpoints: List[ProviderEndpoint], 
        provider: ProviderType
    ) -> ProviderEndpoint:
        """Select endpoint with fastest average response time."""
        fastest_time = float('inf')
        selected_endpoint = endpoints[0]
        
        for endpoint in endpoints:
            endpoint_key = f"{provider}_{endpoint.base_url}"
            health = self.endpoint_health.get(endpoint_key)
            
            response_time = health.response_time if health else 1.0
            
            if response_time < fastest_time:
                fastest_time = response_time
                selected_endpoint = endpoint
        
        return selected_endpoint
    
    async def _run_health_checks(self):
        """Background task to perform health checks on endpoints."""
        while not self._stop_health_checks:
            try:
                await self._perform_health_checks()
                await asyncio.sleep(30)  # Health check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in health check task: {e}")
                await asyncio.sleep(5)  # Short delay on error
    
    async def _perform_health_checks(self):
        """Perform health checks on all endpoints."""
        health_check_tasks = []
        
        for provider_type, endpoints in self.gateway_service.providers.items():
            for endpoint in endpoints:
                endpoint_key = f"{provider_type}_{endpoint.base_url}"
                task = asyncio.create_task(
                    self._check_endpoint_health(endpoint_key, provider_type)
                )
                health_check_tasks.append(task)
        
        if health_check_tasks:
            await asyncio.gather(*health_check_tasks, return_exceptions=True)
    
    async def _check_endpoint_health(self, endpoint_key: str, provider: ProviderType):
        """Check health of a specific endpoint."""
        try:
            # Use the gateway service to test connection
            health_status = await self.gateway_service.test_provider_connection(provider)
            
            if endpoint_key in self.endpoint_health:
                health = self.endpoint_health[endpoint_key]
                
                if health_status.get('status') == 'healthy':
                    health.record_success(health_status.get('response_time', 1.0))
                else:
                    health.record_failure()
                    
        except Exception as e:
            logger.warning(f"Health check failed for {endpoint_key}: {e}")
            if endpoint_key in self.endpoint_health:
                self.endpoint_health[endpoint_key].record_failure()
    
    def get_routing_status(self) -> Dict[str, Any]:
        """Get current routing status and metrics."""
        return {
            'strategy': self.routing_strategy,
            'routing_rules_count': len(self.routing_rules),
            'endpoint_health': {
                key: {
                    'is_healthy': health.is_healthy,
                    'success_rate': health.success_rate,
                    'response_time': health.response_time,
                    'consecutive_failures': health.consecutive_failures,
                    'last_check': health.last_check.isoformat()
                }
                for key, health in self.endpoint_health.items()
            },
            'active_connections': dict(self.connection_counts),
            'round_robin_state': dict(self.round_robin_counters)
        }
    
    def set_routing_strategy(self, strategy: RoutingStrategy):
        """Change the routing strategy."""
        old_strategy = self.routing_strategy
        self.routing_strategy = strategy
        logger.info(f"Routing strategy changed: {old_strategy} -> {strategy}")