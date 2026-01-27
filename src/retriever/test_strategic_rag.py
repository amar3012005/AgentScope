
import os
import json
from dotenv import load_dotenv
from src.retriever.graphrag_retriever import GraphRAGRetriever

# Load environment
load_dotenv()

def test_strategy():
    # Initialize retriever in debug mode to see the "Brain" thinking
    retriever = GraphRAGRetriever(debug=True)
    
    test_queries = [
        {
            "label": "GREETING / SMALL TALK",
            "query": "Hallo! Wer bist du und wie kannst du mir helfen?"
        },
        {
            "label": "SPECIFIC LOCAL SEARCH",
            "query": "Welche konkreten Maßnahmen werden im Tourismuskonzept für 2024 erwähnt?"
        },
        {
            "label": "GLOBAL STRATEGIC SEARCH",
            "query": "Was sind die übergeordneten strategischen Ziele über alle Dokumente hinweg?"
        },
        {
            "label": "CROSS-LANGUAGE SEARCH (English -> German)",
            "query": "What are the key risks mentioned in the contracts?"
        }
    ]

    print("\n" + "="*60)
    print("🚀 STARTING STRATEGIC RAG TEST")
    print("="*60)

    for test in test_queries:
        print(f"\n[TEST: {test['label']}]")
        print(f"User Question: '{test['query']}'")
        
        # We only call the retrieval part to see the Planning results
        # In a real app, generate_answer would follow
        chunks, stats = retriever.graphrag_retrieval(test['query'])
        
        plan = stats.get('planning', {})
        print(f"\n🧠 RETRIEVAL PLAN:")
        print(f"  - Mode: {plan.get('mode')}")
        print(f"  - Reasoning: {plan.get('reasoning')}")
        print(f"  - Vector Search: {plan.get('search_plan', {}).get('use_vector')}")
        print(f"  - Graph Search: {plan.get('search_plan', {}).get('use_graph')}")
        print(f"  - German Entities: {plan.get('entities_german')}")
        
        if chunks and chunks[0].metadata.get('is_direct'):
            print(f"  ⚡ DIRECT REPLY: {chunks[0].page_content[:150]}...")
        else:
            print(f"  📦 CHUNKS FOUND: {len(chunks)}")
            
        print("-" * 60)

    retriever.close()

if __name__ == "__main__":
    test_strategy()
