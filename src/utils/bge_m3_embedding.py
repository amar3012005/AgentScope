"""
BGEM3Embeddings - Powered by OpenAI-compatible API (LiteLLM)
Drop-in replacement for previous implementations.

Migration to OpenAI-compatible:
- Uses OpenAI-compatible API format (v1/embeddings)
- Configured via BGE_M3_SERVICE_URL and BGE_M3_API_KEY
- Removes all AWS dependencies
"""

import os
from typing import List

from dotenv import load_dotenv

# Use standard OpenAI client which is compatible with LiteLLM
try:
    from openai import OpenAI
except ImportError:
    raise ImportError("Could not import openai python package. Please install it with `pip install openai`.")

# Load environment variables
load_dotenv()


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
        self.model_id = model_id or env_model_id or "BAAI/bge-m3"

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

        print(
            "[BGEM3Embeddings:init] "
            f"service_url={self.service_url}, host={service_host}, "
            f"model_id={self.model_id}, dim={self.embedding_dim}"
        )

        # Initialize OpenAI Client
        try:
            self.client = OpenAI(
                base_url=self.service_url,
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize OpenAI client: {e}")

        # Compatibility flags
        self.service_available = True
        self.consecutive_failures = 0

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple documents.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        try:
            print(
                f"[BGEM3Embeddings:embed_documents] "
                f"n_texts={len(texts)}, model={self.model_id}, dim={self.embedding_dim}"
            )
            # OpenAI/LiteLLM standard embedding call
            response = self.client.embeddings.create(
                input=texts,
                model=self.model_id,
                # for Vertex/Gemini via LiteLLM: map to outputDimensionality
                dimensions=self.embedding_dim,
            )
            
            # Extract embeddings ensuring order
            sorted_data = sorted(response.data, key=lambda x: x.index)
            if sorted_data:
                print(
                    f"[BGEM3Embeddings:embed_documents] "
                    f"received_dim={len(sorted_data[0].embedding)}"
                )
            return [data.embedding for data in sorted_data]

        except Exception as e:
            raise Exception(f"Failed to embed documents: {e}")

    def embed_query(self, text: str) -> List[float]:
        """
        Embed a single query text.

        Args:
            text: Text string to embed

        Returns:
            Embedding vector
        """
        if not text:
            raise ValueError("Text cannot be empty")

        try:
            print(
                f"[BGEM3Embeddings:embed_query] "
                f"len(text)={len(text)}, model={self.model_id}, dim={self.embedding_dim}"
            )
            response = self.client.embeddings.create(
                input=[text],
                model=self.model_id,
                dimensions=self.embedding_dim,
            )
            embedding = response.data[0].embedding
            print(
                f"[BGEM3Embeddings:embed_query] "
                f"received_dim={len(embedding)}"
            )
            return embedding

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
