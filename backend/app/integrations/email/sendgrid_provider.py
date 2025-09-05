"""SendGrid email provider implementation."""

import logging
import asyncio
import base64
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

import aiohttp

from app.core.config import settings
from .email_service import BaseEmailProvider, EmailMessage, EmailDeliveryResult

logger = logging.getLogger(__name__)


class SendGridProvider(BaseEmailProvider):
    """SendGrid email provider implementation."""
    
    def __init__(self):
        # SendGrid configuration
        self.api_key = getattr(settings, 'SENDGRID_API_KEY', '')
        self.api_url = 'https://api.sendgrid.com/v3/mail/send'
        
        # Default sender information
        self.default_from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
        self.default_from_name = getattr(settings, 'DEFAULT_FROM_NAME', 'Student Attendance System')
        
        # Rate limiting configuration
        self.rate_limit_per_second = getattr(settings, 'SENDGRID_RATE_LIMIT_PER_SECOND', 10)
        
        # Tracking for rate limiting
        self._requests_this_second = []
        
        logger.info("SendGrid provider initialized")
    
    def is_available(self) -> bool:
        """Check if SendGrid is properly configured."""
        return bool(self.api_key and self.default_from_email)
    
    async def send_email(self, message: EmailMessage) -> EmailDeliveryResult:
        """Send a single email via SendGrid."""
        if not self.is_available():
            return EmailDeliveryResult(
                success=False,
                error_code="NOT_CONFIGURED",
                error_message="SendGrid is not properly configured",
                to_email=message.to_email
            )
        
        # Rate limiting check
        if not await self._check_rate_limit():
            return EmailDeliveryResult(
                success=False,
                error_code="RATE_LIMITED",
                error_message="Rate limit exceeded",
                to_email=message.to_email
            )
        
        try:
            # Create SendGrid request payload
            payload = await self._create_sendgrid_payload(message)
            
            # Send email via SendGrid API
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                }
                
                async with session.post(self.api_url, json=payload, headers=headers) as response:
                    response_text = await response.text()
                    
                    if response.status == 202:  # SendGrid returns 202 for successful sends
                        # Track request for rate limiting
                        await self._track_request()
                        
                        # SendGrid doesn't return message ID in response body for single sends
                        # Message ID would be in X-Message-Id header if available
                        message_id = response.headers.get('X-Message-Id', '')
                        
                        return EmailDeliveryResult(
                            success=True,
                            message_id=message_id,
                            provider_response={
                                "status_code": response.status,
                                "headers": dict(response.headers),
                                "response": response_text
                            },
                            to_email=message.to_email
                        )
                    else:
                        try:
                            error_data = await response.json() if response_text else {}
                        except:
                            error_data = {"message": response_text}
                        
                        return EmailDeliveryResult(
                            success=False,
                            error_code=str(response.status),
                            error_message=error_data.get('message', f'HTTP {response.status}'),
                            provider_response=error_data,
                            to_email=message.to_email
                        )
        
        except aiohttp.ClientError as e:
            logger.error(f"SendGrid HTTP error: {e}")
            return EmailDeliveryResult(
                success=False,
                error_code="HTTP_ERROR",
                error_message=str(e),
                to_email=message.to_email
            )
        except Exception as e:
            logger.error(f"SendGrid email error: {e}")
            return EmailDeliveryResult(
                success=False,
                error_code="SEND_ERROR",
                error_message=str(e),
                to_email=message.to_email
            )
    
    async def send_bulk_email(self, messages: List[EmailMessage]) -> List[EmailDeliveryResult]:
        """Send multiple emails via SendGrid."""
        if not messages:
            return []
        
        if not self.is_available():
            return [
                EmailDeliveryResult(
                    success=False,
                    error_code="NOT_CONFIGURED",
                    error_message="SendGrid is not properly configured",
                    to_email=msg.to_email
                ) for msg in messages
            ]
        
        # SendGrid supports bulk sending, but we'll implement it as concurrent individual sends
        # for better error handling and rate limit management
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
    
    async def _send_batch(self, batch: List[EmailMessage]) -> List[EmailDeliveryResult]:
        """Send a batch of emails concurrently."""
        tasks = [self.send_email(message) for message in batch]
        return await asyncio.gather(*tasks, return_exceptions=False)
    
    async def _create_sendgrid_payload(self, message: EmailMessage) -> Dict[str, Any]:
        """Create SendGrid API payload from EmailMessage."""
        # Determine sender information
        from_email = message.from_email or self.default_from_email
        from_name = message.from_name or self.default_from_name
        
        # Base payload
        payload = {
            "from": {
                "email": from_email,
                "name": from_name
            },
            "personalizations": [
                {
                    "to": [{"email": message.to_email}],
                    "subject": message.subject
                }
            ]
        }
        
        # Add reply-to if specified
        if message.reply_to:
            payload["reply_to"] = {"email": message.reply_to}
        
        # Add CC recipients
        if message.cc:
            payload["personalizations"][0]["cc"] = [{"email": email} for email in message.cc]
        
        # Add BCC recipients
        if message.bcc:
            payload["personalizations"][0]["bcc"] = [{"email": email} for email in message.bcc]
        
        # Add content
        content = []
        if message.text_content:
            content.append({
                "type": "text/plain",
                "value": message.text_content
            })
        
        if message.html_content:
            content.append({
                "type": "text/html",
                "value": message.html_content
            })
        
        payload["content"] = content
        
        # Add attachments
        if message.attachments:
            attachments = []
            for attachment in message.attachments:
                attachments.append({
                    "content": base64.b64encode(attachment.content).decode(),
                    "filename": attachment.filename,
                    "type": attachment.content_type,
                    "disposition": "attachment"
                })
            payload["attachments"] = attachments
        
        # Add custom headers for tracking
        payload["headers"] = {
            "X-Entity-ID": str(message.notification_id) if message.notification_id else "",
            "X-Priority": message.priority
        }
        
        # Add tracking settings
        payload["tracking_settings"] = {
            "click_tracking": {"enable": True},
            "open_tracking": {"enable": True}
        }
        
        return payload
    
    async def get_delivery_status(self, message_id: str) -> Dict[str, Any]:
        """Get delivery status from SendGrid."""
        if not self.is_available():
            return {
                "success": False,
                "error": "SendGrid is not properly configured"
            }
        
        try:
            # SendGrid Activity API requires different endpoint and permissions
            # For basic implementation, we'll return success
            # In production, you would implement the Activity API integration
            return {
                "success": True,
                "status": "sent",
                "message": "SendGrid delivery status requires Activity API integration",
                "message_id": message_id
            }
        
        except Exception as e:
            logger.error(f"Error getting SendGrid delivery status: {e}")
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
            "provider": "sendgrid",
            "requests_this_second": len(recent_requests),
            "limit_per_second": self.rate_limit_per_second,
            "seconds_until_reset": 1
        }