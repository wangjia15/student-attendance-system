"""Email template management system with Jinja2 rendering."""

import logging
import os
from typing import Dict, Any, Optional
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template, TemplateError, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON
from sqlalchemy.sql import func

from app.core.database import Base
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailTemplate(Base):
    """Email template model for database storage."""
    __tablename__ = "email_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Template content
    subject_template = Column(Text, nullable=False)
    html_template = Column(Text, nullable=True)
    text_template = Column(Text, nullable=True)
    
    # Template metadata
    category = Column(String(100), nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    variables = Column(JSON, nullable=True)  # Expected template variables
    
    # Default sender information
    default_from_email = Column(String(255), nullable=True)
    default_from_name = Column(String(255), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EmailTemplateManager:
    """Manages email templates with Jinja2 rendering."""
    
    def __init__(self):
        self.template_dir = getattr(settings, 'EMAIL_TEMPLATE_DIR', 'templates/email')
        self.use_database_templates = getattr(settings, 'USE_DATABASE_EMAIL_TEMPLATES', True)
        
        # Initialize Jinja2 environment
        self.jinja_env = self._initialize_jinja_env()
        
        # Cache for database templates
        self._template_cache = {}
        self._cache_expiry = {}
        
        logger.info("Email Template Manager initialized")
    
    def _initialize_jinja_env(self) -> Environment:
        """Initialize Jinja2 environment with proper settings."""
        template_path = Path(self.template_dir)
        if not template_path.exists():
            template_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created template directory: {template_path}")
        
        env = Environment(
            loader=FileSystemLoader(str(template_path)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Add custom filters
        env.filters['format_date'] = self._format_date_filter
        env.filters['format_time'] = self._format_time_filter
        env.filters['format_datetime'] = self._format_datetime_filter
        
        return env
    
    def _format_date_filter(self, value, format='%Y-%m-%d'):
        """Custom Jinja2 filter for date formatting."""
        if hasattr(value, 'strftime'):
            return value.strftime(format)
        return str(value)
    
    def _format_time_filter(self, value, format='%H:%M'):
        """Custom Jinja2 filter for time formatting."""
        if hasattr(value, 'strftime'):
            return value.strftime(format)
        return str(value)
    
    def _format_datetime_filter(self, value, format='%Y-%m-%d %H:%M'):
        """Custom Jinja2 filter for datetime formatting."""
        if hasattr(value, 'strftime'):
            return value.strftime(format)
        return str(value)
    
    async def render_template(
        self, 
        template_id: str, 
        context: Dict[str, Any],
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Render an email template with the given context.
        
        Args:
            template_id: ID of the template to render
            context: Template variables and data
            db: Database session for database templates
            
        Returns:
            Dictionary with rendered content or error information
        """
        try:
            # Try to get template from database first
            if self.use_database_templates and db:
                template_data = await self._get_database_template(template_id, db)
                if template_data:
                    return await self._render_database_template(template_data, context)
            
            # Fall back to file-based templates
            return await self._render_file_template(template_id, context)
            
        except Exception as e:
            logger.error(f"Error rendering template {template_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "template_id": template_id
            }
    
    async def _get_database_template(
        self, 
        template_id: str, 
        db: AsyncSession
    ) -> Optional[EmailTemplate]:
        """Get template from database."""
        try:
            from sqlalchemy import select
            result = await db.execute(
                select(EmailTemplate).where(
                    EmailTemplate.template_id == template_id,
                    EmailTemplate.is_active == True
                )
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting database template {template_id}: {e}")
            return None
    
    async def _render_database_template(
        self, 
        template_data: EmailTemplate, 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Render template from database data."""
        try:
            # Add default context variables
            full_context = {
                **context,
                'app_name': getattr(settings, 'APP_NAME', 'Student Attendance System'),
                'app_url': getattr(settings, 'FRONTEND_URL', 'http://localhost:3000'),
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@example.com')
            }
            
            # Render subject
            subject_template = Template(template_data.subject_template)
            subject = subject_template.render(**full_context)
            
            # Render HTML content
            html_content = None
            if template_data.html_template:
                html_template = Template(template_data.html_template)
                html_content = html_template.render(**full_context)
            
            # Render text content
            text_content = None
            if template_data.text_template:
                text_template = Template(template_data.text_template)
                text_content = text_template.render(**full_context)
            
            return {
                "success": True,
                "template_id": template_data.template_id,
                "subject": subject,
                "html_content": html_content,
                "text_content": text_content,
                "default_from_email": template_data.default_from_email,
                "default_from_name": template_data.default_from_name
            }
            
        except TemplateError as e:
            logger.error(f"Jinja2 template error: {e}")
            return {
                "success": False,
                "error": f"Template rendering error: {e}",
                "template_id": template_data.template_id
            }
    
    async def _render_file_template(
        self, 
        template_id: str, 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Render template from file system."""
        try:
            # Add default context variables
            full_context = {
                **context,
                'app_name': getattr(settings, 'APP_NAME', 'Student Attendance System'),
                'app_url': getattr(settings, 'FRONTEND_URL', 'http://localhost:3000'),
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@example.com')
            }
            
            # Try to load HTML template
            html_content = None
            try:
                html_template = self.jinja_env.get_template(f"{template_id}.html")
                html_content = html_template.render(**full_context)
            except Exception:
                pass  # HTML template is optional
            
            # Try to load text template
            text_content = None
            try:
                text_template = self.jinja_env.get_template(f"{template_id}.txt")
                text_content = text_template.render(**full_context)
            except Exception:
                pass  # Text template is optional
            
            # Try to load subject template or use default
            subject = f"Notification from {full_context['app_name']}"
            try:
                subject_template = self.jinja_env.get_template(f"{template_id}_subject.txt")
                subject = subject_template.render(**full_context).strip()
            except Exception:
                pass  # Subject template is optional
            
            if not html_content and not text_content:
                return {
                    "success": False,
                    "error": f"No template files found for {template_id}",
                    "template_id": template_id
                }
            
            return {
                "success": True,
                "template_id": template_id,
                "subject": subject,
                "html_content": html_content,
                "text_content": text_content
            }
            
        except TemplateError as e:
            logger.error(f"Jinja2 file template error: {e}")
            return {
                "success": False,
                "error": f"Template rendering error: {e}",
                "template_id": template_id
            }
    
    async def create_template(
        self,
        template_id: str,
        name: str,
        subject_template: str,
        html_template: Optional[str] = None,
        text_template: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        default_from_email: Optional[str] = None,
        default_from_name: Optional[str] = None,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Create a new email template in the database."""
        if not db:
            return {
                "success": False,
                "error": "Database session required for template creation"
            }
        
        try:
            # Check if template already exists
            existing = await self._get_database_template(template_id, db)
            if existing:
                return {
                    "success": False,
                    "error": f"Template {template_id} already exists"
                }
            
            # Create new template
            template = EmailTemplate(
                template_id=template_id,
                name=name,
                description=description,
                subject_template=subject_template,
                html_template=html_template,
                text_template=text_template,
                category=category,
                variables=variables,
                default_from_email=default_from_email,
                default_from_name=default_from_name
            )
            
            db.add(template)
            await db.commit()
            await db.refresh(template)
            
            return {
                "success": True,
                "template_id": template_id,
                "id": template.id
            }
            
        except Exception as e:
            logger.error(f"Error creating template {template_id}: {e}")
            await db.rollback()
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_default_templates(self) -> Dict[str, Dict[str, str]]:
        """Get default email templates for common notifications."""
        return {
            "attendance_reminder": {
                "name": "Attendance Reminder",
                "description": "Reminder for upcoming class attendance",
                "category": "attendance",
                "subject_template": "📚 Class Reminder: {{ class_name }} at {{ class_time }}",
                "html_template": """
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                        <h2 style="color: #2c3e50;">Class Reminder</h2>
                        <p>Hello {{ student_name }},</p>
                        <p>This is a friendly reminder about your upcoming class:</p>
                        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                            <strong>{{ class_name }}</strong><br>
                            📅 Date: {{ class_date | format_date }}<br>
                            🕒 Time: {{ class_time | format_time }}<br>
                            📍 Location: {{ class_location }}
                        </div>
                        <p>Please make sure to attend on time. If you cannot attend, please inform your teacher in advance.</p>
                        <p>Best regards,<br>{{ app_name }}</p>
                    </div>
                </body>
                </html>
                """,
                "text_template": """
Class Reminder

Hello {{ student_name }},

This is a friendly reminder about your upcoming class:

{{ class_name }}
Date: {{ class_date | format_date }}
Time: {{ class_time | format_time }}
Location: {{ class_location }}

Please make sure to attend on time. If you cannot attend, please inform your teacher in advance.

Best regards,
{{ app_name }}
                """,
                "variables": {
                    "student_name": "Student's name",
                    "class_name": "Name of the class",
                    "class_date": "Date of the class",
                    "class_time": "Time of the class", 
                    "class_location": "Class location"
                }
            },
            "absence_alert": {
                "name": "Absence Alert",
                "description": "Alert for student absence",
                "category": "attendance",
                "subject_template": "⚠️ Absence Alert: {{ student_name }} - {{ class_name }}",
                "html_template": """
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                        <h2 style="color: #e74c3c;">Absence Alert</h2>
                        <p>Dear {{ parent_name }},</p>
                        <p>We want to inform you that {{ student_name }} was marked as absent from:</p>
                        <div style="background-color: #fff3cd; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107;">
                            <strong>{{ class_name }}</strong><br>
                            📅 Date: {{ absence_date | format_date }}<br>
                            🕒 Time: {{ class_time | format_time }}<br>
                            📍 Location: {{ class_location }}
                        </div>
                        <p>If this absence was expected, please disregard this message. If you have any questions or concerns, please contact the school.</p>
                        <p>Best regards,<br>{{ app_name }}</p>
                    </div>
                </body>
                </html>
                """,
                "text_template": """
Absence Alert

Dear {{ parent_name }},

We want to inform you that {{ student_name }} was marked as absent from:

{{ class_name }}
Date: {{ absence_date | format_date }}
Time: {{ class_time | format_time }}
Location: {{ class_location }}

If this absence was expected, please disregard this message. If you have any questions or concerns, please contact the school.

Best regards,
{{ app_name }}
                """,
                "variables": {
                    "parent_name": "Parent/guardian name",
                    "student_name": "Student's name",
                    "class_name": "Name of the class",
                    "absence_date": "Date of absence",
                    "class_time": "Time of the class",
                    "class_location": "Class location"
                }
            }
        }
    
    async def install_default_templates(self, db: AsyncSession) -> Dict[str, Any]:
        """Install default email templates to database."""
        try:
            templates = self.get_default_templates()
            installed = []
            skipped = []
            
            for template_id, template_data in templates.items():
                # Check if template already exists
                existing = await self._get_database_template(template_id, db)
                if existing:
                    skipped.append(template_id)
                    continue
                
                result = await self.create_template(
                    template_id=template_id,
                    name=template_data["name"],
                    subject_template=template_data["subject_template"],
                    html_template=template_data["html_template"],
                    text_template=template_data["text_template"],
                    category=template_data.get("category"),
                    description=template_data.get("description"),
                    variables=template_data.get("variables"),
                    db=db
                )
                
                if result["success"]:
                    installed.append(template_id)
                else:
                    logger.error(f"Failed to install template {template_id}: {result['error']}")
            
            return {
                "success": True,
                "installed": installed,
                "skipped": skipped
            }
            
        except Exception as e:
            logger.error(f"Error installing default templates: {e}")
            return {
                "success": False,
                "error": str(e)
            }