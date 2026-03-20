"""
API Key Authentication
"""

import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery

load_dotenv()

# Define API key header
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

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


def _extract_key(
    x_api_key: Optional[str],
    query_api_key: Optional[str],
    bearer: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    """Resolve API key from supported transports."""
    if x_api_key:
        return x_api_key
    if query_api_key:
        return query_api_key
    if bearer and bearer.scheme.lower() == "bearer" and bearer.credentials:
        return bearer.credentials
    return None


async def verify_api_key(
    x_api_key: Optional[str] = Security(api_key_header),
    query_api_key: Optional[str] = Security(api_key_query),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> str:
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
    api_key = _extract_key(x_api_key, query_api_key, bearer)

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing API Key. Use one of: "
                "'Authorization: Bearer <key>', "
                "'X-API-Key: <key>', or '?api_key=<key>'."
            ),
        )

    # Verify API key
    if api_key not in VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )

    return api_key


# Optional: Create a version that doesn't auto-error (for optional auth)
async def optional_api_key(
    x_api_key: Optional[str] = Security(api_key_header),
    query_api_key: Optional[str] = Security(api_key_query),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Optional[str]:
    """
    Optional API key verification (doesn't raise error if missing).
    Returns None if no key provided.
    """
    api_key = _extract_key(x_api_key, query_api_key, bearer)

    if not api_key:
        return None

    if VALID_API_KEYS and api_key not in VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )

    return api_key
