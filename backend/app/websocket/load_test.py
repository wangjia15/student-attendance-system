"""
Load testing script for WebSocket server.
Tests concurrent connections, message throughput, and latency.
"""
import asyncio
import json
import time
import statistics
from datetime import datetime, timezone
from typing import List, Dict, Any
import websockets
from concurrent.futures import ThreadPoolExecutor
import logging

from ..core.security import jwt_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebSocketLoadTester:
    """Load testing utility for WebSocket server."""
    
    def __init__(self, server_url: str = "ws://localhost:8000"):
        self.server_url = server_url
        self.connections = []
        self.test_results = {
            'connection_times': [],
            'message_latencies': [],
            'failed_connections': 0,
            'failed_messages': 0,
            'total_messages_sent': 0,
            'total_messages_received': 0
        }
    
    async def create_test_connection(self, connection_id: str, class_id: str = "test_class") -> bool:
        """Create a single test WebSocket connection."""
        try:
            start_time = time.time()
            
            # Create JWT token for authentication
            token = jwt_manager.create_class_session_token(
                class_id=class_id,
                teacher_id=f"test_teacher_{connection_id}",
                expiration_minutes=60
            )
            
            # Connect to WebSocket
            uri = f"{self.server_url}/ws/v2/{connection_id}"
            websocket = await websockets.connect(uri)
            
            connection_time = time.time() - start_time
            self.test_results['connection_times'].append(connection_time)
            
            # Send authentication message
            auth_message = {
                "type": "auth",
                "data": {
                    "token": token,
                    "class_id": class_id
                }
            }
            
            await websocket.send(json.dumps(auth_message))
            
            # Wait for auth response
            response = await websocket.recv()
            response_data = json.loads(response)
            
            if response_data.get('type') != 'auth_success':
                logger.error(f"Authentication failed for {connection_id}: {response_data}")
                await websocket.close()
                self.test_results['failed_connections'] += 1
                return False
            
            self.connections.append(websocket)
            logger.info(f"Connected {connection_id} in {connection_time:.3f}s")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect {connection_id}: {e}")
            self.test_results['failed_connections'] += 1
            return False
    
    async def send_test_message(self, websocket, message_type: str = "ping") -> float:
        """Send a test message and measure latency."""
        try:
            start_time = time.time()
            
            message = {
                "type": message_type,
                "data": {
                    "timestamp": start_time,
                    "test_data": "load_test_message"
                }
            }
            
            await websocket.send(json.dumps(message))
            self.test_results['total_messages_sent'] += 1
            
            # Wait for response
            response = await websocket.recv()
            end_time = time.time()
            
            latency = end_time - start_time
            self.test_results['message_latencies'].append(latency)
            self.test_results['total_messages_received'] += 1
            
            return latency
            
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            self.test_results['failed_messages'] += 1
            return -1
    
    async def create_concurrent_connections(self, num_connections: int, class_id: str = "test_class"):
        """Create multiple concurrent WebSocket connections."""
        logger.info(f"Creating {num_connections} concurrent connections...")
        
        # Create connection tasks
        tasks = [
            self.create_test_connection(f"test_conn_{i}", class_id)
            for i in range(num_connections)
        ]
        
        # Execute connections concurrently with batching to avoid overwhelming server
        batch_size = 50
        successful_connections = 0
        
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            results = await asyncio.gather(*batch, return_exceptions=True)
            
            successful_connections += sum(1 for result in results if result is True)
            
            # Brief pause between batches
            await asyncio.sleep(0.1)
        
        logger.info(f"Successfully connected {successful_connections}/{num_connections} connections")
        return successful_connections
    
    async def measure_message_throughput(self, duration_seconds: int = 30):
        """Measure message throughput across all connections."""
        if not self.connections:
            logger.error("No active connections for throughput test")
            return
        
        logger.info(f"Starting {duration_seconds}s throughput test with {len(self.connections)} connections...")
        
        start_time = time.time()
        end_time = start_time + duration_seconds
        
        async def send_messages_continuously(websocket):
            """Send messages continuously from a single connection."""
            message_count = 0
            while time.time() < end_time:
                await self.send_test_message(websocket, "ping")
                message_count += 1
                await asyncio.sleep(0.1)  # 10 messages per second per connection
            return message_count
        
        # Start all connections sending messages
        tasks = [send_messages_continuously(ws) for ws in self.connections]
        message_counts = await asyncio.gather(*tasks, return_exceptions=True)
        
        total_messages = sum(count for count in message_counts if isinstance(count, int))
        throughput = total_messages / duration_seconds
        
        logger.info(f"Throughput test complete: {total_messages} messages in {duration_seconds}s ({throughput:.1f} msg/s)")
        return throughput
    
    async def close_all_connections(self):
        """Close all active WebSocket connections."""
        logger.info(f"Closing {len(self.connections)} connections...")
        
        close_tasks = []
        for websocket in self.connections:
            try:
                close_tasks.append(websocket.close())
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
        
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        
        self.connections.clear()
        logger.info("All connections closed")
    
    def get_test_summary(self) -> Dict[str, Any]:
        """Get comprehensive test results summary."""
        connection_times = self.test_results['connection_times']
        latencies = self.test_results['message_latencies']
        
        return {
            "connections": {
                "total_attempted": len(connection_times) + self.test_results['failed_connections'],
                "successful": len(connection_times),
                "failed": self.test_results['failed_connections'],
                "success_rate": len(connection_times) / (len(connection_times) + self.test_results['failed_connections']) * 100 if connection_times else 0,
                "avg_connection_time": statistics.mean(connection_times) if connection_times else 0,
                "max_connection_time": max(connection_times) if connection_times else 0
            },
            "messages": {
                "sent": self.test_results['total_messages_sent'],
                "received": self.test_results['total_messages_received'],
                "failed": self.test_results['failed_messages'],
                "success_rate": (self.test_results['total_messages_received'] / self.test_results['total_messages_sent'] * 100) if self.test_results['total_messages_sent'] else 0
            },
            "latency": {
                "count": len(latencies),
                "avg_ms": statistics.mean(latencies) * 1000 if latencies else 0,
                "min_ms": min(latencies) * 1000 if latencies else 0,
                "max_ms": max(latencies) * 1000 if latencies else 0,
                "p95_ms": statistics.quantiles(latencies, n=20)[18] * 1000 if len(latencies) >= 20 else 0,
                "p99_ms": statistics.quantiles(latencies, n=100)[98] * 1000 if len(latencies) >= 100 else 0
            }
        }


async def run_full_load_test():
    """Run comprehensive load test suite."""
    tester = WebSocketLoadTester()
    
    try:
        logger.info("Starting WebSocket load test suite...")
        
        # Test 1: Connection scalability (gradually increase connections)
        for connection_count in [100, 500, 1000, 1500]:
            logger.info(f"\n=== Testing {connection_count} concurrent connections ===")
            
            # Close previous connections
            await tester.close_all_connections()
            tester.connections.clear()
            
            # Create connections
            successful = await tester.create_concurrent_connections(connection_count)
            
            if successful < connection_count * 0.9:  # Less than 90% success
                logger.warning(f"Poor connection success rate: {successful}/{connection_count}")
                break
            
            # Test message latency with current connection count
            if tester.connections:
                logger.info("Testing message latency...")
                sample_size = min(10, len(tester.connections))
                latency_tasks = [
                    tester.send_test_message(tester.connections[i])
                    for i in range(sample_size)
                ]
                
                latencies = await asyncio.gather(*latency_tasks, return_exceptions=True)
                avg_latency = statistics.mean([l for l in latencies if isinstance(l, (int, float)) and l > 0])
                
                logger.info(f"Average message latency: {avg_latency * 1000:.1f}ms")
                
                # Check if latency is acceptable (<100ms requirement)
                if avg_latency > 0.1:
                    logger.warning(f"High latency detected: {avg_latency * 1000:.1f}ms")
            
            # Brief pause between tests
            await asyncio.sleep(2)
        
        # Test 2: Sustained throughput test with maximum successful connections
        if tester.connections:
            logger.info(f"\n=== Throughput test with {len(tester.connections)} connections ===")
            throughput = await tester.measure_message_throughput(30)
            logger.info(f"Sustained throughput: {throughput:.1f} messages/second")
        
        # Generate final report
        summary = tester.get_test_summary()
        logger.info(f"\n=== LOAD TEST SUMMARY ===")
        logger.info(f"Connection Success Rate: {summary['connections']['success_rate']:.1f}%")
        logger.info(f"Average Connection Time: {summary['connections']['avg_connection_time'] * 1000:.1f}ms")
        logger.info(f"Message Success Rate: {summary['messages']['success_rate']:.1f}%")
        logger.info(f"Average Message Latency: {summary['latency']['avg_ms']:.1f}ms")
        logger.info(f"95th Percentile Latency: {summary['latency']['p95_ms']:.1f}ms")
        
        # Check if requirements are met
        requirements_met = (
            summary['connections']['success_rate'] >= 95 and
            summary['latency']['avg_ms'] < 100 and
            summary['latency']['p95_ms'] < 200
        )
        
        logger.info(f"Performance Requirements Met: {'YES' if requirements_met else 'NO'}")
        
        return summary
        
    except Exception as e:
        logger.error(f"Load test failed: {e}")
        raise
    finally:
        await tester.close_all_connections()


if __name__ == "__main__":
    asyncio.run(run_full_load_test())