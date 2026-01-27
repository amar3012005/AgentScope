# src/utils/llm_logger.py or directly in the file
# Change log path to avoid Docker permission issues
LOG_PATH = "/tmp/llm_error.log"

def log_llm_event(event_type: str, data: dict) -> None:
    """
    event_type example:
      - "llm_error"
      - "llm_fallback_success"
    """
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event_type,
        **data,
    }

    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

"""
GraphRAG Retriever - Hybrid Graph + Vector + Keyword Search
Uses Neo4j for graph traversal, Qdrant for vector search, and LLM for entity extraction.

Multi-Tenant Support:
- filter_label (derived from collection_name) isolates all Neo4j queries
- Same entity name in different tenants = different graph nodes
- All graph traversals are strictly within tenant boundaries
"""

import json
import logging
import math
import os
import re
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from dotenv import load_dotenv
import litellm
from litellm import completion
from langchain_core.documents import Document
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchText, MatchValue

from utils.bge_m3_embedding import BGEM3Embeddings
from utils.qdrant_helpers import compute_point_id

# 260108-BundB Jun – For error log.
import time
import uuid
from utils.llm_logger import log_llm_event


# Suppress warnings
logging.getLogger("neo4j").setLevel(logging.ERROR)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
logging.getLogger("neo4j.io").setLevel(logging.ERROR)
logging.getLogger("qdrant_client").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

# Load environment variables
load_dotenv()


def load_config(config_path: str = "config.yaml") -> Dict:
    """Load configuration from YAML file"""
    config_file = Path(config_path)

    if not config_file.exists():
        config_file = Path("..") / config_path
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    return config


# Load configuration
CONFIG = load_config()

# Qdrant configuration
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_HOST = os.getenv("QDRANT_HOST") or CONFIG.get("qdrant", {}).get("host", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", CONFIG.get("qdrant", {}).get("port", 6333)))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
# Prioritize environment variable over config file
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION") or CONFIG.get("qdrant", {}).get("collection_name", "graphrag_chunks")

# Neo4j configuration
NEO4J_URI = os.getenv("NEO4J_URI") or CONFIG.get("neo4j", {}).get("uri", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER") or CONFIG.get("neo4j", {}).get("user", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# LiteLLM Configuration
LITELLM_PLANNER_MODEL = os.getenv("LITELLM_PLANNER_MODEL", "openai/gpt-4o")
LITELLM_PRE_MODEL = os.getenv("LITELLM_PRE_MODEL", "openai/gpt-4o-mini")
LITELLM_POST_MODEL = os.getenv("LITELLM_POST_MODEL", "openai/gpt-4o")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")

LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
_token_env = os.getenv("LLM_MAX_OUTPUT_TOKENS", "4000")
LLM_MAX_OUTPUT_TOKENS = int(_token_env) if _token_env and _token_env.strip().isdigit() and int(_token_env) > 0 else None

# Pre-Retrieval: The Search Architect Prompt
PRE_RETRIEVAL_SYSTEM_PROMPT = """You are the 'Search Architect' for a high-performance GraphRAG system.
Your mission is to extract key entities and keywords from the user's query to enable a robust multi-database search (Vector + Graph + Keyword).

CRITICAL INSTRUCTIONS:
1. LANGUAGE NORMALIZATION: The knowledge base is written in GERMAN. 
   - If the query is in English (or any other language), extract the concepts and translate the search terms into German.
   - Example (Query: "Who is the supervisor?"): Keywords: ["Abteilungsleiter", "Vorgesetzter", "Leitender Angestellter"]
2. ENTITY TYPES: Extract Persons, Organizations, Locations, Concepts, and specific Numbers/Dates.
3. OUTPUT FORMAT: Respond ONLY with a raw JSON array of strings. No explanations.

Example Output: ["Bundesregierung", "KI-Strategie", "2024", "Mittelstand"]"""

# Strategic Planner: The Dispatcher Prompt (ENHANCED)
STRATEGIC_PLANNER_PROMPT = """You are the 'Strategic Retrieval Planner'. Your task is to analyze the user's query and determine the OPTIMAL execution plan.

## QUERY CLASSIFICATION RULES:

### 1. SMALL_TALK (No document retrieval needed)
Triggers:
- Greetings: "Hello", "Hi", "Good morning", "Hallo", "Guten Tag"
- Identity questions: "Who are you?", "What can you do?", "Wer bist du?"
- Thanks/Farewell: "Thanks", "Goodbye", "Danke", "Tschüss"
- System questions: "Are you online?", "How does this work?"
- Casual: "Okay", "Yes", "No", "Sure"

Action: Skip retrieval entirely. Provide a direct, friendly response.

### 2. DOCUMENT_SEARCH (Precise document retrieval required)
Triggers:
- Specific entity mentions: "Siemens", "Project Alpha", "Contract #12345"
- Document references: "What does the report say?", "Find the contract", "Show me the proposal"
- Factual questions: "What is the budget?", "When was it signed?", "Who is responsible?"
- Comparison requests: "Compare X and Y", "What are the differences?"

Action: Use vector + keyword search. Graph only if entities are involved.

### 3. ANALYTICAL_SEARCH (Cross-document analysis)
Triggers:
- Pattern questions: "What are the common risks?", "What trends do you see?"
- Summary requests: "Summarize all projects", "Give me an overview"
- Strategic questions: "What should we prioritize?", "What are the key takeaways?"

Action: Use all retrieval methods. Prioritize graph for entity relationships.

### 4. CLARIFICATION_NEEDED (Ambiguous query)
Triggers:
- Very short queries (1-2 words) that aren't greetings: "costs", "status"
- Context-dependent: "What about that?", "And the other one?"
- Incomplete: "The project...", "Can you..."

Action: Ask for clarification before retrieval.

## OUTPUT JSON SPECIFICATION:
{
  "mode": "SMALL_TALK" | "DOCUMENT_SEARCH" | "ANALYTICAL_SEARCH" | "CLARIFICATION_NEEDED",
  "confidence": 0.0 to 1.0,
  "reasoning": "Brief explanation of classification",
  "search_plan": {
    "use_vector": boolean,
    "use_graph": boolean,
    "use_keyword": boolean,
    "priority_source": "vector" | "graph" | "keyword" | null
  },
  "entities_extracted": ["List of entities in query (people, orgs, projects, dates)"],
  "entities_german": ["Same entities translated to German for search optimization"],
  "direct_reply": "Only for SMALL_TALK or CLARIFICATION_NEEDED, otherwise null",
  "suggested_keywords": ["Additional search terms that might help"]
}

Respond ONLY with valid JSON. No markdown, no explanations outside JSON."""

# Post-Retrieval: The Answer Synthesis Prompt (ENHANCED)
POST_RETRIEVAL_SYSTEM_PROMPT = """You are an expert Corporate Knowledge Analyst. Your role is to synthesize information from retrieved document chunks into precise, actionable answers.

## CORE PRINCIPLES:

### 1. LANGUAGE MATCHING (MANDATORY)
- Detect the user's query language and respond in THE SAME LANGUAGE.
- If query is German → respond in German.
- If query is English → respond in English.
- The source documents may be in German, but you MUST translate insights to match the query language.

### 2. PRECISION OVER VERBOSITY
- Answer the EXACT question asked. Do not provide tangential information.
- If a user asks "What is the budget?", give the budget, not a summary of the entire project.
- If multiple documents contain the answer, prioritize the most recent or most authoritative.

### 3. SOURCE ATTRIBUTION (ALWAYS)
- Every factual claim MUST be linked to a source.
- Format: "According to [Document Name], Page X, ..."
- If information comes from multiple sources, list all.
- Clean document names by removing hash suffixes (e.g., "_89d2d7b8" → ".pdf").

### 4. HANDLING MISSING INFORMATION
- If the answer is NOT in the provided context, say so explicitly.
- Do NOT guess, hallucinate, or use external knowledge.
- Suggest what additional documents might help if applicable.

### 5. STRUCTURED RESPONSES
For complex queries, use this structure:
- **ANSWER**: Direct response to the question
- **DETAILS**: Supporting information (if needed)
- **SOURCES**: Document citations

### 6. ENTITY AWARENESS
- Pay attention to specific entities (people, organizations, dates, amounts).
- When entities are mentioned, ensure your answer addresses them specifically.
- If an entity appears in multiple documents, note any discrepancies.
"""

BGE_M3_DIMENSION = 1024

# Default System Prompt (for standard queries)
DEFAULT_SYSTEM_PROMPT = """You are a friendly and precise corporate document assistant.

## YOUR TASK:
Answer questions accurately using ONLY the provided document context.

## LANGUAGE RULE:
Always respond in the SAME LANGUAGE as the user's question.

## ANSWER QUALITY STANDARDS:
1. **Accuracy**: Only state facts that appear in the provided context.
2. **Completeness**: Address all parts of multi-part questions.
3. **Clarity**: Use simple, professional language. Avoid jargon unless the user used it.
4. **Citations**: Reference source documents with cleaned names and page numbers.

## WHEN YOU DON'T KNOW:
If the information is not in the context, respond:
"I could not find specific information about [topic] in the available documents. The documents provided discuss [brief summary of available topics], but do not address your question directly."

## DOCUMENT NAME CLEANING:
- Remove trailing hash codes (e.g., "_89d2d7b8")
- Add ".pdf" extension
- Example: "Contract_Siemens_2024_a1b2c3d4" -> "Contract_Siemens_2024.pdf"
"""

DEFAULT_USER_PROMPT = """You are a precise document analysis assistant with self-awareness capabilities.

TEXT SNIPPETS:
{context}

USER QUESTION: {query}

=== STEP 1: REASONING & ANALYSIS ===
Before answering, perform this internal validation:

1. **Query Analysis**: What key elements is the user asking about?
   - Key entities/names mentioned: [list them]
   - Numbers/amounts referenced: [list them]
   - Core intent: [what does the user want to know?]

2. **Evidence Check**: Scan the provided snippets for matches:
   - Which snippets mention the key entities? [list snippet IDs or brief quotes]
   - Do any snippets contain the exact numbers/amounts asked about?
   - What is the context of these mentions?

3. **Self-Validation**: 
   - Does my answer DIRECTLY address the user's question?
   - Am I making assumptions not supported by the text?
   - If I found partial information, am I clearly stating what's missing?

=== STEP 2: STRUCTURED ANSWER ===

Provide your response in the following format:

**REASONING**: [2-3 sentences explaining your analysis process - what you looked for, what you found, and how confident you are]

**ANSWER**: [Your clear, direct answer addressing the user's question. If you found the information, state it clearly. If you found related but incomplete information, explain both what you found AND what's missing]

**CONTEXT**: [Describe the document context - what type of document is this? What is its purpose? This helps the user understand the source]

**SOURCE**: Document [cleaned_name.pdf], Page [X]

**CONFIDENCE**: [HIGH/MEDIUM/LOW] - [One sentence explaining why]

=== IMPORTANT RULES ===
1. ALWAYS include the REASONING section - show your thinking
2. If the user mentions a specific number (like €36.041,66), explicitly confirm whether you found it or not
3. Compare what the user asked vs what you found - be explicit about matches and gaps
4. Respond in the same language as the user's question
5. Never hallucinate - if something is not in the snippets, say so clearly

YOUR RESPONSE:"""

# Entity extraction prompt
ENTITY_EXTRACTION_PROMPT = """Extrahiere alle relevanten Entitäten aus der folgenden Frage.

Entitäten sind:
- Personen (Namen)
- Organisationen (Firmen, Behörden, Institutionen)
- Orte (Städte, Länder, Regionen)
- Konzepte (Fachbegriffe, Strategien, Programme)
- Zahlen und Daten (Jahre, Prozente, Beträge)
- Ereignisse

Frage: {query}

Antworte NUR mit einem JSON-Array der gefundenen Entitäten. Keine Erklärungen.
Beispiel: ["Angela Merkel", "Bundesregierung", "2025", "KI-Strategie", "Berlin"]

JSON-Array:"""

# 260108–BundB Jun - BEGIN
# LiteLLM Unified Invocation
def _invoke_llm(messages, model: str, **kwargs):
    """
    Unified LiteLLM completion call with error handling and provider neutrality.
    """
    call_id = str(uuid.uuid4())
    start = time.time()
    
    # Configure LiteLLM to drop unsupported params (like temperature for o1)
    litellm.drop_params = True
    
    try:
        if os.getenv("DEBUG_LLM", "false").lower() == "true":
            print(f"  [LLM {call_id}] Using api_base: {OPENAI_API_BASE_URL} | Model: {model}")
        
        # Determine parameters
        params = {
            "model": model,
            "messages": messages,
            "timeout": LLM_TIMEOUT_SECONDS,
            "api_base": OPENAI_API_BASE_URL,
            "api_key": OPENAI_API_KEY,
            **kwargs
        }
        
        # Reasoning models (O1, QwQ, etc.) specific handling
        is_reasoning = model.lower().startswith("o1") or "qwq" in model.lower()
        
        if is_reasoning:
            # O1 specific: Remove temperature if set (OpenAI o1 only supports temp 1 or none)
            if model.lower().startswith("o1"):
                params.pop("temperature", None)
            
            # Switch max_tokens to max_completion_tokens if present for reasoning models
            if "max_tokens" in params:
                params["max_completion_tokens"] = params.pop("max_tokens")
            
            # Increase timeout significantly for reasoning models
            params["timeout"] = 300  # 300 seconds (5 minutes) for CoT models
        else:
            # Standard models
            if "temperature" not in params:
                params["temperature"] = 0.0
            
            if "max_tokens" not in params and LLM_MAX_OUTPUT_TOKENS:
                params["max_tokens"] = LLM_MAX_OUTPUT_TOKENS

        # LiteLLM Unified Invocation
        response = litellm.completion(**params)
        
        duration_ms = int((time.time() - start) * 1000)
        
        if os.getenv("DEBUG_LLM", "false").lower() == "true":
            print(f"  [LLM {call_id}] Model: {model} | Duration: {duration_ms}ms")
            
        return response.choices[0].message.content, model

    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        print(f"  ❌ LiteLLM Error ({model}): {str(e)}")
        raise

def _invoke_llm_stream(messages, model: str, **kwargs):
    """
    Unified LiteLLM streaming completion call.
    """
    call_id = str(uuid.uuid4())
    
    # Configure LiteLLM
    litellm.drop_params = True
    
    try:
        if os.getenv("DEBUG_LLM", "false").lower() == "true":
            print(f"  [STREAM {call_id}] Using api_base: {OPENAI_API_BASE_URL} | Model: {model}")
        
        # Determine parameters
        params = {
            "model": model,
            "messages": messages,
            "stream": True,
            "timeout": LLM_TIMEOUT_SECONDS,
            "api_base": OPENAI_API_BASE_URL,
            "api_key": OPENAI_API_KEY,
            **kwargs
        }
        
        # Reasoning models handling
        is_reasoning = model.lower().startswith("o1") or "qwq" in model.lower()
        if is_reasoning:
            if model.lower().startswith("o1"):
                params.pop("temperature", None)
            if "max_tokens" in params:
                params["max_completion_tokens"] = params.pop("max_tokens")
            params["timeout"] = 300
        else:
            if "temperature" not in params:
                params["temperature"] = 0.0
            if "max_tokens" not in params and LLM_MAX_OUTPUT_TOKENS:
                params["max_tokens"] = LLM_MAX_OUTPUT_TOKENS

        # LiteLLM Unified Invocation
        return litellm.completion(**params)

    except Exception as e:
        print(f"  ❌ LiteLLM Stream Error ({model}): {str(e)}")
        raise
        
        log_llm_event("llm_error", {
            "call_id": call_id,
            "model": model,
            "duration_ms": duration_ms,
            "error": str(e)
        })
        raise e
# 260108–BundB Jun - END

class GraphRAGRetriever:
    """
    Hybrid GraphRAG retrieval using Neo4j knowledge graph and Qdrant vector store.

    Multi-Tenant Isolation:
    - collection_name = filter_label for both Qdrant and Neo4j
    - All Neo4j queries filter by filter_label
    - Same entity name in different tenants are separate graph nodes
    - Graph traversals never cross tenant boundaries
    """

    def __init__(
        self,
        debug: bool = False,
        # Qdrant config
        qdrant_url: Optional[str] = None,
        qdrant_host: Optional[str] = None,
        qdrant_port: Optional[int] = None,
        qdrant_api_key: Optional[str] = None,
        collection_name: Optional[str] = None,
        entity_extraction_prompt: Optional[
            str
        ] = None,  # 251204–BundB Jun: configurable entity extraction prompt
        # Neo4j uses env vars / config.yaml
    ):
        """
        Initialize GraphRAG retriever with Qdrant and Neo4j

        Args:
            debug: Enable debug output
            qdrant_url: Qdrant URL (overrides config)
            qdrant_host: Qdrant host (overrides config)
            qdrant_port: Qdrant port (overrides config)
            qdrant_api_key: Qdrant API key
            collection_name: Collection name - REQUIRED for multi-tenant.
                            Used as filter_label for Neo4j queries.
            entity_extraction_prompt: Optional custom prompt template for entity extraction.
                                      Use {query} as placeholder.
        """
        self.debug = debug
        self.neo4j_driver = None

        # === QDRANT CONNECTION ===
        final_url = qdrant_url or QDRANT_URL
        final_api_key = qdrant_api_key or QDRANT_API_KEY
        final_host = qdrant_host or QDRANT_HOST
        final_port = qdrant_port or QDRANT_PORT

        if final_url:
            if self.debug:
                print(f"DEBUG: Connecting to Qdrant at {final_url} (verify=False, prefer_grpc=False)")
            
            # Create custom clients with SSL disabled
            import httpx
            http_client = httpx.Client(verify=False, timeout=30.0)
            async_client = httpx.AsyncClient(verify=False, timeout=30.0) # Critical for async search methods
            
            self.qdrant_client = QdrantClient(
                url=final_url, 
                api_key=final_api_key, 
                prefer_grpc=False,
                https=http_client,
                # Force async client via private usage if necessary, but QdrantClient(async=True) isn't used here.
                # Instead, the QdrantClient automatically creates an async client internally.
                # We need to ensure we pass settings that affect that.
                # Note: valid QdrantClient args don't accept 'async_http_client' directly in all versions.
                # We will Monkey-patch if necessary or rely on env vars.
            )
            
            # MONKEY PATCH: Force the internal async client to verify=False
            # This is robust against library versions
            try:
                if hasattr(self.qdrant_client, "_async_client") and self.qdrant_client._async_client:
                    self.qdrant_client._async_client = httpx.AsyncClient(headers=self.qdrant_client._async_client.headers, verify=False, timeout=30.0)
                
                # Check for newer version 'http' property which holds the client
                if hasattr(self.qdrant_client, "http") and hasattr(self.qdrant_client.http, "async_client"):
                     # This is likely where the async calls happen
                     pass # It's hard to replace deeply.
            except Exception as e:
                print(f"⚠️ Failed to patch async client: {e}")

            print(f"✅ Qdrant connected via URL: {final_url}")
        else:
            self.qdrant_client = QdrantClient(host=final_host, port=final_port, prefer_grpc=False)
            print(f"✅ Qdrant connected at {final_host}:{final_port}")
        
        if self.debug:
            print(f"DEBUG: qdrant_client type is {type(self.qdrant_client)}")
            print(f"DEBUG: available methods: {[m for m in dir(self.qdrant_client) if not m.startswith('_')]}")

        # Collection name = filter_label for multi-tenant isolation
        # Sync with QDRANT_COLLECTION environment variable if not provided
        self.collection_name = collection_name or QDRANT_COLLECTION
        self.filter_label = self.collection_name

        if not self.filter_label:
            print("⚠️ WARNING: No collection_name/filter_label provided!")
            print("   Multi-tenant isolation is DISABLED. This may cause data leaks.")
        else:
            print(f"   📁 Collection: {self.collection_name}")
            print(f"   🏷️ Filter label (tenant): {self.filter_label}")

        # === NEO4J CONNECTION ===
        try:
            if not NEO4J_PASSWORD:
                raise ValueError("NEO4J_PASSWORD not set in environment")

            self.neo4j_driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USER, NEO4J_PASSWORD),
            )
            # Test connection
            with self.neo4j_driver.session() as session:
                session.run("RETURN 1")
            print(f"✅ Neo4j connected at {NEO4J_URI}")
        except Exception as e:
            print(f"⚠️ Neo4j connection failed: {e}")
            print("   GraphRAG will work with reduced graph features")
            self.neo4j_driver = None

        # === EMBEDDINGS ===
        self.embeddings = BGEM3Embeddings(timeout=180)
        self.embedding_dim = BGE_M3_DIMENSION

        # Cache embedding meta for stats/debug
        self.embedding_model = getattr(self.embeddings, "model_id", None)
        self.embedding_service_url = getattr(self.embeddings, "service_url", None)

        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.embedding_service_url) if self.embedding_service_url else None
            embedding_host = parsed.hostname if parsed else None
        except Exception:
            embedding_host = None

        print(
            f"✅ Embeddings ready "
            f"(model={self.embedding_model}, dim={self.embedding_dim}, host={embedding_host})"
        )

        # === LLM for architecture ===
        self.planner_model = LITELLM_PLANNER_MODEL
        self.pre_model = LITELLM_PRE_MODEL
        self.post_model = LITELLM_POST_MODEL

        # === PROMPT TEMPLATES ===
        self.planner_prompt = STRATEGIC_PLANNER_PROMPT
        self.entity_extraction_prompt = (
            entity_extraction_prompt or PRE_RETRIEVAL_SYSTEM_PROMPT
        )

        print("✅ GraphRAG Retriever initialized (Graph + Vector + Keyword)")

    def get_embedding(self, text: str) -> List[float]:
        """Get embedding using BGE-M3 Embeddings"""
        try:
            return self.embeddings.embed_query(text)
        except Exception as e:
            print(f"  ⚠️ Error getting embedding: {e}")
            return [0.0] * self.embedding_dim

    def plan_retrieval(self, query: str) -> Dict:
        """
        Think strategically and plan the retrieval steps.
        """
        try:
            messages = [
                {"role": "system", "content": self.planner_prompt},
                {"role": "user", "content": f"User Query: {query}"}
            ]
            
            content, used_model = _invoke_llm(
                messages,
                model=self.planner_model,
                max_tokens=800
            )
            
            # Clean JSON
            json_text = content.strip()
            if json_text.startswith("```"):
                json_text = re.sub(r"```json?\s*", "", json_text)
                json_text = re.sub(r"```\s*$", "", json_text)
                
            plan = json.loads(json_text)
            
            if self.debug:
                print(f"  🧠 Strategic Plan [{plan.get('mode')}]: {plan.get('reasoning')}")
                
            return plan
        except Exception as e:
            if self.debug:
                print(f"  ⚠️ Strategy Planning failed: {e}. Falling back to default LOCAL_SEARCH.")
            return {
                "mode": "LOCAL_SEARCH",
                "search_plan": {"use_vector": True, "use_graph": True, "use_keyword": True},
                "entities_german": [],
                "direct_reply": None
            }

    def extract_entities_with_llm(self, query: str) -> List[str]:
        """
        Extract entities from query using a hybrid approach:
        1. Fast rule-based extraction for common patterns (< 10ms)
        2. LLM fallback for complex queries
        
        Returns:
            List of extracted entity strings
        """
        entities = []
        
        # === FAST RULE-BASED EXTRACTION (< 10ms) ===
        
        # 1. Extract European currency amounts (€36.041,66)
        euro_amounts = re.findall(r'€\s*\d{1,3}(?:\.\d{3})*(?:,\d{2})?', query)
        entities.extend(euro_amounts)
        
        # 2. Extract percentages
        percentages = re.findall(r'\d+(?:,\d+)?\s*%', query)
        entities.extend(percentages)
        
        # 3. Extract years (1990-2099)
        years = re.findall(r'\b(19\d{2}|20\d{2})\b', query)
        entities.extend(years)
        
        # 4. Extract proper nouns (capitalized words in the middle of sentence)
        # Skip first word and common title words
        words = query.split()
        skip_words = {'Der', 'Die', 'Das', 'Was', 'Wie', 'Wer', 'Wo', 'Warum', 
                      'The', 'What', 'Who', 'Where', 'When', 'Why', 'How', 'Do', 'Does', 'Did',
                      'Can', 'Could', 'Would', 'Should', 'Is', 'Are', 'Was', 'Were', 'Have', 'Has'}
        for i, word in enumerate(words):
            if i > 0 and word[0].isupper() and word not in skip_words:
                clean_word = re.sub(r'[^\w]', '', word)  # Remove punctuation
                if len(clean_word) > 2:
                    entities.append(clean_word)
        
        # 5. Extract German compound nouns (words starting with capital, > 8 chars)
        german_nouns = re.findall(r'\b[A-ZÄÖÜ][a-zäöüß]{7,}\b', query)
        entities.extend(german_nouns)
        
        # 6. Extract organization patterns (GmbH, AG, e.V., etc.)
        org_patterns = re.findall(r'\b[\w\s]+(?:GmbH|AG|e\.V\.|Ltd|Inc|Corp)\b', query, re.IGNORECASE)
        entities.extend(org_patterns)
        
        # Deduplicate
        entities = list(set(entities))
        
        # === LLM FALLBACK for complex queries ===
        # Only call LLM if:
        # 1. We found very few entities (< 2) AND
        # 2. Query is complex (> 30 chars, no clear number pattern)
        use_llm = len(entities) < 2 and len(query) > 30 and not euro_amounts
        
        if use_llm:
            if self.debug:
                print(f"  🤖 Using LLM for complex entity extraction...")
            try:
                messages = [
                    {"role": "system", "content": self.entity_extraction_prompt},
                    {"role": "user", "content": f"Query: {query}"}
                ]
                
                content, used_model = _invoke_llm(
                    messages,
                    model=self.pre_model,
                    max_tokens=500,
                )

                if self.debug:
                    print(f"  🧠 Entity extraction model: {used_model}")
                
                response_text = content.strip()

                # Clean up response
                if response_text.startswith("```"):
                    response_text = re.sub(r"```json?\s*", "", response_text)
                    response_text = re.sub(r"```\s*$", "", response_text)

                llm_entities = json.loads(response_text)
                if isinstance(llm_entities, list):
                    entities.extend(llm_entities)
                    entities = list(set(entities))  # Deduplicate again

            except Exception as e:
                if self.debug:
                    print(f"  ⚠️ LLM entity extraction failed: {e}")
        else:
            if self.debug:
                print(f"  ⚡ Fast rule-based extraction used (skipped LLM)")
        
        if self.debug:
            print(f"  🔍 Extracted entities: {entities}")
        
        return entities

    def _extract_entities_simple(self, query: str) -> List[str]:
        """Fallback: Simple entity extraction without LLM"""
        entities = []

        # Capitalized words
        words = query.split()
        for word in words:
            clean_word = word.strip(".,?!:;")
            if clean_word and clean_word[0].isupper() and len(clean_word) > 2:
                entities.append(clean_word)

        # Numbers and percentages
        numbers = re.findall(r"\b\d+(?:\.\d+)?\s*(?:%|Prozent|Euro|€|Mrd\.|Mio\.)?", query)
        entities.extend(numbers)

        # Years
        years = re.findall(r"\b20[0-5]\d\b", query)
        entities.extend(years)

        return list(set(entities))

    def _execute_neo4j_query(self, session, query: str, params: dict):
        """
        Execute Neo4j query with error handling.
        All queries should include filter_label parameter.
        """
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return session.run(query, params)
        except Exception as e:
            if self.debug:
                print(f"  ⚠️ Neo4j query error: {e}")
            return None

    def entity_based_retrieval(self, entities: List[str], k: int = 20) -> Dict[int, float]:
        """
        Graph-based retrieval using Neo4j with strict filter_label isolation.

        All queries filter by filter_label to ensure multi-tenant isolation.
        Same entity name in different tenants will NOT match.

        Args:
            entities: List of entity names to search for
            k: Number of results per entity

        Returns:
            Dict mapping qdrant_point_id to relevance score
        """
        if not self.neo4j_driver or not entities:
            return {}

        if not self.filter_label:
            if self.debug:
                print("  ⚠️ No filter_label - skipping graph retrieval for safety")
            return {}

        entity_chunk_scores = {}

        try:
            with self.neo4j_driver.session() as session:
                for entity_name in entities:
                    # Query 1: Direct entity-chunk links within tenant
                    result = self._execute_neo4j_query(
                        session,
                        """
                        MATCH (e:Entity {filter_label: $filter_label})-[:APPEARS_IN]->(c:Chunk {filter_label: $filter_label})
                        WHERE toLower(e.name) CONTAINS toLower($entity_name)
                        WITH c, count(DISTINCT e) as entity_count
                        RETURN c.chunk_id as chunk_id,
                               c.qdrant_point_id as qdrant_point_id,
                               entity_count as relevance_score
                        ORDER BY relevance_score DESC
                        LIMIT $limit
                        """,
                        {
                            "filter_label": self.filter_label,
                            "entity_name": entity_name,
                            "limit": k,
                        },
                    )

                    if result:
                        for record in result:
                            qdrant_point_id = record.get("qdrant_point_id")
                            if qdrant_point_id is not None:
                                try:
                                    qdrant_id = int(qdrant_point_id)
                                    score = float(record["relevance_score"]) * 15
                                    entity_chunk_scores[qdrant_id] = (
                                        entity_chunk_scores.get(qdrant_id, 0) + score
                                    )
                                except (ValueError, TypeError):
                                    # Fallback to computing from chunk_id
                                    chunk_id = record.get("chunk_id")
                                    if chunk_id:
                                        qdrant_id = compute_point_id(chunk_id)
                                        if qdrant_id:
                                            score = float(record["relevance_score"]) * 15
                                            entity_chunk_scores[qdrant_id] = (
                                                entity_chunk_scores.get(qdrant_id, 0) + score
                                            )

                    # Query 2: Related entities through relationships (within tenant only)
                    # First get relationship types that exist in this tenant
                    rel_types_result = self._execute_neo4j_query(
                        session,
                        """
                        MATCH (e:Entity {filter_label: $filter_label})-[r]->(:Entity {filter_label: $filter_label})
                        WHERE r.filter_label = $filter_label
                        AND NOT type(r) IN ['APPEARS_IN', 'EXTRACTED_FROM', 'HAS_CHUNK']
                        RETURN DISTINCT type(r) as rel_type
                        LIMIT 10
                        """,
                        {"filter_label": self.filter_label},
                    )

                    rel_types = []
                    if rel_types_result:
                        rel_types = [r["rel_type"] for r in rel_types_result]

                    for rel_type in rel_types:
                        # Find chunks through related entities (strict tenant isolation)
                        result = self._execute_neo4j_query(
                            session,
                            f"""
                            MATCH (e1:Entity {{filter_label: $filter_label}})-[:APPEARS_IN]->(c1:Chunk {{filter_label: $filter_label}})
                            WHERE toLower(e1.name) CONTAINS toLower($entity_name)
                            WITH e1
                            MATCH (e1)-[r:{rel_type} {{filter_label: $filter_label}}]-(e2:Entity {{filter_label: $filter_label}})
                            MATCH (e2)-[:APPEARS_IN]->(c2:Chunk {{filter_label: $filter_label}})
                            WITH c2, count(DISTINCT e2) as rel_count
                            RETURN c2.chunk_id as chunk_id,
                                   c2.qdrant_point_id as qdrant_point_id,
                                   rel_count as relevance_score
                            ORDER BY relevance_score DESC
                            LIMIT $limit
                            """,
                            {
                                "filter_label": self.filter_label,
                                "entity_name": entity_name,
                                "limit": k // 2,
                            },
                        )

                        if result:
                            for record in result:
                                qdrant_point_id = record.get("qdrant_point_id")
                                if qdrant_point_id is not None:
                                    try:
                                        qdrant_id = int(qdrant_point_id)
                                        score = float(record["relevance_score"]) * 8
                                        entity_chunk_scores[qdrant_id] = (
                                            entity_chunk_scores.get(qdrant_id, 0) + score
                                        )
                                    except (ValueError, TypeError):
                                        pass

                    # Query 3: Cross-document entities within tenant (high value for knowledge synthesis)
                    result = self._execute_neo4j_query(
                        session,
                        """
                        MATCH (e:Entity {filter_label: $filter_label})-[:EXTRACTED_FROM]->(d:Document {filter_label: $filter_label})
                        WHERE toLower(e.name) CONTAINS toLower($entity_name)
                        WITH e, count(DISTINCT d) as doc_count
                        WHERE doc_count > 1
                        MATCH (e)-[:APPEARS_IN]->(c:Chunk {filter_label: $filter_label})
                        RETURN c.chunk_id as chunk_id,
                               c.qdrant_point_id as qdrant_point_id,
                               e.name as entity_name,
                               doc_count,
                               doc_count * 10 as relevance_score
                        ORDER BY relevance_score DESC
                        LIMIT $limit
                        """,
                        {
                            "filter_label": self.filter_label,
                            "entity_name": entity_name,
                            "limit": k // 3,
                        },
                    )

                    if result:
                        for record in result:
                            qdrant_point_id = record.get("qdrant_point_id")
                            if qdrant_point_id is not None:
                                try:
                                    qdrant_id = int(qdrant_point_id)
                                    score = float(record["relevance_score"]) * 12
                                    entity_chunk_scores[qdrant_id] = (
                                        entity_chunk_scores.get(qdrant_id, 0) + score
                                    )
                                except (ValueError, TypeError):
                                    pass

        except Exception as e:
            if self.debug:
                print(f"  ⚠️ Neo4j retrieval error: {e}")

        if self.debug and entity_chunk_scores:
            print(f"  🔗 Graph found {len(entity_chunk_scores)} chunks for entities: {entities}")

        return entity_chunk_scores

    def expand_query_with_cot(self, query: str) -> Dict:
        """Chain-of-Thought query expansion"""
        query_lower = query.lower()

        expanded = {
            "original": query,
            "keywords": [],
            "numbers": [],
            "years": [],
            "percentages": [],
            "expected_patterns": [],
        }

        # Extract European-format numbers (periods as thousand separators, comma as decimal)
        # Matches: 36.041,66 or €36.041,66 or 36.041 or 1.234.567,89
        euro_numbers = re.findall(r'€?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)', query)
        # Also extract plain numbers
        plain_numbers = re.findall(r'\b(\d+)\b', query)
        
        # Normalize European numbers for matching (add variants)
        normalized_numbers = []
        for num in euro_numbers:
            normalized_numbers.append(num)  # Original: 36.041,66
            normalized_numbers.append("€ " + num)  # With symbol and space: € 36.041,66
            normalized_numbers.append("€" + num)  # With symbol: €36.041,66
            # Also store without thousand separators for partial matching
            no_thousand = num.replace(".", "")  # 36041,66
            normalized_numbers.append(no_thousand)
        
        expanded["numbers"] = list(set(euro_numbers + plain_numbers + normalized_numbers))
        expanded["years"] = [n for n in plain_numbers if n.isdigit() and 1990 <= int(n) <= 2050]
        expanded["percentages"] = re.findall(r'\d+\s*%', query)

        words = re.findall(r"\b[A-Za-zÄÖÜäöüß]+\b", query)
        
        # Comprehensive stop words: German + English
        stop_words = {
            # German
            "der", "die", "das", "und", "oder", "ist", "sind", "war", "waren",
            "wird", "werden", "wurde", "wurden", "haben", "hat", "hatte", "hatten",
            "welche", "welcher", "welches", "wie", "was", "wann", "wo", "warum",
            "wer", "wem", "wen", "wessen", "bis", "für", "auf", "mit", "von", "zu",
            "bei", "nach", "über", "unter", "vor", "hinter", "neben", "zwischen",
            "durch", "gegen", "ohne", "um", "aus", "an", "in", "im", "am", "zum",
            "zur", "beim", "vom", "ins", "ans", "aufs", "durchs", "fürs", "ums",
            "ob", "wenn", "als", "weil", "dass", "damit", "obwohl", "obgleich",
            "während", "nachdem", "bevor", "sobald", "solange", "sofern", "falls",
            "auch", "noch", "schon", "erst", "nur", "bloß", "aber", "jedoch",
            "sondern", "denn", "doch", "also", "daher", "deshalb", "deswegen",
            "darum", "folglich", "somit", "trotzdem", "dennoch", "allerdings",
            "ein", "eine", "einer", "eines", "einem", "einen", "kein", "keine",
            "keiner", "keines", "keinem", "keinen", "mein", "meine", "dein", "deine",
            "sein", "seine", "ihr", "ihre", "unser", "unsere", "euer", "eure",
            "dieser", "diese", "dieses", "jener", "jene", "jenes", "solcher",
            "solche", "solches", "welch", "irgendein", "irgendeine", "alle", "jede",
            "jeder", "jedes", "manche", "mancher", "manches", "einige", "etliche",
            "mehrere", "viele", "wenige", "beide", "sämtliche", "jedwede",
            "ich", "du", "er", "sie", "es", "wir", "ihr", "Sie", "mich", "dich",
            "ihn", "uns", "euch", "mir", "dir", "ihm", "ihnen",
            "nicht", "nichts", "nie", "niemals", "nirgends", "nirgendwo",
            "sehr", "ganz", "recht", "ziemlich", "etwas", "wenig", "viel", "mehr",
            "genug", "fast", "beinahe", "kaum", "höchst", "äußerst", "besonders",
            "ja", "nein", "vielleicht", "wohl", "etwa", "ungefähr", "circa",
            # English
            "the", "a", "an", "and", "or", "but", "if", "then", "else", "when",
            "at", "by", "for", "with", "about", "against", "between", "into",
            "through", "during", "before", "after", "above", "below", "to", "from",
            "up", "down", "in", "out", "on", "off", "over", "under", "again",
            "further", "once", "here", "there", "where", "why", "how", "all",
            "each", "few", "more", "most", "other", "some", "such", "no", "nor",
            "not", "only", "own", "same", "so", "than", "too", "very", "can",
            "will", "just", "don", "should", "now", "would", "could", "might",
            "must", "shall", "may", "need", "dare", "ought", "used", "had", "has",
            "have", "having", "do", "does", "did", "doing", "be", "been", "being",
            "am", "is", "are", "was", "were", "i", "me", "my", "myself", "we",
            "our", "ours", "ourselves", "you", "your", "yours", "yourself",
            "yourselves", "he", "him", "his", "himself", "she", "her", "hers",
            "herself", "it", "its", "itself", "they", "them", "their", "theirs",
            "themselves", "what", "which", "who", "whom", "this", "that", "these",
            "those", "any", "both", "each", "few", "many", "much", "neither",
            "either", "several", "enough", "another", "every", "nobody", "somebody",
            "anybody", "everybody", "nothing", "something", "anything", "everything",
            "see", "seeing", "seen", "saw", "remember", "document", "documents",
            "find", "finding", "found", "show", "showing", "shown", "tell", "told",
        }
        
        # Filter: not a stop word, at least 3 chars, and contains meaningful content
        expanded["keywords"] = [
            w for w in words 
            if w.lower() not in stop_words 
            and len(w) > 3  # Increased from 2 to 3
            and not w.lower() in ["money", "euro", "euros", "geld", "summe", "sum", "amount"]  # These are covered by number extraction
        ]

        if "anteil" in query_lower or "prozent" in query_lower:
            expanded["expected_patterns"] = [
                "prozent",
                "%",
                "drittel",
                "hälfte",
                "viertel",
                "anteil",
            ]
        if "betrag" in query_lower or "€" in query or "euro" in query_lower:
            expanded["expected_patterns"].extend(["mrd", "milliarden", "€", "euro"])
        if "ziel" in query_lower:
            expanded["expected_patterns"].extend(["bis", "2030", "2035", "2040", "2050", "%"])

        return expanded

    def vector_search(self, query: str, k: int) -> Dict[int, float]:
        """Vector search using embeddings (Qdrant collection = tenant isolation)"""
        query_embedding = self.get_embedding(query)

        # Fallback logic for Qdrant client methods (search vs query)
        try:
            # Manual REST call to bypass QdrantClient connection issues
            import requests
            import json
            
            # Robust connection details
            q_url = os.getenv("QDRANT_URL", "https://qdrant.api.blaiq.ai").rstrip("/")
            search_url = f"{q_url}/collections/{self.collection_name}/points/search"
            
            # Extract API key if set based on client headers
            headers = {}
            api_key = os.getenv("QDRANT_API_KEY") or (self.qdrant_client._api_key if hasattr(self.qdrant_client, "_api_key") else None)
            
            if api_key:
                headers["api-key"] = api_key
            
            payload = {
                "vector": query_embedding,
                "limit": k,
                "with_payload": True,
                "score_threshold": 0.0 # Return all
            }
            
            if self.debug:
                 print(f"DEBUG: Manual Qdrant Search (requests) to {search_url}")

            # Use requests with verify=False
            try:
                resp = requests.post(search_url, json=payload, headers=headers, verify=False, timeout=10.0)
                if self.debug: print(f"DEBUG: Qdrant response status: {resp.status_code}")
            except Exception as req_err:
                print(f"  ❌ requests.post failed: {req_err}")
                raise req_err
            
            if resp.status_code == 200:
                results = resp.json().get("result", [])
                if self.debug: print(f"DEBUG: Qdrant returned {len(results)} results")
                # Do not cast to int, Qdrant IDs can be UUIDs. Ensure score is float.
                return {
                    point.get("id"): float(point.get("score") or 0.0) 
                    for point in results 
                    if point.get("id") is not None
                }
            else:
                print(f"  ⚠️ Manual Qdrant search failed: {resp.status_code} - {resp.text}")
                return {}

        except Exception as e:
            print(f"  ⚠️ Vector search failed (requests): {e}")
            return {}

    def keyword_search(self, query: str, expanded_query: Dict, k: int) -> Dict[int, float]:
        """
        Optimized keyword search using Qdrant's native text matching.
        
        PERFORMANCE: 10-50x faster than scroll-based approach.
        Uses Qdrant's indexed text search instead of Python string matching.
        Enhanced to handle European number formats.
        """
        search_terms = expanded_query["keywords"] + expanded_query["numbers"]
        
        if not search_terms:
            return {}
        
        keyword_scores = {}
        
        if self.debug:
            print(f"  🔑 Keyword search terms: {search_terms[:15]}")
        
        # Strategy: Search for each term separately, then aggregate scores
        # This is much faster than scrolling all documents
        for term in search_terms[:15]:  # Increased limit to include number variants
            term_str = str(term).strip()
            if len(term_str) < 2:  # Skip very short terms
                continue
            
            # Clean the term for Qdrant matching
            # Remove € for cleaner matching, we'll search for the number part
            clean_term = term_str.replace("€", "").strip().lower()
            
            # Skip if it's just symbols
            if not any(c.isalnum() for c in clean_term):
                continue
            
            try:
                # Use Qdrant's MatchText filter for indexed search
                # Use Manual REST for scroll to avoid connection issues
                import requests
                
                q_url = os.getenv("QDRANT_URL", "https://qdrant.api.blaiq.ai").rstrip("/")
                scroll_url = f"{q_url}/collections/{self.collection_name}/points/scroll"
                
                headers = {}
                api_key = os.getenv("QDRANT_API_KEY") or (self.qdrant_client._api_key if hasattr(self.qdrant_client, "_api_key") else None)
                if api_key:
                    headers["api-key"] = api_key

                # For numeric terms with European formatting, extract just digits
                # 36.041,66 -> search for "36041" or "36.041"
                is_number = bool(re.match(r'^[\d.,]+$', clean_term))
                
                if is_number:
                    # For numbers, try multiple search strategies
                    # Strategy 1: Search for digits without separators
                    digits_only = re.sub(r'[^\d]', '', clean_term)
                    # Strategy 2: Search for first significant part (before comma)
                    main_part = clean_term.split(',')[0]
                    
                    search_variants = [clean_term, digits_only, main_part]
                    search_variants = list(set([v for v in search_variants if len(v) >= 3]))
                else:
                    search_variants = [clean_term]

                for variant in search_variants:
                    payload = {
                        "filter": {
                            "must": [
                                {
                                    "key": "text",
                                    "match": {"text": variant}
                                }
                            ]
                        },
                        "limit": min(k * 2, 100),
                        "with_payload": True
                    }

                    resp = requests.post(scroll_url, json=payload, headers=headers, verify=False, timeout=5.0)
                    
                    if resp.status_code == 200:
                        data = resp.json().get("result", {}).get("points", [])
                        # Lightweight object to mimic Qdrant PointStruct for downstream code
                        class SimpleRecord:
                            def __init__(self, d):
                                self.id = d.get("id")
                                self.payload = d.get("payload", {})
                        
                        records = [SimpleRecord(r) for r in data]
                        
                        if self.debug and records:
                            print(f"    📄 Found {len(records)} matches for '{variant}'")
                    else:
                        if self.debug: 
                            print(f"  ⚠️ Keyword scroll failed for '{variant}': {resp.status_code}")
                        records = []
                    
                    # Score based on term frequency in matched documents
                    for record in records:
                        text = record.payload.get("text", "").lower()
                        # For numbers, boost score if the exact amount appears
                        if is_number and clean_term in text:
                            tf = text.count(clean_term)
                            score = math.log(1 + tf) * 20  # Higher boost for exact number match
                        else:
                            tf = text.count(variant)
                            score = math.log(1 + tf) * 10
                        
                        # Aggregate scores for documents matching multiple terms
                        point_id = record.id
                        keyword_scores[point_id] = keyword_scores.get(point_id, 0) + score
                        
            except Exception as e:
                if self.debug:
                    print(f"  ⚠️ Keyword search error for term '{term_str}': {e}")
                # Fallback: continue with other terms
                continue
        
        # Sort by score and return top k
        sorted_results = sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_results[:k])

    def get_adjacent_chunks(self, point_ids: List[int], window_size: int = 1) -> Dict[int, float]:
        """Get adjacent chunks for context expansion in parallel"""
        adjacent_results = {}

        if not point_ids:
            return adjacent_results

        import requests
        from concurrent.futures import ThreadPoolExecutor

        q_url = os.getenv("QDRANT_URL", "https://qdrant.api.blaiq.ai").rstrip("/")
        api_key = os.getenv("QDRANT_API_KEY") or (self.qdrant_client._api_key if hasattr(self.qdrant_client, "_api_key") else None)
        headers = {"api-key": api_key} if api_key else {}

        # 1. Fetch original blocks to get metadata
        try:
            resp = requests.post(
                f"{q_url}/collections/{self.collection_name}/points", 
                json={"ids": point_ids[:40], "with_payload": True}, 
                headers=headers, timeout=5.0
            )
            if resp.status_code != 200:
                return adjacent_results
            
            points_data = resp.json().get("result", [])
        except Exception:
            return adjacent_results

        # 2. Define worker for fetching neighbors
        def fetch_neighbor(doc_id, target_idx, offset):
            try:
                scroll_payload = {
                    "filter": {
                        "must": [
                            {"key": "doc_id", "match": {"text": doc_id}},
                            {"key": "chunk_index", "match": {"value": target_idx}}
                        ]
                    },
                    "limit": 1,
                    "with_payload": True
                }
                res = requests.post(f"{q_url}/collections/{self.collection_name}/points/scroll", 
                                   json=scroll_payload, headers=headers, timeout=2.0)
                if res.status_code == 200:
                    pts = res.json().get("result", {}).get("points", [])
                    if pts:
                        return pts[0].get("id"), 10.0 / (1 + abs(offset))
            except Exception:
                pass
            return None

        # 3. Queue neighbor tasks
        tasks = []
        for p in points_data:
            payload = p.get("payload", {})
            doc_id = payload.get("doc_id")
            chunk_index = payload.get("chunk_index")
            if doc_id is None or chunk_index is None:
                continue
                
            for offset in range(-window_size, window_size + 1):
                if offset == 0: continue
                target_idx = chunk_index + offset
                if target_idx < 0: continue
                tasks.append((doc_id, target_idx, offset))

        # 4. Execute in Parallel
        if tasks:
            with ThreadPoolExecutor(max_workers=min(len(tasks), 20)) as executor:
                futures = [executor.submit(fetch_neighbor, *t) for t in tasks]
                for f in futures:
                    res = f.result()
                    if res:
                        neighbor_id, score = res
                        adjacent_results[neighbor_id] = score

        return adjacent_results

    def weighted_rrf_fusion(
        self,
        rankings: Dict[str, Dict[int, float]],
        weights: Dict[str, float] = None,
        k: int = 60,
    ) -> List[Tuple[int, float]]:
        """Weighted Reciprocal Rank Fusion"""
        if weights is None:
            num_methods = len(rankings)
            weights = {method: 1.0 / num_methods for method in rankings}

        fused_scores = defaultdict(float)

        for method_name, ranking in rankings.items():
            if not ranking:
                continue

            method_weight = weights.get(method_name, 0.1)
            sorted_items = sorted(ranking.items(), key=lambda x: x[1], reverse=True)

            for rank, (doc_id, original_score) in enumerate(sorted_items, 1):
                fused_scores[doc_id] += method_weight * (1 / (k + rank))

        return sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

    def _retrieve_chunks(self, ranked_results: List[Tuple[Any, float]]) -> List[Document]:
        """Retrieve actual chunk documents from ranked results"""
        chunks = []

        if not ranked_results:
            return chunks

        point_ids = [pid for pid, _ in ranked_results]

        try:
            # Manual REST call to bypass QdrantClient connection issues
            import requests
            
            q_url = os.getenv("QDRANT_URL", "https://qdrant.api.blaiq.ai").rstrip("/")
            retrieve_url = f"{q_url}/collections/{self.collection_name}/points"
            
            headers = {}
            api_key = os.getenv("QDRANT_API_KEY") or (self.qdrant_client._api_key if hasattr(self.qdrant_client, "_api_key") else None)
            if api_key:
                headers["api-key"] = api_key
            
            # Use requests with verify=False
            if self.debug:
                 print(f"DEBUG: Retrieving {len(point_ids)} chunks from {retrieve_url}")

            resp = requests.post(
                retrieve_url,
                json={"ids": point_ids, "with_payload": True},
                headers=headers,
                verify=False,
                timeout=5.0
            )

            if resp.status_code == 200:
                points_data = resp.json().get("result", [])
                
                # Create a map for order-preserving lookups
                # Normalize keys to string to handle UUID/Int mix
                points_map = {str(p.get("id")): p for p in points_data}

                for i, (pid, score) in enumerate(ranked_results):
                    point = points_map.get(str(pid))
                    
                    if not point:
                        continue

                    payload = point.get("payload", {})
                    
                    chunk = Document(
                        page_content=payload.get("text", ""),
                        metadata={
                            "qdrant_id": point.get("id"),
                            "doc_id": payload.get("doc_id", ""),
                            "chunk_id": payload.get("chunk_id", ""),
                            "chunk_index": payload.get("chunk_index", 0),
                            "fusion_score": score,
                            "retrieval_rank": i + 1,
                        },
                    )
                    chunks.append(chunk)
            else:
                 print(f"  ⚠️ Failed to retrieve chunks: Status {resp.status_code} - {resp.text}")

        except Exception as e:
            print(f"  ⚠️ Error retrieving chunks: {e}")

        return chunks

    def graphrag_retrieval(
        self, query: str, k: int = 20, debug: bool = None
    ) -> Tuple[List[Document], Dict]:
        """
        Strategic Context-Driven Retrieval.
        Instead of a fixed pipeline, we plan the search first.
        """
        if debug is None:
            debug = self.debug

        # --- STEP 1: STRATEGIC PLANNING ---
        print(f"🎯 Planning retrieval strategy for: '{query[:50]}...'")
        plan = self.plan_retrieval(query)
        search_mode = plan.get("mode", "LOCAL_SEARCH")
        
        # --- RESPONSE BRANCH A: SMALL TALK ---
        if search_mode == "SMALL_TALK":
            print("  ☕ Direct conversational reply (No DB search needed)")
            system_doc = Document(
                page_content=plan.get("direct_reply") or "Hallo! Wie kann ich Ihnen bei Ihren Dokumenten helfen?",
                metadata={"mode": "small_talk", "is_direct": True}
            )
            return [system_doc], {"mode": "small_talk", "plan": plan}

        # --- RESPONSE BRANCH B: GLOBAL HIVE ---
        if search_mode == "GLOBAL_SEARCH":
            print("  🕸️ Global Hive Mode: Strategic summary across corpus")
            summary = self.generate_global_hive_summary(query)
            if summary:
                global_doc = Document(
                    page_content=summary,
                    metadata={"mode": "global_hive", "is_direct": True}
                )
                return [global_doc], {"mode": "global_hive", "plan": plan}
            # If global summary fails, fall back to local search
            print("  ⚠️ Global summary failed, falling back to local search")

        # --- RESPONSE BRANCH C: LOCAL SEARCH (EVENT DRIVEN) ---
        print(f"🔍 Executing Local Search (tenant: {self.filter_label})...")
        
        # Use planner's already extracted entities
        entities = plan.get("entities_german", [])
        if not entities:
            # Fallback to secondary extraction if planner missed them
            entities = self.extract_entities_with_llm(query)
            
        search_plan = plan.get("search_plan", {"use_vector": True, "use_graph": True, "use_keyword": True})
        
        broad_k = k * 10
        rankings = {}
        
        # 1. GRAPH (Conditional)
        if search_plan.get("use_graph") and self.neo4j_driver and entities and self.filter_label:
            graph_results = self.entity_based_retrieval(entities, k=broad_k)
            if graph_results:
                rankings["graph"] = graph_results
                print(f"  🔗 Graph used: {len(graph_results)} entity-linked chunks")
        
        # 2. VECTOR (Conditional)
        if search_plan.get("use_vector"):
            vector_results = self.vector_search(query, k=broad_k)
            rankings["vector"] = vector_results
            print(f"  📊 Vector used: {len(vector_results)} results")
            
        # 3. KEYWORD (Conditional)
        if search_plan.get("use_keyword"):
            expanded_query = self.expand_query_with_cot(query)
            keyword_results = self.keyword_search(query, expanded_query, k=broad_k)
            rankings["keyword"] = keyword_results
            print(f"  🔑 Keyword used: {len(keyword_results)} results")

        # 4. ADJACENT CHUNKS (Context preservation)
        all_top = []
        for r_dict in rankings.values():
            all_top.extend(list(r_dict.keys())[:10])
        all_top = list(set(all_top[:30]))
        
        if all_top:
            adjacent_results = self.get_adjacent_chunks(all_top[:20], window_size=1)
            if adjacent_results:
                rankings["adjacent"] = adjacent_results

        # Stage 4: Fusion
        if not rankings:
            return [], {"mode": "error", "error": "No relevant data found"}

        # Dynamic weights based on planner context
        if "graph" in rankings:
            weights = {"graph": 0.40, "vector": 0.45, "keyword": 0.10, "adjacent": 0.05}
        else:
            weights = {"vector": 0.70, "keyword": 0.25, "adjacent": 0.05}

        fused_results = self.weighted_rrf_fusion(rankings, weights=weights, k=60)
        chunks = self._retrieve_chunks(fused_results[:k])

        stats = {
            "mode": "local_search",
            "planning": plan,
            "graph_used": "graph" in rankings,
            "vector_used": "vector" in rankings,
            "keyword_used": "keyword" in rankings,
            "chunks_retrieved": len(chunks),
            "filter_label": self.filter_label
        }

        return chunks, stats

    def get_graph_for_entities(
        self, entities: List[str], depth: int = 1, limit: int = 50
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Get graph data (entities and relationships) from Neo4j for given entity names.

        Strict filter_label isolation - only returns entities/relationships from current tenant.

        Args:
            entities: List of entity names to search for
            depth: How many hops to traverse (1-3)
            limit: Maximum number of entities to return

        Returns:
            Tuple of (entities_list, relationships_list)
        """
        if not self.neo4j_driver or not entities:
            return [], []

        if not self.filter_label:
            if self.debug:
                print("  ⚠️ No filter_label - skipping graph visualization for safety")
            return [], []

        found_entities = {}
        found_relationships = []

        try:
            with self.neo4j_driver.session() as session:
                for entity_name in entities:
                    # Build query based on depth - ALL queries enforce filter_label
                    if depth == 1:
                        query = """
                        MATCH (e:Entity {filter_label: $filter_label})
                        WHERE toLower(e.name) CONTAINS toLower($entity_name)
                        WITH e
                        LIMIT 10
                        OPTIONAL MATCH (e)-[r]-(e2:Entity {filter_label: $filter_label})
                        WHERE NOT type(r) IN ['APPEARS_IN', 'EXTRACTED_FROM', 'HAS_CHUNK']
                          AND (r.filter_label IS NULL OR r.filter_label = $filter_label)
                        RETURN e, r, e2
                        LIMIT $limit
                        """
                    elif depth == 2:
                        query = """
                        MATCH (e:Entity {filter_label: $filter_label})
                        WHERE toLower(e.name) CONTAINS toLower($entity_name)
                        WITH e
                        LIMIT 5
                        OPTIONAL MATCH path = (e)-[*1..2]-(e2:Entity {filter_label: $filter_label})
                        WHERE ALL(node IN nodes(path) WHERE node:Entity AND node.filter_label = $filter_label)
                          AND ALL(rel IN relationships(path) WHERE 
                              NOT type(rel) IN ['APPEARS_IN', 'EXTRACTED_FROM', 'HAS_CHUNK']
                              AND (rel.filter_label IS NULL OR rel.filter_label = $filter_label))
                        UNWIND relationships(path) as rel
                        WITH e, rel, startNode(rel) as src, endNode(rel) as tgt
                        RETURN DISTINCT e, rel as r, 
                               CASE WHEN src = e THEN tgt ELSE src END as e2
                        LIMIT $limit
                        """
                    else:  # depth == 3
                        query = """
                        MATCH (e:Entity {filter_label: $filter_label})
                        WHERE toLower(e.name) CONTAINS toLower($entity_name)
                        WITH e
                        LIMIT 3
                        OPTIONAL MATCH path = (e)-[*1..3]-(e2:Entity {filter_label: $filter_label})
                        WHERE ALL(node IN nodes(path) WHERE node:Entity AND node.filter_label = $filter_label)
                          AND ALL(rel IN relationships(path) WHERE 
                              NOT type(rel) IN ['APPEARS_IN', 'EXTRACTED_FROM', 'HAS_CHUNK']
                              AND (rel.filter_label IS NULL OR rel.filter_label = $filter_label))
                        UNWIND relationships(path) as rel
                        WITH e, rel, startNode(rel) as src, endNode(rel) as tgt
                        RETURN DISTINCT e, rel as r,
                               CASE WHEN src = e THEN tgt ELSE src END as e2
                        LIMIT $limit
                        """

                    result = self._execute_neo4j_query(
                        session,
                        query,
                        {
                            "filter_label": self.filter_label,
                            "entity_name": entity_name,
                            "limit": limit,
                        },
                    )

                    if result:
                        for record in result:
                            # Process source entity
                            e = record.get("e")
                            if e:
                                eid = e.get("global_id", str(e.id))
                                if eid not in found_entities:
                                    found_entities[eid] = {
                                        "id": eid,
                                        "name": e.get("name", "Unknown"),
                                        "type": e.get("type", "UNKNOWN"),
                                    }

                            # Process target entity
                            e2 = record.get("e2")
                            if e2:
                                e2id = e2.get("global_id", str(e2.id))
                                if e2id not in found_entities:
                                    found_entities[e2id] = {
                                        "id": e2id,
                                        "name": e2.get("name", "Unknown"),
                                        "type": e2.get("type", "UNKNOWN"),
                                    }

                            # Process relationship
                            r = record.get("r")
                            if r and e and e2:
                                rel_data = {
                                    "source_id": e.get("global_id", str(e.id)),
                                    "target_id": e2.get("global_id", str(e2.id)),
                                    "type": r.type,
                                }
                                if rel_data not in found_relationships:
                                    found_relationships.append(rel_data)

        except Exception as e:
            if self.debug:
                print(f"  ⚠️ Graph query error: {e}")

        return list(found_entities.values()), found_relationships

    def discover_communities(self, limit: int = 5) -> List[Dict]:
        """
        Global Hive: Discover structural communities in the graph.
        Identifies clusters of entities that are highly connected.
        """
        if not self.neo4j_driver or not self.filter_label:
            return []

        logger.info(f"🕸️ Discovering communities for tenant: {self.filter_label}")
        
        try:
            with self.neo4j_driver.session() as session:
                # Find entities that have the most relationships within this tenant
                query = """
                MATCH (e:Entity {filter_label: $filter_label})
                WITH e, count{(e)-[:RELATIONSHIP]-(:Entity)} as rel_count
                WHERE rel_count > 1
                MATCH (e)-[:RELATIONSHIP]-(neighbor:Entity {filter_label: $filter_label})
                WITH e, collect(DISTINCT neighbor.name) as connections, rel_count
                ORDER BY rel_count DESC
                LIMIT $limit
                RETURN e.name as community_root, connections, rel_count as density
                """
                result = session.run(query, {"filter_label": self.filter_label, "limit": limit})
                communities = [record.data() for record in result]
                return communities
        except Exception as e:
            logger.error(f"❌ Community discovery failed: {e}")
            return []

    def generate_global_hive_summary(self, query: str) -> Optional[str]:
        """
        Enterprise Hive Intelligence: Answers high-level 'Global' questions 
        by analyzing community structures instead of just local chunks.
        """
        communities = self.discover_communities(limit=10)
        if not communities:
            return None
            
        # Group community info for the LLM
        context = "ENTEPRISE HIVE INTELLIGENCE - GRAPH COMMUNITIES:\n"
        for i, comm in enumerate(communities):
            context += f"Community {i+1} (Root: {comm['community_root']}):\n"
            context += f" - Key Connections: {', '.join(comm['connections'][:10])}\n"
            context += f" - Connection Density: {comm['density']}\n\n"
            
        prompt = f"""
        You are the Enterprise Hive Intelligence. 
        Based on the structural relationships in the Knowledge Graph provided below, 
        answer the user's high-level strategic question.
        
        GRAPH CONTEXT:
        {context}
        
        USER QUESTION:
        {query}
        
        Focus on identifying patterns, shared risks, and commonalities across the entire dataset.
        If the data doesn't provide enough information, state that clearly.
        """
        
        try:
            messages = [
                {"role": "system", "content": "You are a strategic intelligence layer for a Graph-based Knowledge Management system."},
                {"role": "user", "content": prompt}
            ]
            
            # Global summarization also benefits from the reasoning model
            content, used_model = _invoke_llm(
                messages,
                model=self.post_model,
                max_tokens=2000
            )
            return content
        except Exception as e:
            logger.error(f"❌ Global Hive Summary failed: {e}")
            return None

    def neo4j_to_mermaid(self, entities: List[Dict], relationships: List[Dict]) -> str:
        """
        Convert Neo4j graph data to Mermaid flowchart syntax.

        Args:
            entities: List of entity dicts with id, name, type
            relationships: List of relationship dicts with source_id, target_id, type

        Returns:
            Mermaid diagram code string
        """
        if not entities:
            return "graph LR\n    empty[No graph data]"

        lines = ["graph LR"]

        # Create node ID mapping (sanitize for Mermaid)
        node_ids = {}
        for i, entity in enumerate(entities):
            node_ids[entity["id"]] = f"E{i}"

        # Add nodes with shapes based on entity type
        type_shapes = {
            "PERSON": ('["', '"]'),  # Rectangle
            "ROLLE": ('["', '"]'),  # Rectangle
            "ORGANISATION": ('(["', '"])'),  # Stadium shape
            "ORT": ('{{"', '"}}'),  # Rhombus
            "IMMOBILIE": ('{{"', '"}}'),  # Rhombus
            "DOKUMENT": ('(["', '"])'),  # Stadium
            "KONZEPT": ('(("', '"))'),  # Circle
            "EVENT": ('(["', '"])'),  # Stadium
            "ZEIT": ('["', '"]'),  # Rectangle
            "FINANZIELL": ('["', '"]'),  # Rectangle
            "BESTAND": ('["', '"]'),  # Rectangle
            "SERVICE": ('(["', '"])'),  # Stadium
        }

        for entity in entities:
            node_id = node_ids.get(entity["id"])
            if not node_id:
                continue

            etype = entity.get("type", "UNKNOWN")
            name = entity.get("name", "?")

            # Escape special characters for Mermaid
            name = name.replace('"', "'").replace("\n", " ")[:40]
            if len(entity.get("name", "")) > 40:
                name += "..."

            # Get shape based on type
            prefix, suffix = type_shapes.get(etype, ('["', '"]'))
            lines.append(f"    {node_id}{prefix}{name}{suffix}")

        # Add relationships
        for rel in relationships:
            source_id = node_ids.get(rel["source_id"])
            target_id = node_ids.get(rel["target_id"])
            rel_type = rel.get("type", "RELATED")

            # Shorten relationship type for display
            rel_display = rel_type.replace("_", " ")[:15]

            if source_id and target_id:
                lines.append(f"    {source_id} -->|{rel_display}| {target_id}")

        # Add styling
        lines.append("")
        lines.append("    %% Styling")
        lines.append("    classDef person fill:#e1f5fe,stroke:#01579b")
        lines.append("    classDef org fill:#fff3e0,stroke:#e65100")
        lines.append("    classDef place fill:#e8f5e9,stroke:#2e7d32")
        lines.append("    classDef concept fill:#f3e5f5,stroke:#7b1fa2")
        lines.append("    classDef finance fill:#fff8e1,stroke:#f57f17")

        return "\n".join(lines)

    def get_graph_visualization(self, entities: List[str], depth: int = 1) -> Optional[Dict]:
        """
        Get complete graph visualization data for given entities.

        Args:
            entities: List of entity names to visualize
            depth: Graph traversal depth (1-3)

        Returns:
            Dict with mermaid_code, nodes, edges, entities, relationships
            or None if no graph data found
        """
        if not self.neo4j_driver:
            return None

        if not self.filter_label:
            return None

        # Get graph data from Neo4j (filter_label isolated)
        found_entities, found_relationships = self.get_graph_for_entities(
            entities=entities, depth=depth, limit=50
        )

        if not found_entities:
            return None

        # Generate Mermaid code
        mermaid_code = self.neo4j_to_mermaid(found_entities, found_relationships)

        return {
            "mermaid_code": mermaid_code,
            "nodes": len(found_entities),
            "edges": len(found_relationships),
            "entities": found_entities,
            "relationships": found_relationships,
            "filter_label": self.filter_label,
        }

    def get_tenant_stats(self) -> Optional[Dict]:
        """
        Get statistics for current tenant from Neo4j.

        Returns:
            Dict with entity/relationship counts or None if Neo4j unavailable
        """
        if not self.neo4j_driver or not self.filter_label:
            return None

        try:
            with self.neo4j_driver.session() as session:
                result = session.run(
                    """
                    MATCH (e:Entity {filter_label: $filter_label})
                    WITH count(e) as entity_count
                    MATCH (d:Document {filter_label: $filter_label})
                    WITH entity_count, count(d) as doc_count
                    MATCH (c:Chunk {filter_label: $filter_label})
                    WITH entity_count, doc_count, count(c) as chunk_count
                    OPTIONAL MATCH (:Entity {filter_label: $filter_label})-[r]->(:Entity {filter_label: $filter_label})
                    WHERE r.filter_label = $filter_label
                    RETURN entity_count, doc_count, chunk_count, count(r) as rel_count
                    """,
                    {"filter_label": self.filter_label},
                )
                record = result.single()
                if record:
                    return {
                        "filter_label": self.filter_label,
                        "entities": record["entity_count"],
                        "documents": record["doc_count"],
                        "chunks": record["chunk_count"],
                        "relationships": record["rel_count"],
                    }
        except Exception as e:
            if self.debug:
                print(f"  ⚠️ Failed to get tenant stats: {e}")

        return None

    def close(self):
        """Clean up connections"""
        if self.neo4j_driver:
            self.neo4j_driver.close()


def format_chunks_for_context(chunks: List[Document]) -> str:
    """Format chunks for LLM context"""
    context_parts = []

    for i, chunk in enumerate(chunks, 1):
        doc_id = chunk.metadata.get("doc_id", "unknown")
        chunk_id = chunk.metadata.get("chunk_id", "unknown")
        context_parts.append(
            f"[CHUNK {i}]\n"
            f"Dokument: {doc_id}\n"
            f"Chunk-ID: {chunk_id}\n"
            f"Text:\n{chunk.page_content}\n"
            f"[ENDE CHUNK {i}]\n"
        )

    return "\n".join(context_parts)


def generate_answer(
    query: str,
    chunks: List[Document],
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """
    Generate answer using LLM with configurable prompts.

    Args:
        query: User query
        chunks: Retrieved chunks
        system_prompt: Custom system prompt (uses default if None)
        user_prompt: Custom user prompt template with {context} and {query} placeholders
        model: LLM model name

    Returns:
        Generated answer string
    """
    # Post-Retrieval Synthesis with LiteLLM
    final_system_prompt = system_prompt or POST_RETRIEVAL_SYSTEM_PROMPT
    final_user_prompt = user_prompt or DEFAULT_USER_PROMPT

    # Use the specific POST model if not overridden by the call
    actual_model = model or LITELLM_POST_MODEL

    print(f"  🤖 Generating answer with reasoning model: {actual_model}")

    try:
        context = format_chunks_for_context(chunks)
        formatted_user_prompt = final_user_prompt.format(context=context, query=query)

        messages = [
            {"role": "system", "content": final_system_prompt},
            {"role": "user", "content": formatted_user_prompt},
        ]

        # Invoke LLM via the unified handler
        content, used_model = _invoke_llm(
            messages,
            model=actual_model,
            max_tokens=LLM_MAX_OUTPUT_TOKENS
        )
        
        return content

    except Exception as e:
        return f"Fehler bei der Antwortgenerierung: {str(e)}"

def generate_answer_stream(
    query: str,
    chunks: List[Document],
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None,
    model: Optional[str] = None,
):
    """
    Generate answer stream using LLM.
    """
    final_system_prompt = system_prompt or POST_RETRIEVAL_SYSTEM_PROMPT
    final_user_prompt = user_prompt or DEFAULT_USER_PROMPT
    actual_model = model or LITELLM_POST_MODEL

    try:
        context = format_chunks_for_context(chunks)
        formatted_user_prompt = final_user_prompt.format(context=context, query=query)

        messages = [
            {"role": "system", "content": final_system_prompt},
            {"role": "user", "content": formatted_user_prompt},
        ]

        return _invoke_llm_stream(
            messages,
            model=actual_model,
            max_tokens=LLM_MAX_OUTPUT_TOKENS
        )

    except Exception as e:
        print(f"Streaming Error: {e}")
        raise
