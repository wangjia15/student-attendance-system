"""AWS SNS SMS provider implementation."""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError

from app.core.config import settings
from .sms_service import BaseSMSProvider, SMSMessage, SMSDeliveryResult

logger = logging.getLogger(__name__)


class AWSSNSProvider(BaseSMSProvider):
    """AWS SNS SMS provider implementation."""
    
    def __init__(self):
        # AWS configuration
        self.region = getattr(settings, 'AWS_SNS_REGION', 'us-east-1')
        self.access_key_id = getattr(settings, 'AWS_ACCESS_KEY_ID', '')
        self.secret_access_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', '')
        self.sender_id = getattr(settings, 'AWS_SNS_SENDER_ID', 'Attendance')
        
        # Rate limiting configuration
        self.rate_limit_per_second = getattr(settings, 'AWS_SNS_RATE_LIMIT_PER_SECOND', 20)
        
        # Tracking for rate limiting
        self._requests_this_second = []
        
        # Initialize SNS client
        self._client = None
        self._initialize_client()
        
        logger.info("AWS SNS provider initialized")
    
    def _initialize_client(self):
        """Initialize AWS SNS client."""
        try:
            session_kwargs = {
                'region_name': self.region
            }
            
            # Use explicit credentials if provided
            if self.access_key_id and self.secret_access_key:
                session_kwargs.update({
                    'aws_access_key_id': self.access_key_id,
                    'aws_secret_access_key': self.secret_access_key
                })
            
            self._client = boto3.client('sns', **session_kwargs)
            
            # Test client with a simple operation
            self._client.get_account_id()
            
        except (NoCredentialsError, ClientError, BotoCoreError) as e:
            logger.error(f"Error initializing AWS SNS client: {e}")
            self._client = None
    
    def is_available(self) -> bool:
        """Check if AWS SNS is properly configured."""
        return self._client is not None
    
    async def send_sms(self, message: SMSMessage) -> SMSDeliveryResult:
        """Send a single SMS via AWS SNS."""
        if not self.is_available():
            return SMSDeliveryResult(
                success=False,
                error_code="NOT_CONFIGURED",
                error_message="AWS SNS is not properly configured",
                phone_number=message.phone_number
            )
        
        # Rate limiting check
        if not await self._check_rate_limit():
            return SMSDeliveryResult(
                success=False,
                error_code="RATE_LIMITED",
                error_message="Rate limit exceeded",
                phone_number=message.phone_number
            )
        
        try:
            # Prepare message attributes
            message_attributes = {
                'AWS.SNS.SMS.SenderID': {
                    'DataType': 'String',
                    'StringValue': self.sender_id
                },
                'AWS.SNS.SMS.SMSType': {
                    'DataType': 'String',
                    'StringValue': 'Promotional' if message.priority == 'normal' else 'Transactional'
                }
            }
            
            # Set max price based on priority
            if message.priority == "urgent":
                message_attributes['AWS.SNS.SMS.MaxPrice'] = {
                    'DataType': 'Number',
                    'StringValue': '1.00'  # Higher cost limit for urgent messages
                }
            elif message.priority == "high":
                message_attributes['AWS.SNS.SMS.MaxPrice'] = {
                    'DataType': 'Number',
                    'StringValue': '0.50'
                }
            else:
                message_attributes['AWS.SNS.SMS.MaxPrice'] = {
                    'DataType': 'Number',
                    'StringValue': '0.10'
                }
            
            # Run SNS call in thread to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.publish(
                    PhoneNumber=message.phone_number,
                    Message=message.message,
                    MessageAttributes=message_attributes
                )
            )
            
            # Track request for rate limiting
            await self._track_request()
            
            return SMSDeliveryResult(
                success=True,
                message_id=response.get('MessageId'),
                provider_response=response,
                phone_number=message.phone_number
            )
        
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            logger.error(f"AWS SNS ClientError: {error_code} - {error_message}")
            
            return SMSDeliveryResult(
                success=False,
                error_code=error_code,
                error_message=error_message,
                provider_response=e.response,
                phone_number=message.phone_number
            )
        
        except Exception as e:
            logger.error(f"AWS SNS SMS error: {e}")
            return SMSDeliveryResult(
                success=False,
                error_code="UNKNOWN_ERROR",
                error_message=str(e),
                phone_number=message.phone_number
            )
    
    async def send_bulk_sms(self, messages: List[SMSMessage]) -> List[SMSDeliveryResult]:
        """Send multiple SMS messages via AWS SNS."""
        if not messages:
            return []
        
        if not self.is_available():
            return [
                SMSDeliveryResult(
                    success=False,
                    error_code="NOT_CONFIGURED",
                    error_message="AWS SNS is not properly configured",
                    phone_number=msg.phone_number
                ) for msg in messages
            ]
        
        # AWS SNS doesn't have a bulk send API, so we send individually
        # but we can do it concurrently in batches
        results = []
        batch_size = min(self.rate_limit_per_second, 10)  # Conservative batch size
        
        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]
            batch_results = await self._send_batch(batch)
            results.extend(batch_results)
            
            # Add delay between batches if needed
            if i + batch_size < len(messages):
                await asyncio.sleep(1)  # 1 second delay between batches
        
        return results
    
    async def _send_batch(self, batch: List[SMSMessage]) -> List[SMSDeliveryResult]:
        """Send a batch of SMS messages concurrently."""
        tasks = [self.send_sms(message) for message in batch]
        return await asyncio.gather(*tasks, return_exceptions=False)
    
    async def get_delivery_status(self, message_id: str) -> Dict[str, Any]:
        """Get delivery status from AWS SNS."""
        if not self.is_available():
            return {
                "success": False,
                "error": "AWS SNS is not properly configured"
            }
        
        try:
            # AWS SNS doesn't provide direct delivery status checking
            # We would need to set up SNS delivery status logging to CloudWatch
            # or use SNS delivery status features with additional setup
            
            # For now, return a basic success response
            # In a production environment, you would implement CloudWatch integration
            return {
                "success": True,
                "status": "unknown",
                "message": "AWS SNS delivery status requires CloudWatch integration",
                "message_id": message_id
            }
        
        except Exception as e:
            logger.error(f"Error getting AWS SNS delivery status: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _check_rate_limit(self) -> bool:
        """Check if request is within rate limits."""
        now = datetime.now()
        
        # Clean up old requests
        self._requests_this_second = [
            req_time for req_time in self._requests_this_second
            if now - req_time <= timedelta(seconds=1)
        ]
        
        # Check limits
        if len(self._requests_this_second) >= self.rate_limit_per_second:
            return False
        
        return True
    
    async def _track_request(self):
        """Track a request for rate limiting purposes."""
        now = datetime.now()
        self._requests_this_second.append(now)
    
    def get_rate_limit_info(self) -> Dict[str, Any]:
        """Get current rate limiting information."""
        now = datetime.now()
        
        # Clean up old requests
        recent_requests = [
            req_time for req_time in self._requests_this_second
            if now - req_time <= timedelta(seconds=1)
        ]
        
        return {
            "provider": "aws_sns",
            "requests_this_second": len(recent_requests),
            "limit_per_second": self.rate_limit_per_second,
            "seconds_until_reset": 1
        }