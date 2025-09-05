"""
Comprehensive Monitoring and Logging for API Gateway.

This module provides detailed monitoring, metrics collection, and logging
capabilities for all API Gateway operations, enabling observability and
troubleshooting of SIS integration performance.
"""
import asyncio
import json
import logging
import time
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import deque, defaultdict
import threading

from app.services.api_gateway import ProviderType, GatewayResponse


logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MetricType(str, Enum):
    """Types of metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class MetricDataPoint:
    """A single metric data point."""
    timestamp: datetime
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp.isoformat(),
            'value': self.value,
            'labels': self.labels
        }


@dataclass
class Alert:
    """Alert definition and state."""
    alert_id: str
    level: AlertLevel
    message: str
    timestamp: datetime
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'alert_id': self.alert_id,
            'level': self.level.value,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'resolved': self.resolved,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'metadata': self.metadata
        }


class MetricCollector:
    """
    Collects and aggregates metrics for monitoring.
    
    Supports different metric types and provides time-series data
    for analysis and alerting.
    """
    
    def __init__(self, max_data_points: int = 10000):
        self.max_data_points = max_data_points
        self.metrics: Dict[str, List[MetricDataPoint]] = defaultdict(list)
        self.metric_types: Dict[str, MetricType] = {}
        self.lock = threading.RLock()
    
    def record_metric(
        self,
        metric_name: str,
        value: float,
        metric_type: MetricType = MetricType.GAUGE,
        labels: Optional[Dict[str, str]] = None,
        timestamp: Optional[datetime] = None
    ):
        """Record a metric data point."""
        with self.lock:
            if timestamp is None:
                timestamp = datetime.utcnow()
            
            data_point = MetricDataPoint(
                timestamp=timestamp,
                value=value,
                labels=labels or {}
            )
            
            self.metrics[metric_name].append(data_point)
            self.metric_types[metric_name] = metric_type
            
            # Keep only the most recent data points
            if len(self.metrics[metric_name]) > self.max_data_points:
                self.metrics[metric_name] = self.metrics[metric_name][-self.max_data_points:]
    
    def get_metric_data(
        self,
        metric_name: str,
        since: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[MetricDataPoint]:
        """Get metric data points."""
        with self.lock:
            data_points = self.metrics.get(metric_name, [])
            
            if since:
                data_points = [dp for dp in data_points if dp.timestamp >= since]
            
            if limit:
                data_points = data_points[-limit:]
            
            return data_points
    
    def get_metric_summary(self, metric_name: str, minutes: int = 60) -> Dict[str, Any]:
        """Get metric summary statistics."""
        since = datetime.utcnow() - timedelta(minutes=minutes)
        data_points = self.get_metric_data(metric_name, since=since)
        
        if not data_points:
            return {
                'metric_name': metric_name,
                'data_points': 0,
                'min': None,
                'max': None,
                'avg': None,
                'sum': None
            }
        
        values = [dp.value for dp in data_points]
        
        return {
            'metric_name': metric_name,
            'data_points': len(values),
            'min': min(values),
            'max': max(values),
            'avg': sum(values) / len(values),
            'sum': sum(values),
            'latest': values[-1],
            'time_range_minutes': minutes
        }
    
    def get_all_metrics(self) -> List[str]:
        """Get list of all metric names."""
        with self.lock:
            return list(self.metrics.keys())


class LogAggregator:
    """
    Aggregates and analyzes log entries for monitoring and alerting.
    """
    
    def __init__(self, max_entries: int = 50000):
        self.max_entries = max_entries
        self.log_entries: deque = deque(maxlen=max_entries)
        self.error_patterns: Dict[str, int] = defaultdict(int)
        self.lock = threading.RLock()
    
    def add_log_entry(
        self,
        level: str,
        message: str,
        provider: Optional[str] = None,
        operation: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ):
        """Add a log entry."""
        with self.lock:
            if timestamp is None:
                timestamp = datetime.utcnow()
            
            entry = {
                'timestamp': timestamp,
                'level': level.upper(),
                'message': message,
                'provider': provider,
                'operation': operation,
                'metadata': metadata or {}
            }
            
            self.log_entries.append(entry)
            
            # Track error patterns
            if level.upper() in ['ERROR', 'CRITICAL']:
                # Extract error pattern (simplified)
                pattern = self._extract_error_pattern(message)
                self.error_patterns[pattern] += 1
    
    def _extract_error_pattern(self, message: str) -> str:
        """Extract error pattern from message for grouping."""
        # Simplified pattern extraction
        # Remove specific IDs, timestamps, etc.
        import re
        
        # Remove common variable parts
        pattern = re.sub(r'\d+', 'N', message)
        pattern = re.sub(r'[a-f0-9-]{8,}', 'ID', pattern)
        pattern = re.sub(r'\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}', 'TIMESTAMP', pattern)
        
        return pattern[:200]  # Limit pattern length
    
    def get_recent_logs(
        self,
        limit: int = 100,
        level: Optional[str] = None,
        provider: Optional[str] = None,
        minutes: int = 60
    ) -> List[Dict[str, Any]]:
        """Get recent log entries."""
        with self.lock:
            since = datetime.utcnow() - timedelta(minutes=minutes)
            
            filtered_logs = []
            for entry in reversed(self.log_entries):
                if len(filtered_logs) >= limit:
                    break
                
                if entry['timestamp'] < since:
                    continue
                
                if level and entry['level'] != level.upper():
                    continue
                
                if provider and entry['provider'] != provider:
                    continue
                
                # Convert timestamp for serialization
                serialized_entry = entry.copy()
                serialized_entry['timestamp'] = entry['timestamp'].isoformat()
                filtered_logs.append(serialized_entry)
            
            return filtered_logs
    
    def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get error summary statistics."""
        with self.lock:
            since = datetime.utcnow() - timedelta(hours=hours)
            
            error_count = 0
            warning_count = 0
            provider_errors = defaultdict(int)
            
            for entry in self.log_entries:
                if entry['timestamp'] < since:
                    continue
                
                if entry['level'] == 'ERROR':
                    error_count += 1
                    if entry['provider']:
                        provider_errors[entry['provider']] += 1
                elif entry['level'] == 'WARNING':
                    warning_count += 1
            
            # Top error patterns
            recent_patterns = defaultdict(int)
            for pattern, count in self.error_patterns.items():
                if count > 0:
                    recent_patterns[pattern] = count
            
            top_patterns = sorted(
                recent_patterns.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
            
            return {
                'time_range_hours': hours,
                'error_count': error_count,
                'warning_count': warning_count,
                'errors_by_provider': dict(provider_errors),
                'top_error_patterns': [
                    {'pattern': pattern, 'count': count}
                    for pattern, count in top_patterns
                ]
            }


class AlertManager:
    """
    Manages alerts based on metrics and log patterns.
    """
    
    def __init__(self):
        self.alerts: Dict[str, Alert] = {}
        self.alert_rules: List[Callable[[Dict[str, Any]], Optional[Alert]]] = []
        self.lock = threading.RLock()
        
        # Setup default alert rules
        self._setup_default_rules()
    
    def _setup_default_rules(self):
        """Setup default alerting rules."""
        self.alert_rules = [
            self._check_error_rate,
            self._check_response_time,
            self._check_circuit_breakers,
            self._check_queue_size,
            self._check_rate_limiting
        ]
    
    def check_alerts(self, metrics: Dict[str, Any], logs: Dict[str, Any]) -> List[Alert]:
        """Check all alert rules and return triggered alerts."""
        context = {'metrics': metrics, 'logs': logs}
        triggered_alerts = []
        
        with self.lock:
            for rule in self.alert_rules:
                try:
                    alert = rule(context)
                    if alert:
                        # Check if this is a new alert or update to existing
                        existing = self.alerts.get(alert.alert_id)
                        
                        if not existing or existing.resolved:
                            # New alert
                            self.alerts[alert.alert_id] = alert
                            triggered_alerts.append(alert)
                            logger.warning(f"Alert triggered: {alert.message}")
                        
                except Exception as e:
                    logger.error(f"Error in alert rule: {e}")
            
            # Check for resolved alerts
            self._check_resolved_alerts(context)
        
        return triggered_alerts
    
    def _check_error_rate(self, context: Dict[str, Any]) -> Optional[Alert]:
        """Check for high error rate."""
        logs = context.get('logs', {})
        error_count = logs.get('error_count', 0)
        warning_count = logs.get('warning_count', 0)
        
        total_errors = error_count + warning_count
        
        if total_errors > 50:  # More than 50 errors in last hour
            return Alert(
                alert_id="high_error_rate",
                level=AlertLevel.ERROR,
                message=f"High error rate detected: {total_errors} errors in last hour",
                timestamp=datetime.utcnow(),
                metadata={'error_count': error_count, 'warning_count': warning_count}
            )
        
        return None
    
    def _check_response_time(self, context: Dict[str, Any]) -> Optional[Alert]:
        """Check for high response times."""
        metrics = context.get('metrics', {})
        
        # This would check actual response time metrics
        # For now, we'll use a placeholder
        avg_response_time = metrics.get('average_response_time', 0)
        
        if avg_response_time > 5.0:  # More than 5 seconds average
            return Alert(
                alert_id="high_response_time",
                level=AlertLevel.WARNING,
                message=f"High average response time: {avg_response_time:.2f}s",
                timestamp=datetime.utcnow(),
                metadata={'response_time': avg_response_time}
            )
        
        return None
    
    def _check_circuit_breakers(self, context: Dict[str, Any]) -> Optional[Alert]:
        """Check for open circuit breakers."""
        metrics = context.get('metrics', {})
        open_breakers = metrics.get('circuit_breakers_open', 0)
        
        if open_breakers > 0:
            return Alert(
                alert_id="circuit_breakers_open",
                level=AlertLevel.ERROR,
                message=f"Circuit breakers are open: {open_breakers} providers affected",
                timestamp=datetime.utcnow(),
                metadata={'open_breakers': open_breakers}
            )
        
        return None
    
    def _check_queue_size(self, context: Dict[str, Any]) -> Optional[Alert]:
        """Check for large queue sizes."""
        metrics = context.get('metrics', {})
        queue_size = metrics.get('queue_size', 0)
        
        if queue_size > 1000:  # More than 1000 queued requests
            return Alert(
                alert_id="large_queue_size",
                level=AlertLevel.WARNING,
                message=f"Request queue is backing up: {queue_size} requests queued",
                timestamp=datetime.utcnow(),
                metadata={'queue_size': queue_size}
            )
        
        return None
    
    def _check_rate_limiting(self, context: Dict[str, Any]) -> Optional[Alert]:
        """Check for excessive rate limiting."""
        metrics = context.get('metrics', {})
        rate_limited = metrics.get('rate_limited_requests', 0)
        total_requests = metrics.get('total_requests', 1)
        
        rate_limit_percentage = (rate_limited / total_requests) * 100
        
        if rate_limit_percentage > 20:  # More than 20% of requests rate limited
            return Alert(
                alert_id="excessive_rate_limiting",
                level=AlertLevel.WARNING,
                message=f"High rate limiting: {rate_limit_percentage:.1f}% of requests rate limited",
                timestamp=datetime.utcnow(),
                metadata={
                    'rate_limited_requests': rate_limited,
                    'rate_limit_percentage': rate_limit_percentage
                }
            )
        
        return None
    
    def _check_resolved_alerts(self, context: Dict[str, Any]):
        """Check if any alerts should be resolved."""
        for alert_id, alert in self.alerts.items():
            if not alert.resolved:
                # Check if conditions that triggered the alert are resolved
                if alert_id == "high_error_rate":
                    logs = context.get('logs', {})
                    if logs.get('error_count', 0) + logs.get('warning_count', 0) <= 10:
                        alert.resolved = True
                        alert.resolved_at = datetime.utcnow()
                        logger.info(f"Alert resolved: {alert.message}")
                
                elif alert_id == "circuit_breakers_open":
                    metrics = context.get('metrics', {})
                    if metrics.get('circuit_breakers_open', 0) == 0:
                        alert.resolved = True
                        alert.resolved_at = datetime.utcnow()
                        logger.info(f"Alert resolved: {alert.message}")
    
    def get_active_alerts(self) -> List[Alert]:
        """Get all active (unresolved) alerts."""
        with self.lock:
            return [alert for alert in self.alerts.values() if not alert.resolved]
    
    def get_all_alerts(self, limit: int = 100) -> List[Alert]:
        """Get all alerts (resolved and unresolved)."""
        with self.lock:
            all_alerts = list(self.alerts.values())
            # Sort by timestamp, most recent first
            all_alerts.sort(key=lambda a: a.timestamp, reverse=True)
            return all_alerts[:limit]


class GatewayMonitor:
    """
    Main monitoring class that coordinates metrics, logging, and alerting.
    """
    
    def __init__(self):
        self.metric_collector = MetricCollector()
        self.log_aggregator = LogAggregator()
        self.alert_manager = AlertManager()
        
        # Monitoring state
        self.start_time = datetime.utcnow()
        self._monitoring_task: Optional[asyncio.Task] = None
        self._stop_monitoring = False
        
        # Request tracking for metrics
        self.request_counts: Dict[str, int] = defaultdict(int)
        self.response_times: deque = deque(maxlen=1000)
        
        logger.info("Gateway monitor initialized")
    
    async def start_monitoring(self):
        """Start background monitoring tasks."""
        self._stop_monitoring = False
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Gateway monitoring started")
    
    async def stop_monitoring(self):
        """Stop background monitoring."""
        self._stop_monitoring = True
        if self._monitoring_task:
            self._monitoring_task.cancel()
        logger.info("Gateway monitoring stopped")
    
    def record_request(
        self,
        provider: ProviderType,
        method: str,
        path: str,
        response: GatewayResponse,
        processing_time: float
    ):
        """Record a request for monitoring."""
        now = datetime.utcnow()
        provider_str = provider.value
        
        # Record metrics
        self.metric_collector.record_metric(
            f"requests_total_{provider_str}",
            1,
            MetricType.COUNTER,
            labels={'method': method, 'provider': provider_str}
        )
        
        self.metric_collector.record_metric(
            f"response_time_{provider_str}",
            response.duration,
            MetricType.HISTOGRAM,
            labels={'provider': provider_str}
        )
        
        self.metric_collector.record_metric(
            f"processing_time_{provider_str}",
            processing_time,
            MetricType.HISTOGRAM,
            labels={'provider': provider_str}
        )
        
        # Record success/failure
        status = "success" if response.success else "failure"
        self.metric_collector.record_metric(
            f"requests_status_{provider_str}",
            1,
            MetricType.COUNTER,
            labels={'status': status, 'provider': provider_str}
        )
        
        # Record status code
        self.metric_collector.record_metric(
            f"response_status_code_{provider_str}",
            response.status_code,
            MetricType.GAUGE,
            labels={'provider': provider_str}
        )
        
        # Update internal tracking
        self.request_counts[provider_str] += 1
        self.response_times.append(response.duration)
        
        # Log the request
        log_level = "ERROR" if not response.success else "INFO"
        self.log_aggregator.add_log_entry(
            level=log_level,
            message=f"Request {method} {path}: {response.status_code} in {response.duration:.3f}s",
            provider=provider_str,
            operation="request",
            metadata={
                'method': method,
                'path': path,
                'status_code': response.status_code,
                'duration': response.duration,
                'processing_time': processing_time,
                'retry_count': response.retry_count,
                'circuit_breaker_tripped': response.circuit_breaker_tripped
            }
        )
    
    def record_error(
        self,
        provider: Optional[ProviderType],
        operation: str,
        error: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Record an error for monitoring."""
        provider_str = provider.value if provider else "system"
        
        self.metric_collector.record_metric(
            f"errors_total_{provider_str}",
            1,
            MetricType.COUNTER,
            labels={'provider': provider_str, 'operation': operation}
        )
        
        self.log_aggregator.add_log_entry(
            level="ERROR",
            message=error,
            provider=provider_str,
            operation=operation,
            metadata=metadata
        )
    
    async def _monitoring_loop(self):
        """Background monitoring loop."""
        while not self._stop_monitoring:
            try:
                # Collect current metrics
                current_metrics = self._collect_current_metrics()
                
                # Get log summary
                log_summary = self.log_aggregator.get_error_summary(hours=1)
                
                # Check alerts
                self.alert_manager.check_alerts(current_metrics, log_summary)
                
                # Record system metrics
                self._record_system_metrics()
                
                # Wait before next iteration
                await asyncio.sleep(30)  # Run every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(10)
    
    def _collect_current_metrics(self) -> Dict[str, Any]:
        """Collect current system metrics."""
        total_requests = sum(self.request_counts.values())
        uptime = (datetime.utcnow() - self.start_time).total_seconds()
        
        avg_response_time = 0
        if self.response_times:
            avg_response_time = sum(self.response_times) / len(self.response_times)
        
        return {
            'total_requests': total_requests,
            'requests_per_second': total_requests / max(uptime, 1),
            'average_response_time': avg_response_time,
            'uptime_seconds': uptime
        }
    
    def _record_system_metrics(self):
        """Record system-level metrics."""
        # Record overall system health
        active_alerts = len(self.alert_manager.get_active_alerts())
        
        self.metric_collector.record_metric(
            "gateway_active_alerts",
            active_alerts,
            MetricType.GAUGE
        )
        
        # Record memory usage of collections
        self.metric_collector.record_metric(
            "gateway_log_entries",
            len(self.log_aggregator.log_entries),
            MetricType.GAUGE
        )
        
        self.metric_collector.record_metric(
            "gateway_metric_series",
            len(self.metric_collector.metrics),
            MetricType.GAUGE
        )
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive dashboard data."""
        # Recent metrics summaries
        metric_summaries = {}
        for metric_name in self.metric_collector.get_all_metrics():
            if any(key in metric_name for key in ['requests_total', 'response_time', 'errors_total']):
                metric_summaries[metric_name] = self.metric_collector.get_metric_summary(metric_name)
        
        # Recent logs
        recent_logs = self.log_aggregator.get_recent_logs(limit=50)
        
        # Error summary
        error_summary = self.log_aggregator.get_error_summary()
        
        # Active alerts
        active_alerts = [alert.to_dict() for alert in self.alert_manager.get_active_alerts()]
        
        # System info
        uptime = (datetime.utcnow() - self.start_time).total_seconds()
        
        return {
            'system': {
                'uptime_seconds': uptime,
                'start_time': self.start_time.isoformat(),
                'status': 'healthy' if len(active_alerts) == 0 else 'degraded'
            },
            'metrics': metric_summaries,
            'logs': {
                'recent_entries': recent_logs,
                'error_summary': error_summary
            },
            'alerts': {
                'active_alerts': active_alerts,
                'total_alerts': len(self.alert_manager.get_all_alerts())
            }
        }


# Global monitor instance
gateway_monitor = GatewayMonitor()