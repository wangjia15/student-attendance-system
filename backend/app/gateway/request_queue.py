"""
Request Queue System for API Gateway.

This module implements advanced request queuing and prioritization
for handling high-volume requests to SIS providers with proper
backpressure and flow control.
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Callable, Awaitable
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from collections import deque
import heapq
import json

from app.services.api_gateway import GatewayRequest, GatewayResponse


logger = logging.getLogger(__name__)


class RequestPriority(int, Enum):
    """Request priority levels."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class QueueStrategy(str, Enum):
    """Queue processing strategies."""
    FIFO = "fifo"
    PRIORITY = "priority"
    ROUND_ROBIN = "round_robin"
    WEIGHTED_FAIR = "weighted_fair"


@dataclass
class QueuedRequest:
    """A request in the queue with metadata."""
    request: GatewayRequest
    priority: RequestPriority = RequestPriority.NORMAL
    submitted_at: float = field(default_factory=time.time)
    timeout: float = 30.0
    retry_count: int = 0
    max_retries: int = 3
    callback: Optional[Callable[[GatewayResponse], Awaitable[None]]] = None
    future: Optional[asyncio.Future] = None
    queue_id: Optional[str] = None
    
    @property
    def age(self) -> float:
        """Get age of request in seconds."""
        return time.time() - self.submitted_at
    
    @property
    def is_expired(self) -> bool:
        """Check if request has expired."""
        return self.age > self.timeout
    
    @property
    def should_retry(self) -> bool:
        """Check if request should be retried."""
        return self.retry_count < self.max_retries
    
    def __lt__(self, other):
        """Comparison for priority queue (higher priority first, then older first)."""
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.submitted_at < other.submitted_at


@dataclass
class QueueMetrics:
    """Metrics for request queue performance."""
    total_queued: int = 0
    total_processed: int = 0
    total_failed: int = 0
    total_expired: int = 0
    total_retries: int = 0
    current_size: int = 0
    max_size_reached: int = 0
    average_wait_time: float = 0.0
    average_processing_time: float = 0.0
    
    def record_queued(self):
        """Record a request being queued."""
        self.total_queued += 1
        self.current_size += 1
        self.max_size_reached = max(self.max_size_reached, self.current_size)
    
    def record_processed(self, wait_time: float, processing_time: float, success: bool):
        """Record a request being processed."""
        self.total_processed += 1
        self.current_size = max(0, self.current_size - 1)
        
        if success:
            # Update rolling averages
            total_successful = self.total_processed - self.total_failed
            if total_successful == 1:
                self.average_wait_time = wait_time
                self.average_processing_time = processing_time
            else:
                self.average_wait_time = (
                    (self.average_wait_time * (total_successful - 1) + wait_time) / total_successful
                )
                self.average_processing_time = (
                    (self.average_processing_time * (total_successful - 1) + processing_time) / total_successful
                )
        else:
            self.total_failed += 1
    
    def record_expired(self):
        """Record a request expiring."""
        self.total_expired += 1
        self.current_size = max(0, self.current_size - 1)
    
    def record_retry(self):
        """Record a retry attempt."""
        self.total_retries += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        return {
            'total_queued': self.total_queued,
            'total_processed': self.total_processed,
            'total_failed': self.total_failed,
            'total_expired': self.total_expired,
            'total_retries': self.total_retries,
            'current_size': self.current_size,
            'max_size_reached': self.max_size_reached,
            'success_rate': (self.total_processed - self.total_failed) / max(self.total_processed, 1),
            'expiry_rate': self.total_expired / max(self.total_queued, 1),
            'average_wait_time': self.average_wait_time,
            'average_processing_time': self.average_processing_time
        }


class RequestQueue:
    """
    Advanced request queue with priority handling and flow control.
    
    Features:
    - Multiple queue strategies (FIFO, priority, weighted fair queuing)
    - Request prioritization and timeout handling
    - Automatic retries with exponential backoff
    - Flow control and backpressure management
    - Comprehensive metrics and monitoring
    """
    
    def __init__(
        self,
        max_size: int = 10000,
        strategy: QueueStrategy = QueueStrategy.PRIORITY,
        processor_count: int = 10,
        processor_callable: Optional[Callable[[GatewayRequest], Awaitable[GatewayResponse]]] = None,
        enable_metrics: bool = True
    ):
        self.max_size = max_size
        self.strategy = strategy
        self.processor_count = processor_count
        self.processor_callable = processor_callable
        self.enable_metrics = enable_metrics
        
        # Queue storage
        self._priority_queue: List[QueuedRequest] = []
        self._fifo_queue: deque[QueuedRequest] = deque()
        self._provider_queues: Dict[str, deque[QueuedRequest]] = {}
        
        # Processing state
        self._processors: List[asyncio.Task] = []
        self._stop_processing = False
        self._processing_semaphore = asyncio.Semaphore(processor_count)
        
        # Metrics
        self.metrics = QueueMetrics() if enable_metrics else None
        
        # Request tracking
        self._active_requests: Dict[str, QueuedRequest] = {}
        self._request_counter = 0
        
        logger.info(f"Request queue initialized: strategy={strategy}, max_size={max_size}")
    
    async def start(self):
        """Start queue processors."""
        self._stop_processing = False
        
        # Start processor tasks
        for i in range(self.processor_count):
            processor_task = asyncio.create_task(
                self._processor_worker(f"processor_{i}")
            )
            self._processors.append(processor_task)
        
        # Start cleanup task
        cleanup_task = asyncio.create_task(self._cleanup_expired_requests())
        self._processors.append(cleanup_task)
        
        logger.info(f"Started {self.processor_count} queue processors")
    
    async def stop(self):
        """Stop queue processors and cleanup."""
        self._stop_processing = True
        
        # Cancel all processor tasks
        for task in self._processors:
            task.cancel()
        
        # Wait for processors to finish
        if self._processors:
            await asyncio.gather(*self._processors, return_exceptions=True)
        
        # Cancel all pending requests
        await self._cancel_all_pending_requests()
        
        logger.info("Request queue stopped")
    
    async def enqueue(
        self,
        request: GatewayRequest,
        priority: RequestPriority = RequestPriority.NORMAL,
        timeout: float = 30.0,
        max_retries: int = 3,
        callback: Optional[Callable[[GatewayResponse], Awaitable[None]]] = None
    ) -> str:
        """
        Enqueue a request for processing.
        
        Returns:
            Request ID for tracking
            
        Raises:
            asyncio.QueueFull: When queue is at capacity
        """
        if self._is_queue_full():
            raise asyncio.QueueFull("Request queue is at maximum capacity")
        
        # Generate unique request ID
        self._request_counter += 1
        request_id = f"req_{self._request_counter}_{int(time.time() * 1000000)}"
        
        # Create queued request
        queued_request = QueuedRequest(
            request=request,
            priority=priority,
            timeout=timeout,
            max_retries=max_retries,
            callback=callback,
            future=asyncio.Future(),
            queue_id=request_id
        )
        
        # Add to appropriate queue
        await self._add_to_queue(queued_request)
        
        # Track active request
        self._active_requests[request_id] = queued_request
        
        # Record metrics
        if self.metrics:
            self.metrics.record_queued()
        
        logger.debug(f"Enqueued request {request_id} with priority {priority}")
        return request_id
    
    async def enqueue_and_wait(
        self,
        request: GatewayRequest,
        priority: RequestPriority = RequestPriority.NORMAL,
        timeout: float = 30.0,
        max_retries: int = 3
    ) -> GatewayResponse:
        """
        Enqueue a request and wait for the response.
        
        Returns:
            Gateway response
            
        Raises:
            asyncio.TimeoutError: When request times out
            Exception: Any processing error
        """
        request_id = await self.enqueue(
            request=request,
            priority=priority,
            timeout=timeout,
            max_retries=max_retries
        )
        
        queued_request = self._active_requests.get(request_id)
        if not queued_request or not queued_request.future:
            raise RuntimeError(f"Failed to track request {request_id}")
        
        try:
            # Wait for processing to complete
            response = await asyncio.wait_for(
                queued_request.future,
                timeout=timeout
            )
            return response
            
        except asyncio.TimeoutError:
            # Clean up timed out request
            await self._cleanup_request(request_id, "timeout")
            raise
        
        finally:
            # Remove from active requests
            self._active_requests.pop(request_id, None)
    
    async def cancel_request(self, request_id: str) -> bool:
        """Cancel a queued request."""
        queued_request = self._active_requests.get(request_id)
        if not queued_request:
            return False
        
        # Cancel the future
        if queued_request.future and not queued_request.future.done():
            queued_request.future.cancel()
        
        # Remove from queues
        await self._remove_from_queue(queued_request)
        
        # Clean up
        self._active_requests.pop(request_id, None)
        
        logger.debug(f"Cancelled request {request_id}")
        return True
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status and metrics."""
        status = {
            'strategy': self.strategy,
            'max_size': self.max_size,
            'processor_count': self.processor_count,
            'active_processors': len([p for p in self._processors if not p.done()]),
            'queue_sizes': self._get_queue_sizes(),
            'active_requests': len(self._active_requests)
        }
        
        if self.metrics:
            status['metrics'] = self.metrics.get_stats()
        
        return status
    
    def _is_queue_full(self) -> bool:
        """Check if queue is at capacity."""
        total_size = (
            len(self._priority_queue) + 
            len(self._fifo_queue) + 
            sum(len(q) for q in self._provider_queues.values())
        )
        return total_size >= self.max_size
    
    async def _add_to_queue(self, queued_request: QueuedRequest):
        """Add request to appropriate queue based on strategy."""
        if self.strategy == QueueStrategy.PRIORITY:
            heapq.heappush(self._priority_queue, queued_request)
        
        elif self.strategy == QueueStrategy.FIFO:
            self._fifo_queue.append(queued_request)
        
        elif self.strategy in (QueueStrategy.ROUND_ROBIN, QueueStrategy.WEIGHTED_FAIR):
            provider = queued_request.request.provider.value
            if provider not in self._provider_queues:
                self._provider_queues[provider] = deque()
            self._provider_queues[provider].append(queued_request)
        
        else:
            # Default to FIFO
            self._fifo_queue.append(queued_request)
    
    async def _remove_from_queue(self, queued_request: QueuedRequest) -> bool:
        """Remove request from queue."""
        try:
            if self.strategy == QueueStrategy.PRIORITY:
                self._priority_queue.remove(queued_request)
                heapq.heapify(self._priority_queue)
                return True
            
            elif self.strategy == QueueStrategy.FIFO:
                self._fifo_queue.remove(queued_request)
                return True
            
            elif self.strategy in (QueueStrategy.ROUND_ROBIN, QueueStrategy.WEIGHTED_FAIR):
                provider = queued_request.request.provider.value
                if provider in self._provider_queues:
                    self._provider_queues[provider].remove(queued_request)
                    return True
            
        except ValueError:
            pass  # Request not found in queue
        
        return False
    
    async def _get_next_request(self) -> Optional[QueuedRequest]:
        """Get next request based on queue strategy."""
        if self.strategy == QueueStrategy.PRIORITY:
            if self._priority_queue:
                return heapq.heappop(self._priority_queue)
        
        elif self.strategy == QueueStrategy.FIFO:
            if self._fifo_queue:
                return self._fifo_queue.popleft()
        
        elif self.strategy == QueueStrategy.ROUND_ROBIN:
            return self._round_robin_selection()
        
        elif self.strategy == QueueStrategy.WEIGHTED_FAIR:
            return self._weighted_fair_selection()
        
        return None
    
    def _round_robin_selection(self) -> Optional[QueuedRequest]:
        """Round-robin selection from provider queues."""
        if not self._provider_queues:
            return None
        
        # Find non-empty queues
        non_empty_queues = [
            (provider, queue) 
            for provider, queue in self._provider_queues.items() 
            if queue
        ]
        
        if not non_empty_queues:
            return None
        
        # Simple round-robin (could be improved with state tracking)
        provider, queue = non_empty_queues[0]
        return queue.popleft()
    
    def _weighted_fair_selection(self) -> Optional[QueuedRequest]:
        """Weighted fair selection based on provider priority."""
        # For now, implement as round-robin with priority consideration
        # TODO: Implement proper weighted fair queuing
        priority_requests = []
        
        for provider, queue in self._provider_queues.items():
            if queue:
                request = queue[0]  # Peek at first request
                priority_requests.append((request.priority, provider, queue))
        
        if not priority_requests:
            return None
        
        # Sort by priority and select highest
        priority_requests.sort(key=lambda x: x[0], reverse=True)
        _, _, selected_queue = priority_requests[0]
        
        return selected_queue.popleft()
    
    async def _processor_worker(self, worker_id: str):
        """Background worker to process queued requests."""
        logger.debug(f"Queue processor {worker_id} started")
        
        while not self._stop_processing:
            try:
                # Get next request
                queued_request = await self._get_next_request()
                
                if not queued_request:
                    # No requests available, wait a bit
                    await asyncio.sleep(0.1)
                    continue
                
                # Check if request has expired
                if queued_request.is_expired:
                    await self._handle_expired_request(queued_request)
                    continue
                
                # Acquire processing semaphore
                async with self._processing_semaphore:
                    await self._process_request(queued_request, worker_id)
                
            except Exception as e:
                logger.error(f"Error in queue processor {worker_id}: {e}")
                await asyncio.sleep(1.0)  # Brief pause on error
        
        logger.debug(f"Queue processor {worker_id} stopped")
    
    async def _process_request(self, queued_request: QueuedRequest, worker_id: str):
        """Process a single request."""
        start_time = time.time()
        wait_time = start_time - queued_request.submitted_at
        
        try:
            # Process the request
            if self.processor_callable:
                response = await self.processor_callable(queued_request.request)
            else:
                # Default processing (should not happen in production)
                response = GatewayResponse(
                    status_code=500,
                    data={"error": "No processor configured"},
                    headers={},
                    duration=0.0,
                    provider=queued_request.request.provider,
                    success=False,
                    error="No processor configured"
                )
            
            processing_time = time.time() - start_time
            
            # Handle successful processing
            if response.success:
                await self._handle_successful_request(
                    queued_request, response, wait_time, processing_time
                )
            else:
                await self._handle_failed_request(
                    queued_request, response, wait_time, processing_time
                )
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Error processing request in {worker_id}: {e}")
            
            # Create error response
            error_response = GatewayResponse(
                status_code=500,
                data={"error": str(e)},
                headers={},
                duration=processing_time,
                provider=queued_request.request.provider,
                success=False,
                error=str(e)
            )
            
            await self._handle_failed_request(
                queued_request, error_response, wait_time, processing_time
            )
    
    async def _handle_successful_request(
        self, 
        queued_request: QueuedRequest, 
        response: GatewayResponse,
        wait_time: float,
        processing_time: float
    ):
        """Handle successful request completion."""
        # Record metrics
        if self.metrics:
            self.metrics.record_processed(wait_time, processing_time, True)
        
        # Complete the future
        if queued_request.future and not queued_request.future.done():
            queued_request.future.set_result(response)
        
        # Call callback if provided
        if queued_request.callback:
            try:
                await queued_request.callback(response)
            except Exception as e:
                logger.error(f"Error in request callback: {e}")
        
        # Clean up
        if queued_request.queue_id:
            self._active_requests.pop(queued_request.queue_id, None)
    
    async def _handle_failed_request(
        self, 
        queued_request: QueuedRequest, 
        response: GatewayResponse,
        wait_time: float,
        processing_time: float
    ):
        """Handle failed request with potential retry."""
        # Check if should retry
        if queued_request.should_retry:
            queued_request.retry_count += 1
            
            # Record retry
            if self.metrics:
                self.metrics.record_retry()
            
            # Re-queue with exponential backoff delay
            delay = min(2.0 ** queued_request.retry_count, 30.0)  # Max 30 second delay
            
            logger.debug(
                f"Retrying request {queued_request.queue_id} "
                f"(attempt {queued_request.retry_count}) after {delay}s"
            )
            
            # Schedule retry
            asyncio.create_task(self._schedule_retry(queued_request, delay))
            
        else:
            # Max retries reached, fail the request
            if self.metrics:
                self.metrics.record_processed(wait_time, processing_time, False)
            
            if queued_request.future and not queued_request.future.done():
                queued_request.future.set_result(response)
            
            # Call callback if provided
            if queued_request.callback:
                try:
                    await queued_request.callback(response)
                except Exception as e:
                    logger.error(f"Error in request callback: {e}")
            
            # Clean up
            if queued_request.queue_id:
                self._active_requests.pop(queued_request.queue_id, None)
    
    async def _schedule_retry(self, queued_request: QueuedRequest, delay: float):
        """Schedule a request retry after delay."""
        await asyncio.sleep(delay)
        
        # Check if request is still active (not cancelled)
        if (
            queued_request.queue_id and 
            queued_request.queue_id in self._active_requests and
            not queued_request.is_expired
        ):
            # Reset submission time for timeout calculation
            queued_request.submitted_at = time.time()
            
            # Re-queue the request
            await self._add_to_queue(queued_request)
    
    async def _handle_expired_request(self, queued_request: QueuedRequest):
        """Handle an expired request."""
        if self.metrics:
            self.metrics.record_expired()
        
        # Create timeout response
        timeout_response = GatewayResponse(
            status_code=408,
            data={"error": "Request timeout"},
            headers={},
            duration=queued_request.age,
            provider=queued_request.request.provider,
            success=False,
            error="Request timeout"
        )
        
        # Complete the future
        if queued_request.future and not queued_request.future.done():
            queued_request.future.set_result(timeout_response)
        
        # Call callback if provided
        if queued_request.callback:
            try:
                await queued_request.callback(timeout_response)
            except Exception as e:
                logger.error(f"Error in request callback: {e}")
        
        # Clean up
        if queued_request.queue_id:
            self._active_requests.pop(queued_request.queue_id, None)
        
        logger.warning(f"Request {queued_request.queue_id} expired after {queued_request.age:.2f}s")
    
    async def _cleanup_expired_requests(self):
        """Background task to cleanup expired requests."""
        while not self._stop_processing:
            try:
                expired_request_ids = []
                
                # Find expired requests
                for request_id, queued_request in self._active_requests.items():
                    if queued_request.is_expired:
                        expired_request_ids.append(request_id)
                
                # Handle expired requests
                for request_id in expired_request_ids:
                    queued_request = self._active_requests.get(request_id)
                    if queued_request:
                        await self._remove_from_queue(queued_request)
                        await self._handle_expired_request(queued_request)
                
                # Sleep before next cleanup cycle
                await asyncio.sleep(10)  # Cleanup every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in request cleanup task: {e}")
                await asyncio.sleep(5)
    
    async def _cancel_all_pending_requests(self):
        """Cancel all pending requests during shutdown."""
        for queued_request in self._active_requests.values():
            if queued_request.future and not queued_request.future.done():
                queued_request.future.cancel()
        
        self._active_requests.clear()
    
    async def _cleanup_request(self, request_id: str, reason: str):
        """Cleanup a specific request."""
        queued_request = self._active_requests.get(request_id)
        if queued_request:
            await self._remove_from_queue(queued_request)
            self._active_requests.pop(request_id, None)
            
            logger.debug(f"Cleaned up request {request_id}: {reason}")
    
    def _get_queue_sizes(self) -> Dict[str, int]:
        """Get sizes of all queues."""
        sizes = {
            'priority_queue': len(self._priority_queue),
            'fifo_queue': len(self._fifo_queue)
        }
        
        for provider, queue in self._provider_queues.items():
            sizes[f'provider_{provider}'] = len(queue)
        
        return sizes