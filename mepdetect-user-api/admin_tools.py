#!/usr/bin/env python3
"""
Admin User Initialization Script
Creates the first admin user for MEPdetect platform
"""

import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from getpass import getpass

# Import models and auth
from db_models import Base, User, UserRole
from auth import hash_password, generate_api_key

# Misma fuente que user_api (obligatorio en Docker: host postgres, no localhost)
# No credential fallback: the connection string comes from the environment.
DATABASE_URL = os.environ["DATABASE_URL"]

def create_admin_user():
    """Create admin user interactively"""
    
    print("=" * 50)
    print("MEPdetect - Admin User Creation")
    print("=" * 50)
    print()
    
    # Get admin details
    email = input("Admin Email: ").strip()
    full_name = input("Full Name: ").strip()
    password = getpass("Password (min 8 chars): ")
    password_confirm = getpass("Confirm Password: ")
    
    # Validate
    if not email or '@' not in email:
        print("❌ Invalid email address")
        sys.exit(1)
    
    if not full_name:
        print("❌ Full name is required")
        sys.exit(1)
    
    if len(password) < 8:
        print("❌ Password must be at least 8 characters")
        sys.exit(1)
    
    if password != password_confirm:
        print("❌ Passwords do not match")
        sys.exit(1)
    
    # Create database connection
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        # Check if user exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            print(f"❌ User with email {email} already exists")
            sys.exit(1)
        
        # Create admin user
        admin_user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
            email_verified=True,
            api_key=generate_api_key(),
            api_calls_limit=999999  # Unlimited for admin
        )
        
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        
        print()
        print("✅ Admin user created successfully!")
        print()
        print(f"Email: {admin_user.email}")
        print(f"Name: {admin_user.full_name}")
        print(f"Role: {admin_user.role.value}")
        print(f"API Key: {admin_user.api_key}")
        print()
        print("You can now login at: http://localhost:8093/login.html")
        print()
        
    except Exception as e:
        print(f"❌ Error creating admin user: {str(e)}")
        db.rollback()
        sys.exit(1)
    
    finally:
        db.close()


def list_users():
    """List all users in the database"""
    
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        users = db.query(User).all()
        
        if not users:
            print("No users found in database")
            return
        
        print()
        print("=" * 80)
        print(f"{'Email':<30} {'Name':<20} {'Role':<12} {'Active':<8}")
        print("=" * 80)
        
        for user in users:
            print(f"{user.email:<30} {user.full_name:<20} {user.role.value:<12} {str(user.is_active):<8}")
        
        print("=" * 80)
        print(f"Total users: {len(users)}")
        print()
        
    finally:
        db.close()


def reset_password():
    """Reset user password"""
    
    email = input("User Email: ").strip()
    new_password = getpass("New Password: ")
    confirm_password = getpass("Confirm Password: ")
    
    if new_password != confirm_password:
        print("❌ Passwords do not match")
        sys.exit(1)
    
    if len(new_password) < 8:
        print("❌ Password must be at least 8 characters")
        sys.exit(1)
    
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            print(f"❌ User {email} not found")
            sys.exit(1)
        
        user.hashed_password = hash_password(new_password)
        db.commit()
        
        print(f"✅ Password reset for {email}")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
    
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="MEPdetect Admin Tools")
    parser.add_argument("command", choices=["create-admin", "list-users", "reset-password"],
                       help="Command to execute")
    
    args = parser.parse_args()
    
    if args.command == "create-admin":
        create_admin_user()
    elif args.command == "list-users":
        list_users()
    elif args.command == "reset-password":
        reset_password()
