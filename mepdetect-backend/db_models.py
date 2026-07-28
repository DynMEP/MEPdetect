"""
Database Models
User management, subscriptions, orders, and usage tracking
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    ADMIN = "admin"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"
    TRIALING = "trialing"
    EXPIRED = "expired"


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    company = Column(String)
    phone = Column(String)
    
    role = Column(Enum(UserRole), default=UserRole.FREE)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    
    # API Access
    api_key = Column(String, unique=True, index=True)
    api_calls_count = Column(Integer, default=0)
    api_calls_limit = Column(Integer, default=100)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True))
    
    # Password reset fields
    reset_token = Column(String, nullable=True)
    reset_token_expires = Column(DateTime(timezone=True), nullable=True)
    
    subscriptions = relationship("Subscription", back_populates="user")
    orders = relationship("Order", back_populates="user")
    usage_logs = relationship("UsageLog", back_populates="user")
    models = relationship("CustomModel", back_populates="user")


class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    plan_name = Column(String)
    status = Column(Enum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE)
    price = Column(Float)
    currency = Column(String, default="USD")
    billing_period = Column(String)
    
    stripe_subscription_id = Column(String, unique=True)
    stripe_customer_id = Column(String)
    
    api_calls_limit = Column(Integer)
    storage_limit_gb = Column(Float)
    custom_models_limit = Column(Integer)
    
    current_period_start = Column(DateTime(timezone=True))
    current_period_end = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="subscriptions")


class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    order_number = Column(String, unique=True, index=True)
    description = Column(String)
    amount = Column(Float)
    currency = Column(String, default="USD")
    status = Column(String)
    
    stripe_payment_intent_id = Column(String)
    invoice_url = Column(String)
    
    paid_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="orders")


class UsageLog(Base):
    __tablename__ = "usage_logs"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    endpoint = Column(String)
    file_count = Column(Integer, default=1)
    detections_count = Column(Integer)
    processing_time = Column(Float)
    model_name = Column(String)
    credits_used = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="usage_logs")
    custom_model = relationship("CustomModel", back_populates="usage_logs")
    custom_model_id = Column(Integer, ForeignKey("custom_models.id"), nullable=True)


class CustomModel(Base):
    __tablename__ = "custom_models"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    model_name = Column(String)
    model_path = Column(String)
    class_names = Column(JSON)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="models")
    usage_logs = relationship("UsageLog", back_populates="custom_model")


class ContactMessage(Base):
    __tablename__ = "contact_messages"
    
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String)
    company = Column(String)
    message = Column(String)
    status = Column(String, default="new")
    created_at = Column(DateTime(timezone=True), server_default=func.now())