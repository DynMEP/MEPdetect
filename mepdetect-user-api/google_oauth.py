"""
Google OAuth ID token verification for Sign in with Google.
"""

import os
from typing import Any, Dict

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")


def is_google_oauth_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID)


def verify_google_id_token(token: str) -> Dict[str, Any]:
    """Verify a Google ID token (credential from GIS) and return claims."""
    if not GOOGLE_CLIENT_ID:
        raise ValueError("Google OAuth is not configured (GOOGLE_CLIENT_ID missing)")

    idinfo = id_token.verify_oauth2_token(
        token,
        google_requests.Request(),
        GOOGLE_CLIENT_ID,
    )

    issuer = idinfo.get("iss")
    if issuer not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError("Invalid token issuer")

    if not idinfo.get("email"):
        raise ValueError("Google account has no email")

    if idinfo.get("email_verified") is False:
        raise ValueError("Google email is not verified")

    return idinfo
