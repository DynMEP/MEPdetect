"""
Authentication & Authorization
JWT-based authentication with role-based access control
"""

import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import secrets

# Configuration
# CRITICAL: Load from environment to ensure consistency across restarts
SECRET_KEY = os.getenv("JWT_SECRET_KEY", os.getenv("SECRET_KEY", secrets.token_urlsafe(32)))
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # Default 24 hours
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Warn if using random secret (will cause 401 errors on restart)
if not os.getenv("JWT_SECRET_KEY") and not os.getenv("SECRET_KEY"):
    import warnings
    warnings.warn(
        "⚠️  JWT_SECRET_KEY not set in environment! Using random secret. "
        "This will cause 401 errors when container restarts. "
        "Set JWT_SECRET_KEY in .env file to fix this.",
        RuntimeWarning
    )

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against hash"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


def create_refresh_token(data: dict):
    """Create JWT refresh token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


def verify_token(token: str) -> dict:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )


def generate_api_key() -> str:
    """Generate a unique API key"""
    return f"mep_{secrets.token_urlsafe(32)}"


# ============================================================
# CRITICAL FIX: Proper database dependency
# ============================================================

def get_db():
    """
    Database dependency generator
    This MUST be imported and used by user_api.py
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import os
    
    # No credential fallback: the connection string comes from the
    # environment, so a missing one fails loudly instead of quietly
    # reaching for a password baked into the source.
    DATABASE_URL = os.environ["DATABASE_URL"]
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)  # ← FIXED: Use proper get_db function
):
    """Get current authenticated user from JWT token"""
    
    token = credentials.credentials
    payload = verify_token(token)
    
    email: str = payload.get("sub")
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    # Get user from database
    from db_models import User
    user = db.query(User).filter(User.email == email).first()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    
    return user


async def require_admin(current_user = Depends(get_current_user)):
    """Require admin role"""
    from db_models import UserRole
    
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    return current_user


async def require_pro_or_higher(current_user = Depends(get_current_user)):
    """Require pro, enterprise, or admin role"""
    from db_models import UserRole
    
    allowed_roles = {UserRole.PRO, UserRole.ENTERPRISE, UserRole.ADMIN}
    
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pro subscription required"
        )
    
    return current_user


async def verify_api_key(api_key: str, db: Session):
    """Verify API key and return user"""
    from db_models import User
    
    if not api_key.startswith("mep_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format"
        )
    
    user = db.query(User).filter(User.api_key == api_key).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive account"
        )
    
    return user


def check_api_rate_limit(user) -> bool:
    """Check if user has exceeded API rate limit"""
    return user.api_calls_count < user.api_calls_limit


def increment_api_usage(user, db: Session):
    """Increment user's API usage counter"""
    user.api_calls_count += 1
    db.commit()