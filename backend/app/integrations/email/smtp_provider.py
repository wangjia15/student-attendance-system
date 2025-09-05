"""SMTP email provider implementation."""

import logging
import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import ssl

from app.core.config import settings
from .email_service import BaseEmailProvider, EmailMessage, EmailDeliveryResult

logger = logging.getLogger(__name__)


class SMTPProvider(BaseEmailProvider):
    """SMTP email provider implementation."""
    
    def __init__(self):
        # SMTP configuration
        self.host = getattr(settings, 'SMTP_HOST', '')
        self.port = getattr(settings, 'SMTP_PORT', 587)
        self.username = getattr(settings, 'SMTP_USERNAME', '')
        self.password = getattr(settings, 'SMTP_PASSWORD', '')
        self.use_tls = getattr(settings, 'SMTP_USE_TLS', True)
        self.use_ssl = getattr(settings, 'SMTP_USE_SSL', False)
        self.timeout = getattr(settings, 'SMTP_TIMEOUT', 30)
        
        # Default sender information
        self.default_from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', self.username)
        self.default_from_name = getattr(settings, 'DEFAULT_FROM_NAME', 'Student Attendance System')
        
        # Rate limiting configuration
        self.rate_limit_per_minute = getattr(settings, 'SMTP_RATE_LIMIT_PER_MINUTE', 100)
        
        # Tracking for rate limiting
        self._requests_this_minute = []
        
        logger.info("SMTP provider initialized")
    
    def is_available(self) -> bool:
        """Check if SMTP is properly configured."""
        return bool(self.host and self.username and self.password)
    
    async def send_email(self, message: EmailMessage) -> EmailDeliveryResult:
        """Send a single email via SMTP."""
        if not self.is_available():
            return EmailDeliveryResult(
                success=False,
                error_code="NOT_CONFIGURED",
                error_message="SMTP is not properly configured",
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
            # Create MIME message
            mime_message = await self._create_mime_message(message)
            
            # Send email in thread to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._send_smtp_message,
                mime_message,
                message.to_email
            )
            
            # Track request for rate limiting
            await self._track_request()
            
            return result
            
        except Exception as e:
            logger.error(f"SMTP email error: {e}")
            return EmailDeliveryResult(
                success=False,
                error_code="SEND_ERROR",
                error_message=str(e),
                to_email=message.to_email
            )
    
    async def send_bulk_email(self, messages: List[EmailMessage]) -> List[EmailDeliveryResult]:
        """Send multiple emails via SMTP."""
        if not messages:
            return []
        
        if not self.is_available():
            return [
                EmailDeliveryResult(
                    success=False,
                    error_code="NOT_CONFIGURED",
                    error_message="SMTP is not properly configured",
                    to_email=msg.to_email
                ) for msg in messages
            ]
        
        results = []
        
        # Process messages in batches to respect rate limits
        batch_size = min(self.rate_limit_per_minute // 10, 10)  # Conservative batch size
        
        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]
            batch_results = await self._send_batch(batch)
            results.extend(batch_results)
            
            # Add delay between batches if needed
            if i + batch_size < len(messages):
                await asyncio.sleep(6)  # 6 second delay to manage rate limiting
        
        return results
    
    async def _send_batch(self, batch: List[EmailMessage]) -> List[EmailDeliveryResult]:
        """Send a batch of emails sequentially through one SMTP connection."""
        results = []
        
        try:
            # Create single SMTP connection for the batch
            loop = asyncio.get_event_loop()
            smtp_server = await loop.run_in_executor(None, self._create_smtp_connection)
            
            try:
                for message in batch:
                    if not await self._check_rate_limit():
                        results.append(EmailDeliveryResult(
                            success=False,
                            error_code="RATE_LIMITED",
                            error_message="Rate limit exceeded",
                            to_email=message.to_email
                        ))
                        continue
                    
                    try:
                        # Create MIME message
                        mime_message = await self._create_mime_message(message)
                        
                        # Send through existing connection
                        result = await loop.run_in_executor(
                            None,
                            self._send_through_connection,
                            smtp_server,
                            mime_message,
                            message.to_email
                        )
                        
                        results.append(result)
                        await self._track_request()
                        
                    except Exception as e:
                        logger.error(f"Error sending email to {message.to_email}: {e}")
                        results.append(EmailDeliveryResult(
                            success=False,
                            error_code="SEND_ERROR",
                            error_message=str(e),
                            to_email=message.to_email
                        ))
            
            finally:
                # Close SMTP connection
                await loop.run_in_executor(None, smtp_server.quit)
        
        except Exception as e:
            logger.error(f"Error in batch send: {e}")
            # Return error results for remaining messages
            for message in batch[len(results):]:
                results.append(EmailDeliveryResult(
                    success=False,
                    error_code="BATCH_ERROR",
                    error_message=str(e),
                    to_email=message.to_email
                ))
        
        return results
    
    def _create_smtp_connection(self):
        """Create and authenticate SMTP connection."""
        # Create SMTP connection
        if self.use_ssl:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            if self.use_tls:
                context = ssl.create_default_context()
                server.starttls(context=context)
        
        # Authenticate
        server.login(self.username, self.password)
        return server
    
    def _send_smtp_message(self, mime_message: MIMEMultipart, to_email: str) -> EmailDeliveryResult:
        """Send a single MIME message via SMTP."""
        try:
            # Create SMTP connection
            server = self._create_smtp_connection()
            
            try:
                # Send message
                server.send_message(mime_message, to_addrs=[to_email])
                
                return EmailDeliveryResult(
                    success=True,
                    message_id=mime_message.get('Message-ID', ''),
                    to_email=to_email
                )
            
            finally:
                server.quit()
        
        except smtplib.SMTPRecipientsRefused as e:
            return EmailDeliveryResult(
                success=False,
                error_code="RECIPIENTS_REFUSED",
                error_message=f"Recipients refused: {e}",
                to_email=to_email
            )
        except smtplib.SMTPSenderRefused as e:
            return EmailDeliveryResult(
                success=False,
                error_code="SENDER_REFUSED", 
                error_message=f"Sender refused: {e}",
                to_email=to_email
            )
        except smtplib.SMTPDataError as e:
            return EmailDeliveryResult(
                success=False,
                error_code="DATA_ERROR",
                error_message=f"SMTP data error: {e}",
                to_email=to_email
            )
        except Exception as e:
            return EmailDeliveryResult(
                success=False,
                error_code="SMTP_ERROR",
                error_message=str(e),
                to_email=to_email
            )
    
    def _send_through_connection(self, server, mime_message: MIMEMultipart, to_email: str) -> EmailDeliveryResult:
        """Send message through existing SMTP connection."""
        try:
            server.send_message(mime_message, to_addrs=[to_email])
            
            return EmailDeliveryResult(
                success=True,
                message_id=mime_message.get('Message-ID', ''),
                to_email=to_email
            )
        
        except Exception as e:
            return EmailDeliveryResult(
                success=False,
                error_code="SEND_ERROR",
                error_message=str(e),
                to_email=to_email
            )
    
    async def _create_mime_message(self, message: EmailMessage) -> MIMEMultipart:
        """Create MIME message from EmailMessage."""
        # Determine sender information
        from_email = message.from_email or self.default_from_email
        from_name = message.from_name or self.default_from_name
        
        # Create multipart message
        mime_message = MIMEMultipart('alternative')
        mime_message['From'] = f"{from_name} <{from_email}>"
        mime_message['To'] = message.to_email
        mime_message['Subject'] = message.subject
        
        # Add reply-to if specified
        if message.reply_to:
            mime_message['Reply-To'] = message.reply_to
        
        # Add CC recipients
        if message.cc:
            mime_message['CC'] = ', '.join(message.cc)
        
        # Add message ID
        mime_message['Message-ID'] = f"<{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{hash(message.to_email)}@{self.host}>"
        
        # Add text content
        if message.text_content:
            text_part = MIMEText(message.text_content, 'plain', 'utf-8')
            mime_message.attach(text_part)
        
        # Add HTML content
        if message.html_content:
            html_part = MIMEText(message.html_content, 'html', 'utf-8')
            mime_message.attach(html_part)
        
        # Add attachments
        for attachment in message.attachments:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.content)
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {attachment.filename}'
            )
            mime_message.attach(part)
        
        return mime_message
    
    async def get_delivery_status(self, message_id: str) -> Dict[str, Any]:
        """Get delivery status - SMTP doesn't provide tracking."""
        return {
            "success": True,
            "status": "sent",
            "message": "SMTP doesn't provide delivery tracking",
            "message_id": message_id
        }
    
    async def _check_rate_limit(self) -> bool:
        """Check if request is within rate limits."""
        now = datetime.now()
        
        # Clean up old requests
        self._requests_this_minute = [
            req_time for req_time in self._requests_this_minute
            if now - req_time <= timedelta(minutes=1)
        ]
        
        # Check limits
        if len(self._requests_this_minute) >= self.rate_limit_per_minute:
            return False
        
        return True
    
    async def _track_request(self):
        """Track a request for rate limiting purposes."""
        now = datetime.now()
        self._requests_this_minute.append(now)
    
    def get_rate_limit_info(self) -> Dict[str, Any]:
        """Get current rate limiting information."""
        now = datetime.now()
        
        # Clean up old requests
        recent_requests = [
            req_time for req_time in self._requests_this_minute
            if now - req_time <= timedelta(minutes=1)
        ]
        
        return {
            "provider": "smtp",
            "requests_this_minute": len(recent_requests),
            "limit_per_minute": self.rate_limit_per_minute,
            "minutes_until_reset": 1
        }