# src/retriever/rag_retriever.py

"""
RAG Retriever - Vector + Keyword Search using Qdrant
Minimal changes from original implementation, now with configurable prompts.
"""

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
from langchain.schema import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchText, MatchValue

from utils.bge_m3_embedding import BGEM3Embeddings

# 260108-BundB Jun – For error log.
import time
import uuid
from utils.llm_logger import log_llm_event

# Suppress warnings
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

# Qdrant configuration - prioritize environment variables
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_HOST = os.getenv("QDRANT_HOST") or CONFIG.get("qdrant", {}).get("host", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", CONFIG.get("qdrant", {}).get("port", 6333)))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = CONFIG.get("qdrant", {}).get("collection_name", "graphrag_chunks")

# LLM configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# 260107–BundB Jun: fallback model & timeout for all LLM calls
OPENAI_FALLBACK_MODEL = os.getenv("OPENAI_FALLBACK_MODEL")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
_token_env = os.getenv("LLM_MAX_OUTPUT_TOKENS", "1200")
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

# ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
# 260107–BundB Jun – BEGIN
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
                timeout=LLM_TIMEOUT_SECONDS,
            )
            if current_model != primary_model:
                print(f"  ⚠️ Falling back to LLM model: {current_model}")
            
            response = llm.invoke(messages)
            duration_ms = int((time.time() - start) * 1000)

            if current_model != primary_model:
                log_llm_event(
                    "llm_fallback_success",
                    {
                        "call_id": call_id,
                        "service": "python",
                        "module": __name__,
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

# 260107–BundB Jun – END
# ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


class RAGRetriever:
    """RAG retrieval using Qdrant vector store with keyword search"""

    def __init__(
        self,
        debug: bool = False,
        qdrant_url: Optional[str] = None,
        qdrant_host: Optional[str] = None,
        qdrant_port: Optional[int] = None,
        qdrant_api_key: Optional[str] = None,
        collection_name: Optional[str] = None,
    ):
        """
        Initialize RAG retriever with Qdrant configuration

        Args:
            debug: Enable debug output
            qdrant_url: Qdrant URL (overrides config)
            qdrant_host: Qdrant host (overrides config)
            qdrant_port: Qdrant port (overrides config)
            qdrant_api_key: Qdrant API key
            collection_name: Collection name (overrides config)
        """
        self.debug = debug

        # === QDRANT CONNECTION: API params > ENV vars > config.yaml ===
        final_url = qdrant_url or QDRANT_URL
        final_api_key = qdrant_api_key or QDRANT_API_KEY
        final_host = qdrant_host or QDRANT_HOST
        final_port = qdrant_port or QDRANT_PORT

        # Connect to Qdrant
        if final_url:
            self.qdrant_client = QdrantClient(url=final_url, api_key=final_api_key)
            print(f"✅ Qdrant connected via URL: {final_url}")
        else:
            self.qdrant_client = QdrantClient(host=final_host, port=final_port)
            print(f"✅ Qdrant connected at {final_host}:{final_port}")

        # Collection name
        self.collection_name = collection_name or QDRANT_COLLECTION
        print(f"   📁 Collection: {self.collection_name}")

        # Initialize embeddings
        self.embeddings = BGEM3Embeddings(timeout=180)
        self.embedding_dim = BGE_M3_DIMENSION

        # Cache embedding meta info for stats / debugging
        self.embedding_model = getattr(self.embeddings, "model_id", None)
        self.embedding_service_url = getattr(self.embeddings, "service_url", None)

        # Optional: print embedding configuration once
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

        print("✅ RAG Retriever initialized (Vector + Keyword search)")

    def get_embedding(self, text: str) -> List[float]:
        """Get embedding using BGE-M3 Embeddings"""
        try:
            embedding = self.embeddings.embed_query(text)
            return embedding
        except Exception as e:
            print(f"  ⚠️ Error getting embedding: {e}")
            return [0.0] * self.embedding_dim

    def expand_query_with_cot(self, query: str) -> Dict:
        """
        Chain-of-Thought query expansion for better retrieval
        """
        query_lower = query.lower()

        expanded = {
            "original": query,
            "keywords": [],
            "numbers": [],
            "years": [],
            "percentages": [],
            "expected_patterns": [],
        }

        # Extract numbers and years
        expanded["numbers"] = re.findall(r"\b\d+\b", query)
        expanded["years"] = [n for n in expanded["numbers"] if 1990 <= int(n) <= 2050]
        expanded["percentages"] = re.findall(r"\d+\s*%", query)

        # Extract key terms
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

        # Detect expected answer patterns
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
        """Vector search using embeddings"""
        query_embedding = self.get_embedding(query)

        results = self.qdrant_client.search(
            collection_name=self.collection_name, query_vector=query_embedding, limit=k
        )
        return {int(point.id): point.score for point in results}

    def keyword_search(self, query: str, expanded_query: Dict, k: int) -> Dict[int, float]:
        """Keyword search using expanded query terms"""
        search_terms = expanded_query["keywords"] + expanded_query["numbers"]

        keyword_scores = {}
        offset = None

        while True:
            try:
                records, next_offset = self.qdrant_client.scroll(
                    collection_name=self.collection_name,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                )

                for record in records:
                    text = record.payload.get("text", "").lower()
                    score = 0

                    for term in search_terms:
                        term_lower = str(term).lower()
                        if term_lower in text:
                            tf = text.count(term_lower)
                            score += math.log(1 + tf) * 10

                    if score > 0:
                        keyword_scores[record.id] = score

                if next_offset is None:
                    break
                offset = next_offset

            except Exception as e:
                print(f"  ⚠️ Keyword search error: {e}")
                break

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

    def rag_retrieval(
        self, query: str, k: int = 20, debug: bool = None
    ) -> Tuple[List[Document], Dict]:
        """
        RAG retrieval combining vector and keyword search with RRF fusion

        Args:
            query: User query
            k: Number of chunks to retrieve
            debug: Enable debug output

        Returns:
            Tuple of (chunks, stats)
        """
        if debug is None:
            debug = self.debug

        print("🔍 Starting RAG retrieval...")

        # Stage 1: Query expansion
        expanded_query = self.expand_query_with_cot(query)
        print(
            f"  📝 Expanded: {len(expanded_query['keywords'])} keywords, {len(expanded_query['numbers'])} numbers"
        )

        # Stage 2: Multi-source retrieval
        broad_k = k * 10
        rankings = {}

        # Vector search
        vector_results = self.vector_search(query, k=broad_k)
        rankings["vector"] = vector_results
        print(f"  📊 Vector search: {len(vector_results)} results")

        # Keyword search
        keyword_results = self.keyword_search(query, expanded_query, k=broad_k)
        rankings["keyword"] = keyword_results
        print(f"  🔑 Keyword search: {len(keyword_results)} results")

        # Adjacent chunks
        all_top = list(vector_results.keys())[:10] + list(keyword_results.keys())[:10]
        all_top = list(set(all_top[:20]))

        adjacent_results = self.get_adjacent_chunks(all_top, window_size=1)
        if adjacent_results:
            rankings["adjacent"] = adjacent_results
            print(f"  📄 Adjacent chunks: {len(adjacent_results)} results")

        # Stage 3: RRF Fusion
        weights = {
            "vector": 0.70,
            "keyword": 0.25,
            "adjacent": 0.05,
        }

        fused_results = self.weighted_rrf_fusion(rankings, weights=weights, k=60)

        # Stage 4: Retrieve final chunks
        chunks = self._retrieve_chunks(fused_results[:k])

        # Statistics
        stats = {
            "total_candidates": len(fused_results),
            "vector_chunks": len(rankings.get("vector", {})),
            "keyword_chunks": len(rankings.get("keyword", {})),
            "adjacent_chunks": len(rankings.get("adjacent", {})),
            "expanded_keywords": len(expanded_query["keywords"]),
            "retrieval_methods_used": len([r for r in rankings.values() if r]),
            "final_chunks": len(chunks),
            "mode": "rag",
            "embedding_model": getattr(self, "embedding_model", None),
            "embedding_service_url": getattr(self, "embedding_service_url", None),
            "embedding_dim": getattr(self, "embedding_dim", None),
        }

        return chunks, stats

    def close(self):
        """Clean up connections"""
        # Qdrant client doesn't need explicit closing
        pass


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
    Generate answer using LLM with configurable prompts

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

    # Use defaults if not provided
    final_system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    final_user_prompt = user_prompt or DEFAULT_USER_PROMPT

    print(f"  🤖 Generating answer with: {model}")

    try:
        # # Initialize LLM
        # llm = ChatOpenAI(
        #     model=model,
        #     temperature=0.0,
        #     max_tokens=1000,
        #     openai_api_key=OPENAI_API_KEY,
        #     openai_api_base=OPENAI_API_BASE_URL,
        # )

        # Format context from chunks
        context = format_chunks_for_context(chunks)

        # Format user prompt with placeholders
        formatted_user_prompt = final_user_prompt.format(context=context, query=query)

        # Create messages
        messages = [
            SystemMessage(content=final_system_prompt),
            HumanMessage(content=formatted_user_prompt),
        ]

        # # Get response
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
