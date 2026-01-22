# src/retriever/graphrag_retriever.py

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
from typing import Dict, List, Optional, Tuple

import yaml
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
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
QDRANT_COLLECTION = CONFIG.get("qdrant", {}).get("collection_name", "graphrag_chunks")

# Neo4j configuration
NEO4J_URI = os.getenv("NEO4J_URI") or CONFIG.get("neo4j", {}).get("uri", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER") or CONFIG.get("neo4j", {}).get("user", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# LLM configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# 260107–BundB Jun: fallback model & timeout for all LLM calls
OPENAI_FALLBACK_MODEL = os.getenv("OPENAI_FALLBACK_MODEL")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
_token_env = os.getenv("LLM_MAX_OUTPUT_TOKENS", "4000")
LLM_MAX_OUTPUT_TOKENS = int(_token_env) if _token_env and _token_env.strip().isdigit() and int(_token_env) > 0 else None

BGE_M3_DIMENSION = 1024

# Default prompts
DEFAULT_SYSTEM_PROMPT = """Du bist ein freundlicher und kompetenter Assistent für deutsche Dokumente. Deine Aufgabe ist es, Fragen präzise und verständlich zu beantworten, basierend auf den bereitgestellten Kontextinformationen.

DEINE ARBEITSWEISE:
- Erfasse alle Aspekte und Nuancen der gestellten Frage
- Identifiziere Entitäten und spezifische Begriffe in der Frage
- Formuliere eigenständige, prägnante Antworten basierend auf dem Kontext
- Vermeide wörtliche Kopien - erkläre in deinen eigenen Worten
- Bleibe sachlich korrekt, aber freundlich im Ton
- Gib kurzen Kontext zum Fundort der Information

WICHTIGER GRUNDSATZ:
- Antworte NUR mit Informationen aus dem bereitgestellten Kontext
- Der Kontext soll auf die identifizierten Entitäten und Begriffe in der Frage behandeln
- Wenn die gesuchte Information NICHT im Kontext vorhanden ist, gib dies ehrlich und höflich zu
- Erfinde niemals Informationen oder rate


DOKUMENTENNAMEN UND SEITENZAHLEN:
- Bereinige Dokumentennamen: Entferne den letzten Unterstrich und die darauffolgende Hash-Kombination
- Füge ".pdf" zum bereinigten Namen hinzu
- Beispiel: "150424_Tourismuskonzept_89d2d7b8" wird zu "150424_Tourismuskonzept.pdf"
- Extrahiere Seitenzahlen aus den Chunks:
  * Suche nach "## Page X" Markierungen
  * Suche nach Seitenzahlen im Format "**XX | YY**" 
  * Suche nach "'page': X" in Metadaten
- Gib wenn möglich einen Seitenbereich an"""

DEFAULT_USER_PROMPT = """Beantworte die folgende Frage basierend auf den bereitgestellten Textausschnitten:

TEXTAUSSCHNITTE:
{context}

FRAGE: {query}

ANTWORTSTRUKTUR:

FALL A - Information gefunden:
1. Beantworte die Frage vollständig und verständlich in eigenen Worten
2. Erwähne kurz den thematischen Zusammenhang des Fundorts
3. Extrahiere Seitenzahlen aus dem verwendeten Chunk (suche nach "## Page", "**XX | YY**" oder "'page': X")
4. Bereinige den Dokumentennamen (entferne "_[Hash]" und füge ".pdf" hinzu)

Format:
ANTWORT: [Verständliche Antwort in eigenen Worten, die alle Aspekte der Frage abdeckt]
KONTEXT: [Kurze Beschreibung des Abschnitts, aus dem die Information stammt]
QUELLE: Dokument [bereinigter_Name.pdf], Seite [X] oder Seiten [X-Y]

Beispiel für QUELLE: Dokument 150424_Tourismuskonzept.pdf, Seiten 12-13

FALL B - Keine Information gefunden:
ANTWORT: Leider konnte ich in den mir vorliegenden Textausschnitten keine Informationen zu [Thema der Frage] finden. Die verfügbaren Abschnitte behandeln [kurze Erwähnung der vorhandenen Themen], enthalten aber keine Angaben zu Ihrer spezifischen Frage.

DEINE ANTWORT:"""

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
def _invoke_chat_llm(messages, model: Optional[str] = None, max_tokens: Optional[int] = LLM_MAX_OUTPUT_TOKENS):
    """
    Helper to call ChatOpenAI with timeout and optional fallback model.

    Returns:
        (response, used_model)
    """
    call_id = str(uuid.uuid4())
    
    primary_model = model or OPENAI_MODEL
    fallback_model = (
        OPENAI_FALLBACK_MODEL
        if OPENAI_FALLBACK_MODEL and OPENAI_FALLBACK_MODEL != primary_model
        else None
    )

    last_error = None

    # prompt preview (for logging)
    try:
        user_msg = next((m for m in messages if isinstance(m, HumanMessage)), None)
        prompt_preview = (user_msg.content[:200] if getattr(user_msg, "content", None) else "")
        prompt_chars = len(getattr(user_msg, "content", "") or "")
    except Exception:
        prompt_preview = ""
        prompt_chars = 0

    for current_model in (primary_model, fallback_model):
        if not current_model:
            continue

        start = time.time()
        try:
            llm = ChatOpenAI(
                model=current_model,
                temperature=0.0,
                max_tokens=max_tokens,
                openai_api_key=OPENAI_API_KEY,
                openai_api_base=OPENAI_API_BASE_URL,
                timeout=LLM_TIMEOUT_SECONDS,  # hard client-side timeout
            )
            if current_model != primary_model:
                print(f"  ⚠️ Falling back to LLM model: {current_model}")
            
            response = llm.invoke(messages)
            duration_ms = int((time.time() - start) * 1000)

            # fallback가 실제로 사용된 경우에만 성공 로그
            if current_model != primary_model:
                log_llm_event(
                    "llm_fallback_success",
                    {
                        "call_id": call_id,
                        "service": "python",
                        "module": __name__,          # src.retriever.graphrag_retriever
                        "primary_model": primary_model,
                        "used_model": current_model,
                        "duration_ms": duration_ms,
                        "timeout_s": LLM_TIMEOUT_SECONDS,
                        "prompt_chars": prompt_chars,
                        "prompt_preview": prompt_preview,
                    },
                )

            return response, current_model

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            last_error = e

            # 에러 로그
            log_llm_event(
                "llm_error",
                {
                    "call_id": call_id,
                    "service": "python",
                    "module": __name__,
                    "model": current_model,
                    "primary_model": primary_model,
                    "duration_ms": duration_ms,
                    "timeout_s": LLM_TIMEOUT_SECONDS,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:500],
                },
            )
            if current_model == primary_model:
                print(f"  ⚠️ Primary LLM model '{primary_model}' failed: {e}")
            else:
                print(f"  ❌ Fallback LLM model '{current_model}' failed: {e}")

    if last_error:
        raise last_error
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
            self.qdrant_client = QdrantClient(url=final_url, api_key=final_api_key)
            print(f"✅ Qdrant connected via URL: {final_url}")
        else:
            self.qdrant_client = QdrantClient(host=final_host, port=final_port)
            print(f"✅ Qdrant connected at {final_host}:{final_port}")

        # Collection name = filter_label for multi-tenant isolation
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

        # === LLM for entity extraction ===
        # self.llm = ChatOpenAI(
        #     model=OPENAI_MODEL,
        #     temperature=0.0,
        #     max_tokens=500,
        #     openai_api_key=OPENAI_API_KEY,
        #     openai_api_base=OPENAI_API_BASE_URL,
        # )
        # 260107–BundB Jun: use lazy client with timeout + fallback wrapper
        self.entity_llm_model = OPENAI_MODEL

        # === ENTITY EXTRACTION PROMPT TEMPLATE ===
        self.entity_extraction_prompt = (
            entity_extraction_prompt or ENTITY_EXTRACTION_PROMPT
        )  # 251204–BundB Jun: Allows overriding the default template from outside (API layer)

        print("✅ GraphRAG Retriever initialized (Graph + Vector + Keyword)")

    def get_embedding(self, text: str) -> List[float]:
        """Get embedding using BGE-M3 Embeddings"""
        try:
            return self.embeddings.embed_query(text)
        except Exception as e:
            print(f"  ⚠️ Error getting embedding: {e}")
            return [0.0] * self.embedding_dim

    def extract_entities_with_llm(self, query: str) -> List[str]:
        """
        Extract entities from query using LLM.
        Fast since query text is short.

        Args:
            query: User query

        Returns:
            List of extracted entity strings
        """
        try:
            # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
            # 251204–BundB Jun – BEGIN
            # Use instance-level template to allow customization
            template = getattr(self, "entity_extraction_prompt", ENTITY_EXTRACTION_PROMPT)
            try:
                # Allow {query} placeholder in template
                prompt = template.format(query=query)
            except Exception as e:
                # Fallback to default template if custom one is malformed
                if self.debug:
                    print(f"  ⚠️ Failed to format entity extraction prompt, using default: {e}")
                prompt = ENTITY_EXTRACTION_PROMPT.format(query=query)
            # 251204–BundB Jun – END
            # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

            # prompt = ENTITY_EXTRACTION_PROMPT.format(query=query)

            # response = self.llm.invoke([HumanMessage(content=prompt)])
            
            # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
            # 260107–BundB Jun – BEGIN
            # use timeout + fallback wrapper
            response, used_model = _invoke_chat_llm(
                [HumanMessage(content=prompt)],
                model=getattr(self, "entity_llm_model", OPENAI_MODEL),
                max_tokens=500,
            )

            if self.debug:
                print(f"  🧠 Entity extraction model: {used_model}")
            # 260107–BundB Jun – END
            # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


            # Parse JSON response
            response_text = response.content.strip()

            # Clean up response if needed
            if response_text.startswith("```"):
                response_text = re.sub(r"```json?\s*", "", response_text)
                response_text = re.sub(r"```\s*$", "", response_text)

            entities = json.loads(response_text)

            if isinstance(entities, list):
                if self.debug:
                    print(f"  🔍 LLM extracted entities: {entities}")
                return entities
            else:
                return []

        except json.JSONDecodeError as e:
            if self.debug:
                print(f"  ⚠️ Failed to parse entity extraction response: {e}")
            return self._extract_entities_simple(query)
        except Exception as e:
            if self.debug:
                print(f"  ⚠️ Entity extraction error: {e}")
            return self._extract_entities_simple(query)

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

        expanded["numbers"] = re.findall(r"\b\d+\b", query)
        expanded["years"] = [n for n in expanded["numbers"] if 1990 <= int(n) <= 2050]
        expanded["percentages"] = re.findall(r"\d+\s*%", query)

        words = re.findall(r"\b[A-Za-zÄÖÜäöüß]+\b", query)
        stop_words = {
            "der",
            "die",
            "das",
            "und",
            "oder",
            "ist",
            "wird",
            "werden",
            "wurde",
            "wurden",
            "welche",
            "welcher",
            "welches",
            "wie",
            "was",
            "wann",
            "wo",
            "bis",
            "für",
            "auf",
            "mit",
            "von",
            "zu",
        }
        expanded["keywords"] = [w for w in words if w.lower() not in stop_words and len(w) > 2]

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

        results = self.qdrant_client.search(
            collection_name=self.collection_name, query_vector=query_embedding, limit=k
        )
        return {int(point.id): point.score for point in results}

    def keyword_search(self, query: str, expanded_query: Dict, k: int) -> Dict[int, float]:
        """
        Optimized keyword search using Qdrant's native text matching.
        
        PERFORMANCE: 10-50x faster than scroll-based approach.
        Uses Qdrant's indexed text search instead of Python string matching.
        """
        search_terms = expanded_query["keywords"] + expanded_query["numbers"]
        
        if not search_terms:
            return {}
        
        keyword_scores = {}
        
        # Strategy: Search for each term separately, then aggregate scores
        # This is much faster than scrolling all documents
        for term in search_terms[:10]:  # Limit to top 10 terms to avoid too many queries
            term_str = str(term).lower()
            if len(term_str) < 2:  # Skip very short terms
                continue
            
            try:
                # Use Qdrant's MatchText filter for indexed search
                results = self.qdrant_client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="text",
                                match=MatchText(text=term_str)
                            )
                        ]
                    ),
                    limit=min(k * 2, 100),  # Get more than k to allow for aggregation
                    with_payload=True
                )
                
                records = results[0] if results else []
                
                # Score based on term frequency in matched documents
                for record in records:
                    text = record.payload.get("text", "").lower()
                    tf = text.count(term_str)
                    score = math.log(1 + tf) * 10
                    
                    # Aggregate scores for documents matching multiple terms
                    point_id = int(record.id)
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
        """Get adjacent chunks for context expansion"""
        adjacent_results = {}

        if not point_ids:
            return adjacent_results

        points = self.qdrant_client.retrieve(
            collection_name=self.collection_name,
            ids=point_ids[:30],
        )

        for point in points:
            doc_id = point.payload.get("doc_id", "")
            chunk_index = point.payload.get("chunk_index", 0)

            for offset in range(-window_size, window_size + 1):
                if offset == 0:
                    continue

                target_idx = chunk_index + offset
                if target_idx < 0:
                    continue

                try:
                    results, _ = self.qdrant_client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter=Filter(
                            must=[
                                FieldCondition(key="doc_id", match=MatchText(text=doc_id)),
                                FieldCondition(
                                    key="chunk_index", match=MatchValue(value=target_idx)
                                ),
                            ]
                        ),
                        limit=1,
                    )

                    if results:
                        score = 10.0 / (1 + abs(offset))
                        adjacent_results[results[0].id] = score
                except:
                    continue

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

    def _retrieve_chunks(self, ranked_results: List[Tuple[int, float]]) -> List[Document]:
        """Retrieve actual chunk documents from ranked results"""
        chunks = []

        if not ranked_results:
            return chunks

        point_ids = [pid for pid, _ in ranked_results]

        try:
            points = self.qdrant_client.retrieve(
                collection_name=self.collection_name, ids=point_ids
            )

            for i, point in enumerate(points):
                score = next((s for pid, s in ranked_results if pid == point.id), 0.0)

                chunk = Document(
                    page_content=point.payload.get("text", ""),
                    metadata={
                        "qdrant_id": point.id,
                        "doc_id": point.payload.get("doc_id", ""),
                        "chunk_id": point.payload.get("chunk_id", ""),
                        "chunk_index": point.payload.get("chunk_index", 0),
                        "fusion_score": score,
                        "retrieval_rank": i + 1,
                    },
                )
                chunks.append(chunk)

        except Exception as e:
            print(f"  ⚠️ Error retrieving chunks: {e}")

        return chunks

    def graphrag_retrieval(
        self, query: str, k: int = 20, debug: bool = None
    ) -> Tuple[List[Document], Dict]:
        """
        Full GraphRAG retrieval combining graph, vector, and keyword search.

        All graph queries are isolated by filter_label (tenant).

        Args:
            query: User query
            k: Number of chunks to retrieve
            debug: Enable debug output

        Returns:
            Tuple of (chunks, stats)
        """
        if debug is None:
            debug = self.debug

        print(f"🔍 Starting GraphRAG retrieval (tenant: {self.filter_label})...")

        # Stage 1: Query expansion
        expanded_query = self.expand_query_with_cot(query)
        print(
            f"  📝 Expanded: {len(expanded_query['keywords'])} keywords, {len(expanded_query['numbers'])} numbers"
        )

        # Stage 2: LLM-based entity extraction
        entities = self.extract_entities_with_llm(query)
        print(f"  🔍 Extracted entities: {entities}")

        # Stage 3: Multi-source retrieval
        broad_k = k * 10
        rankings = {}

        # Graph-based retrieval (Neo4j) with filter_label isolation
        if self.neo4j_driver and entities and self.filter_label:
            graph_results = self.entity_based_retrieval(entities, k=broad_k)
            if graph_results:
                rankings["graph"] = graph_results
                print(f"  🔗 Graph retrieval: {len(graph_results)} entity-linked chunks")
        else:
            if not self.neo4j_driver:
                print("  ⚠️ Graph retrieval skipped (no Neo4j connection)")
            elif not entities:
                print("  ⚠️ Graph retrieval skipped (no entities extracted)")
            elif not self.filter_label:
                print("  ⚠️ Graph retrieval skipped (no filter_label - safety)")

        # Vector search (Qdrant - isolated by collection_name)
        vector_results = self.vector_search(query, k=broad_k)
        rankings["vector"] = vector_results
        print(f"  📊 Vector search: {len(vector_results)} results")

        # Keyword search (within collection)
        keyword_results = self.keyword_search(query, expanded_query, k=broad_k)
        rankings["keyword"] = keyword_results
        print(f"  🔑 Keyword search: {len(keyword_results)} results")

        # Adjacent chunks
        all_top = []
        if "graph" in rankings:
            all_top.extend(list(rankings["graph"].keys())[:10])
        all_top.extend(list(vector_results.keys())[:10])
        all_top.extend(list(keyword_results.keys())[:10])
        all_top = list(set(all_top[:30]))

        adjacent_results = self.get_adjacent_chunks(all_top[:20], window_size=1)
        if adjacent_results:
            rankings["adjacent"] = adjacent_results
            print(f"  📄 Adjacent chunks: {len(adjacent_results)} results")

        # Stage 4: RRF Fusion with weights
        if "graph" in rankings and rankings["graph"]:
            # Weights when graph data is available
            weights = {
                "graph": 0.40,
                "vector": 0.45,
                "keyword": 0.10,
                "adjacent": 0.05,
            }
        else:
            # Fallback weights without graph
            weights = {
                "vector": 0.70,
                "keyword": 0.25,
                "adjacent": 0.05,
            }

        fused_results = self.weighted_rrf_fusion(rankings, weights=weights, k=60)

        # Stage 5: Retrieve final chunks
        chunks = self._retrieve_chunks(fused_results[:k])

        # Statistics
        stats = {
            "total_candidates": len(fused_results),
            "graph_chunks": len(rankings.get("graph", {})),
            "vector_chunks": len(rankings.get("vector", {})),
            "keyword_chunks": len(rankings.get("keyword", {})),
            "adjacent_chunks": len(rankings.get("adjacent", {})),
            "entities_extracted": entities,
            "expanded_keywords": len(expanded_query["keywords"]),
            "retrieval_methods_used": len([r for r in rankings.values() if r]),
            "final_chunks": len(chunks),
            "filter_label": self.filter_label,
            "neo4j_enabled": self.neo4j_driver is not None,
            "graph_used": "graph" in rankings and len(rankings["graph"]) > 0,
            "mode": "graphrag",
            "embedding_model": getattr(self, "embedding_model", None),
            "embedding_service_url": getattr(self, "embedding_service_url", None),
            "embedding_dim": getattr(self, "embedding_dim", None),
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
    if model is None:
        model = OPENAI_MODEL

    final_system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    final_user_prompt = user_prompt or DEFAULT_USER_PROMPT

    print(f"  🤖 Generating answer with: {model}")

    try:
        # llm = ChatOpenAI(
        #     model=model,
        #     temperature=0.0,
        #     max_tokens=1000,
        #     openai_api_key=OPENAI_API_KEY,
        #     openai_api_base=OPENAI_API_BASE_URL,
        # )

        context = format_chunks_for_context(chunks)

        formatted_user_prompt = final_user_prompt.format(context=context, query=query)

        messages = [
            SystemMessage(content=final_system_prompt),
            HumanMessage(content=formatted_user_prompt),
        ]

        # response = llm.invoke(messages)
        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
        # 260107–BundB Jun – BEGIN
        # use shared timeout + fallback wrapper
        response, used_model = _invoke_chat_llm(
            messages,
            model=model,
            max_tokens=LLM_MAX_OUTPUT_TOKENS,
        )
        # 260107–BundB Jun – END
        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

        if hasattr(response, "content"):
            return response.content
        else:
            return str(response)

    except Exception as e:
        return f"Fehler bei der Antwortgenerierung: {str(e)}"
