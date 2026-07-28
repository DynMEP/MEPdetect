"""
User Management & Subscription API
Complete system for users, subscriptions, orders, and admin management
"""

from fastapi import FastAPI, Depends, HTTPException, status, Header, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import create_engine, desc, func, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker
from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime, timedelta
import stripe
import httpx
import os
import secrets
import shutil
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from db_models import Base, User, Subscription, Order, UsageLog, CustomModel, ContactMessage, UserRole, SubscriptionStatus
from auth import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    generate_api_key, get_current_user, require_admin, verify_api_key,
    check_api_rate_limit, increment_api_usage
)
from google_oauth import verify_google_id_token, is_google_oauth_configured, GOOGLE_CLIENT_ID

# Suppress Pydantic model_type warning (cosmetic only, functionality not affected)
import warnings
warnings.filterwarnings("ignore", message=".*model_type.*conflict.*protected namespace.*")

# Database setup
# No credential fallback: a baked-in default would ship a password in the
# source and silently connect somewhere unintended when the environment is
# misconfigured. Missing DATABASE_URL is a startup error, not a guess.
DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
MODELS_DIR = Path("/app/models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Email Configuration (add to environment variables)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "your-email@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "your-app-password")
EMAIL_FROM = os.getenv("EMAIL_FROM", "MEPdetect <noreply@mepdetect.com>")
BASE_URL = os.getenv("BASE_URL", "https://mepdetect.com")

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-super-secret-jwt-key-change-in-production")
JWT_ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Serialize DDL across uvicorn workers (each worker imports this module; concurrent CREATE TYPE / CREATE TABLE can race on pg_type).
SCHEMA_INIT_LOCK_KEY = 712889441


def _plans_and_contact_messages_ddl(conn, inspector):
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS plans (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                plan_key VARCHAR(50) UNIQUE NOT NULL,
                display_name VARCHAR(100) NOT NULL,
                description TEXT,
                price DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                billing_period VARCHAR(20) NOT NULL DEFAULT 'monthly',
                api_calls_limit INTEGER NOT NULL DEFAULT 100,
                drawings_limit INTEGER,
                storage_limit_gb DECIMAL(10, 2),
                custom_models_limit INTEGER,
                stripe_price_id VARCHAR(100),
                features TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                is_featured BOOLEAN DEFAULT FALSE,
                is_popular BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_plans_plan_key ON plans(plan_key)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_plans_is_active ON plans(is_active)")
    )
    conn.execute(
        text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS drawings_limit INTEGER")
    )
    conn.execute(
        text(
            """
            INSERT INTO plans (name, plan_key, display_name, description, price, billing_period,
                api_calls_limit, drawings_limit, storage_limit_gb, custom_models_limit,
                features, is_active, is_featured, is_popular)
            VALUES
                ('Basic', 'free', 'Basic', 'Forever free', 0.00, 'monthly',
                    100, 5, 1.0, 0,
                    '5 drawings per month,Standard MEP symbols', TRUE, FALSE, FALSE),
                ('Professional', 'pro', 'Professional', 'Most popular plan', 49.00, 'monthly',
                    10000, -1, 50.0, 5,
                    'Unlimited drawings,Batch processing', TRUE, FALSE, TRUE),
                ('Enterprise', 'enterprise', 'Enterprise', 'For large teams', 0.00, 'custom',
                    999999, -1, 500.0, -1,
                    'Enterprise features', TRUE, TRUE, FALSE),
                ('Administrator', 'admin', 'Administrator', 'Full platform access', 0.00, 'monthly',
                    999999, -1, NULL, NULL,
                    'Unlimited', TRUE, FALSE, FALSE)
            ON CONFLICT (plan_key) DO NOTHING
            """
        )
    )
    if inspector.has_table("contact_messages"):
        cm_cols = [c["name"] for c in inspector.get_columns("contact_messages")]
        if "subject" not in cm_cols:
            conn.execute(
                text("ALTER TABLE contact_messages ADD COLUMN subject VARCHAR(500)")
            )
        if "admin_reply" not in cm_cols:
            conn.execute(
                text("ALTER TABLE contact_messages ADD COLUMN admin_reply TEXT")
            )
        if "replied_by" not in cm_cols:
            conn.execute(
                text(
                    "ALTER TABLE contact_messages ADD COLUMN replied_by INTEGER REFERENCES users(id)"
                )
            )
        if "replied_at" not in cm_cols:
            conn.execute(
                text(
                    "ALTER TABLE contact_messages ADD COLUMN replied_at TIMESTAMP WITH TIME ZONE"
                )
            )
        if "updated_at" not in cm_cols:
            conn.execute(
                text(
                    "ALTER TABLE contact_messages ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE"
                )
            )
        if "priority" not in cm_cols:
            conn.execute(
                text(
                    "ALTER TABLE contact_messages ADD COLUMN priority VARCHAR(20) DEFAULT 'normal'"
                )
            )


def _wait_for_database(max_attempts: int = 30, delay_seconds: float = 2.0) -> None:
    """Retry until Postgres accepts connections (e.g. during container startup)."""
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError as e:
            if attempt == max_attempts:
                raise
            logger.warning(
                "Database not ready (attempt %s/%s): %s",
                attempt,
                max_attempts,
                str(e).split("\n", 1)[0],
            )
            time.sleep(delay_seconds)


def _bootstrap_database_schema() -> None:
    """
    ORM create_all + SQL migrations under one session-scoped advisory lock.
    Avoids releasing the lock between ENUM creation and CREATE TABLE plans (multi-worker pg_type races).
    """
    _wait_for_database()
    print("🔄 Checking database schema...")
    migrations_needed = []
    plans_ok = False
    conn = engine.connect()
    try:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": SCHEMA_INIT_LOCK_KEY})
        conn.commit()
        try:
            try:
                Base.metadata.create_all(bind=conn)
                conn.commit()
            except (ProgrammingError, IntegrityError) as e:
                orig = getattr(e, "orig", e)
                msg = str(orig)
                if "pg_type_typname_nsp_index" in msg or "duplicate_object" in msg.lower():
                    logger.warning(
                        "Postgres duplicate ENUM/type (concurrent startup); retrying DDL: %s",
                        msg[:240],
                    )
                    conn.rollback()
                    Base.metadata.create_all(bind=conn)
                    conn.commit()
                else:
                    raise

            inspector = inspect(engine)
            existing_columns = [col["name"] for col in inspector.get_columns("users")]
            migrations_needed.clear()
            if "reset_token" not in existing_columns:
                migrations_needed.append("ADD COLUMN reset_token VARCHAR(255)")
            if "reset_token_expires" not in existing_columns:
                migrations_needed.append("ADD COLUMN reset_token_expires TIMESTAMP")
            if "google_id" not in existing_columns:
                migrations_needed.append("ADD COLUMN google_id VARCHAR(255)")
            if "auth_provider" not in existing_columns:
                migrations_needed.append("ADD COLUMN auth_provider VARCHAR(20) DEFAULT 'local'")

            if migrations_needed:
                print(f"⚠️  Running {len(migrations_needed)} database migrations...")
                for migration in migrations_needed:
                    try:
                        conn.execute(text(f"ALTER TABLE users {migration}"))
                        conn.commit()
                        print(f"✅ Applied: {migration}")
                    except Exception as e:
                        print(f"❌ Failed: {migration} - {str(e)}")
                try:
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS idx_users_reset_token ON users(reset_token)"
                        )
                    )
                    conn.commit()
                    print("✅ Created index: idx_users_reset_token")
                except Exception as e:
                    print(f"⚠️  Index creation: {str(e)}")

            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id "
                        "ON users(google_id) WHERE google_id IS NOT NULL"
                    )
                )
                conn.commit()
            except Exception as e:
                print(f"⚠️  google_id index: {str(e)}")

            try:
                conn.execute(
                    text("ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL")
                )
                conn.commit()
            except Exception as e:
                if "does not exist" not in str(e).lower():
                    print(f"⚠️  hashed_password nullable migration: {str(e)}")

            try:
                with conn.begin():
                    _plans_and_contact_messages_ddl(conn, inspector)
                plans_ok = True
            except ProgrammingError as e:
                orig = getattr(e, "orig", e)
                msg = str(orig)
                if "pg_type_typname_nsp_index" in msg or "duplicate_object" in msg.lower():
                    logger.warning(
                        "Postgres DDL race on plans; retrying: %s",
                        msg[:240],
                    )
                    try:
                        with conn.begin():
                            _plans_and_contact_messages_ddl(conn, inspector)
                        plans_ok = True
                    except Exception as e2:
                        print(f"⚠️  plans/contact_messages migration: {e2}")
                else:
                    print(f"⚠️  plans/contact_messages migration: {e}")
            except Exception as e:
                print(f"⚠️  plans/contact_messages migration: {e}")
        finally:
            conn.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": SCHEMA_INIT_LOCK_KEY}
            )
    finally:
        conn.close()

    if plans_ok:
        print("✅ Plans table and contact_messages columns verified.")
    if migrations_needed:
        print("✅ User table migrations completed.")
    print("✅ Database schema check complete.")


# Stripe configuration
stripe.api_key = os.getenv("STRIPE_API_KEY", "sk_test_...")

# reCAPTCHA configuration
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "6LexampleSecretKey")
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
RECAPTCHA_MIN_SCORE = float(os.getenv("RECAPTCHA_MIN_SCORE", "0.5"))
RECAPTCHA_ENABLED = os.getenv("RECAPTCHA_ENABLED", "true").lower() == "true"

app = FastAPI(title="MEPdetect User Management API", version="1.0.0")

# CORS
_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "https://mepdetect.com,http://localhost:8090,http://127.0.0.1:8090",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    _bootstrap_database_schema()


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def verify_recaptcha(token: str, action: str = None) -> bool:
    """
    Verify reCAPTCHA token with Google API
    
    Args:
        token: reCAPTCHA token from frontend
        action: Expected action (for v3)
        
    Returns:
        True if verification passes, False otherwise
    """
    # Allow disabling reCAPTCHA for testing
    if not RECAPTCHA_ENABLED:
        print("⚠️  reCAPTCHA is disabled (RECAPTCHA_ENABLED=false)")
        return True
    
    if not token:
        print("❌ reCAPTCHA token missing")
        return False
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                RECAPTCHA_VERIFY_URL,
                data={
                    'secret': RECAPTCHA_SECRET_KEY,
                    'response': token
                },
                timeout=5.0
            )
            
            result = response.json()
            
            # For reCAPTCHA v3
            if 'score' in result:
                score = result.get('score', 0)
                success = result.get('success', False)
                
                # Check action matches (optional but recommended)
                if action and result.get('action') != action:
                    print(f"❌ reCAPTCHA action mismatch: expected {action}, got {result.get('action')}")
                    return False
                
                # Check score threshold
                if success and score >= RECAPTCHA_MIN_SCORE:
                    print(f"✅ reCAPTCHA v3 verified: score={score}, action={action}")
                    return True
                else:
                    print(f"❌ reCAPTCHA v3 failed: score={score}, success={success}")
                    return False
            
            # For reCAPTCHA v2
            else:
                success = result.get('success', False)
                if success:
                    print("✅ reCAPTCHA v2 verified")
                else:
                    print(f"❌ reCAPTCHA v2 failed: {result.get('error-codes')}")
                return success
                
    except httpx.TimeoutException:
        print(f"❌ reCAPTCHA timeout - Google API unreachable")
        # For high availability, you might want to return True here
        # and log the event for manual review
        return False
    except Exception as e:
        print(f"❌ reCAPTCHA verification error: {str(e)}")
        return False


# Pydantic Models
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    company: Optional[str] = None
    phone: Optional[str] = None
    recaptcha_token: str  # Required for registration


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    recaptcha_token: str  # Required for login


class GoogleAuthRequest(BaseModel):
    credential: str


class GoogleAuthConfigResponse(BaseModel):
    client_id: str
    enabled: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    id: int
    email: str
    full_name: str
    company: Optional[str]
    phone: Optional[str]
    role: str
    api_key: str  # ← ADD THIS LINE
    api_calls_count: int
    api_calls_limit: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class SubscriptionCreate(BaseModel):
    plan_name: str  # pro, enterprise


class ContactForm(BaseModel):
    name: str
    email: EmailStr
    company: Optional[str]
    message: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AdminUserUpdate(BaseModel):
    """Request model for admin user updates"""
    full_name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    api_calls_limit: Optional[int] = None
    is_active: Optional[bool] = None
    email_verified: Optional[bool] = None


class PlanCreate(BaseModel):
    """Request model for creating a new subscription plan"""
    name: str
    plan_key: str
    display_name: str
    description: Optional[str] = None
    price: float
    billing_period: str
    api_calls_limit: int = 100
    drawings_limit: int = 5  # ⭐ ADD THIS LINE
    storage_limit_gb: Optional[float] = None
    custom_models_limit: Optional[int] = None
    stripe_price_id: Optional[str] = None
    features: Optional[List[str]] = None
    is_active: bool = True
    is_featured: bool = False
    is_popular: bool = False


class PlanUpdate(BaseModel):
    """Request model for updating a subscription plan"""
    name: Optional[str] = None
    plan_key: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    billing_period: Optional[str] = None
    api_calls_limit: Optional[int] = None
    drawings_limit: Optional[int] = None  # ⭐ ADD THIS LINE
    storage_limit_gb: Optional[float] = None
    custom_models_limit: Optional[int] = None
    stripe_price_id: Optional[str] = None
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None
    is_popular: Optional[bool] = None


class CheckoutSessionRequest(BaseModel):
    plan_name: str  # "pro" or "enterprise"
    
class ModelBase(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str
    display_name: str
    description: Optional[str] = None
    version: Optional[str] = None
    model_type: str = "yolo11"
    is_public: bool = False
    supported_classes: List[str] = []
    training_data_info: Optional[str] = None

class ModelCreate(ModelBase):
    pass

class ModelUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    display_name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    is_public: Optional[bool] = None
    supported_classes: Optional[List[str]] = None
    training_data_info: Optional[str] = None

# ============= AUTH ENDPOINTS =============

def _issue_tokens_for_user(user: User) -> dict:
    user.last_login = datetime.utcnow()
    return {
        "access_token": create_access_token({"sub": user.email, "role": user.role.value}),
        "refresh_token": create_refresh_token({"sub": user.email}),
    }


def _find_or_create_google_user(db: Session, idinfo: dict) -> User:
    google_sub = idinfo["sub"]
    email = idinfo["email"].lower()
    full_name = idinfo.get("name") or email.split("@")[0]

    user = db.query(User).filter(User.google_id == google_sub).first()
    if user:
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account inactive")
        return user

    user = db.query(User).filter(User.email == email).first()
    if user:
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account inactive")
        if user.google_id and user.google_id != google_sub:
            raise HTTPException(
                status_code=400,
                detail="This email is linked to a different Google account",
            )
        user.google_id = google_sub
        user.auth_provider = "google"
        user.email_verified = True
        user.email_verified_at = user.email_verified_at or datetime.utcnow()
        if not user.full_name and full_name:
            user.full_name = full_name
        return user

    user = User(
        email=email,
        hashed_password=None,
        google_id=google_sub,
        auth_provider="google",
        full_name=full_name,
        role=UserRole.FREE,
        api_key=generate_api_key(),
        api_calls_limit=100,
        email_verified=True,
        email_verified_at=datetime.utcnow(),
    )
    db.add(user)
    return user


@app.get("/auth/google/config", response_model=GoogleAuthConfigResponse)
async def google_auth_config():
    """Public Google client ID for Sign in with Google (frontend)."""
    return GoogleAuthConfigResponse(
        client_id=GOOGLE_CLIENT_ID or "",
        enabled=is_google_oauth_configured(),
    )


@app.post("/auth/google", response_model=TokenResponse)
async def google_auth(request: GoogleAuthRequest, db: Session = Depends(get_db)):
    """
    Sign in or register with Google (ID token from Google Identity Services).
    Creates a new account on first use; links Google to an existing email account.
    """
    if not is_google_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured on this server",
        )

    try:
        idinfo = verify_google_id_token(request.credential)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google sign-in token")

    user = _find_or_create_google_user(db, idinfo)
    tokens = _issue_tokens_for_user(user)
    db.commit()

    return {**tokens, "token_type": "bearer"}


@app.post("/auth/register")
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """Register new user with email verification"""
    
    # Verify reCAPTCHA
    recaptcha_valid = await verify_recaptcha(user_data.recaptcha_token, action='register')
    if not recaptcha_valid:
        raise HTTPException(
            status_code=400,
            detail="reCAPTCHA verification failed. Please try again."
        )
    
    # Check if email exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user with email_verified = False
    user = User(
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        auth_provider="local",
        full_name=user_data.full_name,
        company=user_data.company,
        phone=user_data.phone,
        role=UserRole.FREE,
        api_key=generate_api_key(),
        api_calls_limit=100,  # Free tier: 100 calls/month
        email_verified=False  # Require email verification
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Generate verification token
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=24)
    
    db.execute(text("""
        INSERT INTO email_verifications (user_id, token, expires_at)
        VALUES (:user_id, :token, :expires_at)
    """), {
        "user_id": user.id,
        "token": token,
        "expires_at": expires_at
    })
    
    db.commit()
    
    # Send verification email
    verification_link = f"{BASE_URL}/verify-email.html?token={token}"
    
    try:
        send_email(
            to_email=user.email,
            subject="Verify your MEPdetect email address",
            html_body=get_verification_email(user.full_name or "there", verification_link),
            email_type="verification",
            user_id=user.id
        )
    except Exception as e:
        print(f"⚠️  Failed to send verification email: {e}")
        # Continue anyway - user can request resend later
    
    return {
        "message": "Registration successful! Please check your email to verify your account.",
        "email": user.email,
        "requires_verification": True
    }


@app.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """Login user"""
    
    # Verify reCAPTCHA
    recaptcha_valid = await verify_recaptcha(credentials.recaptcha_token, action='login')
    if not recaptcha_valid:
        raise HTTPException(
            status_code=400,
            detail="reCAPTCHA verification failed. Please try again."
        )
    
    user = db.query(User).filter(User.email == credentials.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account uses Google sign-in. Please use Continue with Google.",
        )

    if not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")
    
    # Check email verification
    if not user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Please check your inbox for the verification link."
        )
    
    tokens = _issue_tokens_for_user(user)
    db.commit()
    return {**tokens, "token_type": "bearer"}


@app.post("/auth/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    request: ForgotPasswordRequest,
    db: Session = Depends(get_db)
):
    """
    Request password reset.
    
    SECURITY: Always returns success to prevent email enumeration attacks.
    Never reveals whether an email exists in the database or not.
    """
    
    # Find user by email
    user = db.query(User).filter(User.email == request.email).first()
    
    if user and user.is_active:
        # Generate secure random token
        reset_token = secrets.token_urlsafe(32)
        
        # Store token and expiration (24 hours)
        user.reset_token = reset_token
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=24)
        
        db.commit()
        
        # TODO: Send email with reset link
        # Uncomment this when you set up email:
        # try:
        #     from utils.email import send_password_reset_email
        #     send_password_reset_email(
        #         email=user.email,
        #         token=reset_token,
        #         user_name=user.full_name or user.email
        #     )
        # except Exception as e:
        #     print(f"Failed to send email: {e}")
        
        print(f"✅ Reset token generated for {user.email}: {reset_token}")
        print(f"   Reset URL: https://mepdetect.com/reset-password?token={reset_token}")
    else:
        # SECURITY: Don't reveal that email doesn't exist
        # Just log it for internal tracking
        print(f"⚠️  Password reset requested for non-existent email: {request.email}")
    
    # SECURITY: Always return the same success message
    # This prevents attackers from discovering valid email addresses
    return ForgotPasswordResponse(
        message="If an account exists with this email, you will receive password reset instructions shortly.",
        email=request.email
    )


@app.post("/auth/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    """
    Reset password with valid token.
    
    SECURITY: Generic error message to prevent token enumeration.
    """
    
    # Find user with this token
    user = db.query(User).filter(
        User.reset_token == request.token
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Check if token is expired
    if not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        # Clear expired token
        user.reset_token = None
        user.reset_token_expires = None
        db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Validate password strength (basic check)
    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )
    
    # Hash new password
    user.hashed_password = hash_password(request.new_password)
    
    # Clear reset token (one-time use)
    user.reset_token = None
    user.reset_token_expires = None
    
    db.commit()
    
    print(f"✅ Password reset successful for {user.email}")
    
    return {"message": "Password reset successful"}

@app.get("/user/usage-logs")
async def get_usage_logs(
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get recent detection usage logs for current user
    Returns list of recent detections with details
    
    IMPORTANT: Table structure has these columns:
    - file_count (NOT file_name!)
    - detections_count
    - processing_time
    - model_name
    - credits_used
    - custom_model_id
    """
    try:
        logs = db.query(UsageLog)\
            .filter(UsageLog.user_id == current_user.id)\
            .order_by(desc(UsageLog.created_at))\
            .limit(limit)\
            .all()
        
        return {
            "logs": [
                {
                    "id": log.id,
                    "created_at": log.created_at.isoformat(),
                    "file_name": f"{log.file_count} file(s)" if hasattr(log, 'file_count') else "Unknown",
                    "symbols_found": log.detections_count if hasattr(log, 'detections_count') else 0,
                    "status": "completed",
                    "processing_time": log.processing_time if hasattr(log, 'processing_time') else None,
                    "model_name": log.model_name if hasattr(log, 'model_name') else "Unknown",
                    "endpoint": log.endpoint
                }
                for log in logs
            ]
        }
    except Exception as e:
        print(f"Error getting usage logs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage logs"
        )

# ============= ADMIN USER USAGE MANAGEMENT =============

@app.get("/admin/users/{user_id}/usage-stats")
async def get_user_usage_stats(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Get usage statistics for a specific user (admin only)
    """
    try:
        # Get the user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get current month usage
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        monthly_detections = db.query(UsageLog).filter(
            UsageLog.user_id == user_id,
            UsageLog.created_at >= current_month_start
        ).count()
        
        # Get total symbols detected
        total_symbols = db.query(func.sum(UsageLog.detections_count)).filter(
            UsageLog.user_id == user_id
        ).scalar() or 0
        
        # Get current subscription to determine limit
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user_id,
            Subscription.status == 'active'
        ).first()
        
        # Determine drawings limit based on plan
        drawings_limit = 5  # Default for free plan
        if subscription:
            plan = db.query(Plan).filter(Plan.id == subscription.plan_id).first()
            if plan and plan.drawings_limit is not None:
                drawings_limit = plan.drawings_limit
        elif user.role == 'pro' or user.role == 'enterprise':
            drawings_limit = -1  # Unlimited
        
        return {
            "user_id": user_id,
            "drawings_this_month": monthly_detections,
            "drawings_limit": drawings_limit,
            "total_symbols": int(total_symbols),
            "current_month_start": current_month_start.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user usage stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/users/{user_id}/reset-usage")
async def reset_user_monthly_usage(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Reset a user's monthly drawing count (admin only)
    This deletes all UsageLog entries for the current month for the specified user
    """
    try:
        # Verify user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get current month start
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Count entries to be deleted
        entries_to_delete = db.query(UsageLog).filter(
            UsageLog.user_id == user_id,
            UsageLog.created_at >= current_month_start
        ).count()
        
        # Delete all usage log entries for current month
        db.query(UsageLog).filter(
            UsageLog.user_id == user_id,
            UsageLog.created_at >= current_month_start
        ).delete()
        
        db.commit()
        
        logger.info(f"Admin {current_user.email} reset monthly usage for user {user.email} (deleted {entries_to_delete} entries)")
        
        return {
            "success": True,
            "message": f"Reset monthly usage for user {user.email}",
            "entries_deleted": entries_to_delete,
            "user_id": user_id,
            "reset_by": current_user.email,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error resetting user usage: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/models")
async def get_user_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's custom models"""
    
    models = db.query(CustomModel).filter(
        CustomModel.user_id == current_user.id
    ).order_by(
        CustomModel.created_at.desc()
    ).all()
    
    return [{
        "id": model.id,
        "model_name": model.model_name,
        "model_path": model.model_path,
        "class_names": model.class_names,
        "is_active": model.is_active,
        "created_at": model.created_at.isoformat()
    } for model in models]


@app.put("/user/profile")
async def update_profile(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user profile"""
    
    if data.full_name is not None:
        current_user.full_name = data.full_name
    
    if data.company is not None:
        current_user.company = data.company
    
    if data.phone is not None:
        current_user.phone = data.phone
    
    db.commit()
    db.refresh(current_user)
    
    return {
        "message": "Profile updated successfully",
        "user": {
            "email": current_user.email,
            "full_name": current_user.full_name,
            "company": current_user.company,
            "phone": current_user.phone
        }
    }


@app.put("/admin/users/{user_id}", dependencies=[Depends(require_admin)])
async def update_user(
    user_id: int,
    data: AdminUserUpdate,
    db: Session = Depends(get_db)
):
    """Update user information - Admin only"""
    
    # Find user
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update fields if provided
    updated = False
    
    if data.full_name is not None:
        user.full_name = data.full_name
        updated = True
    
    if data.company is not None:
        user.company = data.company
        updated = True
    
    if data.phone is not None:
        user.phone = data.phone
        updated = True
    
    if data.role is not None:
        if data.role not in ['free', 'pro', 'enterprise', 'admin']:
            raise HTTPException(status_code=400, detail="Invalid role")
        user.role = UserRole(data.role)
        updated = True
    
    if data.api_calls_limit is not None:
        user.api_calls_limit = data.api_calls_limit
        updated = True
    
    if data.is_active is not None:
        user.is_active = data.is_active
        updated = True
    
    if data.email_verified is not None:
        user.email_verified = data.email_verified
        if data.email_verified:
            user.email_verified_at = datetime.utcnow()
        updated = True
    
    if not updated:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    try:
        db.commit()
        db.refresh(user)
        
        return {
            "message": "User updated successfully",
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "company": user.company,
                "phone": user.phone,
                "role": user.role.value,
                "api_calls_limit": user.api_calls_limit,
                "is_active": user.is_active,
                "email_verified": user.email_verified
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating user: {str(e)}")

@app.post("/user/change-password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Change user password"""

    if not current_user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google accounts cannot change password here. Set a password via forgot-password if needed.",
        )

    # Verify current password
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Validate new password
    if len(data.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters"
        )
    
    # Update password
    current_user.hashed_password = hash_password(data.new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}


@app.post("/user/regenerate-api-key")
async def regenerate_api_key(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Regenerate user's API key"""
    
    # Generate new API key
    new_api_key = generate_api_key()
    current_user.api_key = new_api_key
    
    db.commit()
    
    return {"api_key": new_api_key}

@app.get("/user/detection-stats")
async def get_detection_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detection statistics for current user
    Includes current month usage, limits, and recent activity
    """
    try:
        # Get current month usage
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        monthly_detections = db.query(UsageLog).filter(
            UsageLog.user_id == current_user.id,
            UsageLog.created_at >= current_month_start
        ).count()

        # Get total detections ever
        total_detections = db.query(UsageLog).filter(
            UsageLog.user_id == current_user.id
        ).count()

        # Get total symbols detected
        total_symbols = db.query(func.sum(UsageLog.detections_count)).filter(
            UsageLog.user_id == current_user.id
        ).scalar() or 0

        # ---- DEBUG scaffold ----
        role_value = getattr(current_user.role, "value", current_user.role)
        role_text = (str(role_value) if role_value is not None else None)
        debug_payload = {
            "user": {
                "id": current_user.id,
                "email": getattr(current_user, "email", None),
                "role_raw": str(current_user.role),
                "role_value": role_text,
            },
            "queries": {
                "subscription": None,
                "plan_by_id": None,
                "plan_by_key": None,
            },
            "computed": {
                "drawings_limit": None,
                "limit_source": None,
            }
        }

        # Get drawings_limit from plan using RAW SQL (no Plan model needed)
        drawings_limit = 5  # Default for free/basic
        limit_source = "default"

        # Try to get from subscription
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id,
            Subscription.status == 'active'
        ).first()

        debug_payload["queries"]["subscription"] = None if not subscription else {
            "id": getattr(subscription, "id", None),
            "user_id": getattr(subscription, "user_id", None),
            "plan_id": getattr(subscription, "plan_id", None),
            "status": getattr(subscription, "status", None),
            "created_at": subscription.created_at.isoformat() if getattr(subscription, "created_at", None) else None,
        }

        sub_plan_id = getattr(subscription, "plan_id", None) if subscription else None
        if subscription and sub_plan_id:
            # Use raw SQL to get plan.drawings_limit
            plan_result = db.execute(
                text("SELECT id, plan_key, drawings_limit FROM plans WHERE id = :plan_id"),
                {"plan_id": sub_plan_id}
            ).first()

            debug_payload["queries"]["plan_by_id"] = None if not plan_result else {
                "id": plan_result[0],
                "plan_key": plan_result[1],
                "drawings_limit": plan_result[2],
            }

            if plan_result and plan_result[2] is not None:
                drawings_limit = plan_result[2]
                limit_source = "subscription.plan_id -> plans.id"
        else:
            # No active subscription - try to find plan by user's role
            if role_text:
                plan_result = db.execute(
                    text("""
        SELECT id, plan_key, drawings_limit
        FROM plans
        WHERE UPPER(plan_key) = UPPER(:plan_key)
        LIMIT 1
    """),
                    {"plan_key": role_text}  # your original behavior
                ).first()

                debug_payload["queries"]["plan_by_key"] = None if not plan_result else {
                    "input_plan_key": role_text,
                    "id": plan_result[0],
                    "plan_key": plan_result[1],
                    "drawings_limit": plan_result[2],
                }

                if plan_result and plan_result[2] is not None:
                    drawings_limit = plan_result[2]
                    limit_source = "users.role -> plans.plan_key"

        debug_payload["computed"]["drawings_limit"] = drawings_limit
        debug_payload["computed"]["limit_source"] = limit_source

        # Get recent detection history
        recent_logs = db.query(UsageLog)\
            .filter(UsageLog.user_id == current_user.id)\
            .order_by(desc(UsageLog.created_at))\
            .limit(10)\
            .all()

        recent_activity = []
        for log in recent_logs:
            activity = {
                "date": log.created_at.isoformat(),
                "detections_count": log.detections_count or 0
            }
            if hasattr(log, 'file_name') and log.file_name:
                activity["file_name"] = log.file_name
            else:
                activity["file_name"] = "Detection"

            recent_activity.append(activity)

        return {
            "drawings_this_month": monthly_detections,
            "drawings_limit": drawings_limit,
            "total_drawings": total_detections,
            "total_symbols": int(total_symbols),
            "recent_activity": recent_activity,
            "current_month_start": current_month_start.isoformat(),
            #"debug": debug_payload,  # <--- added
        }

    except Exception as e:
        logger.error(f"Error getting detection stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/subscriptions/create-checkout-session")
async def create_checkout_session(
    data: CheckoutSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create Stripe checkout session for subscription"""
    
    # Check if Stripe is configured
    if not STRIPE_API_KEY or STRIPE_API_KEY.startswith('sk_test_'):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Payment processing is not configured. Please contact support."
        )
    
    # Plan pricing
    plan_prices = {
        "pro": {
            "price": 4900,  # $49.00 in cents
            "name": "Pro Plan",
            "api_calls": 10000,
            "storage_gb": 50,
            "models": 5
        },
        "enterprise": {
            "price": 29900,  # $299.00 in cents
            "name": "Enterprise Plan",
            "api_calls": 999999,
            "storage_gb": 500,
            "models": 999
        }
    }
    
    if data.plan_name not in plan_prices:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid plan name"
        )
    
    plan_info = plan_prices[data.plan_name]
    
    try:
        # Create Stripe checkout session
        import stripe
        stripe.api_key = STRIPE_API_KEY
        
        session = stripe.checkout.Session.create(
            customer_email=current_user.email,
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': plan_info['name'],
                        'description': f"{plan_info['api_calls']} API calls/month, {plan_info['storage_gb']}GB storage"
                    },
                    'unit_amount': plan_info['price'],
                    'recurring': {
                        'interval': 'month'
                    }
                },
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"{os.getenv('APP_URL', 'https://mepdetect.com')}/dashboard.html?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{os.getenv('APP_URL', 'https://mepdetect.com')}/dashboard.html",
            metadata={
                'user_id': current_user.id,
                'plan_name': data.plan_name
            }
        )
        
        return {"checkout_url": session.url}
        
    except Exception as e:
        print(f"Stripe error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session"
        )


class CreateCheckoutRequest(BaseModel):
    plan_key: str
    success_url: str
    cancel_url: str

@app.post("/subscriptions/create-checkout")
async def create_stripe_checkout(
    request: CreateCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a Stripe checkout session for subscription
    """
    try:
        # Get plan details
        plan = db.query(Plan).filter(Plan.plan_key == request.plan_key).first()
        
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        if not plan.stripe_price_id:
            raise HTTPException(
                status_code=400, 
                detail="This plan does not have Stripe integration configured"
            )
        
        # Check if user already has an active subscription
        existing_sub = db.query(Subscription).filter(
            Subscription.user_id == current_user.id,
            Subscription.status == 'active'
        ).first()
        
        # Create or get Stripe customer
        if not current_user.stripe_customer_id:
            # Create new Stripe customer
            stripe_customer = stripe.Customer.create(
                email=current_user.email,
                name=current_user.full_name,
                metadata={
                    'user_id': current_user.id
                }
            )
            current_user.stripe_customer_id = stripe_customer.id
            db.commit()
        
        # Create Stripe checkout session
        checkout_session = stripe.checkout.Session.create(
            customer=current_user.stripe_customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': plan.stripe_price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.success_url,
            cancel_url=request.cancel_url,
            subscription_data={
                'trial_period_days': 14,  # 14-day free trial
                'metadata': {
                    'user_id': current_user.id,
                    'plan_key': request.plan_key,
                    'plan_id': plan.id
                }
            },
            metadata={
                'user_id': current_user.id,
                'plan_key': request.plan_key,
                'plan_id': plan.id
            }
        )
        
        logger.info(f"Created checkout session {checkout_session.id} for user {current_user.email}, plan {request.plan_key}")
        
        return {
            "checkout_url": checkout_session.url,
            "session_id": checkout_session.id
        }
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating checkout: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        logger.error(f"Error creating checkout session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Stripe webhook events
    """
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_...")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        # Get user and plan info from metadata
        user_id = int(session['metadata']['user_id'])
        plan_id = int(session['metadata']['plan_id'])
        
        # Create or update subscription
        subscription = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            stripe_subscription_id=session['subscription'],
            status='active',
            current_period_start=datetime.utcnow(),
            current_period_end=datetime.utcnow() + timedelta(days=30)
        )
        
        db.add(subscription)
        
        # Update user role
        user = db.query(User).filter(User.id == user_id).first()
        plan = db.query(Plan).filter(Plan.id == plan_id).first()
        if user and plan:
            user.role = plan.plan_key
        
        db.commit()
        
        logger.info(f"Subscription activated for user {user_id}")
    
    elif event['type'] == 'customer.subscription.updated':
        subscription = event['data']['object']
        
        # Update subscription status in database
        db_subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == subscription['id']
        ).first()
        
        if db_subscription:
            db_subscription.status = subscription['status']
            db.commit()
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        
        # Cancel subscription in database
        db_subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == subscription['id']
        ).first()
        
        if db_subscription:
            db_subscription.status = 'cancelled'
            db_subscription.cancelled_at = datetime.utcnow()
            
            # Downgrade user to free plan
            user = db.query(User).filter(User.id == db_subscription.user_id).first()
            if user:
                user.role = 'free'
            
            db.commit()
    
    return {"status": "success"}


# ============= USER ENDPOINTS =============

@app.get("/user/profile", response_model=UserProfile)
async def get_profile(current_user: User = Depends(get_current_user)):
    """Get current user profile"""
    return current_user


@app.get("/user/usage")
async def get_usage_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user usage statistics"""
    
    # Get current month usage
    current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)
    
    monthly_usage = db.query(UsageLog).filter(
        UsageLog.user_id == current_user.id,
        UsageLog.created_at >= current_month_start
    ).count()
    
    # Get total detections
    total_detections = db.query(func.sum(UsageLog.detections_count)).filter(
        UsageLog.user_id == current_user.id
    ).scalar() or 0
    
    # Recent activity
    recent = db.query(UsageLog).filter(
        UsageLog.user_id == current_user.id
    ).order_by(desc(UsageLog.created_at)).limit(10).all()
    
    return {
        "current_month_calls": monthly_usage,
        "limit": current_user.api_calls_limit,
        "total_detections": total_detections,
        "recent_activity": [
            {
                "endpoint": log.endpoint,
                "detections": log.detections_count,
                "time": log.created_at
            }
            for log in recent
        ]
    }

@app.get("/user/api-key")
async def get_api_key(current_user: User = Depends(get_current_user)):
    """Get user's API key"""
    return {"api_key": current_user.api_key}


# ============= SUBSCRIPTION ENDPOINTS =============

@app.get("/subscriptions/plans")
async def get_plans():
    """Get available subscription plans"""
    return {
        "plans": [
            {
                "name": "free",
                "price": 0,
                "billing_period": "monthly",
                "features": {
                    "api_calls": 100,
                    "storage_gb": 1,
                    "custom_models": 0,
                    "support": "Community"
                }
            },
            {
                "name": "pro",
                "price": 49,
                "billing_period": "monthly",
                "features": {
                    "api_calls": 10000,
                    "storage_gb": 50,
                    "custom_models": 5,
                    "support": "Email"
                }
            },
            {
                "name": "enterprise",
                "price": 299,
                "billing_period": "monthly",
                "features": {
                    "api_calls": "Unlimited",
                    "storage_gb": 500,
                    "custom_models": "Unlimited",
                    "support": "Priority + Phone"
                }
            }
        ]
    }


@app.get("/subscriptions/current")
async def get_current_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current subscription"""
    
    subscription = db.query(Subscription).filter(
        Subscription.user_id == current_user.id,
        Subscription.status == SubscriptionStatus.ACTIVE
    ).first()
    
    if not subscription:
        return {"plan": "free", "status": "active"}
    
    return {
        "plan": subscription.plan_name,
        "status": subscription.status.value,
        "current_period_end": subscription.current_period_end,
        "api_calls_limit": subscription.api_calls_limit
    }

@app.post("/billing/portal")
async def create_billing_portal(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create Stripe billing portal session
    Allows users to manage subscription, payment methods, and invoices
    """
    try:
        # Get user's Stripe customer ID
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).order_by(desc(Subscription.created_at)).first()
        
        if not subscription or not subscription.stripe_customer_id:
            raise HTTPException(
                status_code=400,
                detail="No active subscription found. Please subscribe to a plan first."
            )
        
        # Create billing portal session
        session = stripe.billing_portal.Session.create(
            customer=subscription.stripe_customer_id,
            return_url=f"{os.getenv('APP_URL', 'https://mepdetect.com')}/dashboard.html"
        )
        
        return {"url": session.url}
        
    except stripe.error.StripeError as e:
        print(f"Stripe error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create billing portal session"
        )
    except Exception as e:
        print(f"Error creating billing portal: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ============= ADMIN ENDPOINTS =============

@app.get("/admin/users", dependencies=[Depends(require_admin)])
async def get_all_users(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Get all users (admin only)"""
    
    total = db.query(User).count()
    users = db.query(User).offset(skip).limit(limit).all()
    
    return {
        "total": total,
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "company": u.company,
                "phone": u.phone,
                "role": u.role.value,
                "api_calls_limit": u.api_calls_limit,
                "is_active": u.is_active,
                "email_verified": u.email_verified,
                "created_at": u.created_at
            }
            for u in users
        ]
    }


@app.get("/admin/stats", dependencies=[Depends(require_admin)])
async def get_admin_stats(db: Session = Depends(get_db)):
    """Get platform statistics"""
    
    total_users = db.query(User).count()
    active_subscriptions = db.query(Subscription).filter(
        Subscription.status == SubscriptionStatus.ACTIVE
    ).count()
    total_revenue = db.query(func.sum(Order.amount)).filter(
        Order.status == "paid"
    ).scalar() or 0
    
    # Recent signups
    last_week = datetime.utcnow() - timedelta(days=7)
    new_users = db.query(User).filter(User.created_at >= last_week).count()
    
    return {
        "total_users": total_users,
        "active_subscriptions": active_subscriptions,
        "total_revenue": total_revenue,
        "new_users_7d": new_users
    }

# ============================================================================
# Admin Plans Management Endpoints
# ============================================================================

@app.get("/admin/plans", dependencies=[Depends(require_admin)])
async def get_all_plans(db: Session = Depends(get_db)):
    """Get all subscription plans"""
    
    plans = db.execute(text("""
        SELECT * FROM plans
        ORDER BY price ASC
    """)).fetchall()
    
    return {
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "plan_key": p.plan_key,
                "display_name": p.display_name,
                "description": p.description,
                "price": float(p.price),
                "billing_period": p.billing_period,
                "api_calls_limit": p.api_calls_limit,
                "drawings_limit": p.drawings_limit,
                "storage_limit_gb": float(p.storage_limit_gb) if p.storage_limit_gb else None,
                "custom_models_limit": p.custom_models_limit,
                "stripe_price_id": p.stripe_price_id,
                "features": p.features if isinstance(p.features, list) else (p.features.split(',') if p.features else []),
                "is_active": p.is_active,
                "is_featured": p.is_featured,
                "is_popular": p.is_popular,
                "created_at": p.created_at.isoformat() if p.created_at else None
            }
            for p in plans
        ]
    }


@app.post("/admin/plans", dependencies=[Depends(require_admin)])
async def create_plan(plan: PlanCreate, db: Session = Depends(get_db)):
    """Create a new subscription plan"""
    
    # Check if plan_key already exists
    existing = db.execute(
        text("SELECT id FROM plans WHERE plan_key = :key"),
        {"key": plan.plan_key}
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Plan key already exists")
    
    features_json = ','.join(plan.features) if plan.features else None
    
    result = db.execute(text("""
        INSERT INTO plans (
            name, plan_key, display_name, description, price, billing_period,
            api_calls_limit, drawings_limit, storage_limit_gb, custom_models_limit, 
            stripe_price_id, features, is_active, is_featured, is_popular
        ) VALUES (
            :name, :plan_key, :display_name, :description, :price, :billing_period,
            :api_calls_limit, :drawings_limit, :storage_limit_gb, :custom_models_limit,
            :stripe_price_id, :features, :is_active, :is_featured, :is_popular
        ) RETURNING id
    """), {
        "name": plan.name,
        "plan_key": plan.plan_key,
        "display_name": plan.display_name,
        "description": plan.description,
        "price": plan.price,
        "billing_period": plan.billing_period,
        "api_calls_limit": plan.api_calls_limit,
        "drawings_limit": plan.drawings_limit,
        "storage_limit_gb": plan.storage_limit_gb,
        "custom_models_limit": plan.custom_models_limit,
        "stripe_price_id": plan.stripe_price_id,
        "features": features_json,
        "is_active": plan.is_active,
        "is_featured": plan.is_featured,
        "is_popular": plan.is_popular
    })
    
    plan_id = result.fetchone()[0]
    db.commit()
    
    return {
        "message": "Plan created successfully",
        "plan_id": plan_id
    }


@app.put("/admin/plans/{plan_id}", dependencies=[Depends(require_admin)])
async def update_plan(plan_id: int, plan: PlanUpdate, db: Session = Depends(get_db)):
    """Update a subscription plan"""
    
    # Check if plan exists
    existing = db.execute(
        text("SELECT id FROM plans WHERE id = :id"),
        {"id": plan_id}
    ).first()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Build update query dynamically
    updates = []
    params = {"id": plan_id}
    
    if plan.name is not None:
        updates.append("name = :name")
        params["name"] = plan.name
    
    if plan.plan_key is not None:
        # Check if new key is already used by another plan
        key_check = db.execute(
            text("SELECT id FROM plans WHERE plan_key = :key AND id != :id"),
            {"key": plan.plan_key, "id": plan_id}
        ).first()
        if key_check:
            raise HTTPException(status_code=400, detail="Plan key already exists")
        updates.append("plan_key = :plan_key")
        params["plan_key"] = plan.plan_key
    
    if plan.display_name is not None:
        updates.append("display_name = :display_name")
        params["display_name"] = plan.display_name
    
    if plan.description is not None:
        updates.append("description = :description")
        params["description"] = plan.description
    
    if plan.price is not None:
        updates.append("price = :price")
        params["price"] = plan.price
    
    if plan.billing_period is not None:
        updates.append("billing_period = :billing_period")
        params["billing_period"] = plan.billing_period
    
    if plan.api_calls_limit is not None:
        updates.append("api_calls_limit = :api_calls_limit")
        params["api_calls_limit"] = plan.api_calls_limit
    
    if plan.drawings_limit is not None:
        updates.append("drawings_limit = :drawings_limit")
        params["drawings_limit"] = plan.drawings_limit
    
    if plan.storage_limit_gb is not None:
        updates.append("storage_limit_gb = :storage_limit_gb")
        params["storage_limit_gb"] = plan.storage_limit_gb
    
    if plan.custom_models_limit is not None:
        updates.append("custom_models_limit = :custom_models_limit")
        params["custom_models_limit"] = plan.custom_models_limit
    
    if plan.stripe_price_id is not None:
        updates.append("stripe_price_id = :stripe_price_id")
        params["stripe_price_id"] = plan.stripe_price_id
    
    if plan.features is not None:
        features_json = ','.join(plan.features) if plan.features else None
        updates.append("features = :features")
        params["features"] = features_json
    
    if plan.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = plan.is_active
    
    if plan.is_featured is not None:
        updates.append("is_featured = :is_featured")
        params["is_featured"] = plan.is_featured
    
    if plan.is_popular is not None:
        updates.append("is_popular = :is_popular")
        params["is_popular"] = plan.is_popular
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    query = f"UPDATE plans SET {', '.join(updates)} WHERE id = :id"
    db.execute(text(query), params)
    db.commit()
    
    return {
        "message": "Plan updated successfully"
    }


@app.delete("/admin/plans/{plan_id}", dependencies=[Depends(require_admin)])
async def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    """Delete a subscription plan"""
    
    # Check if plan exists
    plan = db.execute(
        text("SELECT name FROM plans WHERE id = :id"),
        {"id": plan_id}
    ).first()
    
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Check if any active subscriptions use this plan
    active_subs = db.execute(
        text("SELECT COUNT(*) FROM subscriptions WHERE plan_name = (SELECT plan_key FROM plans WHERE id = :id) AND status = 'active'"),
        {"id": plan_id}
    ).scalar()
    
    if active_subs > 0:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot delete plan with {active_subs} active subscriptions. Deactivate the plan instead."
        )
    
    db.execute(text("DELETE FROM plans WHERE id = :id"), {"id": plan_id})
    db.commit()
    
    return {
        "message": f"Plan '{plan.name}' deleted successfully"
    }

# ============================================================================
# Admin Model Management Endpoints
# ============================================================================

@app.get("/admin/models", dependencies=[Depends(require_admin)])
async def get_models(
    include_inactive: bool = False,
    db: Session = Depends(get_db)
):
    """Get all models with file system info"""
    
    query = db.execute(text("""
        SELECT m.*, u.email as uploaded_by_email
        FROM models m
        LEFT JOIN users u ON m.uploaded_by = u.id
        WHERE m.is_active = true OR :include_inactive = true
        ORDER BY m.is_default DESC, m.created_at DESC
    """), {"include_inactive": include_inactive})
    
    models = []
    for row in query:
        # Check if file exists
        file_exists = os.path.exists(row.file_path)
        file_size = os.path.getsize(row.file_path) if file_exists else 0
        
        models.append({
            "id": row.id,
            "name": row.name,
            "display_name": row.display_name,
            "description": row.description,
            "file_path": row.file_path,
            "file_size": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size > 0 else 0,
            "file_exists": file_exists,
            "version": row.version,
            "model_type": row.model_type,
            "is_default": row.is_default,
            "is_active": row.is_active,
            "is_public": row.is_public,
            "uploaded_by_email": row.uploaded_by_email,
            "supported_classes": row.supported_classes if row.supported_classes else [],
            "accuracy_metrics": row.accuracy_metrics if row.accuracy_metrics else {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None
        })
    
    return {"models": models}


@app.get("/admin/models/scan", dependencies=[Depends(require_admin)])
async def scan_models_directory(db: Session = Depends(get_db)):
    """Scan /app/models directory and list all .pt files"""
    
    models_in_db = {}
    db_models = db.execute(text("SELECT name, file_path FROM models"))
    for row in db_models:
        models_in_db[row.file_path] = row.name
    
    found_models = []
    if MODELS_DIR.exists():
        for model_file in MODELS_DIR.glob("*.pt"):
            file_path = str(model_file)
            file_size = model_file.stat().st_size
            
            found_models.append({
                "filename": model_file.name,
                "file_path": file_path,
                "file_size": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2),
                "in_database": file_path in models_in_db,
                "db_name": models_in_db.get(file_path, None)
            })
    
    return {
        "models_directory": str(MODELS_DIR),
        "found_models": found_models,
        "total_files": len(found_models)
    }


@app.post("/admin/models/register", dependencies=[Depends(require_admin)])
async def register_existing_model(
    file_path: str,
    model: ModelCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Register an existing model file in the database"""
    
    # Verify file exists
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Model file not found")
    
    # Check if model name already exists
    existing = db.execute(
        text("SELECT id FROM models WHERE name = :name"),
        {"name": model.name}
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Model with this name already exists")
    
    # Get file size
    file_size = os.path.getsize(file_path)
    
    # Insert model
    result = db.execute(text("""
        INSERT INTO models (
            name, display_name, description, file_path, file_size,
            version, model_type, is_public, uploaded_by, supported_classes
        ) VALUES (
            :name, :display_name, :description, :file_path, :file_size,
            :version, :model_type, :is_public, :uploaded_by, :supported_classes::jsonb
        )
        RETURNING id, name, display_name, is_default, is_active
    """), {
        "name": model.name,
        "display_name": model.display_name,
        "description": model.description,
        "file_path": file_path,
        "file_size": file_size,
        "version": model.version,
        "model_type": model.model_type,
        "is_public": model.is_public,
        "uploaded_by": current_user.id,
        "supported_classes": json.dumps(model.supported_classes)
    })
    
    db.commit()
    row = result.first()
    
    return {
        "id": row.id,
        "name": row.name,
        "display_name": row.display_name,
        "is_default": row.is_default,
        "is_active": row.is_active,
        "message": "Model registered successfully"
    }


@app.put("/admin/models/{model_id}", dependencies=[Depends(require_admin)])
async def update_model(
    model_id: int,
    model: ModelUpdate,
    db: Session = Depends(get_db)
):
    """Update model metadata"""
    
    updates = []
    params = {"model_id": model_id}
    
    if model.display_name is not None:
        updates.append("display_name = :display_name")
        params["display_name"] = model.display_name
    
    if model.description is not None:
        updates.append("description = :description")
        params["description"] = model.description
    
    if model.version is not None:
        updates.append("version = :version")
        params["version"] = model.version
    
    if model.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = model.is_active
    
    if model.is_public is not None:
        updates.append("is_public = :is_public")
        params["is_public"] = model.is_public
    
    if model.supported_classes is not None:
        updates.append("supported_classes = :supported_classes::jsonb")
        params["supported_classes"] = json.dumps(model.supported_classes)
    
    if model.training_data_info is not None:
        updates.append("training_data_info = :training_data_info")
        params["training_data_info"] = model.training_data_info
    
    # Handle default flag specially
    if model.is_default is not None and model.is_default:
        # Unset all other defaults first
        db.execute(text("UPDATE models SET is_default = false WHERE is_default = true"))
        updates.append("is_default = true")
    
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    updates.append("updated_at = NOW()")
    
    query = f"""
        UPDATE models
        SET {", ".join(updates)}
        WHERE id = :model_id
        RETURNING id, name, display_name, is_default, is_active
    """
    
    result = db.execute(text(query), params)
    db.commit()
    
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    
    return {
        "id": row.id,
        "name": row.name,
        "display_name": row.display_name,
        "is_default": row.is_default,
        "is_active": row.is_active,
        "message": "Model updated successfully"
    }


@app.post("/admin/models/{model_id}/set-default", dependencies=[Depends(require_admin)])
async def set_default_model(
    model_id: int,
    db: Session = Depends(get_db)
):
    """Set a model as the default for all detections"""
    
    # Verify model exists and is active
    model = db.execute(
        text("SELECT id, name, display_name, is_active FROM models WHERE id = :model_id"),
        {"model_id": model_id}
    ).first()
    
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    if not model.is_active:
        raise HTTPException(status_code=400, detail="Cannot set inactive model as default")
    
    # Unset all other defaults
    db.execute(text("UPDATE models SET is_default = false WHERE is_default = true"))
    
    # Set this model as default
    db.execute(
        text("UPDATE models SET is_default = true, updated_at = NOW() WHERE id = :model_id"),
        {"model_id": model_id}
    )
    
    db.commit()
    
    return {
        "id": model.id,
        "name": model.name,
        "display_name": model.display_name,
        "is_default": True,
        "message": f"{model.display_name} is now the default model"
    }


@app.delete("/admin/models/{model_id}", dependencies=[Depends(require_admin)])
async def delete_model(
    model_id: int,
    delete_file: bool = False,
    db: Session = Depends(get_db)
):
    """Deactivate or delete a model"""
    
    # Get model info
    model = db.execute(
        text("SELECT id, name, file_path, is_default FROM models WHERE id = :model_id"),
        {"model_id": model_id}
    ).first()
    
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    if model.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default model. Set another model as default first.")
    
    if delete_file:
        # Delete the actual file
        if os.path.exists(model.file_path):
            os.remove(model.file_path)
        # Delete from database
        db.execute(text("DELETE FROM models WHERE id = :model_id"), {"model_id": model_id})
        message = "Model and file deleted"
    else:
        # Just deactivate
        db.execute(
            text("UPDATE models SET is_active = false, updated_at = NOW() WHERE id = :model_id"),
            {"model_id": model_id}
        )
        message = "Model deactivated"
    
    db.commit()
    
    return {"success": True, "message": message}

@app.delete("/admin/users/{user_id}", dependencies=[Depends(require_admin)])
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db)
):
    """Delete a user - Admin only"""
    
    logger.info(f"Attempting to delete user with id: {user_id}")
    
    try:
        # Find user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.warning(f"User {user_id} not found")
            raise HTTPException(status_code=404, detail="User not found")
        
        logger.info(f"Found user: {user.email}, role: {user.role}")
        
        # Prevent deleting admin users (safety check)
        # Compare role value as string to avoid enum comparison issues
        if str(user.role.value) == 'admin' or user.role == UserRole.ADMIN:
            logger.warning(f"Attempted to delete admin user: {user.email}")
            raise HTTPException(status_code=400, detail="Cannot delete admin users. Change role first.")
        
        user_email = user.email
        logger.info(f"Starting deletion process for user: {user_email}")
        
        # Delete related records first to avoid foreign key constraints
        logger.info("Deleting email_verifications...")
        try:
            db.execute(text("DELETE FROM email_verifications WHERE user_id = :user_id"), {"user_id": user_id})
        except Exception as e:
            logger.warning(f"Could not delete email_verifications: {e}")
            db.rollback()  # Reset transaction state
        
        logger.info("Deleting usage_log...")
        try:
            db.execute(text("DELETE FROM usage_log WHERE user_id = :user_id"), {"user_id": user_id})
        except Exception as e:
            logger.warning(f"Could not delete usage_log (table may not exist): {e}")
            db.rollback()  # Reset transaction state
        
        # Delete subscriptions if they exist
        logger.info("Deleting subscriptions...")
        try:
            count = db.query(Subscription).filter(Subscription.user_id == user_id).delete()
            logger.info(f"Deleted {count} subscriptions")
        except Exception as e:
            logger.warning(f"No subscriptions to delete or error: {e}")
            db.rollback()  # Reset transaction state
        
        # Delete orders if they exist  
        logger.info("Deleting orders...")
        try:
            count = db.query(Order).filter(Order.user_id == user_id).delete()
            logger.info(f"Deleted {count} orders")
        except Exception as e:
            logger.warning(f"No orders to delete or error: {e}")
            db.rollback()  # Reset transaction state
        
        # Re-fetch the user to ensure clean session state after any rollbacks
        logger.info(f"Re-fetching user to ensure clean session state...")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} no longer exists after cleanup")
            raise HTTPException(status_code=404, detail="User not found after cleanup")
        
        # Delete the user
        logger.info(f"Deleting user object: {user_email}")
        db.delete(user)
        db.commit()
        
        logger.info(f"Successfully deleted user: {user_email}")
        
        return {
            "message": f"User {user_email} deleted successfully"
        }
        
    except HTTPException:
        logger.error("HTTPException raised, re-raising")
        raise
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting user: {str(e)}")

@app.get("/public/models/default")
async def get_default_model(db: Session = Depends(get_db)):
    """Get the current default model (public endpoint)"""
    
    model = db.execute(text("""
        SELECT name, display_name, version, model_type, file_path
        FROM models
        WHERE is_default = true AND is_active = true
        LIMIT 1
    """)).first()
    
    if not model:
        raise HTTPException(status_code=404, detail="No default model configured")
    
    return {
        "name": model.name,
        "display_name": model.display_name,
        "version": model.version,
        "model_type": model.model_type,
        "file_path": model.file_path
    }


@app.get("/public/plans")
async def get_public_plans(db: Session = Depends(get_db)):
    """Get all active subscription plans (public endpoint)"""
    
    plans = db.execute(text("""
        SELECT id, name, plan_key, display_name, description, price, 
               billing_period, api_calls_limit, drawings_limit, storage_limit_gb, 
               custom_models_limit, features, is_featured, is_popular
        FROM plans
        WHERE is_active = true
        ORDER BY price ASC
    """)).fetchall()
    
    return {
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "plan_key": p.plan_key,
                "display_name": p.display_name,
                "description": p.description,
                "price": float(p.price),
                "billing_period": p.billing_period,
                "api_calls_limit": p.api_calls_limit,
                "drawings_limit": p.drawings_limit,
                "storage_limit_gb": float(p.storage_limit_gb) if p.storage_limit_gb else None,
                "custom_models_limit": p.custom_models_limit,
                "features": p.features.split(',') if p.features else [],
                "is_featured": p.is_featured,
                "is_popular": p.is_popular
            }
            for p in plans
        ]
    }


@app.post("/admin/models/upload", dependencies=[Depends(require_admin)])
async def upload_model(
    file: UploadFile = File(...),
    name: str = Form(...),
    display_name: str = Form(...),
    description: str = Form(None),
    version: str = Form(None),
    model_type: str = Form("yolo11"),
    is_public: bool = Form(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a new model file"""
    
    # Validate file extension
    if not file.filename.endswith('.pt'):
        raise HTTPException(status_code=400, detail="Only .pt files are allowed")
    
    # Check if model name already exists
    existing = db.execute(
        text("SELECT id FROM models WHERE name = :name"),
        {"name": name}
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Model with this name already exists")
    
    # Save file
    file_path = MODELS_DIR / f"{name}.pt"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    file_size = os.path.getsize(file_path)
    
    # Register in database
    result = db.execute(text("""
        INSERT INTO models (
            name, display_name, description, file_path, file_size,
            version, model_type, is_public, uploaded_by
        ) VALUES (
            :name, :display_name, :description, :file_path, :file_size,
            :version, :model_type, :is_public, :uploaded_by
        )
        RETURNING id, name, display_name
    """), {
        "name": name,
        "display_name": display_name,
        "description": description,
        "file_path": str(file_path),
        "file_size": file_size,
        "version": version,
        "model_type": model_type,
        "is_public": is_public,
        "uploaded_by": current_user.id
    })
    
    db.commit()
    row = result.first()
    
    return {
        "id": row.id,
        "name": row.name,
        "display_name": row.display_name,
        "file_size_mb": round(file_size / (1024 * 1024), 2),
        "message": "Model uploaded successfully"
    }



# ============================================================================
# Admin Revenue & Usage Endpoints
# ============================================================================

@app.get("/admin/revenue", dependencies=[Depends(require_admin)])
async def get_admin_revenue(db: Session = Depends(get_db)):
    """Get detailed revenue analytics"""
    
    # Total revenue
    total_revenue = db.query(func.sum(Order.amount)).filter(
        Order.status == "paid"
    ).scalar() or 0
    
    # This month's revenue
    current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_revenue = db.query(func.sum(Order.amount)).filter(
        Order.status == "paid",
        Order.created_at >= current_month_start
    ).scalar() or 0
    
    # Last month's revenue
    last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
    last_month_revenue = db.query(func.sum(Order.amount)).filter(
        Order.status == "paid",
        Order.created_at >= last_month_start,
        Order.created_at < current_month_start
    ).scalar() or 0
    
    # Average revenue per user
    total_users = db.query(User).count()
    avg_revenue_per_user = total_revenue / total_users if total_users > 0 else 0
    
    # Recent transactions
    recent_transactions = db.query(Order)\
        .filter(Order.status == "paid")\
        .order_by(desc(Order.created_at))\
        .limit(20)\
        .all()
    
    transactions = []
    for order in recent_transactions:
        user = db.query(User).filter(User.id == order.user_id).first()
        subscription = db.query(Subscription).filter(
            Subscription.user_id == order.user_id,
            Subscription.status == SubscriptionStatus.ACTIVE
        ).first()
        
        transactions.append({
            "id": order.id,
            "date": order.created_at.isoformat(),
            "user_email": user.email if user else "Unknown",
            "plan": subscription.plan_name if subscription else "Unknown",
            "amount": float(order.amount),
            "status": order.status
        })
    
    return {
        "total_revenue": float(total_revenue),
        "month_revenue": float(month_revenue),
        "last_month_revenue": float(last_month_revenue),
        "avg_revenue_per_user": float(avg_revenue_per_user),
        "transactions": transactions
    }


@app.get("/admin/usage", dependencies=[Depends(require_admin)])
async def get_admin_usage(db: Session = Depends(get_db)):
    """Get platform usage statistics"""
    
    total_api_calls = db.query(UsageLog).count()
    
    current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_api_calls = db.query(UsageLog).filter(
        UsageLog.created_at >= current_month_start
    ).count()
    
    total_drawings = total_api_calls
    total_symbols = db.query(func.sum(UsageLog.detections_count)).scalar() or 0
    
    user_usage = db.query(
        User.id,
        User.email,
        User.full_name,
        func.count(UsageLog.id).label('drawing_count'),
        func.sum(UsageLog.detections_count).label('symbol_count'),
        func.max(UsageLog.created_at).label('last_activity')
    ).outerjoin(UsageLog, User.id == UsageLog.user_id)\
     .group_by(User.id, User.email, User.full_name)\
     .order_by(desc('drawing_count'))\
     .limit(50)\
     .all()
    
    usage_stats = []
    for stat in user_usage:
        usage_stats.append({
            "user_id": stat.id,
            "user_email": stat.email,
            "user_name": stat.full_name or "N/A",
            "drawings": stat.drawing_count or 0,
            "symbols": int(stat.symbol_count or 0),
            "last_activity": stat.last_activity.isoformat() if stat.last_activity else "Never"
        })
    
    return {
        "total_api_calls": total_api_calls,
        "month_api_calls": month_api_calls,
        "total_drawings": total_drawings,
        "total_symbols": int(total_symbols),
        "user_usage": usage_stats
    }

# ============================================================================
# Detection History Endpoints
# ============================================================================

@app.get("/user/detection-history")
async def get_detection_history(
    limit: int = 10,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's detection history"""
    
    total = db.query(UsageLog).filter(UsageLog.user_id == current_user.id).count()
    
    history = db.query(UsageLog)\
        .filter(UsageLog.user_id == current_user.id)\
        .order_by(desc(UsageLog.created_at))\
        .limit(limit)\
        .offset(offset)\
        .all()
    
    return {
        "total": total,
        "history": [
            {
                "id": log.id,
                "filename": f"Detection #{log.id}",
                "detections_count": log.detections_count,
                "processing_time": round(log.processing_time, 2) if log.processing_time else 0,
                "model_name": log.model_name or "default",
                "credits_used": log.credits_used,
                "created_at": log.created_at.isoformat(),
                "status": "completed",
                "endpoint": log.endpoint,
                "file_count": log.file_count or 1,  # ⭐ Added
            }
            for log in history
        ]
    }


@app.get("/user/usage-stats")
async def get_usage_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's usage statistics"""
    
    # Current month stats
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    monthly_detections = db.query(func.count(UsageLog.id))\
        .filter(UsageLog.user_id == current_user.id)\
        .filter(UsageLog.created_at >= start_of_month)\
        .scalar()
    
    total_symbols = db.query(func.sum(UsageLog.detections_count))\
        .filter(UsageLog.user_id == current_user.id)\
        .scalar() or 0
    
    # Get active subscription
    active_sub = db.query(Subscription)\
        .filter(Subscription.user_id == current_user.id)\
        .filter(Subscription.status == SubscriptionStatus.ACTIVE)\
        .first()
    # Get current subscription to determine limit
    subscription = db.query(Subscription).filter(
        Subscription.user_id == current_user.id,
        Subscription.status == SubscriptionStatus.ACTIVE
    ).first()

    # Determine drawings limit based on plan
    monthly_limit = 5  # Default for free plan
    plan = None

    if subscription and getattr(subscription, 'plan_id', None):
        plan = db.query(Plan).filter(Plan.id == subscription.plan_id).first()
        if plan and plan.drawings_limit is not None:
            monthly_limit = plan.drawings_limit
    else:
        # Fallback: map role -> plan_key (case-insensitive)
        role_text = (getattr(current_user.role, 'value', str(current_user.role)) or '').strip()
        plan_row = db.execute(text(
            "SELECT drawings_limit FROM plans WHERE UPPER(plan_key) = UPPER(:plan_key) LIMIT 1"
        ), {'plan_key': role_text}).first()
        if plan_row and plan_row[0] is not None:
            monthly_limit = plan_row[0]
    
    return {
        "monthly_detections": monthly_detections or 0,
        "monthly_limit": monthly_limit,
        "total_symbols_detected": int(total_symbols),
        "current_plan": (plan.plan_key if plan else getattr(current_user.role, "value", str(current_user.role))),
        "api_calls_count": current_user.api_calls_count,
        "api_calls_limit": current_user.api_calls_limit,
        "has_active_subscription": active_sub is not None
    }


# ============================================================================
# Billing & Subscription Management Endpoints
# ============================================================================

@app.get("/user/subscription")
async def get_subscription_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's current subscription information"""
    
    active_sub = db.query(Subscription)\
        .filter(Subscription.user_id == current_user.id)\
        .filter(Subscription.status == SubscriptionStatus.ACTIVE)\
        .first()
    
    if not active_sub:
        return {
            "has_subscription": False,
            "plan_name": "Free",
            "role": current_user.role.value,
            "status": "active",
            "monthly_detections_limit": 5,
            "api_calls_limit": 100,
            "features": [
                "5 detections per month",
                "Basic symbol detection",
                "JSON, CSV, Excel export"
            ]
        }
    
    return {
        "has_subscription": True,
        "subscription_id": active_sub.id,
        "plan_name": active_sub.plan_name,
        "role": current_user.role.value,
        "status": active_sub.status.value,
        "price": active_sub.price,
        "currency": active_sub.currency,
        "billing_period": active_sub.billing_period,
        "current_period_start": active_sub.current_period_start.isoformat() if active_sub.current_period_start else None,
        "current_period_end": active_sub.current_period_end.isoformat() if active_sub.current_period_end else None,
        "monthly_detections_limit": active_sub.api_calls_limit,
        "stripe_customer_id": active_sub.stripe_customer_id,
        "features": get_plan_features(current_user.role)
    }


@app.get("/api/plans")
async def get_available_plans():
    """Get all available subscription plans"""
    
    return {
        "plans": [
            {
                "id": "free",
                "name": "Free",
                "price": 0,
                "currency": "USD",
                "billing_period": "forever",
                "detections_limit": 5,
                "features": [
                    "5 detections per month",
                    "Basic symbol detection",
                    "JSON, CSV, Excel export",
                    "Standard support"
                ],
                "stripe_price_id": None
            },
            {
                "id": "pro",
                "name": "Professional",
                "price": 49,
                "currency": "USD",
                "billing_period": "month",
                "detections_limit": 100,
                "features": [
                    "100 detections per month",
                    "Advanced symbol detection",
                    "Custom model training",
                    "All export formats",
                    "Priority support",
                    "API access"
                ],
                "stripe_price_id": os.getenv("STRIPE_PRO_PRICE_ID", "price_pro_monthly")
            },
            {
                "id": "enterprise",
                "name": "Enterprise",
                "price": 199,
                "currency": "USD",
                "billing_period": "month",
                "detections_limit": 1000,
                "features": [
                    "1000 detections per month",
                    "Advanced symbol detection",
                    "Unlimited custom models",
                    "Batch processing",
                    "All export formats",
                    "Dedicated support",
                    "API access",
                    "White-label option"
                ],
                "stripe_price_id": os.getenv("STRIPE_ENTERPRISE_PRICE_ID", "price_enterprise_monthly")
            }
        ]
    }


@app.post("/user/create-checkout-session")
async def create_checkout_session(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create Stripe checkout session for plan upgrade"""
    
    if plan_id not in ["pro", "enterprise"]:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    # Get plan details
    plans_response = await get_available_plans()
    plan = next((p for p in plans_response["plans"] if p["id"] == plan_id), None)
    
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    try:
        # Create or get Stripe customer
        customers = stripe.Customer.list(email=current_user.email, limit=1)
        if customers.data:
            customer_id = customers.data[0].id
        else:
            customer = stripe.Customer.create(
                email=current_user.email,
                name=current_user.full_name,
                metadata={"user_id": str(current_user.id)}
            )
            customer_id = customer.id
        
        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': plan["stripe_price_id"],
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f'https://mepdetect.com/dashboard.html?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url='https://mepdetect.com/dashboard.html?upgrade=cancelled',
            metadata={
                "user_id": str(current_user.id),
                "plan_id": plan_id
            }
        )
        
        return {
            "checkout_url": checkout_session.url,
            "session_id": checkout_session.id
        }
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/user/cancel-subscription")
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel user's active subscription"""
    
    active_sub = db.query(Subscription)\
        .filter(Subscription.user_id == current_user.id)\
        .filter(Subscription.status == SubscriptionStatus.ACTIVE)\
        .first()
    
    if not active_sub:
        raise HTTPException(status_code=404, detail="No active subscription found")
    
    try:
        # Cancel in Stripe
        if active_sub.stripe_subscription_id:
            stripe.Subscription.modify(
                active_sub.stripe_subscription_id,
                cancel_at_period_end=True
            )
        
        # Update in database
        active_sub.status = SubscriptionStatus.CANCELLED
        db.commit()
        
        return {
            "message": "Subscription cancelled successfully",
            "cancels_at": active_sub.current_period_end.isoformat() if active_sub.current_period_end else None
        }
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/user/billing-history")
async def get_billing_history(
    limit: int = 10,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's billing/order history"""
    
    orders = db.query(Order)\
        .filter(Order.user_id == current_user.id)\
        .order_by(desc(Order.created_at))\
        .limit(limit)\
        .offset(offset)\
        .all()
    
    return {
        "orders": [
            {
                "id": order.id,
                "order_number": order.order_number,
                "description": order.description,
                "amount": order.amount,
                "currency": order.currency,
                "status": order.status,
                "invoice_url": order.invoice_url,
                "paid_at": order.paid_at.isoformat() if order.paid_at else None,
                "created_at": order.created_at.isoformat()
            }
            for order in orders
        ]
    }


def get_plan_features(role: UserRole) -> List[str]:
    """Get feature list for a role"""
    
    if role == UserRole.FREE:
        return [
            "5 detections per month",
            "Basic symbol detection",
            "JSON, CSV, Excel export",
            "Standard support"
        ]
    elif role == UserRole.PRO:
        return [
            "100 detections per month",
            "Advanced symbol detection",
            "Custom model training",
            "All export formats",
            "Priority support",
            "API access"
        ]
    elif role == UserRole.ENTERPRISE:
        return [
            "1000 detections per month",
            "Advanced symbol detection",
            "Unlimited custom models",
            "Batch processing",
            "All export formats",
            "Dedicated support",
            "API access",
            "White-label option"
        ]
    else:  # ADMIN
        return ["Unlimited access to all features"]


# ============================================================================
# Stripe Webhook Handler
# ============================================================================

@app.post("/api/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """Handle Stripe webhook events"""
    
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv("STRIPE_WEBHOOK_SECRET")
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle subscription events
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        # Get user
        user_id = int(session['metadata']['user_id'])
        plan_id = session['metadata']['plan_id']
        
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            # Update user role
            if plan_id == "pro":
                user.role = UserRole.PRO
            elif plan_id == "enterprise":
                user.role = UserRole.ENTERPRISE
            
            # Create subscription record
            subscription = Subscription(
                user_id=user.id,
                plan_name=plan_id.title(),
                status=SubscriptionStatus.ACTIVE,
                stripe_subscription_id=session.get('subscription'),
                stripe_customer_id=session.get('customer'),
                current_period_start=datetime.now(),
                current_period_end=datetime.now() + timedelta(days=30)
            )
            db.add(subscription)
            db.commit()
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription_id = event['data']['object']['id']
        
        # Find and cancel subscription
        sub = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == subscription_id
        ).first()
        
        if sub:
            sub.status = SubscriptionStatus.EXPIRED
            # Downgrade user to free
            user = db.query(User).filter(User.id == sub.user_id).first()
            if user:
                user.role = UserRole.FREE
            db.commit()
    
    return {"status": "success"}


@app.post("/admin/users/{user_id}/toggle-active", dependencies=[Depends(require_admin)])
async def toggle_user_active(user_id: int, db: Session = Depends(get_db)):
    """Toggle user active status"""
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.is_active = not user.is_active
    db.commit()
    
    return {"success": True, "is_active": user.is_active}


# ============= CONTACT FORM =============

@app.post("/contact")
async def submit_contact_form(form: ContactForm, db: Session = Depends(get_db)):
    """Submit contact form"""
    
    message = ContactMessage(
        name=form.name,
        email=form.email,
        company=form.company,
        message=form.message
    )
    
    db.add(message)
    db.commit()
    
    return {"success": True, "message": "Thank you for contacting us!"}


# ============================================================================
# Email Service Functions
# ============================================================================

def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    email_type: str = "general",
    user_id: Optional[int] = None
):
    """Send email via SMTP"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = EMAIL_FROM
        msg['To'] = to_email
        
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
        
        print(f"✅ Email sent to {to_email}: {subject}")
        return True
        
    except Exception as e:
        print(f"❌ Email send failed to {to_email}: {e}")
        return False


def get_verification_email(user_name: str, verification_link: str) -> str:
    """Email verification template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background: #f5f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: white; border-radius: 12px; overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px 20px; text-align: center; }}
            .header h1 {{ color: white; margin: 0; font-size: 28px; }}
            .content {{ padding: 40px 30px; }}
            .button {{ display: inline-block; background: #00d4ff; color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 20px 0; }}
            .footer {{ background: #f9fafb; padding: 20px; text-align: center; font-size: 12px; color: #6b7280; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎉 Welcome to MEPdetect!</h1>
            </div>
            <div class="content">
                <h2>Hi {user_name},</h2>
                <p>Thanks for signing up! We're excited to have you on board.</p>
                <p>To get started, please verify your email address by clicking the button below:</p>
                <p style="text-align: center;">
                    <a href="{verification_link}" class="button">Verify Email Address</a>
                </p>
                <p style="font-size: 14px; color: #6b7280;">
                    Or copy and paste this link into your browser:<br>
                    <a href="{verification_link}">{verification_link}</a>
                </p>
                <p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
                    This link will expire in 24 hours.
                </p>
            </div>
            <div class="footer">
                <p>MEPdetect - Automated MEP Symbol Detection</p>
                <p>If you didn't create an account, please ignore this email.</p>
            </div>
        </div>
    </body>
    </html>
    """


def get_welcome_email(user_name: str) -> str:
    """Welcome email template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background: #f5f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: white; border-radius: 12px; overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px 20px; text-align: center; }}
            .header h1 {{ color: white; margin: 0; font-size: 28px; }}
            .content {{ padding: 40px 30px; }}
            .feature {{ background: #f9fafb; padding: 20px; border-radius: 8px; margin: 15px 0; }}
            .feature h3 {{ margin: 0 0 10px 0; color: #1a1d29; }}
            .button {{ display: inline-block; background: #00d4ff; color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 20px 0; }}
            .footer {{ background: #f9fafb; padding: 20px; text-align: center; font-size: 12px; color: #6b7280; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>✅ You're All Set!</h1>
            </div>
            <div class="content">
                <h2>Welcome, {user_name}! 🎉</h2>
                <p>Your email has been verified and your account is ready to use.</p>
                
                <h3 style="margin-top: 30px;">Here's what you can do:</h3>
                
                <div class="feature">
                    <h3>📊 Upload Drawings</h3>
                    <p>Upload PDF or image files of your MEP drawings for instant symbol detection.</p>
                </div>
                
                <div class="feature">
                    <h3>🤖 AI Detection</h3>
                    <p>Our YOLO11 AI models automatically detect electrical, HVAC, and plumbing symbols.</p>
                </div>
                
                <div class="feature">
                    <h3>📥 Export Results</h3>
                    <p>Download results in CSV, Excel, JSON, or annotated images.</p>
                </div>
                
                <p style="text-align: center; margin-top: 30px;">
                    <a href="{BASE_URL}/dashboard.html" class="button">Go to Dashboard</a>
                </p>
                
                <p style="margin-top: 40px; font-size: 14px; color: #6b7280;">
                    <strong>Need help?</strong> Contact us anytime through the dashboard's Support section.
                </p>
            </div>
            <div class="footer">
                <p>MEPdetect - Automated MEP Symbol Detection</p>
                <p><a href="{BASE_URL}">mepdetect.com</a></p>
            </div>
        </div>
    </body>
    </html>
    """


def get_message_reply_email(user_name: str, original_message: str, reply: str) -> str:
    """Message reply template"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background: #f5f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: white; border-radius: 12px; overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px 20px; text-align: center; }}
            .header h1 {{ color: white; margin: 0; font-size: 24px; }}
            .content {{ padding: 30px; }}
            .message-box {{ background: #f9fafb; padding: 20px; border-left: 4px solid #00d4ff; border-radius: 4px; margin: 20px 0; }}
            .footer {{ background: #f9fafb; padding: 20px; text-align: center; font-size: 12px; color: #6b7280; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📧 Reply from MEPdetect Support</h1>
            </div>
            <div class="content">
                <p>Hi {user_name},</p>
                <p>We've replied to your message:</p>
                
                <div class="message-box">
                    <strong>Your message:</strong><br>
                    {original_message}
                </div>
                
                <div class="message-box" style="border-left-color: #10b981;">
                    <strong>Our reply:</strong><br>
                    {reply}
                </div>
                
                <p style="margin-top: 30px;">
                    If you have any further questions, feel free to reply to this email or contact us through your dashboard.
                </p>
            </div>
            <div class="footer">
                <p>MEPdetect Support Team</p>
                <p><a href="{BASE_URL}">mepdetect.com</a></p>
            </div>
        </div>
    </body>
    </html>
    """


# ============================================================================
# Contact Messages & Support
# ============================================================================

class ContactMessageCreate(BaseModel):
    name: str
    email: str
    subject: Optional[str] = None
    message: str


@app.post("/contact/message")
async def submit_contact_message(
    msg: ContactMessageCreate,
    db: Session = Depends(get_db)
):
    """Submit a contact message"""
    
    result = db.execute(text("""
        INSERT INTO contact_messages (name, email, subject, message, status)
        VALUES (:name, :email, :subject, :message, 'new')
        RETURNING id
    """), {
        "name": msg.name,
        "email": msg.email,
        "subject": msg.subject or "General Inquiry",
        "message": msg.message
    })
    
    db.commit()
    message_id = result.first()[0]
    
    return {
        "id": message_id,
        "message": "Message sent successfully. We'll get back to you soon!"
    }


@app.get("/user/messages")
async def get_user_messages(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all messages from current user"""
    
    messages = db.execute(text("""
        SELECT id, subject, message, status, admin_reply, 
               replied_at, created_at
        FROM contact_messages
        WHERE email = :email
        ORDER BY created_at DESC
    """), {"email": current_user.email})
    
    result = []
    for msg in messages:
        result.append({
            "id": msg.id,
            "subject": msg.subject,
            "message": msg.message,
            "status": msg.status,
            "admin_reply": msg.admin_reply,
            "replied_at": msg.replied_at.isoformat() if msg.replied_at else None,
            "created_at": msg.created_at.isoformat() if msg.created_at else None
        })
    
    return {"messages": result}


@app.get("/admin/messages", dependencies=[Depends(require_admin)])
async def get_all_messages(
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all contact messages (admin only)"""
    
    query = """
        SELECT cm.*, u.email as user_email, 
               admin.email as replied_by_email
        FROM contact_messages cm
        LEFT JOIN users u ON cm.email = u.email
        LEFT JOIN users admin ON cm.replied_by = admin.id
    """
    
    if status:
        query += " WHERE cm.status = :status"
    
    query += " ORDER BY cm.created_at DESC"
    
    params = {"status": status} if status else {}
    messages = db.execute(text(query), params)
    
    result = []
    for msg in messages:
        result.append({
            "id": msg.id,
            "user_email": msg.user_email,
            "name": msg.name,
            "email": msg.email,
            "subject": msg.subject,
            "message": msg.message,
            "status": msg.status,
            "priority": msg.priority if hasattr(msg, 'priority') else 'normal',
            "admin_reply": msg.admin_reply,
            "replied_by_email": msg.replied_by_email,
            "replied_at": msg.replied_at.isoformat() if msg.replied_at else None,
            "created_at": msg.created_at.isoformat() if msg.created_at else None
        })
    
    return {"messages": result}


class MessageReply(BaseModel):
    reply: str
    send_email: bool = True


@app.post("/admin/messages/{message_id}/reply", dependencies=[Depends(require_admin)])
async def reply_to_message(
    message_id: int,
    reply_data: MessageReply,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reply to a contact message"""
    
    msg = db.execute(
        text("SELECT * FROM contact_messages WHERE id = :id"),
        {"id": message_id}
    ).first()
    
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    db.execute(text("""
        UPDATE contact_messages
        SET admin_reply = :reply,
            replied_by = :admin_id,
            replied_at = NOW(),
            status = 'replied',
            updated_at = NOW()
        WHERE id = :message_id
    """), {
        "reply": reply_data.reply,
        "admin_id": current_user.id,
        "message_id": message_id
    })
    
    db.commit()
    
    if reply_data.send_email:
        send_email(
            to_email=msg.email,
            subject=f"Re: {msg.subject}",
            html_body=get_message_reply_email(msg.name, msg.message, reply_data.reply),
            email_type="message_reply"
        )
    
    return {"message": "Reply sent successfully"}


@app.put("/admin/messages/{message_id}/status", dependencies=[Depends(require_admin)])
async def update_message_status(
    message_id: int,
    status: str,
    db: Session = Depends(get_db)
):
    """Update message status"""
    
    if status not in ['new', 'read', 'replied', 'closed']:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    db.execute(text("""
        UPDATE contact_messages
        SET status = :status, updated_at = NOW()
        WHERE id = :message_id
    """), {"status": status, "message_id": message_id})
    
    db.commit()
    
    return {"message": "Status updated"}


# ============================================================================
# Email Verification
# ============================================================================

@app.post("/auth/send-verification")
async def send_verification_email_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send email verification link"""
    
    if current_user.email_verified:
        return {"message": "Email already verified"}
    
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=24)
    
    db.execute(text("""
        INSERT INTO email_verifications (user_id, token, expires_at)
        VALUES (:user_id, :token, :expires_at)
        ON CONFLICT (user_id) 
        DO UPDATE SET token = :token, expires_at = :expires_at, created_at = NOW()
    """), {
        "user_id": current_user.id,
        "token": token,
        "expires_at": expires_at
    })
    
    db.commit()
    
    verification_link = f"{BASE_URL}/verify-email.html?token={token}"
    
    send_email(
        to_email=current_user.email,
        subject="Verify your MEPdetect email address",
        html_body=get_verification_email(current_user.full_name or "there", verification_link),
        email_type="verification",
        user_id=current_user.id
    )
    
    return {"message": "Verification email sent. Please check your inbox."}


@app.get("/auth/verify-email")
async def verify_email(
    token: str,
    db: Session = Depends(get_db)
):
    """Verify email with token"""
    
    verification = db.execute(
        text("""
            SELECT ev.*, u.email, u.full_name
            FROM email_verifications ev
            JOIN users u ON ev.user_id = u.id
            WHERE ev.token = :token AND ev.verified = false
        """),
        {"token": token}
    ).first()
    
    if not verification:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    
    if verification.expires_at < datetime.now():
        raise HTTPException(status_code=400, detail="Verification link has expired")
    
    db.execute(text("""
        UPDATE email_verifications
        SET verified = true, verified_at = NOW()
        WHERE token = :token
    """), {"token": token})
    
    db.execute(text("""
        UPDATE users
        SET email_verified = true, email_verified_at = NOW()
        WHERE id = :user_id
    """), {"user_id": verification.user_id})
    
    db.commit()
    
    send_email(
        to_email=verification.email,
        subject="Welcome to MEPdetect! 🎉",
        html_body=get_welcome_email(verification.full_name or "there"),
        email_type="welcome",
        user_id=verification.user_id
    )
    
    return {"message": "Email verified successfully! Welcome to MEPdetect."}


# ============= WEBHOOKS =============

@app.post("/webhooks/stripe")
async def stripe_webhook(request: dict, stripe_signature: str = Header(None), db: Session = Depends(get_db)):
    """Handle Stripe webhooks"""
    
    # Verify webhook signature
    webhook_secret = "whsec_..."  # From Stripe
    
    try:
        event = stripe.Webhook.construct_event(
            request, stripe_signature, webhook_secret
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Handle different event types
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        # Create subscription record
        user_id = session['metadata']['user_id']
        plan_name = session['metadata']['plan_name']
        
        subscription = Subscription(
            user_id=user_id,
            plan_name=plan_name,
            status=SubscriptionStatus.ACTIVE,
            stripe_subscription_id=session['subscription'],
            stripe_customer_id=session['customer']
        )
        
        db.add(subscription)
        
        # Update user role
        user = db.query(User).filter(User.id == user_id).first()
        user.role = UserRole.PRO if plan_name == "pro" else UserRole.ENTERPRISE
        user.api_calls_limit = 10000 if plan_name == "pro" else 999999
        
        db.commit()
    
    return {"success": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8093)