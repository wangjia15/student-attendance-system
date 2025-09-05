"""
JWT token generation and security utilities for class sessions.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from jose import jwt
from fastapi import HTTPException, status


class JWTManager:
    """Manages JWT tokens for class sessions with security features."""
    
    def __init__(self, secret_key: str = None, algorithm: str = "HS256"):
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        self.algorithm = algorithm
        self.default_expiration_minutes = 30
    
    def create_class_session_token(
        self,
        class_id: str,
        teacher_id: str,
        expiration_minutes: int = None
    ) -> str:
        """Create a JWT token for class session with security claims."""
        expiration_minutes = expiration_minutes or self.default_expiration_minutes
        exp_time = datetime.now(timezone.utc) + timedelta(minutes=expiration_minutes)
        
        payload = {
            "class_id": class_id,
            "teacher_id": teacher_id,
            "iat": datetime.now(timezone.utc),
            "exp": exp_time,
            "type": "class_session",
            "jti": secrets.token_urlsafe(16)
        }
        
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def verify_class_session_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode a class session JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            if payload.get("type") != "class_session":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type"
                )
            
            return payload
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )


class VerificationCodeManager:
    """Manages 6-digit verification codes with collision avoidance."""
    
    def __init__(self):
        self.active_codes: Dict[str, Dict] = {}
    
    def generate_verification_code(self, class_id: str, expiration_minutes: int = 30) -> str:
        """Generate a 6-digit verification code with collision detection."""
        max_attempts = 100
        exp_time = datetime.now(timezone.utc) + timedelta(minutes=expiration_minutes)
        
        for _ in range(max_attempts):
            code = f"{secrets.randbelow(999999):06d}"
            
            if code not in self.active_codes:
                self.active_codes[code] = {
                    "class_id": class_id,
                    "created": datetime.now(timezone.utc),
                    "expires": exp_time
                }
                return code
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to generate unique verification code"
        )


# Global instances
jwt_manager = JWTManager()
verification_code_manager = VerificationCodeManager()


# Convenience functions for easier importing
def create_class_token(data: Dict[str, Any]) -> str:
    """Create a JWT token for class session."""
    from app.core.config import settings
    import secrets
    
    # Add required fields
    token_data = data.copy()
    token_data.update({
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        "type": "class_session",
        "jti": secrets.token_urlsafe(16)
    })
    
    return jwt.encode(token_data, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_verification_code() -> str:
    """Generate a 6-digit verification code."""
    return f"{secrets.randbelow(999999):06d}"


def verify_verification_code(code: str) -> bool:
    """Verify a verification code (placeholder implementation)."""
    # In a real implementation, this would check against stored codes
    return len(code) == 6 and code.isdigit()


def encrypt_data(data: str) -> str:
    """Encrypt data for secure storage (placeholder implementation)."""
    # In production, use proper encryption like Fernet
    # For now, return as-is for testing purposes
    return data


def decrypt_data(encrypted_data: str) -> str:
    """Decrypt data (placeholder implementation)."""
    # In production, use proper decryption
    # For now, return as-is for testing purposes  
    return encrypted_data