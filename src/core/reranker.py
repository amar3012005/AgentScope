import logging
import time
from typing import List, Dict, Any, Tuple
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

class Reranker:
    """
    Elite Status Reranker - Boosts RAG accuracy by re-scoring top candidates 
    using a deep Cross-Encoder model.
    """
    
    def __init__(self, model_name: str = "BAAI/bge-reranker-base", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self.tokenizer = None
        self.use_onnx = False
        self.enabled = False
        
            # Try initializing ONNX Runtime first (Fastest on CPU)
        try:
            from optimum.onnxruntime import ORTModelForSequenceClassification
            from transformers import AutoTokenizer
            from onnxruntime import SessionOptions, GraphOptimizationLevel
            import os
            
            logger.info(f"🚀 Initializing Optimized ONNX Reranker with {model_name}...")
            
            # CPU Optimization: Use all available cores and optimize graph
            session_options = SessionOptions()
            session_options.intra_op_num_threads = os.cpu_count() or 4
            session_options.inter_op_num_threads = os.cpu_count() or 4
            # Pass the enum value directly to the property
            session_options.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
            
            try:
                self.model = ORTModelForSequenceClassification.from_pretrained(
                    model_name, 
                    export=False,
                    file_name="model.onnx",
                    session_options=session_options
                )
                logger.info("✅ Loaded existing ONNX model from cache.")
            except Exception:
                logger.info("🔄 ONNX model not found in cache, exporting...")
                self.model = ORTModelForSequenceClassification.from_pretrained(
                    model_name, 
                    export=True,
                    file_name="model.onnx",
                    session_options=session_options
                )
            
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.use_onnx = True
            self.enabled = True
            logger.info(f"✅ ONNX Reranker initialized (Provider: {self.model.providers[0] if hasattr(self.model, 'providers') else 'CPU'})")
            
        except ImportError as e:
            logger.warning(f"⚠️ Optimum/ONNX not found (Error: {e}). Falling back to standard Torch CrossEncoder.")
        except Exception as e:
            logger.error(f"❌ ONNX Initialization failed: {e}. Falling back to standard Torch.")

        # Fallback to SentenceTransformers (Slower but reliable)
        if not self.enabled:
            try:
                from sentence_transformers import CrossEncoder
                self.model = CrossEncoder(model_name, device=device)
                self.use_onnx = False
                self.enabled = True
                logger.info(f"✅ Standard Reranker initialized using Torch on {device}")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Reranker: {e}")
                self.enabled = False

    def rerank(self, query: str, documents: List[Document], top_n: int = 10) -> List[Document]:
        """
        Re-scores documents based on the query.
        """
        if not self.enabled or not documents:
            return documents[:top_n]
            
        start_time = time.time()
        
        try:
            # Prepare pairs
            pairs = [[query, doc.page_content] for doc in documents]
            
            scores = []
            
            if self.use_onnx:
                import torch
                # ONNX Inference
                inputs = self.tokenizer(
                    pairs, 
                    padding=True, 
                    truncation=True, 
                    return_tensors="pt", 
                    max_length=384
                )
                
                # Run inference
                outputs = self.model(**inputs)
                logits = outputs.logits
                
                # BAAI/bge-reranker-base outputs a single logit. 
                # Use sigmoid to normalize if needed, but raw logits are fine for sorting.
                if logits.shape[1] == 1:
                    scores = logits.view(-1).float().cpu().numpy()
                else:
                    # Some rerankers output [neg, pos]
                    scores = logits[:, 1].float().cpu().numpy()
            else:
                # SentenceTransformers Inference
                scores = self.model.predict(pairs)
            
            # Attach scores to documents
            for i, score in enumerate(scores):
                documents[i].metadata["rerank_score"] = float(score)
            
            # Sort by rerank_score (higher is better)
            reranked_docs = sorted(
                documents, 
                key=lambda x: x.metadata["rerank_score"], 
                reverse=True
            )
            
            if self.tokenizer:
                total_tokens = sum(len(self.tokenizer.encode(p[1])) for p in pairs)
                token_info = f" ({total_tokens} tokens)"
            else:
                token_info = ""

            duration = (time.time() - start_time) * 1000
            logger.info(f"🎯 Reranked {len(documents)} docs{token_info} in {duration:.2f}ms ({'ONNX' if self.use_onnx else 'Torch'})")
            
            return reranked_docs[:top_n]
            
        except Exception as e:
            logger.error(f"❌ Error during reranking: {e}")
            return documents[:top_n]

# Global instance for easy reuse
_reranker_instance = None

def get_reranker(model_name: str = "BAAI/bge-reranker-base"):
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = Reranker(model_name=model_name)
    return _reranker_instance
