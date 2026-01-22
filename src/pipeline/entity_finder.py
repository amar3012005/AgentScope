# src/pipeline/entity_finder.py

# %%
import gc
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import dependencies with fallbacks
try:
    from utils.bge_m3_embedding import BGEM3Embeddings

    BGE_M3_AVAILABLE = True
except ImportError:
    print("⚠️ BGE-M3 embeddings not available for schema normalization")
    BGE_M3_AVAILABLE = False

from langchain.schema import HumanMessage

try:
    from langchain_openai import ChatOpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    print("⚠️ langchain-openai not available - required for entity extraction")
    OPENAI_AVAILABLE = False


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def cosine_similarity_numpy(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between vectors using only numpy

    Args:
        a: Query vector (1D or 2D array)
        b: Reference vectors (2D array where each row is a vector)

    Returns:
        Similarity scores (1D array)
    """
    # Ensure a is 2D (1, dimensions)
    if a.ndim == 1:
        a = a.reshape(1, -1)

    # Normalize vectors
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-10)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-10)

    # Compute cosine similarity (dot product of normalized vectors)
    similarities = np.dot(a_norm, b_norm.T)

    # Return as 1D array
    if similarities.shape[0] == 1:
        return similarities[0]
    return similarities


# %%
@dataclass
class ProcessingTask:
    """Data class for processing tasks"""

    doc_id: str
    text: str
    metadata: Dict
    chunk_id: Optional[str] = None


@dataclass
class ExtractionResult:
    """Data class for extraction results"""

    doc_id: str
    entities: List[Dict]
    relationships: List[Dict]
    processing_time: float
    error: Optional[str] = None
    chunk_id: Optional[str] = None


# %%
class FastEntitySchema:
    """Schema manager that loads from schema files with optimized normalization"""

    def __init__(self, schema_dir: str = None, config_path: str = "config.yaml"):
        """
        Initialize entity schema with BGE-M3 embeddings for type normalization

        Args:
            schema_dir: Directory containing entity_types.json and relationship_types.json.
                       If None, will try to load from config.yaml or use default "schemas"
            config_path: Path to config.yaml for fallback schema_dir

        Strategy:
        1. String matching (fast, no API calls)
        2. Case-insensitive matching
        3. Alias lookup
        4. BGE-M3 similarity matching (for unknown/creative types from LLM)
        """
        # Determine schema directory
        if schema_dir:
            self.schema_dir = Path(schema_dir)
        else:
            # Try to load schema dir from config
            try:
                with open(config_path, "r") as f:
                    config = yaml.safe_load(f)
                    if "schema" in config and "schema_dir" in config["schema"]:
                        self.schema_dir = Path(config["schema"]["schema_dir"])
                    else:
                        self.schema_dir = Path("schemas")
            except:
                self.schema_dir = Path("schemas")

        print(f"📂 Loading schema from: {self.schema_dir}")

        # Load schemas from files
        self.entity_types = self._load_entity_schema()
        self.relationship_types = self._load_relationship_schema()

        # Get allowed types lists
        self.allowed_entity_types = list(self.entity_types.keys())
        self.allowed_relationship_types = list(self.relationship_types.keys())

        # Create case-insensitive lookup sets for faster normalization
        self._entity_types_upper = {t.upper(): t for t in self.allowed_entity_types}
        self._relationship_types_upper = {t.upper(): t for t in self.allowed_relationship_types}

        # Create alias lookup maps for faster normalization
        self._entity_aliases = {}
        for entity_type, info in self.entity_types.items():
            for alias in info.get("aliases", []):
                self._entity_aliases[alias.lower()] = entity_type

        # Initialize BGE-M3 embeddings for similarity matching
        self.embedding_model = None
        self._entity_embeddings_cache = None
        self._relationship_embeddings_cache = None

        # Load embedding model config
        embedding_config = self._load_embedding_config(config_path)

        # Initialize BGE-M3 if available and enabled
        if BGE_M3_AVAILABLE and embedding_config.get("enabled", True):
            try:
                self.embedding_model = BGEM3Embeddings()
                print("✅ Schema normalization: BGE-M3 embeddings enabled")
                print("   This allows mapping creative LLM entity types to schema types")
            except Exception as e:
                print(f"⚠️ Could not initialize BGE-M3 for schema normalization: {e}")
                print("   Falling back to string-matching only")
                self.embedding_model = None
        else:
            if not BGE_M3_AVAILABLE:
                print("⚠️ BGE-M3 not available - using string-matching only")
                print("   Install utils.bge_m3_embeddings for better type mapping")
            else:
                print("✅ Schema normalization: String-matching only (embeddings disabled)")

        print("✅ Schema loaded from files:")
        print(f"   Entity types: {len(self.allowed_entity_types)}")
        print(f"   Relationship types: {len(self.allowed_relationship_types)}")
        print(f"   Entity aliases: {len(self._entity_aliases)}")
        print(
            f"   Embedding fallback: {'Enabled (BGE-M3)' if self.embedding_model else 'Disabled'}"
        )

    def _load_embedding_config(self, config_path: str) -> Dict:
        """Load embedding configuration for schema normalization"""
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
                return config.get("schema", {}).get(
                    "normalization_embedding",
                    {"enabled": True, "provider": "bge-m3"},
                )
        except:
            print("⚠️ Could not load schema embedding config - using defaults")
            return {"enabled": True, "provider": "bge-m3"}

    def _has_gpu(self) -> bool:
        """Check if CUDA GPU is available"""
        try:
            import torch

            return torch.cuda.is_available()
        except ImportError:
            return False

    def _load_entity_schema(self) -> Dict:
        """Load entity schema from JSON file"""
        schema_file = self.schema_dir / "entity_types.json"
        if schema_file.exists():
            with open(schema_file, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            raise FileNotFoundError(f"Entity schema file not found: {schema_file}")

    def _load_relationship_schema(self) -> Dict:
        """Load relationship schema from JSON file"""
        schema_file = self.schema_dir / "relationship_types.json"
        if schema_file.exists():
            with open(schema_file, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            raise FileNotFoundError(f"Relationship schema file not found: {schema_file}")

    def _precompute_embeddings(self):
        """
        Precompute BGE-M3 embeddings for entity and relationship types

        This is called lazily on first use of similarity matching.
        Caches embeddings to avoid repeated API calls.
        """
        if not self.embedding_model:
            return

        if self._entity_embeddings_cache is not None:
            return  # Already computed

        try:
            print("🔄 Pre-computing BGE-M3 embeddings for schema types...")

            # Create rich descriptions for entity types
            entity_descriptions = []
            for entity_type in self.allowed_entity_types:
                info = self.entity_types[entity_type]
                # Combine type, description, examples, and aliases for rich context
                parts = [
                    entity_type,
                    info.get("description", ""),
                    " ".join(info.get("examples", [])),
                    " ".join(info.get("aliases", [])),
                ]
                description = " ".join(filter(None, parts))
                entity_descriptions.append(description)

            # Create descriptions for relationship types
            relationship_descriptions = []
            for rel_type in self.allowed_relationship_types:
                info = self.relationship_types[rel_type]
                parts = [rel_type, info.get("description", ""), " ".join(info.get("examples", []))]
                description = " ".join(filter(None, parts))
                relationship_descriptions.append(description)

            # Compute BGE-M3 embeddings
            self._entity_embeddings_cache = np.array(
                self.embedding_model.embed_documents(entity_descriptions)
            )

            self._relationship_embeddings_cache = np.array(
                self.embedding_model.embed_documents(relationship_descriptions)
            )

            print(
                f"✅ Pre-computed BGE-M3 embeddings: "
                f"{len(self.allowed_entity_types)} entity types, "
                f"{len(self.allowed_relationship_types)} relationship types"
            )

        except Exception as e:
            print(f"⚠️ Failed to pre-compute embeddings: {e}")
            print("   Will fall back to string-matching only")
            self._entity_embeddings_cache = None
            self._relationship_embeddings_cache = None

    def get_entity_type_description(self) -> str:
        """Get formatted entity type descriptions from schema"""
        descriptions = []
        for entity_type, info in self.entity_types.items():
            desc = info.get("description", "")
            examples = info.get("examples", [])
            example_text = ", ".join(examples[:3]) if examples else ""
            descriptions.append(f"- {entity_type}: {desc} (Beispiele: {example_text})")
        return "\n".join(descriptions)

    def get_relationship_type_description(self) -> str:
        """Get formatted relationship type descriptions from schema"""
        descriptions = []
        for rel_type, info in self.relationship_types.items():
            desc = info.get("description", "")
            examples = info.get("examples", [])
            example_text = ", ".join(examples[:2]) if examples else ""
            descriptions.append(f"- {rel_type}: {desc} (z.B. {example_text})")
        return "\n".join(descriptions)

    def normalize_entity_type(self, suggested_type: str) -> str:
        """
        Normalize entity type using multi-stage approach:

        1. Exact match (case-sensitive) - O(1)
        2. Case-insensitive match - O(1)
        3. Alias lookup - O(1)
        4. BGE-M3 similarity (for creative LLM types) - O(n) with API call

        Args:
            suggested_type: Entity type suggested by LLM

        Returns:
            Normalized entity type from schema
        """
        if not suggested_type or not suggested_type.strip():
            return "KONZEPT"

        suggested_type = suggested_type.strip()

        # Stage 1: Direct match (case-sensitive)
        if suggested_type in self.allowed_entity_types:
            return suggested_type

        # Stage 2: Case-insensitive match
        suggested_upper = suggested_type.upper()
        if suggested_upper in self._entity_types_upper:
            return self._entity_types_upper[suggested_upper]

        # Stage 3: Alias lookup (case-insensitive)
        suggested_lower = suggested_type.lower()
        if suggested_lower in self._entity_aliases:
            return self._entity_aliases[suggested_lower]

        # Stage 4: BGE-M3 similarity matching (for unknown types)
        if self.embedding_model:
            # Lazy load embeddings if not already computed
            if self._entity_embeddings_cache is None:
                self._precompute_embeddings()

            if self._entity_embeddings_cache is not None:
                try:
                    # Get BGE-M3 embedding for suggested type
                    suggested_embedding = self.embedding_model.embed_query(suggested_type)
                    suggested_embedding = np.array(suggested_embedding)

                    # Compute cosine similarity with all schema types
                    similarities = cosine_similarity_numpy(
                        suggested_embedding, self._entity_embeddings_cache
                    )

                    # Find best match
                    best_idx = np.argmax(similarities)
                    best_similarity = similarities[best_idx]
                    best_type = self.allowed_entity_types[best_idx]

                    # Only use if similarity is reasonably high (>0.5)
                    if best_similarity > 0.5:
                        return best_type

                except Exception:
                    # Silent fallback - don't spam logs
                    pass

        # Default fallback for completely unknown types
        return "KONZEPT"

    def normalize_relationship_type(self, suggested_type: str) -> str:
        """
        Normalize relationship type using multi-stage approach:

        1. Exact match (case-sensitive) - O(1)
        2. Case-insensitive match - O(1)
        3. BGE-M3 similarity (for creative LLM types) - O(n) with API call

        Args:
            suggested_type: Relationship type suggested by LLM

        Returns:
            Normalized relationship type from schema
        """
        if not suggested_type or not suggested_type.strip():
            return "BEZIEHT_SICH_AUF"

        suggested_type = suggested_type.strip()

        # Stage 1: Direct match (case-sensitive)
        if suggested_type in self.allowed_relationship_types:
            return suggested_type

        # Stage 2: Case-insensitive match
        suggested_upper = suggested_type.upper()
        if suggested_upper in self._relationship_types_upper:
            return self._relationship_types_upper[suggested_upper]

        # Stage 3: BGE-M3 similarity matching (for unknown types)
        if self.embedding_model:
            # Lazy load embeddings if not already computed
            if self._relationship_embeddings_cache is None:
                self._precompute_embeddings()

            if self._relationship_embeddings_cache is not None:
                try:
                    # Get BGE-M3 embedding for suggested type
                    suggested_embedding = self.embedding_model.embed_query(suggested_type)
                    suggested_embedding = np.array(suggested_embedding)

                    # Compute cosine similarity with all schema types
                    similarities = cosine_similarity_numpy(
                        suggested_embedding, self._relationship_embeddings_cache
                    )

                    # Find best match
                    best_idx = np.argmax(similarities)
                    best_similarity = similarities[best_idx]
                    best_type = self.allowed_relationship_types[best_idx]

                    # Only use if similarity is reasonably high (>0.5)
                    if best_similarity > 0.5:
                        return best_type

                except Exception:
                    # Silent fallback
                    pass

        # Default fallback
        return "BEZIEHT_SICH_AUF"

    def validate_entity_type(self, entity_type: str) -> bool:
        """Check if entity type is valid"""
        return entity_type in self.allowed_entity_types

    def validate_relationship_type(self, relationship_type: str) -> bool:
        """Check if relationship type is valid"""
        return relationship_type in self.allowed_relationship_types

    def validate_relationship(self, source_type: str, target_type: str, rel_type: str) -> bool:
        """Validate relationship between entity types"""
        if rel_type not in self.relationship_types:
            return False

        rel_info = self.relationship_types[rel_type]
        source_allowed = rel_info.get("source_types", [])
        target_allowed = rel_info.get("target_types", [])

        source_valid = "*" in source_allowed or source_type in source_allowed
        target_valid = "*" in target_allowed or target_type in target_allowed

        return source_valid and target_valid


# %%
class FastEntityExtractor:
    """
    Entity extractor with filter_label support for multi-tenant GraphRAG.
    Uses OpenAI for entity extraction.
    """

    def __init__(
        self,
        schema: FastEntitySchema = None,
        config_path: str = "config.yaml",
        filter_label: str = None,
        **kwargs,
    ):
        """
        Initialize entity extractor with config.yaml support and filter_label

        Args:
            schema: FastEntitySchema instance
            config_path: Path to config.yaml
            filter_label: Label to add to all entities and relationships for filtering
            **kwargs: Additional parameters (chunk_size, max_workers, etc.)
        """

        # Load configuration
        self.config = self._load_config(config_path)

        # Use provided schema or create new one
        self.schema = schema or FastEntitySchema(config_path=config_path)

        # Store filter_label for multi-tenant support
        self.filter_label = filter_label
        if self.filter_label:
            print(f"🏷️ Filter label: {self.filter_label}")

        # Extract configuration with kwargs overrides
        entity_config = self.config["entity_extraction"]

        # Core parameters (with kwargs overrides)
        self.chunk_size = kwargs.get("chunk_size", entity_config.get("chunk_size", 4000))
        self.batch_size = kwargs.get("batch_size", 8)

        # Worker configuration
        max_workers_default = min(os.cpu_count(), 6)
        self.max_workers = kwargs.get(
            "max_workers", entity_config.get("max_workers", max_workers_default)
        )

        # Get allowed types from schema
        self.allowed_entity_types = self.schema.allowed_entity_types
        self.allowed_relationship_types = self.schema.allowed_relationship_types

        # Cache configuration
        self._cache_enabled = entity_config.get("cache_enabled", True)
        self._clear_cache_between_docs = entity_config.get("clear_cache_between_docs", False)
        self._result_cache = {}
        self._cache_hits = 0
        self._cache_misses = 0

        # Debug mode
        self.debug_mode = kwargs.get("debug_mode", entity_config.get("debug_mode", False))

        # Initialize LLM
        self.llm = None
        self.model_name = None
        self.llm_config = {}
        self._initialize_llm()

        # Create optimized prompt
        self.prompt_template = self._create_optimized_prompt()

        print("✅ FastEntityExtractor initialized with OpenAI:")
        print(f"   🤖 Model: {self.model_name}")
        print(f"   🔧 Max workers: {self.max_workers}")
        print(f"   📄 Chunk size: {self.chunk_size}")
        print(f"   🎯 Entity types: {len(self.allowed_entity_types)}")
        print(f"   🔗 Relationship types: {len(self.allowed_relationship_types)}")
        print(f"   💾 Result caching: {'Enabled' if self._cache_enabled else 'Disabled'}")
        if self.filter_label:
            print(f"   🏷️ Filter label: {self.filter_label}")
        if self.debug_mode:
            print("   🐛 Debug mode: Enabled")

    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file"""
        default_config = {
            "entity_extraction": {
                "chunk_size": 4000,
                "cache_enabled": True,
                "clear_cache_between_docs": False,
                "debug_mode": False,
                "max_workers": 4,
                "openai": {
                    "temperature": 0.5,
                    "max_tokens": 1500,
                },
            }
        }

        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)

                if "entity_extraction" in config:
                    # Deep merge
                    for key, value in config["entity_extraction"].items():
                        if isinstance(value, dict) and key in default_config["entity_extraction"]:
                            if isinstance(default_config["entity_extraction"][key], dict):
                                default_config["entity_extraction"][key].update(value)
                            else:
                                default_config["entity_extraction"][key] = value
                        else:
                            default_config["entity_extraction"][key] = value

                print(f"✅ Loaded config from {config_path}")
        except Exception as e:
            print(f"⚠️ Using default config: {e}")

        return default_config

    def _initialize_llm(self):
        """Initialize LangChain ChatOpenAI"""
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "langchain-openai not installed. Install with: pip install langchain-openai"
            )

        # Get model and API key from environment variables
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        openai_api_key = os.getenv("OPENAI_API_KEY")
        openai_base_url = os.getenv("OPENAI_API_BASE_URL")

        # Validate required environment variables
        if not openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY not found in environment variables. "
                "Please add it to your .env file."
            )

        # Get parameters from config
        entity_config = self.config["entity_extraction"]

        # Use config values or defaults
        temperature = entity_config.get("openai", {}).get("temperature", 0.5)
        max_tokens = entity_config.get("openai", {}).get("max_tokens", 1500)

        # Store config for later use
        self.llm_config = {
            "model": self.model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            # Initialize LangChain ChatOpenAI
            llm_params = {
                "model": self.model_name,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "api_key": openai_api_key,
            }

            # Add base URL if provided
            if openai_base_url:
                llm_params["base_url"] = openai_base_url

            self.llm = ChatOpenAI(**llm_params)

            print(f"✅ Initialized OpenAI: {self.model_name}")
            if openai_base_url:
                print(f"   Base URL: {openai_base_url}")

        except Exception as e:
            print(f"❌ Failed to initialize OpenAI: {e}")
            raise

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text"""
        return hashlib.md5(text.encode()).hexdigest()[:16]

    def _create_optimized_prompt(self) -> str:
        """Create optimized prompt for German entity extraction"""
        entity_desc = self.schema.get_entity_type_description()
        relationship_desc = self.schema.get_relationship_type_description()

        entity_list = ", ".join(self.allowed_entity_types)
        relationship_list = ", ".join(self.allowed_relationship_types)

        return f"""Du bist ein Experte für deutsche und englische Textanalyse. Extrahiere ALLE Entitäten und Beziehungen aus dem folgenden Text.

WICHTIG: Verwende NUR diese vordefinierten Typen:

ENTITÄTS-TYPEN (verwende EXAKT diese):
{entity_desc}

ERLAUBTE TYPEN: {entity_list}

BEZIEHUNGS-TYPEN (verwende EXAKT diese):
{relationship_desc}

ERLAUBTE BEZIEHUNGEN: {relationship_list}

KRITISCHE REGELN:
1. Verwende NUR die oben gelisteten Entitäts-Typen: {entity_list}
2. Verwende NUR die oben gelisteten Beziehungs-Typen: {relationship_list}
3. Extrahiere ALLE wichtigen Entitäten - sei großzügig bei der Erkennung
4. Erkenne auch Teilnamen und Abkürzungen (z.B. "Heimkehr" für "Wohnungsgenossenschaft Heimkehr eG")
5. Adressen sind ORT, Firmen sind ORGANISATION, Daten/Uhrzeiten sind ZEIT, Veranstaltungen sind EVENT
6. Bei Unsicherheit verwende KONZEPT für abstrakte Begriffe oder ORGANISATION für Gruppen/Firmen
7. Erstelle KEINE neuen Typen, verwende NUR die vordefinierten

BEISPIELE:
- "Wohnungsgenossenschaft Heimkehr eG" → ORGANISATION
- "Döhren", "Hannover", "Hildesheimer Str. 89" → ORT
- "25. November 2016", "15:30 Uhr" → ZEIT
- "Einweihung", "Servicepunkt" → EVENT
- "Team der Heimkehr" → ORGANISATION oder PERSON

TEXT:
{{text}}

Antworte AUSSCHLIESSLICH mit gültigem JSON (keine Erklärungen):

{{{{
  "entities": [
    {{{{"name": "Entitätsname", "type": "ENTITÄTS_TYP", "context": "kurzer Kontext"}}}}
  ],
  "relationships": [
    {{{{"source": "Entität1", "target": "Entität2", "type": "BEZIEHUNGS_TYP", "context": "kurzer Kontext"}}}}
  ]
}}}}"""

    def _preprocess_text(self, text: str) -> str:
        """Preprocess text for better extraction"""
        if not text:
            return ""

        # Remove page markers
        text = re.sub(r"--- Page \d+ ---", "", text)
        text = re.sub(r"^\s*Page \d+\s*$", "", text, flags=re.MULTILINE)

        # Clean up soft hyphens and special characters
        text = text.replace("­", "")
        text = text.replace("\u00ad", "")
        text = text.replace("Â", "")

        # Normalize whitespace
        text = re.sub(r"\n\s*\n", "\n\n", text)
        text = re.sub(r" +", " ", text)

        return text.strip()

    def _chunk_text(self, text: str, doc_id: str) -> List[ProcessingTask]:
        """Split large text into processable chunks"""
        text = self._preprocess_text(text)

        if len(text) <= self.chunk_size:
            return [ProcessingTask(doc_id, text, {})]

        chunks = []
        overlap = 200

        for i in range(0, len(text), self.chunk_size - overlap):
            chunk_text = text[i : i + self.chunk_size]
            chunk_id = f"{doc_id}_chunk_{len(chunks)}"
            chunks.append(ProcessingTask(doc_id, chunk_text, {}, chunk_id))

        return chunks

    def _extract_single(self, task: ProcessingTask) -> ExtractionResult:
        """Extract entities from a single task using OpenAI with retry logic"""
        if not self.llm:
            return ExtractionResult(task.doc_id, [], [], 0.0, "LLM not initialized", task.chunk_id)

        # Check cache first - include filter_label in cache key for multi-tenant isolation
        cache_key = None
        if self._cache_enabled:
            # Include filter_label in cache key for multi-tenant isolation
            cache_key = f"{self._get_cache_key(task.text)}_{self.filter_label or 'default'}"
            if cache_key in self._result_cache:
                self._cache_hits += 1
                cached_result = self._result_cache[cache_key]

                # Apply current filter_label to cached entities
                entities = []
                for e in cached_result["entities"]:
                    entity_copy = e.copy()
                    if self.filter_label:
                        entity_copy["filter_label"] = self.filter_label
                    entities.append(entity_copy)

                # Apply current filter_label to cached relationships
                relationships = []
                for r in cached_result["relationships"]:
                    rel_copy = r.copy()
                    if self.filter_label:
                        rel_copy["filter_label"] = self.filter_label
                    relationships.append(rel_copy)

                return ExtractionResult(
                    task.doc_id,
                    entities,
                    relationships,
                    0.001,
                    None,
                    task.chunk_id,
                )

        self._cache_misses += 1
        start_time = time.time()

        # Retry logic for throttling
        max_retries = 5
        base_delay = 1.0  # Start with 1 second

        for attempt in range(max_retries):
            try:
                # Rate limiting delay
                if attempt > 0:
                    delay = base_delay * (2**attempt)
                    if self.debug_mode:
                        print(f"🔄 Retry attempt {attempt + 1}/{max_retries} after {delay}s delay")
                    time.sleep(delay)
                else:
                    time.sleep(0.5)

                # Preprocess text
                text_to_process = self._preprocess_text(task.text)

                if len(text_to_process) < 10:
                    return ExtractionResult(
                        task.doc_id, [], [], 0.001, "Text too short", task.chunk_id
                    )

                # Limit text size
                if len(text_to_process) > self.chunk_size:
                    text_to_process = text_to_process[: self.chunk_size]

                prompt = self.prompt_template.format(text=text_to_process)
                messages = [HumanMessage(content=prompt)]

                # Call LLM via LangChain
                response = self.llm.invoke(messages)
                processing_time = time.time() - start_time

                if response and hasattr(response, "content"):
                    content = response.content

                    if self.debug_mode:
                        print(f"🐛 DEBUG: Raw response for {task.doc_id}: {content[:200]}...")

                    extracted_data = self._parse_json_response(content)

                    if not extracted_data:
                        error_msg = "JSON parsing failed"
                        return ExtractionResult(
                            task.doc_id, [], [], processing_time, error_msg, task.chunk_id
                        )

                    normalized_data = self._normalize_and_validate(
                        extracted_data, task.doc_id, task.metadata
                    )

                    # Cache successful results (without filter_label - it's applied on retrieval)
                    if self._cache_enabled and cache_key:
                        # Store without filter_label in cache - we apply it when retrieving
                        cache_entities = []
                        for e in normalized_data["entities"]:
                            e_copy = e.copy()
                            e_copy.pop("filter_label", None)  # Remove for cache storage
                            cache_entities.append(e_copy)

                        cache_relationships = []
                        for r in normalized_data["relationships"]:
                            r_copy = r.copy()
                            r_copy.pop("filter_label", None)  # Remove for cache storage
                            cache_relationships.append(r_copy)

                        self._result_cache[cache_key] = {
                            "entities": cache_entities,
                            "relationships": cache_relationships,
                        }

                    return ExtractionResult(
                        task.doc_id,
                        normalized_data["entities"],
                        normalized_data["relationships"],
                        processing_time,
                        None,
                        task.chunk_id,
                    )
                else:
                    return ExtractionResult(
                        task.doc_id, [], [], processing_time, "No response", task.chunk_id
                    )

            except Exception as e:
                error_str = str(e)
                # Check if it's a throttling error
                if "ThrottlingException" in error_str or "Too many requests" in error_str:
                    if attempt < max_retries - 1:
                        continue
                    else:
                        processing_time = time.time() - start_time
                        return ExtractionResult(
                            task.doc_id,
                            [],
                            [],
                            processing_time,
                            f"Rate limit exceeded after {max_retries} retries",
                            task.chunk_id,
                        )
                else:
                    processing_time = time.time() - start_time
                    if self.debug_mode:
                        print(f"🐛 DEBUG: Exception in {task.doc_id}: {e}")
                    return ExtractionResult(
                        task.doc_id, [], [], processing_time, str(e), task.chunk_id
                    )

        # Should not reach here
        processing_time = time.time() - start_time
        return ExtractionResult(
            task.doc_id, [], [], processing_time, "Unknown error", task.chunk_id
        )

    def _parse_json_response(self, content: str) -> Optional[Dict[str, Any]]:
        """Parse JSON response with multiple strategies"""
        if not content or not content.strip():
            return None

        content = content.strip()

        # Strategy 1: Direct JSON parsing
        try:
            result = json.loads(content)
            if isinstance(result, dict):
                return self._ensure_json_structure(result)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract from markdown code blocks
        code_block_patterns = [r"```json\s*(.*?)\s*```", r"```\s*(\{.*?\})\s*```", r"`(\{.*?\})`"]

        for pattern in code_block_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1).strip()
                    result = json.loads(json_str)
                    if isinstance(result, dict):
                        return self._ensure_json_structure(result)
                except json.JSONDecodeError:
                    continue

        # Strategy 3: Find JSON object in text
        json_start = content.find("{")
        json_end = content.rfind("}")
        if json_start != -1 and json_end != -1 and json_end > json_start:
            for end_pos in range(json_end, json_start, -1):
                if content[end_pos] == "}":
                    try:
                        json_str = content[json_start : end_pos + 1]
                        result = json.loads(json_str)
                        if isinstance(result, dict):
                            return self._ensure_json_structure(result)
                    except json.JSONDecodeError:
                        continue

        # Strategy 4: Manual regex extraction
        try:
            entities = []
            relationships = []

            entity_patterns = [
                r'"name":\s*"([^"]+)"[^}]*"type":\s*"([^"]+)"',
                r'\{\s*"name":\s*"([^"]+)"[^}]*"type":\s*"([^"]+)"[^}]*\}',
            ]

            for pattern in entity_patterns:
                matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    if len(match) >= 2:
                        name, etype = match[0], match[1]
                        if name and etype and len(name) > 1:
                            entities.append(
                                {"name": name.strip(), "type": etype.strip(), "context": ""}
                            )
                if entities:
                    break

            rel_patterns = [
                r'"source":\s*"([^"]+)"[^}]*"target":\s*"([^"]+)"[^}]*"type":\s*"([^"]+)"',
            ]

            for pattern in rel_patterns:
                matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    if len(match) >= 3:
                        source, target, rtype = match[0], match[1], match[2]
                        if source and target and rtype:
                            relationships.append(
                                {
                                    "source": source.strip(),
                                    "target": target.strip(),
                                    "type": rtype.strip(),
                                    "context": "",
                                }
                            )
                if relationships:
                    break

            if entities or relationships:
                return {"entities": entities, "relationships": relationships}
        except Exception:
            pass

        # If nothing works, return empty structure
        return {"entities": [], "relationships": []}

    def _ensure_json_structure(self, result: Dict) -> Dict:
        """Ensure the JSON has the required structure"""
        if "entities" not in result:
            result["entities"] = []
        if "relationships" not in result:
            result["relationships"] = []

        # Clean and validate entities
        fixed_entities = []
        for entity in result.get("entities", []):
            if isinstance(entity, dict) and entity.get("name"):
                fixed_entities.append(
                    {
                        "name": str(entity.get("name", "")).strip(),
                        "type": str(entity.get("type", "KONZEPT")),
                        "context": str(entity.get("context", "")),
                    }
                )
        result["entities"] = fixed_entities

        # Clean and validate relationships
        fixed_relationships = []
        for rel in result.get("relationships", []):
            if isinstance(rel, dict) and rel.get("source") and rel.get("target"):
                fixed_relationships.append(
                    {
                        "source": str(rel.get("source", "")).strip(),
                        "target": str(rel.get("target", "")).strip(),
                        "type": str(rel.get("type", "BEZIEHT_SICH_AUF")),
                        "context": str(rel.get("context", "")),
                    }
                )
        result["relationships"] = fixed_relationships

        return result

    def _normalize_and_validate(
        self, extracted_data: Dict, doc_id: str, metadata: dict
    ) -> Dict[str, Any]:
        """
        Normalize and validate extracted data using optimized schema normalization.
        Adds filter_label to all entities and relationships.
        """
        normalized_entities = []
        normalized_relationships = []

        document_name = metadata.get("filename", metadata.get("file_name", ""))

        # Process entities with optimized normalization
        entity_map = {}
        for entity in extracted_data.get("entities", []):
            if not entity.get("name"):
                continue

            try:
                normalized_type = self.schema.normalize_entity_type(entity["type"])

                if not self.schema.validate_entity_type(normalized_type):
                    normalized_type = "KONZEPT"

                normalized_entity = {
                    "name": entity["name"].strip(),
                    "type": normalized_type,
                    "context": entity.get("context", ""),
                    "original_type": entity["type"],
                    "document_id": doc_id,
                    "document_name": document_name,
                }

                # Add filter_label if configured
                if self.filter_label:
                    normalized_entity["filter_label"] = self.filter_label

                normalized_entities.append(normalized_entity)
                entity_map[entity["name"]] = normalized_type
            except Exception:
                continue

        # Process relationships
        for relationship in extracted_data.get("relationships", []):
            try:
                source_name = relationship.get("source", "").strip()
                target_name = relationship.get("target", "").strip()

                if not source_name or not target_name:
                    continue

                if source_name not in entity_map or target_name not in entity_map:
                    continue

                source_type = entity_map[source_name]
                target_type = entity_map[target_name]

                normalized_rel_type = self.schema.normalize_relationship_type(relationship["type"])

                if self.schema.validate_relationship(source_type, target_type, normalized_rel_type):
                    normalized_relationship = {
                        "source": source_name,
                        "target": target_name,
                        "type": normalized_rel_type,
                        "context": relationship.get("context", ""),
                        "original_type": relationship["type"],
                        "document_id": doc_id,
                        "document_name": document_name,
                    }

                    # Add filter_label if configured
                    if self.filter_label:
                        normalized_relationship["filter_label"] = self.filter_label

                    normalized_relationships.append(normalized_relationship)
            except Exception:
                continue

        return {"entities": normalized_entities, "relationships": normalized_relationships}

    def extract_entities_threaded(self, documents: List[Tuple[str, str, Dict]]) -> List[Dict]:
        """Process documents using optimized threaded approach"""
        if not documents:
            return []

        print(f"🚀 Processing {len(documents)} documents with {self.max_workers} threads")
        print(f"   OpenAI: {self.model_name}")
        if self.filter_label:
            print(f"   🏷️ Filter label: {self.filter_label}")

        # Create tasks
        all_tasks = []
        for doc_id, text, metadata in documents:
            chunks = self._chunk_text(text, doc_id)
            for chunk in chunks:
                chunk.metadata = metadata
                all_tasks.append(chunk)

        print(f"📦 Created {len(all_tasks)} processing tasks")

        # Process with ThreadPoolExecutor
        start_time = time.time()
        all_results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {
                executor.submit(self._extract_single, task): task for task in all_tasks
            }

            completed_count = 0
            for future in as_completed(future_to_task):
                try:
                    result = future.result()
                    all_results.append(result)
                    completed_count += 1

                    if completed_count % 25 == 0 or completed_count == len(all_tasks):
                        print(f"  📊 Progress: {completed_count}/{len(all_tasks)} tasks completed")

                except Exception as e:
                    task = future_to_task[future]
                    error_result = ExtractionResult(task.doc_id, [], [], 0.0, str(e), task.chunk_id)
                    all_results.append(error_result)
                    completed_count += 1

        total_time = time.time() - start_time

        # Combine results by document
        doc_results = {}
        for result in all_results:
            if result.doc_id not in doc_results:
                doc_results[result.doc_id] = {
                    "doc_id": result.doc_id,
                    "extracted_at": datetime.now().isoformat(),
                    "processing_time_sec": 0.0,
                    "entities": [],
                    "relationships": [],
                    "metadata": {},
                    "error": None,
                    "stats": {},
                    "extraction_config": {
                        "provider": "openai",
                        "model": self.model_name,
                        "temperature": self.llm_config.get("temperature", 0.5),
                        "max_tokens": self.llm_config.get("max_tokens", 1500),
                        "cache_enabled": self._cache_enabled,
                        "filter_label": self.filter_label,
                    },
                }

            doc_results[result.doc_id]["processing_time_sec"] += result.processing_time
            doc_results[result.doc_id]["entities"].extend(result.entities)
            doc_results[result.doc_id]["relationships"].extend(result.relationships)

            if result.error:
                if not doc_results[result.doc_id]["error"]:
                    doc_results[result.doc_id]["error"] = result.error

        # Remove duplicates and add statistics
        for doc_id, doc_result in doc_results.items():
            # Remove duplicate entities
            seen_entities = set()
            unique_entities = []
            for entity in doc_result["entities"]:
                entity_key = (entity["name"], entity["type"])
                if entity_key not in seen_entities:
                    seen_entities.add(entity_key)
                    unique_entities.append(entity)
            doc_result["entities"] = unique_entities

            # Remove duplicate relationships
            seen_relationships = set()
            unique_relationships = []
            for rel in doc_result["relationships"]:
                rel_key = (rel["source"], rel["target"], rel["type"])
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    unique_relationships.append(rel)
            doc_result["relationships"] = unique_relationships

            # Add stats
            doc_result["stats"] = {
                "total_entities": len(doc_result["entities"]),
                "total_relationships": len(doc_result["relationships"]),
                "entity_types": list(set(e["type"] for e in doc_result["entities"])),
                "relationship_types": list(set(r["type"] for r in doc_result["relationships"])),
                "provider": "openai",
                "model": self.model_name,
                "filter_label": self.filter_label,
            }

            # Clear cache between docs if configured
            if self._clear_cache_between_docs:
                self.clear_cache()

        successful_docs = len([r for r in doc_results.values() if not r.get("error")])
        failed_docs = len(doc_results) - successful_docs
        total_entities = sum(r["stats"]["total_entities"] for r in doc_results.values())
        total_relationships = sum(r["stats"]["total_relationships"] for r in doc_results.values())

        print(f"⚡ Processing completed in {total_time:.2f}s")
        print(f"📊 Average: {total_time/len(documents):.3f}s per document")
        print(f"✅ Success: {successful_docs}/{len(documents)} documents")
        print(f"🎯 Total entities extracted: {total_entities}")
        print(f"🔗 Total relationships extracted: {total_relationships}")
        print(f"💾 Cache stats: {self._cache_hits} hits, {self._cache_misses} misses")
        if self.filter_label:
            print(f"🏷️ All entities/relationships tagged with filter_label: {self.filter_label}")
        if failed_docs > 0:
            print(f"❌ Failed: {failed_docs} documents")

        if self._clear_cache_between_docs:
            self.clear_cache()

        return list(doc_results.values())

    def extract_entities_parallel(self, documents: List[Tuple[str, str, Dict]]) -> List[Dict]:
        """Alias for threaded processing"""
        return self.extract_entities_threaded(documents)

    def clear_cache(self):
        """Clear the result cache"""
        self._result_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        gc.collect()


# %%
def test_with_config():
    """Test the extractor with config integration"""
    print("🧪 Testing FastEntityExtractor with filter_label support...")

    test_text = """Wohnungsgenossenschaft Heimkehr eG
Hildesheimer Str. 89 | 30169 Hannover
Einweihung Servicepunkt Döhren
Freitag, 25. November 2016 | 15:30 Uhr"""

    schema = FastEntitySchema()
    extractor = FastEntityExtractor(
        schema=schema, config_path="config.yaml", debug_mode=True, filter_label="test_collection"
    )

    test_documents = [("test_doc", test_text, {"filename": "test.pdf"})]

    print("\n📄 Processing with OpenAI...")
    results = extractor.extract_entities_threaded(test_documents)

    for result in results:
        if result.get("error"):
            print(f"  ❌ Error: {result['error']}")
        else:
            print(
                f"\n✅ Found {len(result['entities'])} entities, "
                f"{len(result['relationships'])} relationships"
            )

            if result["entities"]:
                print("\n📋 Entities:")
                for entity in result["entities"]:
                    filter_label = entity.get("filter_label", "N/A")
                    print(f"  - {entity['name']} [{entity['type']}] (filter_label: {filter_label})")

            if result["relationships"]:
                print("\n🔗 Relationships:")
                for rel in result["relationships"]:
                    filter_label = rel.get("filter_label", "N/A")
                    print(
                        f"  - {rel['source']} --[{rel['type']}]--> {rel['target']} (filter_label: {filter_label})"
                    )

    print(
        f"\n💾 Cache efficiency: " f"{extractor._cache_hits + extractor._cache_misses} total calls"
    )


if __name__ == "__main__":
    test_with_config()
