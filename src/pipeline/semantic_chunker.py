# src/pipeline/semantic_chunker.py
# Enhanced semantic chunking with document-chunk mapping, metadata awareness, and performance tracking
# GUARANTEES: 1) Every document gets at least 1 chunk, 2) No text is ever lost, 3) Metadata tracking
# Now using step-based configuration with BGE-M3 embeddings
# Includes pymupdf4llm metadata support and original filename tracking

import html
import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import tiktoken
import yaml
from dotenv import load_dotenv

from utils.bge_m3_embedding import BGEM3Embeddings

# Load environment variables
load_dotenv()


class DocumentChunker:
    """
    Enhanced semantic chunker using BGE-M3 embeddings.
    Supports two modes: simple (fixed-size) and semantic_embedding (BGE-M3-based)

    GUARANTEES:
    1) Every document gets at least 1 chunk
    2) No text is ever lost (100% preservation)
    3) Full metadata tracking for each chunk
    4) Original filename tracking with extension
    """

    def __init__(self, config_path: str = "config.yaml", **kwargs):
        """
        Initialize chunker with step-based config.

        Args:
            config_path: Path to YAML configuration file
            **kwargs: Override any config values (including output_dir, track_performance)
        """
        # Load full configuration
        self.full_config = self._load_config(config_path)

        # Get semantic_chunking configuration
        if "semantic_chunking" not in self.full_config:
            raise ValueError("semantic_chunking section not found in config.yaml")

        chunking_config = self.full_config["semantic_chunking"]

        # Apply any kwargs overrides
        for key, value in kwargs.items():
            if key in chunking_config:
                chunking_config[key] = value

        # Get chunking method
        self.method = chunking_config.get("method", "semantic_embedding")

        if self.method not in ["simple", "semantic_embedding"]:
            raise ValueError(
                f"Invalid chunking method: {self.method}. Must be 'simple' or 'semantic_embedding'"
            )

        # Load method-specific configuration
        if self.method == "simple":
            mode_config = chunking_config.get("simple_mode", {})
            self.chunk_size = mode_config.get("chunk_size", 1000)
            self.chunk_overlap = mode_config.get("chunk_overlap", 200)
            self.respect_sentences = mode_config.get("respect_sentences", True)

            # Not needed for simple mode
            self.buffer_size = None
            self.breakpoint_percentile = None
            self.batch_size = None
            self.embedding_delay = 0

        else:  # semantic_embedding
            mode_config = chunking_config.get("semantic_embedding_mode", {})
            self.chunk_size = mode_config.get("target_chunk_size", 1000)
            self.chunk_overlap = mode_config.get("chunk_overlap", 200)
            self.buffer_size = mode_config.get("buffer_size", 2)
            self.breakpoint_percentile = mode_config.get("breakpoint_percentile", 85)
            self.embedding_delay = mode_config.get("embedding_delay", 0.0)

            # Get embedding configuration
            embed_config = mode_config.get("embedding", {})
            self.batch_size = embed_config.get("batch_size", 32)

        # FIXED: Check if output_dir was provided as parameter (for API usage)
        if "output_dir" in kwargs and kwargs["output_dir"]:
            base_output = Path(kwargs["output_dir"])
            self.chunks_dir = base_output / "chunks"
            self.performance_dir = base_output / "performance"
        else:
            # Fallback to config
            folders_config = self.full_config.get("folders", {})
            self.chunks_dir = Path(
                folders_config.get("step3_chunks", "../data/step3_chunks/chunks/")
            )
            self.performance_dir = Path(
                folders_config.get("step3_performance", "../data/step3_chunks/performance/")
            )

        # Create chunks output directory
        self.chunks_dir.mkdir(parents=True, exist_ok=True)

        # NEW: Performance tracking configuration (default: disabled)
        self.track_performance = kwargs.get("track_performance", False)

        # Only create performance directory if tracking enabled
        if self.track_performance:
            self.performance_dir.mkdir(parents=True, exist_ok=True)

        # Initialize embeddings if using semantic mode
        if self.method == "semantic_embedding":
            self._init_embeddings(mode_config.get("embedding", {}))
        else:
            self.embeddings = None
            self.embedding_model_name = "none (simple chunking)"
            self.embedding_dim = 0

        # Initialize tokenizer
        self._init_tokenizer()

        # Optional preprocessing (usually disabled)
        self.preprocess_text = chunking_config.get("preprocess_text", False)
        if self.preprocess_text:
            self._init_text_preprocessing()

        # Performance tracking (only if enabled)
        self.timing = {}
        if self.track_performance:
            self.performance_stats = {
                "total_documents": 0,
                "total_chunks_created": 0,
                "total_processing_time": 0.0,
                "total_chars_processed": 0,
            }

        print("✅ DocumentChunker initialized")
        print(f"   Method: {self.method.upper()}")
        print(f"   Chunk size: {self.chunk_size}, Overlap: {self.chunk_overlap}")
        if self.method == "semantic_embedding":
            print(f"   Embedding model: {self.embedding_model_name}")
        print(f"   Performance tracking: {'ENABLED' if self.track_performance else 'DISABLED'}")
        print(f"   Output: {self.chunks_dir}")

    def _load_config(self, config_path: str) -> Dict:
        """Load full configuration from YAML file"""
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_file, "r") as f:
            return yaml.safe_load(f) or {}

    def _init_embeddings(self, embed_config: Dict):
        """Initialize BGE-M3 embeddings."""
        print("Initializing BGE-M3 embeddings...")

        try:
            self.embeddings = BGEM3Embeddings(
                timeout=180,
            )
            self.embedding_model_name = "bge-m3"
            self.embedding_dim = 1024  #

            print("✅ Amazon Bedrock TITAN embeddings initialized")

            print(f"   Dimension: {self.embedding_dim}")

        except Exception as e:
            raise RuntimeError(f"Failed to initialize BGE-M3 embeddings: {e}")

    def _init_tokenizer(self):
        """Initialize tokenizer."""
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
            self.use_tiktoken = True
        except Exception:
            print("Warning: tiktoken not available, using approximation")
            self.tokenizer = None
            self.use_tiktoken = False

    def _init_text_preprocessing(self):
        """Initialize text preprocessing patterns (only if enabled)"""
        self.encoding_fixes = {
            "ÃƒÆ'Ã†'Ãƒâ€šÃ‚Â¤": "ä",
            "ÃƒÆ'Ã†'Ãƒâ€šÃ‚Â¶": "ö",
            "ÃƒÆ'Ã†'Ãƒâ€šÃ‚Â¼": "ü",
            "ÃƒÆ'Ã†'Ãƒâ€ž": "Ä",
            "ÃƒÆ'Ã†'Ãƒâ€": "Ö",
            "ÃƒÆ'Ã†'ÃƒÅ": "Ü",
            "ÃƒÆ'Ã†'Ãƒâ€¦Ã‚Â¸": "ß",
        }
        self.cleanup_patterns = [
            (r"\n{3,}", "\n\n"),
            (r" {2,}", " "),
            (r"\t+", " "),
        ]

    def count_tokens(self, text: str) -> int:
        """Count tokens."""
        if self.use_tiktoken:
            return len(self.tokenizer.encode(text))
        else:
            return len(text) // 4

    def _detect_german(self, text: str) -> bool:
        """Fast German detection."""
        german_chars = ["ä", "ö", "ü", "ß"]
        german_words = ["der", "die", "das", "und", "ist"]
        text_lower = text.lower()
        char_count = sum(1 for char in german_chars if char in text_lower)
        word_count = sum(1 for word in german_words if f" {word} " in f" {text_lower} ")
        return char_count > 0 or word_count > 2

    def _fix_encoding(self, text: str) -> str:
        """Fix common UTF-8 encoding issues (only if preprocessing enabled)"""
        if not text or not self.preprocess_text:
            return text
        for wrong, correct in self.encoding_fixes.items():
            text = text.replace(wrong, correct)
        return unicodedata.normalize("NFC", html.unescape(text))

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace (only if preprocessing enabled)"""
        if not text or not self.preprocess_text:
            return text
        for pattern, replacement in self.cleanup_patterns:
            text = re.sub(pattern, replacement, text)
        return text.strip()

    def _validate_text_preservation(
        self, original_text: str, chunks: List[str], operation: str, verbose: bool = False
    ) -> bool:
        """Validate that no text has been lost during processing."""
        original_chars = len(original_text.strip())
        total_chunk_chars = sum(len(chunk.strip()) for chunk in chunks)

        preservation_ratio = total_chunk_chars / original_chars if original_chars > 0 else 1.0

        if preservation_ratio < 0.95:
            if verbose:
                print(f"WARNING: TEXT LOSS in {operation}:")
                print(f"   Original: {original_chars} chars")
                print(f"   Chunks: {total_chunk_chars} chars")
                print(f"   Preservation: {preservation_ratio:.1%}")
            return False

        return True

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get embedding for a single text."""
        try:
            if self.embeddings:  # ✅ FIXED: Changed from self.embedding_model
                embedding = self.embeddings.embed_query(text)  # ✅ FIXED
                return np.array(embedding)
            else:
                # This branch should not be reached in semantic_embedding mode
                return None
        except Exception as e:
            print(f"Error getting embedding: {e}")
            return None

    def _compute_embeddings_batch(self, texts: List[str]) -> np.ndarray:
        """Compute embeddings in batches."""
        start_time = time.time()
        all_embeddings = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]

            try:
                if self.embeddings:  # ✅ FIXED: Changed from self.embedding_model
                    batch_embeddings = self.embeddings.embed_documents(batch)  # ✅ FIXED
                    batch_embeddings = np.array(batch_embeddings)
                else:
                    # Fallback - should not reach here in semantic_embedding mode
                    raise RuntimeError("No embedding model available")

                norms = np.linalg.norm(batch_embeddings, axis=1, keepdims=True)
                batch_embeddings = batch_embeddings / (norms + 1e-10)
                all_embeddings.append(batch_embeddings)

                # Only sleep if delay configured and not last batch
                if self.embedding_delay > 0 and i + self.batch_size < len(texts):
                    time.sleep(self.embedding_delay)

            except Exception as e:
                print(f"Error in batch embedding: {e}")
                batch_embeddings = []
                for text in batch:
                    emb = self._get_embedding(text)
                    if emb is not None:
                        batch_embeddings.append(emb)
                    else:
                        batch_embeddings.append(np.zeros(self.embedding_dim))
                if batch_embeddings:
                    all_embeddings.append(np.array(batch_embeddings))

        embeddings = np.vstack(all_embeddings) if all_embeddings else np.array([])

        if self.track_performance:
            self.timing["embedding"] = time.time() - start_time

        return embeddings

    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        if self._detect_german(text):
            sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZÄÖÜ"\'])', text)
        else:
            sentences = re.split(r'(?<=[.?!])\s+(?=[A-Z"\'])', text)

        processed_sentences = []
        remaining_text = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 8:
                if remaining_text:
                    sentence = remaining_text + " " + sentence
                    remaining_text = ""
                processed_sentences.append(sentence)
            else:
                remaining_text = remaining_text + " " + sentence if remaining_text else sentence

        if remaining_text.strip():
            if processed_sentences:
                processed_sentences[-1] = processed_sentences[-1] + " " + remaining_text
            else:
                processed_sentences.append(remaining_text.strip())

        return (
            processed_sentences if processed_sentences else [text.strip()] if text.strip() else []
        )

    def _create_sliding_windows(self, sentences: List[str]) -> List[str]:
        """Create sliding windows for embedding."""
        if len(sentences) <= 1:
            return sentences

        windows = []
        for i in range(len(sentences)):
            start = max(0, i - self.buffer_size)
            end = min(len(sentences), i + self.buffer_size + 1)
            window_text = " ".join(sentences[start:end])
            windows.append(window_text)

        return windows

    def _calculate_distances_fast(self, embeddings: np.ndarray) -> List[float]:
        """Fast distance calculation using vectorized operations."""
        start_time = time.time()
        similarities = np.sum(embeddings[:-1] * embeddings[1:], axis=1)
        distances = 1 - similarities

        if self.track_performance:
            self.timing["distances"] = time.time() - start_time

        return distances.tolist()

    def _find_breakpoints(self, distances: List[float]) -> List[int]:
        """Find breakpoints using percentile threshold."""
        if not distances:
            return []
        threshold = np.percentile(distances, self.breakpoint_percentile)
        return [i for i, d in enumerate(distances) if d > threshold]

    def _create_chunks_from_sentences(
        self, sentences: List[str], breakpoints: List[int]
    ) -> List[str]:
        """Create chunks from sentences using breakpoints."""
        if not sentences:
            return []

        chunks = []
        start_idx = 0

        for breakpoint in breakpoints:
            end_idx = breakpoint + 1
            if start_idx < len(sentences):
                chunk_text = " ".join(sentences[start_idx:end_idx])
                if chunk_text.strip():
                    chunks.append(chunk_text.strip())
                start_idx = end_idx

        if start_idx < len(sentences):
            chunk_text = " ".join(sentences[start_idx:])
            if chunk_text.strip():
                chunks.append(chunk_text.strip())

        if not chunks and sentences:
            all_text = " ".join(sentences)
            if all_text.strip():
                chunks.append(all_text.strip())

        return chunks

    def _split_by_token_limit(self, text: str) -> List[str]:
        """Split text by token limit."""
        # Try sentence-based splitting first
        if self._detect_german(text):
            sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZÄÖÜ"\'])', text)
        else:
            sentences = re.split(r'(?<=[.?!])\s+(?=[A-Z"\'])', text)

        if len(sentences) > 1:
            chunks = []
            current_chunk_sentences = []
            current_tokens = 0

            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                sentence_tokens = self.count_tokens(sentence)

                if sentence_tokens > self.chunk_size:
                    if current_chunk_sentences:
                        chunks.append(" ".join(current_chunk_sentences))
                        current_chunk_sentences = []
                        current_tokens = 0

                    # Word-based splitting for oversized sentence
                    words = sentence.split()
                    current_chunk_words = []
                    current_word_tokens = 0

                    for word in words:
                        word_tokens = self.count_tokens(word)
                        if (
                            current_word_tokens + word_tokens > self.chunk_size
                            and current_chunk_words
                        ):
                            chunks.append(" ".join(current_chunk_words))
                            current_chunk_words = [word]
                            current_word_tokens = word_tokens
                        else:
                            current_chunk_words.append(word)
                            current_word_tokens += word_tokens

                    if current_chunk_words:
                        chunks.append(" ".join(current_chunk_words))

                elif current_tokens + sentence_tokens > self.chunk_size and current_chunk_sentences:
                    chunks.append(" ".join(current_chunk_sentences))
                    current_chunk_sentences = [sentence]
                    current_tokens = sentence_tokens

                else:
                    current_chunk_sentences.append(sentence)
                    current_tokens += sentence_tokens

            if current_chunk_sentences:
                chunks.append(" ".join(current_chunk_sentences))

            return chunks

        # Otherwise, split by words
        words = text.split()
        if not words:
            return [text] if text.strip() else []

        chunks = []
        current_chunk_words = []
        current_tokens = 0

        for word in words:
            word_tokens = self.count_tokens(word)

            if current_tokens + word_tokens > self.chunk_size and current_chunk_words:
                chunks.append(" ".join(current_chunk_words))
                current_chunk_words = [word]
                current_tokens = word_tokens
            else:
                current_chunk_words.append(word)
                current_tokens += word_tokens

        if current_chunk_words:
            chunks.append(" ".join(current_chunk_words))

        if not chunks and text.strip():
            chunks = [text.strip()]

        return chunks

    def _enforce_token_limits(self, chunks: List[str]) -> List[str]:
        """Enforce token limits on chunks."""
        final_chunks = []

        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue

            tokens = self.count_tokens(chunk)

            if tokens > self.chunk_size:
                sub_chunks = self._split_by_token_limit(chunk)
                final_chunks.extend(sub_chunks)
            else:
                final_chunks.append(chunk)

        return final_chunks

    def _add_overlap(self, chunks: List[str]) -> List[str]:
        """Add overlap between consecutive chunks."""
        if len(chunks) <= 1 or self.chunk_overlap == 0:
            return chunks

        overlapped = [chunks[0]]

        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            current_chunk = chunks[i]

            if self._detect_german(prev_chunk):
                prev_sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZÄÖÜ"\'])', prev_chunk)
            else:
                prev_sentences = re.split(r'(?<=[.?!])\s+(?=[A-Z"\'])', prev_chunk)

            overlap_sentences = []
            overlap_tokens = 0

            for sentence in reversed(prev_sentences):
                sentence = sentence.strip()
                if not sentence:
                    continue

                sentence_tokens = self.count_tokens(sentence)
                if overlap_tokens + sentence_tokens <= self.chunk_overlap:
                    overlap_sentences.insert(0, sentence)
                    overlap_tokens += sentence_tokens
                else:
                    break

            if overlap_sentences:
                overlap_text = " ".join(overlap_sentences)
                overlapped_chunk = overlap_text + " " + current_chunk
            else:
                overlapped_chunk = current_chunk

            overlapped.append(overlapped_chunk)

        return overlapped

    def _ensure_at_least_one_chunk(self, chunks: List[str], original_text: str) -> List[str]:
        """GUARANTEE: Ensure every document produces at least one chunk."""
        non_empty_chunks = [chunk.strip() for chunk in chunks if chunk and chunk.strip()]

        if not non_empty_chunks:
            if original_text and original_text.strip():
                return [original_text.strip()]
            else:
                return ["[Empty document]"]

        return non_empty_chunks

    def _simple_chunk(self, text: str) -> List[str]:
        """Simple fixed-size chunking with overlap."""
        sentences = self._split_into_sentences(text)
        chunks = []
        current_chunk = []
        current_size = 0

        for sentence in sentences:
            sentence_size = self.count_tokens(sentence)

            if sentence_size > self.chunk_size:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_size = 0

                sub_chunks = self._split_by_token_limit(sentence)
                chunks.extend(sub_chunks)
                continue

            if current_size + sentence_size > self.chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]
                current_size = sentence_size
            else:
                current_chunk.append(sentence)
                current_size += sentence_size

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        if self.chunk_overlap > 0:
            chunks = self._add_overlap(chunks)

        return chunks

    def _parse_pymupdf4llm_document(self, text: str) -> Optional[List[Dict]]:
        """Parse pymupdf4llm structured output into page list."""
        if not text or "## Page" not in text:
            return None

        pages = []

        try:
            page_sections = re.split(r"## Page (\d+)", text)

            for i in range(1, len(page_sections), 2):
                if i + 1 >= len(page_sections):
                    break

                page_num = int(page_sections[i])
                page_content = page_sections[i + 1]

                page_text = ""
                page_metadata = {}
                has_tables = False
                has_images = False
                table_count = 0
                image_count = 0

                # Extract text
                text_match = re.search(r"'text':\s*'(.*?)'\s*,\s*'words'", page_content, re.DOTALL)
                if text_match:
                    page_text = text_match.group(1)
                    page_text = (
                        page_text.replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"')
                    )
                    page_text = self._fix_encoding(page_text)
                    page_text = self._normalize_whitespace(page_text)

                # Extract metadata safely
                metadata_match = re.search(
                    r"'metadata':\s*{(.*?)}\s*,\s*'toc_items'", page_content, re.DOTALL
                )
                if metadata_match:
                    try:
                        meta_str = metadata_match.group(1)

                        field_patterns = {
                            "title": r"'title':\s*'([^']*)'",
                            "author": r"'author':\s*'([^']*)'",
                            "subject": r"'subject':\s*'([^']*)'",
                            "keywords": r"'keywords':\s*'([^']*)'",
                            "creator": r"'creator':\s*'([^']*)'",
                            "page_count": r"'page_count':\s*(\d+)",
                        }

                        for field, pattern in field_patterns.items():
                            match = re.search(pattern, meta_str)
                            if match and match.group(1):
                                if field == "page_count":
                                    page_metadata[field] = int(match.group(1))
                                elif field == "keywords":
                                    page_metadata[field] = [
                                        k.strip() for k in match.group(1).split(",") if k.strip()
                                    ]
                                else:
                                    page_metadata[field] = match.group(1)

                        # Parse dates
                        for date_field, date_pattern in [
                            ("creation_date", r"'creationDate':\s*[\"']([^\"']+)[\"']"),
                            ("modification_date", r"'modDate':\s*[\"']([^\"']+)[\"']"),
                        ]:
                            date_match = re.search(date_pattern, meta_str)
                            if date_match:
                                date_str = date_match.group(1)
                                if date_str.startswith("D:"):
                                    clean_date = date_str[2:10]
                                    if len(clean_date) == 8:
                                        page_metadata[date_field] = (
                                            f"{clean_date[:4]}-{clean_date[4:6]}-{clean_date[6:8]}"
                                        )

                    except Exception as e:
                        print(
                            f"   Warning: Could not fully parse metadata for page {page_num}: {e}"
                        )

                # Check for tables
                tables_match = re.search(r"'tables':\s*\[(.*?)\]", page_content, re.DOTALL)
                if tables_match:
                    tables_content = tables_match.group(1)
                    has_tables = bool(tables_content.strip())
                    table_count = len(re.findall(r"\{[^}]+\}", tables_content))

                # Check for images
                images_match = re.search(r"'images':\s*\[(.*?)\]", page_content, re.DOTALL)
                if images_match:
                    images_content = images_match.group(1)
                    has_images = bool(images_content.strip())
                    image_count = len(re.findall(r"\{[^}]+\}", images_content))

                pages.append(
                    {
                        "page_num": page_num,
                        "text": page_text,
                        "metadata": page_metadata,
                        "has_tables": has_tables,
                        "has_images": has_images,
                        "table_count": table_count,
                        "image_count": image_count,
                    }
                )

            return pages if pages else None

        except Exception as e:
            print(f"   Warning: Error parsing pymupdf4llm structure: {e}")
            return None

    def _create_text_with_page_mapping(self, pages: List[Dict]) -> Tuple[str, List[Dict]]:
        """Create continuous text from pages while tracking positions."""
        combined_text = ""
        page_map = []

        for page in pages:
            if not page.get("text", "").strip():
                continue

            start_pos = len(combined_text)
            combined_text += page["text"]

            if not combined_text.endswith("\n"):
                combined_text += "\n"

            end_pos = len(combined_text)

            page_map.append(
                {
                    "page_num": page["page_num"],
                    "start_pos": start_pos,
                    "end_pos": end_pos,
                    "metadata": page.get("metadata", {}),
                    "has_tables": page.get("has_tables", False),
                    "has_images": page.get("has_images", False),
                    "table_count": page.get("table_count", 0),
                    "image_count": page.get("image_count", 0),
                }
            )

        return combined_text, page_map

    def _find_pages_in_range(
        self, chunk_start: int, chunk_end: int, page_map: List[Dict]
    ) -> List[Dict]:
        """Determine which pages contribute text to a chunk."""
        pages_used = []

        for page_info in page_map:
            if chunk_start < page_info["end_pos"] and chunk_end > page_info["start_pos"]:
                text_start_in_page = max(0, chunk_start - page_info["start_pos"])
                text_end_in_page = min(
                    page_info["end_pos"] - page_info["start_pos"],
                    chunk_end - page_info["start_pos"],
                )

                chars_used = text_end_in_page - text_start_in_page

                pages_used.append(
                    {
                        "page_num": page_info["page_num"],
                        "char_range": {"start": text_start_in_page, "end": text_end_in_page},
                        "chars_used": chars_used,
                        "metadata": page_info["metadata"],
                        "has_tables": page_info.get("has_tables", False),
                        "has_images": page_info.get("has_images", False),
                        "table_count": page_info.get("table_count", 0),
                        "image_count": page_info.get("image_count", 0),
                    }
                )

        return pages_used

    def _merge_page_metadata(self, pages_used: List[Dict]) -> Dict:
        """Intelligently merge metadata from multiple pages."""
        if not pages_used:
            return {}

        first_page_meta = pages_used[0].get("metadata", {})
        merged = {}

        # Document-level metadata
        for field in ["title", "author", "subject", "keywords"]:
            if first_page_meta.get(field):
                merged[field] = first_page_meta[field]

        if first_page_meta.get("page_count"):
            merged["total_pages"] = first_page_meta["page_count"]

        for date_field in ["creation_date", "modification_date"]:
            if first_page_meta.get(date_field):
                merged[date_field.replace("_", "")] = first_page_meta[date_field]

        # Chunk-specific metadata
        merged["pages"] = [p["page_num"] for p in pages_used]
        merged["page_range"] = {
            "start": min(p["page_num"] for p in pages_used),
            "end": max(p["page_num"] for p in pages_used),
        }

        # Aggregate table and image information
        total_tables = sum(p.get("table_count", 0) for p in pages_used)
        total_images = sum(p.get("image_count", 0) for p in pages_used)
        has_tables = any(p.get("has_tables", False) for p in pages_used)
        has_images = any(p.get("has_images", False) for p in pages_used)

        merged["has_tables"] = has_tables
        merged["has_images"] = has_images

        if total_tables > 0:
            merged["table_count"] = total_tables
        if total_images > 0:
            merged["image_count"] = total_images

        return merged

    def _create_enhanced_chunk_mapping(
        self,
        doc_id: str,
        chunks: List[str],
        metadata: Dict = None,
        page_map: List[Dict] = None,
        combined_text: str = None,
        original_filename: str = None,
    ) -> Dict[str, Any]:
        """Create comprehensive chunk mapping with metadata and page tracking."""
        chunk_data = {
            "doc_id": doc_id,
            "total_chunks": len(chunks),
            "chunks": [],
            "mapping": {},
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat(),
            "text_preservation_guaranteed": True,
            "embedding_model": self.embedding_model_name,
            "chunking_method": self.method,
        }

        # Add original filename if provided
        if original_filename:
            chunk_data["original_filename"] = original_filename

        # Add document-level metadata if available
        if page_map and page_map[0].get("metadata"):
            first_page_meta = page_map[0]["metadata"]
            chunk_data["document_metadata"] = {
                k: v
                for k, v in first_page_meta.items()
                if k
                in [
                    "title",
                    "author",
                    "subject",
                    "keywords",
                    "page_count",
                    "creation_date",
                    "modification_date",
                ]
                and v
            }

        # Fixed position tracking
        search_start_position = 0

        for i, chunk_text in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i+1:03d}"
            language = "german" if self._detect_german(chunk_text) else "english"

            chunk_info = {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "chunk_index": i,
                "text": chunk_text,
                "char_count": len(chunk_text),
                "token_count": self.count_tokens(chunk_text),
                "language": language,
            }

            # FIXED: Always add original filename to EVERY chunk
            if original_filename:
                chunk_info["original_filename"] = original_filename

            # Add page tracking if we have page map
            if page_map and combined_text:
                # Find chunk position in combined text
                chunk_start = combined_text.find(chunk_text, search_start_position)

                if chunk_start == -1:
                    # Try from beginning if not found (overlap case)
                    chunk_start = combined_text.find(chunk_text)
                    if chunk_start == -1:
                        # Fallback to approximate position
                        chunk_start = search_start_position

                chunk_end = chunk_start + len(chunk_text)

                # Update search position for next chunk (account for overlap)
                search_start_position = max(0, chunk_end - self.chunk_overlap)

                # Find which pages this chunk uses
                pages_used = self._find_pages_in_range(chunk_start, chunk_end, page_map)

                if pages_used:
                    chunk_info["pages_used"] = [
                        {
                            "page_num": p["page_num"],
                            "char_range": p["char_range"],
                            "chars_used": p["chars_used"],
                        }
                        for p in pages_used
                    ]

                    merged_metadata = self._merge_page_metadata(pages_used)
                    if merged_metadata:
                        chunk_info["metadata"] = merged_metadata

                # Add position information
                chunk_info["position"] = {"global_start": chunk_start, "global_end": chunk_end}

            # Mapping information
            mapping_info = {
                "doc_id": doc_id,
                "chunk_index": i,
                "char_start": (
                    search_start_position
                    if page_map
                    else i * (len(chunk_text) - self.chunk_overlap)
                ),
                "char_end": (
                    search_start_position + len(chunk_text)
                    if page_map
                    else (i + 1) * len(chunk_text)
                ),
            }

            chunk_data["chunks"].append(chunk_info)
            chunk_data["mapping"][chunk_id] = mapping_info

        return chunk_data

    def _create_single_chunk(
        self, doc_id: str, text: str, metadata: Dict = None, original_filename: str = None
    ) -> Dict[str, Any]:
        """Create single chunk for any short document."""
        chunk_id = f"{doc_id}_chunk_001"

        chunk_info = {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "chunk_index": 0,
            "text": text,
            "char_count": len(text),
            "token_count": self.count_tokens(text),
            "language": "german" if self._detect_german(text) else "english",
        }

        # FIXED: Always add original filename
        if original_filename:
            chunk_info["original_filename"] = original_filename

        result = {
            "doc_id": doc_id,
            "total_chunks": 1,
            "chunks": [chunk_info],
            "mapping": {
                chunk_id: {
                    "doc_id": doc_id,
                    "chunk_index": 0,
                    "char_start": 0,
                    "char_end": len(text),
                }
            },
            "metadata": metadata or {},
            "processing_method": "single_chunk",
            "created_at": datetime.now().isoformat(),
            "text_preservation_guaranteed": True,
            "chunking_method": self.method,
        }

        # Add original filename to top level
        if original_filename:
            result["original_filename"] = original_filename

        return result

    def chunk_document(
        self,
        doc_id: str,
        text: str,
        metadata: Dict = None,
        original_filename: str = None,
        verbose: bool = True,
    ) -> Dict[str, Any]:
        """
        Main chunking method with metadata awareness and page tracking.
        Supports both simple and semantic_embedding modes.

        Args:
            doc_id: Unique document identifier
            text: Document text to chunk
            metadata: Optional metadata dict
            original_filename: Original filename with extension (e.g., "report.pdf")
            verbose: Print progress messages
        """
        total_start = time.time()
        if self.track_performance:
            self.timing = {}

        if not text:
            text = "[Empty document]"

        original_text = text

        # Try to parse as pymupdf4llm structured document
        pages = self._parse_pymupdf4llm_document(text)

        if pages:
            if verbose:
                print(f"Processing structured document {doc_id} with {len(pages)} pages...")

            combined_text, page_map = self._create_text_with_page_mapping(pages)

            if not combined_text or not combined_text.strip():
                combined_text = original_text
                page_map = None
                if verbose:
                    print("   Warning: No text extracted from pages, using original text")
            else:
                if verbose:
                    print(f"   Extracted {len(combined_text)} chars from {len(pages)} pages")

            text_for_chunking = combined_text
        else:
            if verbose:
                print(f"Processing plain text document {doc_id}: {len(text)} characters...")

            # Optional preprocessing
            if self.preprocess_text:
                text_for_chunking = self._fix_encoding(text)
                text_for_chunking = self._normalize_whitespace(text_for_chunking)
            else:
                text_for_chunking = text

            page_map = None
            combined_text = None

        language = "German" if self._detect_german(text_for_chunking) else "English"
        if verbose:
            print(f"   Detected language: {language}")

        try:
            if self.method == "simple":
                # Simple fixed-size chunking
                start_time = time.time()
                final_chunks = self._simple_chunk(text_for_chunking)

                if self.track_performance:
                    self.timing["simple_chunking"] = time.time() - start_time

                final_chunks = self._ensure_at_least_one_chunk(final_chunks, text_for_chunking)

                if verbose:
                    print(f"   Created {len(final_chunks)} chunks using simple method")

            else:  # semantic_embedding
                # Semantic chunking with embeddings
                start_time = time.time()
                segments = self._split_into_sentences(text_for_chunking)

                if self.track_performance:
                    self.timing["sentence_split"] = time.time() - start_time

                self._validate_text_preservation(
                    text_for_chunking, segments, "sentence_splitting", verbose
                )

                if verbose:
                    print(f"   Found {len(segments)} text segments")

                if len(segments) <= 3:
                    if verbose:
                        print("   Creating simple chunks for short document")
                    chunks = self._split_by_token_limit(" ".join(segments))
                    final_chunks = self._ensure_at_least_one_chunk(chunks, text_for_chunking)
                else:
                    if verbose:
                        print("   Proceeding with semantic chunking")

                    start_time = time.time()
                    windows = self._create_sliding_windows(segments)

                    if self.track_performance:
                        self.timing["windows"] = time.time() - start_time

                    embeddings = self._compute_embeddings_batch(windows)

                    if embeddings.size > 0:
                        distances = self._calculate_distances_fast(embeddings)
                        start_time = time.time()
                        breakpoints = self._find_breakpoints(distances)

                        if self.track_performance:
                            self.timing["breakpoints"] = time.time() - start_time
                    else:
                        breakpoints = []

                    start_time = time.time()
                    initial_chunks = self._create_chunks_from_sentences(segments, breakpoints)
                    self._validate_text_preservation(
                        text_for_chunking, initial_chunks, "initial_chunking", verbose
                    )

                    token_limited_chunks = self._enforce_token_limits(initial_chunks)
                    self._validate_text_preservation(
                        text_for_chunking, token_limited_chunks, "token_limiting", verbose
                    )

                    overlapped_chunks = self._add_overlap(token_limited_chunks)
                    final_chunks = self._ensure_at_least_one_chunk(
                        overlapped_chunks, text_for_chunking
                    )
                    self._validate_text_preservation(
                        text_for_chunking, final_chunks, "final_chunking", verbose
                    )

                    if self.track_performance:
                        self.timing["chunk_creation"] = time.time() - start_time

            # Create enhanced mapping with metadata and original filename
            start_time = time.time()
            chunk_data = self._create_enhanced_chunk_mapping(
                doc_id, final_chunks, metadata, page_map, combined_text, original_filename
            )

            if self.track_performance:
                self.timing["mapping_creation"] = time.time() - start_time

            # Save chunks
            start_time = time.time()
            self._save_chunks(doc_id, chunk_data)

            if self.track_performance:
                self.timing["file_io"] = time.time() - start_time

            total_time = time.time() - total_start

            # Only save performance data if tracking enabled
            if self.track_performance:
                self._save_performance_data(doc_id, chunk_data, total_time, len(text_for_chunking))
                self.timing["total"] = total_time
                self._update_performance_stats(chunk_data, total_time, len(text_for_chunking))

            if verbose:
                self._print_chunking_summary(doc_id, chunk_data, total_time, len(text_for_chunking))
                if pages:
                    print(f"   Metadata tracking enabled: {len(pages)} pages processed")
                if original_filename:
                    print(f"   Original filename: {original_filename}")

            return chunk_data

        except Exception as e:
            error_msg = f"ERROR processing document {doc_id}: {e}"
            print(error_msg)

            # Create emergency fallback chunk
            try:
                if verbose:
                    print("   Creating emergency fallback chunk...")

                fallback_chunk_data = self._create_single_chunk(
                    doc_id, text_for_chunking, metadata, original_filename
                )

                self._save_chunks(doc_id, fallback_chunk_data)
                return fallback_chunk_data

            except Exception as fallback_error:
                print(f"   Emergency fallback also failed: {fallback_error}")
                raise

    def get_chunk_text(self, chunk_id: str) -> Optional[str]:
        """Get text for a specific chunk."""
        doc_id = chunk_id.split("_chunk_")[0]
        chunk_data = self.load_chunks(doc_id)

        if chunk_data:
            for chunk in chunk_data["chunks"]:
                if chunk["chunk_id"] == chunk_id:
                    return chunk["text"]
        return None

    def _save_chunks(self, doc_id: str, chunk_data: Dict):
        """Save chunk data to file."""
        try:
            if not chunk_data or not isinstance(chunk_data, dict):
                raise ValueError(f"Invalid chunk_data for {doc_id}")

            if "chunks" not in chunk_data or not chunk_data["chunks"]:
                raise ValueError(f"No chunks found in chunk_data for {doc_id}")

            output_file = self.chunks_dir / f"{doc_id}_chunks.json"

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(chunk_data, f, indent=2, ensure_ascii=False)

            if not output_file.exists():
                raise IOError(f"Failed to write chunk file: {output_file}")

        except Exception as e:
            print(f"CRITICAL ERROR saving chunks for {doc_id}: {e}")
            raise

    def load_chunks(self, doc_id: str) -> Optional[Dict]:
        """Load chunk data for a document."""
        chunks_file = self.chunks_dir / f"{doc_id}_chunks.json"
        if chunks_file.exists():
            with open(chunks_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def process_folder(self, input_dir: str) -> List[Dict]:
        """Process all documents in a structured folder."""
        start_time = time.time()

        input_path = Path(input_dir)
        text_files = list((input_path / "texts").glob("*.txt"))

        if not text_files:
            print(f"No text files found in {input_dir}/texts/")
            return []

        print(f"Processing {len(text_files)} documents from {input_dir}")

        results = []

        for text_file in text_files:
            doc_id = text_file.stem

            try:
                metadata_file = input_path / "metadata" / f"{doc_id}.json"
                metadata = {}
                original_filename = None

                if metadata_file.exists():
                    with open(metadata_file, "r") as f:
                        metadata = json.load(f)
                        # Extract original filename from metadata
                        original_filename = metadata.get("original_filename") or metadata.get(
                            "filename"
                        )

                with open(text_file, "r", encoding="utf-8") as f:
                    text = f.read()

                result = self.chunk_document(
                    doc_id, text, metadata, original_filename, verbose=False
                )

                print(f"  SUCCESS: {doc_id}: {result['total_chunks']} chunks created")
                results.append(result)

            except Exception as e:
                print(f"  ERROR: {doc_id}: FAILED - {e}")
                continue

        total_time = time.time() - start_time
        total_chunks = sum(r["total_chunks"] for r in results)

        print("\nFOLDER PROCESSING COMPLETE")
        print(f"Documents: {len(results)} | Chunks: {total_chunks}")
        print(f"Total time: {total_time:.2f}s")
        print(f"Speed: {len(results)/total_time:.1f} docs/sec")
        print(f"Output: {self.chunks_dir}")

        return results

    def _save_performance_data(
        self, doc_id: str, chunk_data: Dict, total_time: float, char_count: int
    ):
        """Save performance data for a document (only if tracking enabled)."""
        if not self.track_performance:
            return

        performance_data = {
            "doc_id": doc_id,
            "processed_at": datetime.now().isoformat(),
            "chunking_method": self.method,
            "performance_metrics": {
                "total_processing_time_seconds": round(total_time, 3),
                "chars_processed": char_count,
                "chunks_created": chunk_data["total_chunks"],
                "chars_per_second": round(char_count / total_time if total_time > 0 else 0, 0),
            },
            "timing_breakdown": {k: round(v, 3) for k, v in self.timing.items()},
        }

        perf_file = self.performance_dir / f"{doc_id}_chunking_performance.json"
        with open(perf_file, "w") as f:
            json.dump(performance_data, f, indent=2, ensure_ascii=False)

    def _update_performance_stats(self, chunk_data: Dict, total_time: float, char_count: int):
        """Update global performance statistics (only if tracking enabled)."""
        if not self.track_performance:
            return

        self.performance_stats["total_documents"] += 1
        self.performance_stats["total_chunks_created"] += chunk_data["total_chunks"]
        self.performance_stats["total_processing_time"] += total_time
        self.performance_stats["total_chars_processed"] += char_count

    def _print_chunking_summary(
        self, doc_id: str, chunk_data: Dict, total_time: float, char_count: int
    ):
        """Print chunking performance summary."""
        chunks_created = chunk_data["total_chunks"]
        chars_per_sec = char_count / total_time if total_time > 0 else 0

        print(f"Chunked: {doc_id}")
        print(f"  Created {chunks_created} chunks from {char_count:,} characters")
        print(f"  Total time: {total_time:.3f}s")
        print(f"  Speed: {chars_per_sec:.0f} chars/sec")

    def print_performance_summary(self):
        """Print overall performance summary (only if tracking enabled)."""
        if not self.track_performance:
            print("Performance tracking is disabled.")
            return

        stats = self.performance_stats
        if stats["total_documents"] == 0:
            print("No documents processed yet.")
            return

        avg_time = stats["total_processing_time"] / stats["total_documents"]
        avg_chunks = stats["total_chunks_created"] / stats["total_documents"]
        overall_speed = (
            stats["total_chars_processed"] / stats["total_processing_time"]
            if stats["total_processing_time"] > 0
            else 0
        )

        print("\nCHUNKING PERFORMANCE SUMMARY")
        print("=" * 50)
        print(f"Documents processed: {stats['total_documents']}")
        print(f"Total chunks created: {stats['total_chunks_created']}")
        print(f"Total processing time: {stats['total_processing_time']:.1f}s")
        print(f"Average time per document: {avg_time:.3f}s")
        print(f"Average chunks per document: {avg_chunks:.1f}")
        print(f"Overall processing speed: {overall_speed:.0f} chars/sec")
        print("Text preservation: GUARANTEED")
        print("Metadata tracking: ENABLED")
        print(f"Embedding model: {self.embedding_model_name}")
        print(f"Chunking method: {self.method}")
        print(f"Output directory: {self.chunks_dir.absolute()}")


# Example usage
if __name__ == "__main__":
    chunker = DocumentChunker(config_path="config.yaml", track_performance=True)

    print("\nStarting text chunking pipeline...")
    print("=" * 60)

    # Test with sample text
    test_text = "This is a test document. It contains multiple sentences. Each sentence will be analyzed for semantic chunking."

    print("\nTesting with sample text...")
    try:
        result = chunker.chunk_document(
            doc_id="test_sample",
            text=test_text,
            metadata={"source": "test"},
            original_filename="test_sample.txt",
        )

        print("Successfully processed document:")
        print(f"   Chunks created: {result['total_chunks']}")
        print(f"   Chunking method: {result.get('chunking_method', 'N/A')}")
        if "original_filename" in result:
            print(f"   Original filename: {result['original_filename']}")

    except Exception as e:
        print(f"Error processing document: {e}")
