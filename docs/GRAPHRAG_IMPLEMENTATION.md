# GraphRAG: Knowledge Graph Implementation in BLAIQ Core

## What is GraphRAG?

**GraphRAG** combines three retrieval paradigms:
- **G**raph: Entity relationships (Neo4j)
- **R**etrieval: Augmented generation (RAG)
- **A**ugmented: Enhanced with context

Unlike traditional RAG (vector-only), GraphRAG understands **relationships** between entities.

## How GraphRAG Works

### Step 1: Entity Extraction from Documents

During document processing, LLM identifies entities and relationships:

```python
# Document text
text = """
John Smith, CEO of TechCorp, met with Jane Wilson from DataInc to discuss
their partnership agreement. The meeting covered API integration, data sharing,
and revenue sharing models.
"""

# LLM extracts entities and relationships
extracted = {
  "entities": [
    {"name": "John Smith", "type": "PERSON", "role": "CEO"},
    {"name": "TechCorp", "type": "ORGANIZATION"},
    {"name": "Jane Wilson", "type": "PERSON"},
    {"name": "DataInc", "type": "ORGANIZATION"},
    {"name": "API integration", "type": "CONCEPT"},
    {"name": "Revenue sharing", "type": "CONCEPT"}
  ],
  "relationships": [
    {"source": "John Smith", "target": "TechCorp", "type": "WORKS_FOR"},
    {"source": "John Smith", "target": "Jane Wilson", "type": "MET_WITH"},
    {"source": "TechCorp", "target": "DataInc", "type": "PARTNERSHIP"},
    {"source": "TechCorp", "target": "API integration", "type": "IMPLEMENTS"},
    {"source": "TechCorp", "target": "Revenue sharing", "type": "NEGOTIATES"}
  ]
}
```

### Step 2: Graph Construction in Neo4j

Entities and relationships are stored in Neo4j with tenant isolation:

```cypher
// Create entities (each tagged with filter_label for multi-tenancy)
CREATE (p1:Entity {
  id: "PERSON_John_Smith",
  name: "John Smith",
  type: "PERSON",
  properties: {role: "CEO"},
  filter_label: "tenant_a"
})

CREATE (o1:Entity {
  id: "ORGANIZATION_TechCorp",
  name: "TechCorp",
  type: "ORGANIZATION",
  filter_label: "tenant_a"
})

CREATE (c1:Entity {
  id: "CONCEPT_API_integration",
  name: "API integration",
  type: "CONCEPT",
  filter_label: "tenant_a"
})

// Create relationships
CREATE (p1)-[:WORKS_FOR {confidence: 0.95, chunk_count: 3}]->(o1)
CREATE (p1)-[:MET_WITH {confidence: 0.92, date: "2026-03-20"}]->(p2)
CREATE (o1)-[:PARTNERSHIP {confidence: 0.88, active: true}]->(o2)
CREATE (o1)-[:IMPLEMENTS {confidence: 0.90}]->(c1)
```

**Graph Structure:**
```
    John Smith (PERSON)
         │
         ├─── WORKS_FOR ──→ TechCorp (ORGANIZATION)
         │                      │
         │                      ├─── PARTNERSHIP ──→ DataInc
         │                      │
         │                      └─── IMPLEMENTS ──→ API integration
         │
         └─── MET_WITH ──→ Jane Wilson (PERSON)
                               │
                               └─── WORKS_FOR ──→ DataInc
```

### Step 3: Query Entity Extraction

When a user queries, entities are extracted from the query:

```python
user_query = "What partnerships does TechCorp have?"

# LLM extracts entities from query
entities = extract_entities(user_query)
# Result: [
#   {"name": "TechCorp", "type": "ORGANIZATION"},
#   {"name": "partnerships", "type": "CONCEPT"}
# ]
```

### Step 4: Graph Traversal

Starting from seed entities, traverse relationships:

```cypher
# Find all partnerships of TechCorp
MATCH (org:Entity {name: "TechCorp", filter_label: "tenant_a"})
-[rel:PARTNERSHIP|:RELATED_TO*1..2]->(connected:Entity)
RETURN org, rel, connected, connected.name as partner_name

# Result:
# TechCorp -PARTNERSHIP-> DataInc
# TechCorp -IMPLEMENTS-> API integration
# TechCorp -PARTNERSHIP-> OtherCorp (via intermediary)
```

### Step 5: Collect Related Chunks

For each found entity, retrieve associated chunks:

```cypher
# Get all chunks mentioning TechCorp or its partners
MATCH (e:Entity {filter_label: "tenant_a"})
-[:MENTIONED_IN]->(chunk:Chunk {filter_label: "tenant_a"})
WHERE e.name IN ["TechCorp", "DataInc", "API integration"]
RETURN chunk, chunk.text

# Result: All chunks containing information about TechCorp's partnerships
```

### Step 6: Hybrid Ranking (RRF Fusion)

Combine graph results with vector and keyword searches:

```python
# Retrieve from 3 sources
graph_chunks = neo4j_search(entities)        # 8 chunks
vector_chunks = qdrant_search(query)         # 10 chunks
keyword_chunks = keyword_search(query)       # 6 chunks

# RRF fusion
ranked_chunks = rrf_fusion([
  graph_chunks,      # Graph found 8
  vector_chunks,     # Vector found 10
  keyword_chunks     # Keyword found 6
])

# Result: Unified ranking of all unique chunks
# Example:
# 1. Chunk about partnership agreement (found by all 3)
# 2. Chunk about revenue sharing (found by vector + keyword)
# 3. Chunk about API specs (found by graph + keyword)
```

### Step 7: Answer Generation with Context

LLM generates answer using fused context:

```python
retrieved_context = format_chunks(ranked_chunks)

prompt = """Based on the context below, answer: What partnerships does TechCorp have?

Context:
{context}

Answer:"""

answer = llm.generate(prompt)
# "TechCorp has partnerships with DataInc (covering API integration and
#  revenue sharing), and OtherCorp (through intermediary relationships).
#  The API integration project is particularly significant, involving
#  specialized data sharing agreements."
```

## Neo4j Graph Structure

### Entity Types

```cypher
// People, roles, positions
PERSON
  - name: string
  - title: string
  - department: string

// Companies, teams, groups
ORGANIZATION
  - name: string
  - industry: string
  - sector: string

// Locations, buildings
LOCATION
  - name: string
  - region: string
  - country: string

// Technologies, products, concepts
CONCEPT
  - name: string
  - domain: string
  - definition: string

// Specific documents, reports, events
DOCUMENT
  - name: string
  - doc_type: string
  - date: string
```

### Relationship Types

```cypher
// Person relationships
WORKS_FOR        → Person to Organization
MANAGED_BY       → Person to Person
RESPONSIBLE_FOR  → Person to Project
ASSOCIATED_WITH  → Person to Person (general)

// Organization relationships
PARTNERSHIP      → Organization to Organization
OWNS             → Organization to Organization
HEADQUARTERED_IN → Organization to Location
OPERATES_IN      → Organization to Location

// Concept relationships
MENTIONS         → Concept to Any
IMPLEMENTS       → Organization to Concept
USES             → Person/Org to Concept
RELATED_TO       → Concept to Concept

// Document relationships
MENTIONED_IN     → Entity to Chunk
DESCRIBES        → Chunk to Entity
REFERENCES       → Chunk to Chunk
CONTAINS         → Document to Concept
```

## Query Examples

### Example 1: Simple Entity Lookup

```
Query: "Tell me about John Smith"

1. Extract entities: [John Smith]
2. Graph traversal: 1-hop
   - Find: John Smith node
   - Connected to: TechCorp (WORKS_FOR)
   - Connected to: Jane Wilson (MET_WITH)
3. Retrieve chunks mentioning John Smith or connections
4. Generate answer with context
```

### Example 2: Multi-Hop Relationship

```
Query: "What companies are connected to TechCorp through partnerships?"

1. Extract entities: [TechCorp, partnerships, companies]
2. Graph traversal: 2-hops
   - Start: TechCorp
   - 1st hop: PARTNERSHIP → DataInc, OtherCorp
   - 2nd hop: PARTNERSHIP from DataInc → ThirdCorp
3. Retrieve all partnership-related chunks
4. Generate comprehensive answer
```

### Example 3: Concept Discovery

```
Query: "Where is API integration used in our partnerships?"

1. Extract entities: [API integration, partnerships]
2. Graph traversal: 2-hops
   - Start: API integration (CONCEPT)
   - 1st hop: IMPLEMENTED_BY → TechCorp
   - Connected via: PARTNERSHIP → DataInc
3. Retrieve chunks about API integration and partnerships
4. Explain the connection and usage
```

## Multi-Tenancy in GraphRAG

Every Neo4j query includes `filter_label` to ensure tenant isolation:

```cypher
// Tenant A query
MATCH (e:Entity {filter_label: "tenant_a"})
-[:PARTNERSHIP]->(partner:Entity {filter_label: "tenant_a"})
RETURN e, partner

// Tenant B query - completely separate
MATCH (e:Entity {filter_label: "tenant_b"})
-[:PARTNERSHIP]->(partner:Entity {filter_label: "tenant_b"})
RETURN e, partner

// Same entities in different tenants are never mixed
Tenant A: "John Smith" = PERSON_1234 with filter_label: "tenant_a"
Tenant B: "John Smith" = PERSON_5678 with filter_label: "tenant_b"
```

## Advantages of GraphRAG

| Aspect | Traditional RAG | GraphRAG |
|--------|-----------------|----------|
| **Search** | Keyword + Vector | Keyword + Vector + Graph |
| **Relationships** | Implicit (in text) | Explicit (in graph) |
| **Multi-hop** | Poor (need high context) | Excellent (natural traversal) |
| **Entity Linking** | Requires same naming | Unified nodes |
| **Query Time** | Fast (100-200ms) | Slower (300-500ms) |
| **Accuracy** | Good for simple queries | Better for complex queries |
| **Scalability** | Linear O(n) | Depends on graph density |

## Limitations & Considerations

### Current Limitations
1. **Entity Extraction Quality**: LLM quality varies; some entities missed
2. **Relationship Completeness**: Not all relationships captured from text
3. **Hallucination Risk**: LLM may invent relationships not in documents
4. **Performance**: Graph traversal slower than vector search
5. **Complexity**: More moving parts, harder to debug

### Mitigation Strategies
1. **Entity Validation**: Manually verify extracted entities
2. **Confidence Scoring**: Store confidence (0-1) for each relationship
3. **Source Attribution**: Always trace answer back to chunks
4. **Query Optimization**: Limit traversal depth to 2-3 hops
5. **Logging**: Comprehensive logging of extraction and traversal

## Performance Optimization

### Techniques
```python
# 1. Limit traversal depth
depth = min(user_depth, 3)  # Max 3 hops

# 2. Filter by relationship type
query += " WHERE rel.type IN $allowed_types"

# 3. Use indexes in Neo4j
CREATE INDEX entity_name ON Entity(name)
CREATE INDEX filter_label_idx ON Entity(filter_label)

# 4. Batch entity lookups
entities = extract_entities(query)
# Instead of querying each entity individually,
# query all in one Cypher statement

# 5. Cache common entity lookups
entity_cache = {}
if entity_name in entity_cache:
    use_cached_result()
```

### Performance Metrics
- Entity extraction: 200-500ms per query
- Graph traversal (1-hop): 100-150ms
- Graph traversal (2-hop): 200-300ms
- Chunk retrieval: 50-100ms per entity
- Total graph search: 300-500ms (vs 100-200ms for vector)

## Future Enhancements

1. **Bidirectional Traversal**: Expand in both directions from seed entity
2. **Subgraph Extraction**: Return connected component as explanation
3. **Entity Disambiguation**: Handle same names (e.g., "Smith" vs "John Smith")
4. **Relationship Extraction**: Learn relationship quality over time
5. **Query-Adaptive Depth**: Determine optimal traversal depth per query
6. **Semantic Graph Clustering**: Group similar entities automatically

## Implementation Notes

### Code Location
- **Graph Construction**: `src/pipeline/pipeline.py` step 4
- **Query Execution**: `src/retriever/graphrag_retriever.py` lines 600-800
- **Entity Extraction**: `src/prompts/xml/` entity_extraction_prompt.xml
- **RRF Fusion**: `src/retriever/graphrag_retriever.py` lines 1200-1300

### Configuration
```yaml
# config.yaml
graphrag:
  neo4j:
    uri: neo4j+s://neo4j.api.blaiq.ai:7689
    user: neo4j
    password: ${NEO4J_PASSWORD}

  entity_extraction:
    model: claude-sonnet-4-6
    timeout_seconds: 25
    confidence_threshold: 0.7

  graph_traversal:
    max_depth: 3
    max_entities_per_query: 10
    relationship_types:
      - WORKS_FOR
      - PARTNERSHIP
      - MENTIONS
      - IMPLEMENTS
```
