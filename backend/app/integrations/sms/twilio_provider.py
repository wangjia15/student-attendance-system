"""Twilio SMS provider implementation."""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

import aiohttp
import base64
from urllib.parse import urlencode

from app.core.config import settings
from .sms_service import BaseSMSProvider, SMSMessage, SMSDeliveryResult

logger = logging.getLogger(__name__)


class TwilioSMSProvider(BaseSMSProvider):
    """Twilio SMS provider implementation."""
    
    def __init__(self):
        self.account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
        self.auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
        self.from_number = getattr(settings, 'TWILIO_FROM_NUMBER', '')
        self.webhook_url = getattr(settings, 'TWILIO_WEBHOOK_URL', None)
        
        # Rate limiting configuration
        self.rate_limit_per_second = getattr(settings, 'TWILIO_RATE_LIMIT_PER_SECOND', 10)
        self.rate_limit_per_minute = getattr(settings, 'TWILIO_RATE_LIMIT_PER_MINUTE', 60)
        
        # Tracking for rate limiting
        self._requests_this_second = []
        self._requests_this_minute = []
        
        # Base API URL
        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}"
        
        logger.info("Twilio SMS provider initialized")
    
    def is_available(self) -> bool:
        """Check if Twilio is properly configured."""
        return bool(self.account_sid and self.auth_token and self.from_number)
    
    async def send_sms(self, message: SMSMessage) -> SMSDeliveryResult:
        """Send a single SMS via Twilio."""
        if not self.is_available():
            return SMSDeliveryResult(
                success=False,
                error_code="NOT_CONFIGURED",
                error_message="Twilio is not properly configured",
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
            # Prepare request data
            data = {
                'To': message.phone_number,
                'From': self.from_number,
                'Body': message.message
            }
            
            # Add webhook URL if configured
            if self.webhook_url:
                data['StatusCallback'] = self.webhook_url
                data['StatusCallbackMethod'] = 'POST'
            
            # Add priority-based settings
            if message.priority == "urgent":
                data['ValidityPeriod'] = '60'  # 1 hour validity for urgent messages
            elif message.priority == "high":
                data['ValidityPeriod'] = '240'  # 4 hours validity for high priority
            else:
                data['ValidityPeriod'] = '1440'  # 24 hours validity for normal messages
            
            # Make API request
            async with aiohttp.ClientSession() as session:
                auth = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
                headers = {
                    'Authorization': f'Basic {auth}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
                
                url = f"{self.base_url}/Messages.json"
                body = urlencode(data)
                
                async with session.post(url, headers=headers, data=body) as response:
                    response_data = await response.json()
                    
                    if response.status == 201:  # Twilio returns 201 for successful creation
                        # Track request for rate limiting
                        await self._track_request()
                        
                        return SMSDeliveryResult(
                            success=True,
                            message_id=response_data.get('sid'),
                            provider_response=response_data,
                            cost=float(response_data.get('price', 0)) if response_data.get('price') else None,
                            phone_number=message.phone_number
                        )
                    else:
                        error_info = response_data.get('error', {}) if isinstance(response_data, dict) else {}
                        return SMSDeliveryResult(
                            success=False,
                            error_code=str(error_info.get('code', response.status)),
                            error_message=error_info.get('message', f'HTTP {response.status}'),
                            provider_response=response_data,
                            phone_number=message.phone_number
                        )
        
        except aiohttp.ClientError as e:
            logger.error(f"Twilio HTTP error: {e}")
            return SMSDeliveryResult(
                success=False,
                error_code="HTTP_ERROR",
                error_message=str(e),
                phone_number=message.phone_number
            )
        except Exception as e:
            logger.error(f"Twilio SMS error: {e}")
            return SMSDeliveryResult(
                success=False,
                error_code="UNKNOWN_ERROR",
                error_message=str(e),
                phone_number=message.phone_number
            )
    
    async def send_bulk_sms(self, messages: List[SMSMessage]) -> List[SMSDeliveryResult]:
        """Send multiple SMS messages via Twilio."""
        if not messages:
            return []
        
        if not self.is_available():
            return [
                SMSDeliveryResult(
                    success=False,
                    error_code="NOT_CONFIGURED",
                    error_message="Twilio is not properly configured",
                    phone_number=msg.phone_number
                ) for msg in messages
            ]
        
        results = []
        
        # Process messages in batches to respect rate limits
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
        """Get delivery status from Twilio."""
        if not self.is_available():
            return {
                "success": False,
                "error": "Twilio is not properly configured"
            }
        
        try:
            async with aiohttp.ClientSession() as session:
                auth = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
                headers = {
                    'Authorization': f'Basic {auth}',
                    'Accept': 'application/json'
                }
                
                url = f"{self.base_url}/Messages/{message_id}.json"
                
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "success": True,
                            "status": data.get('status'),
                            "error_code": data.get('error_code'),
                            "error_message": data.get('error_message'),
                            "price": data.get('price'),
                            "date_sent": data.get('date_sent'),
                            "date_updated": data.get('date_updated'),
                            "raw_response": data
                        }
                    else:
                        response_data = await response.json()
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}",
                            "response": response_data
                        }
        
        except Exception as e:
            logger.error(f"Error getting Twilio delivery status: {e}")
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
        self._requests_this_minute = [
            req_time for req_time in self._requests_this_minute
            if now - req_time <= timedelta(minutes=1)
        ]
        
        # Check limits
        if len(self._requests_this_second) >= self.rate_limit_per_second:
            return False
        if len(self._requests_this_minute) >= self.rate_limit_per_minute:
            return False
        
        return True
    
    async def _track_request(self):
        """Track a request for rate limiting purposes."""
        now = datetime.now()
        self._requests_this_second.append(now)
        self._requests_this_minute.append(now)
    
    def get_rate_limit_info(self) -> Dict[str, Any]:
        """Get current rate limiting information."""
        now = datetime.now()
        
        # Clean up old requests
        recent_second_requests = [
            req_time for req_time in self._requests_this_second
            if now - req_time <= timedelta(seconds=1)
        ]
        recent_minute_requests = [
            req_time for req_time in self._requests_this_minute
            if now - req_time <= timedelta(minutes=1)
        ]
        
        return {
            "provider": "twilio",
            "requests_this_second": len(recent_second_requests),
            "requests_this_minute": len(recent_minute_requests),
            "limit_per_second": self.rate_limit_per_second,
            "limit_per_minute": self.rate_limit_per_minute,
            "seconds_until_reset": 1,
            "minutes_until_reset": 1
        }