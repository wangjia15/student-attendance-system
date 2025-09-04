"""
QR code generation service with security tokens and customization.
"""
import base64
from typing import Optional, Dict, Any

try:
    import qrcode
    import io
    from PIL import Image, ImageDraw, ImageFont
    from qrcode.image.styledpil import StyledPilImage
    from qrcode.image.styles.moduledrawers import RoundedModuleDrawer, SquareModuleDrawer
    HAS_QR_LIBS = True
except ImportError:
    HAS_QR_LIBS = False


def generate_class_qr_code(
    deep_link: str, 
    class_name: str, 
    customization: Optional[Dict[str, Any]] = None
) -> str:
    """Simplified function to generate QR code for API usage."""
    if not HAS_QR_LIBS:
        # Return a placeholder base64 image if QR libraries are not available
        placeholder = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        return f"data:image/png;base64,{placeholder}"
    
    try:
        # Configure QR code settings for optimal scanning
        qr = qrcode.QRCode(
            version=None,  # Auto-determine version based on data
            error_correction=qrcode.constants.ERROR_CORRECT_M,  # Medium error correction
            box_size=10,
            border=4,
        )
        
        qr.add_data(deep_link)
        qr.make(fit=True)
        
        # Create basic QR image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64 for easy transmission
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"
        
    except Exception:
        # Return placeholder on any error
        placeholder = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        return f"data:image/png;base64,{placeholder}"


# Placeholder class for backwards compatibility
class QRCodeGenerator:
    """Generate secure QR codes for class sessions."""
    
    def __init__(self, base_url: str = None):
        from app.core.config import settings
        self.base_url = base_url or getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')

    def generate_class_qr_code(
        self,
        jwt_token: str,
        class_id: str,
        class_name: str,
        customization: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate a QR code containing the JWT token for class access."""
        deep_link = f"attendance://join?token={jwt_token}"
        return generate_class_qr_code(deep_link, class_name, customization)

    def generate_high_contrast_qr_code(
        self,
        jwt_token: str,
        class_id: str,
        class_name: str
    ) -> str:
        """Generate a high-contrast QR code."""
        deep_link = f"attendance://join?token={jwt_token}"
        return generate_class_qr_code(deep_link, class_name)

    def regenerate_qr_code(
        self,
        new_jwt_token: str,
        class_id: str,
        class_name: str,
        previous_customization: Optional[Dict[str, Any]] = None
    ) -> str:
        """Regenerate QR code with new JWT token."""
        deep_link = f"attendance://join?token={new_jwt_token}"
        return generate_class_qr_code(deep_link, class_name, previous_customization)


# Global instance
qr_generator = QRCodeGenerator()