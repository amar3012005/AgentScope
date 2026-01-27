import os
import time
import json
import logging
import requests
import litellm
from qdrant_client import QdrantClient
from neo4j import GraphDatabase
from dotenv import load_dotenv

# Load env
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "bundb_app_blaiq_ai_knowledgeglobal_421765297988070tsxTz6itX0BGb9_nXy35B")
# User Query
QUERY = "Vielen Dank B&B Markenagentur"  # Snippet from your log

print("="*60)
print(f"🚀 FULL FLOW TEST: '{QUERY}'")
print("="*60)

# 1. STRATEGIC INTENT (LiteLLM)
print("\n🧠 STEP 1: STRATEGIC PLANNING")
try:
    plan_prompt = f"""
    Analyze this query: "{QUERY}"
    
    Determine:
    1. Is it local (specific fact) or global (summary)?
    2. What are the German entities?
    3. What is the intent?

    Output JSON like: {{"mode": "LOCAL_SEARCH", "entities": [...]}}
    """
    
    response = litellm.completion(
        model=os.getenv("LITELLM_PLANNER_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": plan_prompt}],
        api_base=os.getenv("OPENAI_API_BASE_URL"),
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0
    )
    intent = response.choices[0].message.content
    print(f"  ✅ Intent: {intent}")
except Exception as e:
    print(f"  ❌ Intent Failed: {e}")

# 2. EMBEDDINGS (BGE-M3 Direct)
print("\n🔢 STEP 2: GENERATING EMBEDDING")
try:
    embed_url = f"{os.getenv('BGE_M3_SERVICE_URL').rstrip('/')}/embeddings"
    api_key = os.getenv("BGE_M3_API_KEY")
    
    resp = requests.post(
        embed_url,
        json={"model": os.getenv("BGE_M3_MODEL_ID"), "input": [QUERY]},
        headers={"Authorization": f"Bearer {api_key}"},
        verify=False
    )
    if resp.status_code == 200:
        vector = resp.json()['data'][0]['embedding']
        print(f"  ✅ Generated Vector: {len(vector)} dimensions")
    else:
        print(f"  ❌ Embedding Failed: {resp.text}")
        vector = None
except Exception as e:
    print(f"  ❌ Embedding Error: {e}")
    vector = None

# 3. VECTOR SEARCH (Qdrant Direct)
print("\n🔎 STEP 3: VECTOR SEARCH (Qdrant)")
if vector:
    try:
        # Using Direct REST to bypass QdrantClient connection issues
        qdrant_url = os.getenv("QDRANT_URL")
        search_url = f"{qdrant_url}/collections/{COLLECTION_NAME}/points/search"
        qdrant_key = os.getenv("QDRANT_API_KEY")
        
        payload = {
            "vector": vector,
            "limit": 3,
            "with_payload": True
        }
        
        resp = requests.post(
            search_url,
            json=payload,
            headers={"api-key": qdrant_key},
            verify=False
        )
        
        if resp.status_code == 200:
            results = resp.json()['result']
            print(f"  ✅ Found {len(results)} chunks")
            for i, hit in enumerate(results):
                content = hit.get('payload', {}).get('page_content', 'No content')[:100]
                score = hit.get('score')
                print(f"     [{i+1}] Score: {score:.4f} | Content: {content}...")
        else:
            print(f"  ❌ Search Failed {resp.status_code}: {resp.text}")

    except Exception as e:
        print(f"  ❌ Search Error: {e}")

# 4. GRAPH SEARCH (Neo4j)
print("\n🕸️ STEP 4: GRAPH SEARCH (Neo4j)")
try:
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    pwd = os.getenv("NEO4J_PASSWORD")
    
    # Simple check query using filter_label
    cypher = f"""
    MATCH (c:Chunk)
    WHERE c.filter_label = '{COLLECTION_NAME}'
    RETURN count(c) as count
    """
    
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        # Verify Connectivity
        driver.verify_connectivity()
        print(f"  ✅ Neo4j Connected to {uri}")
        
        # Run Query
        with driver.session() as session:
            result = session.run(cypher).single()
            count = result['count']
            print(f"  ✅ Found {count} chunks in Graph with filter_label='{COLLECTION_NAME}'")

except Exception as e:
    print(f"  ❌ Graph Error: {e}")

print("\n" + "="*60)
