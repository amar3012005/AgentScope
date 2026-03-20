# BLAIQ Core - Hybrid GraphRAG Document Intelligence System

**Version**: 3.0.0
**Status**: Production
**Last Updated**: 2026-03-20

## Overview

BLAIQ Core is a sophisticated document processing and retrieval system combining **vector search**, **knowledge graphs**, and **LLM-powered question answering** with flexible metadata support and comprehensive file management.

### Key Capabilities

- **Hybrid Search**: Vector similarity + Keyword matching + Graph traversal
- **Multi-Tenant Isolation**: Strict data separation via collection_name/filter_label
- **Flexible Metadata**: Attach custom key-value pairs to documents
- **File Management**: Upload, organize, delete with security protections
- **GraphRAG**: Entity extraction + Neo4j graph traversal + vector search
- **LLM Integration**: Anthropic Claude models for advanced reasoning
- **Streaming API**: Real-time responses via Server-Sent Events (SSE)

## System Architecture

```
┌─────────────┐
│  Documents  │
└──────┬──────┘
       │
       ▼
┌──────────────────────────────────────┐
│     Pipeline API                     │
│  ┌─────────────────────────────────┐ │
│  │ Document Processing             │ │
│  │ • Extract text (PDF, DOCX, etc) │ │
│  │ • Parse metadata                │ │
│  │ • Organize by folder_path       │ │
│  └─────────────────────────────────┘ │
└──────┬───────────────────────────────┘
       │
       ├─────────────┬─────────────┬──────────────┐
       ▼             ▼             ▼              ▼
   ┌────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐
   │ Chunking│ │Embedding│ │Entity    │  │Cleanup  │
   │         │ │(BGE-M3) │ │Extraction│  │Strategy │
   └────────┘  └─────────┘  └──────────┘  └──────────┘
       │
       ├─────────────┬─────────────┐
       ▼             ▼             ▼
   ┌────────────┐ ┌────────┐ ┌──────────┐
   │   Qdrant   │ │ Neo4j  │ │ Metadata │
   │(Vectors)   │ │(Graph) │ │ (Storage)│
   └────────────┘ └────────┘ └──────────┘
       │
       └─────────────┬─────────────┘
                     ▼
              ┌──────────────────┐
              │  Retriever API   │
              │  ┌──────────────┐│
              │  │ RAG Query   ││
              │  ├──────────────┤│
              │  │ GraphRAG    ││
              │  └──────────────┘│
              └──────────────────┘
                     │
                     ▼
              ┌──────────────────┐
              │  Answer + Stream │
              │  (SSE + JSON)    │
              └──────────────────┘
```

## Core Components

### 1. Pipeline API (`src/pipeline/pipeline_api.py`)
- **Upload**: Documents with custom metadata
- **Process**: Extract, chunk, embed, index
- **Manage**: List, delete files and folders
- **Status**: Job tracking and result retrieval

### 2. Retriever API (`src/retriever/retriever_api_optimized.py`)
- **RAG Query**: Vector + Keyword search only
- **GraphRAG Query**: Hybrid (Graph + Vector + Keyword)
- **Answer Generation**: LLM-powered responses
- **Graph Visualization**: Mermaid diagrams of relationships

### 3. GraphRAG Retriever (`src/retriever/graphrag_retriever.py`)
- **Core Logic**: 2500+ lines of hybrid search implementation
- **Entity Extraction**: LLM-based entity identification from queries
- **Graph Traversal**: Neo4j relationship exploration
- **RRF Fusion**: Reciprocal Rank Fusion of multiple retrieval methods
- **Streaming**: Real-time response generation

### 4. Prompt System (`src/prompts/`)
- **XML-based Prompts**: Configurable system prompts
- **Unified Planner**: Single LLM call for planning + entity extraction + keyword expansion
- **Dynamic Loading**: Runtime prompt customization

## API Endpoints

### Pipeline API
```
POST   /upload                      # Upload documents
POST   /process                     # Start processing job
GET    /status/{job_id}            # Check job status
GET    /result/{job_id}            # Get processing results
GET    /get-user-files             # List files (tree view)
GET    /get-user-files-flat        # List files (flat, paginated)
POST   /delete-file                # Delete multiple files
POST   /delete-folder              # Delete entire folder
DELETE /document/qdrant            # Remove from vector DB
DELETE /document/neo4j             # Remove from graph DB
```

### Retriever API
```
POST /query/rag                     # Traditional RAG search
POST /query/graphrag                # Hybrid GraphRAG search
GET  /status                        # Check system health
```

## Key Features

### Multi-Tenancy
- **Isolation**: Each tenant gets separate collection_name
- **Guarantee**: Same entity names in different tenants = separate graph nodes
- **Scope**: All queries filtered by filter_label (derived from collection_name)

### Evidence System
- **Chunk Attribution**: Every answer traces back to source documents
- **Metadata Preservation**: Original filename, document ID, chunk position
- **Citation Tracking**: Exact chunk text included in responses
- **Source Filtering**: Optional filtering by metadata fields

### Streaming Response
- **Format**: Server-Sent Events (SSE)
- **Data**: `data: {json}\n\n` followed by `data: [DONE]\n\n`
- **Real-time**: User sees answer generation as it happens

### Error Resilience
- **LLM Fallback**: Primary model fails → automatic fallback to secondary
- **Timeout Protection**: 25-second timeout on all LLM calls
- **Graceful Degradation**: Service continues if LLM unavailable (returns context only)

## Configuration

### Environment Variables
```bash
# API Authentication
API_KEY=your_api_key

# LLM Models (Anthropic Claude via LiteLLM)
LITELLM_PLANNER_MODEL=claude-opus-4-6
LITELLM_POST_MODEL=claude-sonnet-4-6
LITELLM_PRE_MODEL=claude-haiku-4-5

# Qdrant (Vector Database)
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=your_qdrant_key
QDRANT_COLLECTION=graphrag_chunks

# Neo4j (Knowledge Graph)
NEO4J_URI=neo4j+s://neo4j.api.blaiq.ai:7689
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password

# LLM Resilience
LLM_TIMEOUT_SECONDS=25
OPENAI_FALLBACK_MODEL=gpt-3.5-turbo
```

## Deployment

### Docker Compose
```bash
docker-compose up --build -d
```

### Production Checklist
- [ ] Strong API_KEY configured
- [ ] HTTPS enabled
- [ ] Qdrant persistence configured
- [ ] Backup strategy for `data/` directory
- [ ] Rate limiting on public endpoints
- [ ] LLM timeout and fallback models configured
- [ ] Monitoring and alerting setup
- [ ] Audit logging enabled

## Performance Optimizations (2026-02-16)

### Pipeline Improvements
- **Unified Planner**: Planner + entity extraction + keyword expansion in 1 LLM call
- **Integrated Formatting**: Response generation without separate reformat call
- **Vector Validation**: Embedding consistency checks with fallback
- **Reduced Calls**: 6 LLM calls → 2 (planner + answer generation)

### Retrieval Speed
- Manual REST calls to Qdrant (avoids QdrantClient SSL issues)
- Parallel retrieval (vector + keyword + graph)
- RRF fusion for efficient ranking

## Next Steps

1. **Evidence Enhancement**: Detailed source attribution in responses
2. **Graph Quality**: Entity linking improvements
3. **Query Optimization**: Advanced entity extraction patterns
4. **Scale Testing**: Load testing with 10M+ vectors
5. **UI Integration**: Frontend for graph visualization

## Support

- **API Docs**: https://second.amar.blaiq.ai/pipeline/docs
- **Issues**: Check logs in `logs/llm_error.log`
- **Monitoring**: Production dashboard at grafana.internal/d/api-latency
