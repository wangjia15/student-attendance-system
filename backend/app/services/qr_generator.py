"""
QR code generation service with security tokens and customization.
"""
import qrcode
import io
import base64
from typing import Optional, Dict, Any
from PIL import Image, ImageDraw, ImageFont
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer, SquareModuleDrawer


class QRCodeGenerator:
    """Generate secure QR codes for class sessions."""
    
    def __init__(self):
        self.base_url = "https://attendance.school.edu"  # Configure based on environment
        
    def generate_class_qr_code(
        self,
        jwt_token: str,
        class_id: str,
        class_name: str,
        customization: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate a QR code containing the JWT token for class access.
        
        Args:
            jwt_token: Secure JWT token for the class session
            class_id: Unique class identifier
            class_name: Display name of the class
            customization: Optional styling and branding options
            
        Returns:
            Base64-encoded PNG image of the QR code
        """
        # Construct the deep link URL
        qr_data = f"{self.base_url}/join/{class_id}?token={jwt_token}"
        
        # Configure QR code settings for optimal scanning
        qr = qrcode.QRCode(
            version=None,  # Auto-determine version based on data
            error_correction=qrcode.constants.ERROR_CORRECT_M,  # Medium error correction
            box_size=10,
            border=4,
        )
        
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        # Apply customization if provided
        if customization:
            img = self._create_styled_qr_code(qr, customization)
        else:
            img = qr.make_image(fill_color="black", back_color="white")
        
        # Add class information overlay if requested
        if customization and customization.get("add_class_info", False):
            img = self._add_class_info_overlay(img, class_name, class_id)
        
        # Convert to base64 for easy transmission
        return self._image_to_base64(img)
    
    def _create_styled_qr_code(self, qr: qrcode.QRCode, customization: Dict[str, Any]) -> Image.Image:
        """Create a styled QR code with custom colors and shapes."""
        
        # Color customization
        fill_color = customization.get("fill_color", "black")
        back_color = customization.get("back_color", "white")
        
        # Module shape customization
        module_drawer = SquareModuleDrawer()
        if customization.get("rounded_modules", False):
            module_drawer = RoundedModuleDrawer()
        
        # Create styled image
        img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=module_drawer,
            fill_color=fill_color,
            back_color=back_color
        )
        
        return img
    
    def _add_class_info_overlay(
        self, 
        qr_img: Image.Image, 
        class_name: str, 
        class_id: str
    ) -> Image.Image:
        """Add class information overlay to the QR code image."""
        
        # Create a new image with extra space for text
        img_width, img_height = qr_img.size
        new_height = img_height + 80
        new_img = Image.new("RGB", (img_width, new_height), "white")
        
        # Paste the QR code
        new_img.paste(qr_img, (0, 0))
        
        # Add text overlay
        draw = ImageDraw.Draw(new_img)
        
        try:
            # Try to use a nice font
            font = ImageFont.truetype("arial.ttf", 16)
            small_font = ImageFont.truetype("arial.ttf", 12)
        except OSError:
            # Fallback to default font
            font = ImageFont.load_default()
            small_font = ImageFont.load_default()
        
        # Draw class name
        text_width = draw.textlength(class_name, font=font)
        text_x = (img_width - text_width) // 2
        draw.text((text_x, img_height + 10), class_name, font=font, fill="black")
        
        # Draw class ID
        id_text = f"Class ID: {class_id}"
        id_width = draw.textlength(id_text, font=small_font)
        id_x = (img_width - id_width) // 2
        draw.text((id_x, img_height + 35), id_text, font=small_font, fill="gray")
        
        # Add scanning instructions
        instruction_text = "Scan with camera or attendance app"
        inst_width = draw.textlength(instruction_text, font=small_font)
        inst_x = (img_width - inst_width) // 2
        draw.text((inst_x, img_height + 55), instruction_text, font=small_font, fill="gray")
        
        return new_img
    
    def _image_to_base64(self, img: Image.Image) -> str:
        """Convert PIL Image to base64 string."""
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"
    
    def generate_high_contrast_qr_code(
        self,
        jwt_token: str,
        class_id: str,
        class_name: str
    ) -> str:
        """
        Generate a high-contrast QR code optimized for various lighting conditions.
        
        Args:
            jwt_token: Secure JWT token
            class_id: Class identifier
            class_name: Class display name
            
        Returns:
            Base64-encoded high-contrast QR code
        """
        customization = {
            "fill_color": "#000000",
            "back_color": "#FFFFFF",
            "add_class_info": True,
            "rounded_modules": False  # Square modules for better contrast
        }
        
        return self.generate_class_qr_code(jwt_token, class_id, class_name, customization)
    
    def regenerate_qr_code(
        self,
        new_jwt_token: str,
        class_id: str,
        class_name: str,
        previous_customization: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Regenerate QR code with new JWT token, maintaining previous styling.
        
        Args:
            new_jwt_token: Updated JWT token
            class_id: Class identifier
            class_name: Class display name
            previous_customization: Previous styling to maintain
            
        Returns:
            Base64-encoded regenerated QR code
        """
        return self.generate_class_qr_code(
            new_jwt_token,
            class_id,
            class_name,
            previous_customization
        )


# Global instance
qr_generator = QRCodeGenerator()