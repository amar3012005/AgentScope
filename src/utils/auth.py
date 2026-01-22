"""
API Key Authentication
"""

import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

load_dotenv()

# Define API key header
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# Load API keys from environment
VALID_API_KEYS = set()

# Support multiple API keys (comma-separated in env)
api_keys_env = os.getenv("API_KEYS", "")
if api_keys_env:
    VALID_API_KEYS = {key.strip() for key in api_keys_env.split(",") if key.strip()}

# Fallback to single API key
single_key = os.getenv("API_KEY", "")
if single_key:
    VALID_API_KEYS.add(single_key.strip())


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    """
    Verify API key from request header.

    Raises:
        HTTPException: If API key is missing or invalid

    Returns:
        str: The validated API key
    """
    # Check if authentication is enabled
    if not VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API authentication is not configured. Set API_KEY or API_KEYS environment variable.",
        )

    # Check if API key was provided
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key. Include 'X-API-Key' header in your request.",
        )

    # Verify API key
    if api_key not in VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )

    return api_key


# Optional: Create a version that doesn't auto-error (for optional auth)
async def optional_api_key(api_key: Optional[str] = Security(api_key_header)) -> Optional[str]:
    """
    Optional API key verification (doesn't raise error if missing).
    Returns None if no key provided.
    """
    if not api_key:
        return None

    if VALID_API_KEYS and api_key not in VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )

    return api_key
