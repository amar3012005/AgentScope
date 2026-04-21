"""
BGEM3Embeddings - Powered by OpenAI-compatible API (LiteLLM)
Drop-in replacement for previous implementations.

Migration to OpenAI-compatible:
- Uses OpenAI-compatible API format (v1/embeddings)
- Configured via BGE_M3_SERVICE_URL and BGE_M3_API_KEY
- Removes all AWS dependencies
"""

import os
import logging
from typing import List

from dotenv import load_dotenv

# Use standard OpenAI client which is compatible with LiteLLM
try:
    from openai import OpenAI
except ImportError:
    raise ImportError("Could not import openai python package. Please install it with `pip install openai`.")

# Load environment variables
load_dotenv()
logger = logging.getLogger("bge_m3_embedding")


class BGEM3Embeddings:
    """
    OpenAI-compatible Embeddings Client (LiteLLM).
    
    Uses BGE_M3_SERVICE_URL and BGE_M3_API_KEY from environment 
    to connect to a LiteLLM or OpenAI-compatible embedding service.
    """

    def __init__(
        self,
        service_url: str = None,
        api_key: str = None,
        timeout: int = 180,
        max_retries: int = 3,
        model_id: str = None,
        # model_id: str = os.getenv("BGE_M3_MODEL_ID", "BAAI/bge-m3"),  # Default model name
        retry_delay: float = 2.0,
        backoff_factor: float = 2.0,
        **kwargs
    ):
        """
        Initialize OpenAI-compatible embeddings client.

        Args:
            service_url: Base URL for the embedding service. Defaults to BGE_M3_SERVICE_URL env var.
            api_key: API Key for the service. Defaults to BGE_M3_API_KEY env var.
            timeout: Request timeout in seconds
            max_retries: Max retry attempts (handled by OpenAI client)
            model_id: Model name to request (default: BAAI/bge-m3)
        """
        # Configuration priority: Argument > Env Var
        self.service_url = service_url or os.getenv("BGE_M3_SERVICE_URL")
        self.api_key = api_key or os.getenv("BGE_M3_API_KEY")
        
        # Fallback if critical config is missing
        if not self.service_url:
            # Try OPENAI_API_BASE_URL as fallback if BGE specific one is missing
            self.service_url = os.getenv("OPENAI_API_BASE_URL")
            
        if not self.api_key:
            self.api_key = os.getenv("OPENAI_API_KEY", "sk-placeholder")

        # Priority: argument > env > default
        env_model_id = os.getenv("BGE_M3_MODEL_ID")
        self.model_id = model_id or env_model_id or "bge-m3"

        # Store request config
        self.timeout = timeout
        self.max_retries = max_retries
        
        # Model configuration
        self.embedding_dim = 1024
        self.normalize = True

        if not self.service_url:
            raise ValueError(
                "Service URL not found! Set BGE_M3_SERVICE_URL or OPENAI_API_BASE_URL in .env file"
            )

        # Debug: show resolved embedding configuration
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.service_url) if self.service_url else None
            service_host = parsed.hostname if parsed else None
        except Exception:
            service_host = None

        logger.info(
            "event=embedding_client_init service_url=%s host=%s model_id=%s dim=%s",
            self.service_url,
            service_host,
            self.model_id,
            self.embedding_dim,
        )

        # Initialize OpenAI Client (with SSL bypass for proxy)
        try:
            import httpx
            self.client = OpenAI(
                base_url=self.service_url,
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=self.max_retries,
                http_client=httpx.Client(verify=False)
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize OpenAI client: {e}")

        # Compatibility flags
        self.service_available = True
        self.consecutive_failures = 0

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple documents using direct requests to the proxy.
        (Matches working curl configuration)
        """
        if not texts:
            return []

        try:
            import requests
            url = self.service_url.rstrip("/")
            if not url.endswith("/embed"):
                url += "/embed"
            
            resp = requests.post(
                url,
                json={"texts": texts},
                headers={"api-key": self.api_key},
                timeout=self.timeout,
                verify=False
            )
            
            if resp.status_code == 200:
                return resp.json().get("embeddings", [])
            else:
                raise Exception(f"Failed to embed (Status {resp.status_code}): {resp.text}")
        except Exception as e:
            raise Exception(f"Failed to embed documents: {e}")

    def embed_query(self, text: str) -> List[float]:
        """
        Embed a single query text.
        """
        if not text:
            raise ValueError("Text cannot be empty")

        try:
            import requests
            url = self.service_url.rstrip("/")
            if not url.endswith("/embed"):
                url += "/embed"
            
            resp = requests.post(
                url,
                json={"texts": [text]},
                headers={"api-key": self.api_key},
                timeout=self.timeout,
                verify=False
            )
            
            if resp.status_code == 200:
                embeddings = resp.json().get("embeddings", [])
                return embeddings[0] if embeddings else []
            else:
                raise Exception(f"Failed to embed (Status {resp.status_code}): {resp.text}")
        except Exception as e:
            raise Exception(f"Failed to embed query: {e}")

    # Compatibility methods
    def is_available(self) -> bool:
        return self.service_available

    def reset_circuit_breaker(self):
        self.consecutive_failures = 0
        self.service_available = True

    def get_status(self) -> dict:
        return {
            "service": "OpenAI-compatible (LiteLLM)",
            "model": self.model_id,
            "url": self.service_url,
            "dimension": self.embedding_dim,
            "service_available": self.service_available,
        }

    def close(self):
        if hasattr(self.client, "close"):
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

# Test the replacement
if __name__ == "__main__":
    print("=" * 60)
    print("Testing BGEM3Embeddings (via OpenAI-compatible API)")
    print("=" * 60)

    try:
        embeddings = BGEM3Embeddings()
        print(f"\n✅ Initialized with URL: {embeddings.service_url}")
        
        # Test single query (requires running service)
        print("\n1. Testing single query...")
        try:
            vec = embeddings.embed_query("test")
            print(f"   ✅ Success! Dimension: {len(vec)}")
        except Exception as e:
            print(f"   ⚠️ Query failed (Expected if service is not running): {e}")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
