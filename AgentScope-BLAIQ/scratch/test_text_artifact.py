# -*- coding: utf-8 -*-
import asyncio
import httpx
import json
import uuid

async def get_streamed_content(client, url, payload):
    content = ""
    print(f"\n--- Calling {url} (Target: {payload.get('target')}) ---")
    try:
        async with client.stream("POST", url, json=payload, timeout=300.0) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        text_part = ""
                        
                        # Handle different AgentScope message structures
                        content = data.get("content")
                        if isinstance(content, str):
                            text_part = content
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict):
                                    if part.get("type") == "text":
                                        text_part += part.get("text", "")
                                    elif part.get("type") == "data":
                                        # Tool call or data artifact
                                        call_data = part.get("data", {})
                                        if "name" in call_data:
                                            text_part += f"\n[TOOL CALL] {call_data['name']}({call_data.get('arguments', '')})"
                        
                        if text_part:
                            print(text_part, end="", flush=True)
                        
                        # Handle direct text field
                        if "text" in data and data["text"]:
                            print(data["text"], end="", flush=True)
                        
                        # Handle Artifacts in metadata
                        if "metadata" in data and data["metadata"].get("kind") == "artifact":
                            detail = data["metadata"].get("detail", {})
                            print(f"\n[INTERNAL] Artifact found in stream.")
                    except Exception:
                        continue
    except Exception as e:
        print(f"\n[ERROR] Request failed: {e}")
    return content

async def test_text_artifact_real():
    session_id = f"real-text-{uuid.uuid4().hex[:6]}"
    print(f"Starting REAL Text Artifact Test for Session: {session_id}")
    
    def build_payload(msgs, session_id, target):
        # The correct AaaS input format for AgentRequest
        return {
            "input": msgs,
            "session_id": session_id,
            "user_id": "tester",
            "target": target
        }

    async with httpx.AsyncClient(timeout=300.0) as client:
        
        # --- STAGE 1: STRATEGIST ---
        print("\n[STRATEGIST] Planning...")
        msgs = [{"name": "user", "content": [{"type": "text", "text": "Write a LinkedIn post about Solvis GmbH efficiency. Use research-first."}], "role": "user"}]
        await get_streamed_content(client, "http://localhost:8095/process", build_payload(msgs, session_id, "StrategistV2"))

        # --- STAGE 2: RESEARCH ---
        print("\n\n[RESEARCH] Gathering facts...")
        msgs = [{"role": "system", "content": [{"type": "text", "text": "Research Solvis GmbH solar efficiency improvements"}]}]
        evidence = await get_streamed_content(client, "http://localhost:8096/process", build_payload(msgs, session_id, "DeepResearchV2"))
        print(f"\nEvidence Collected: {len(evidence)} chars.")

        # --- STAGE 4: SYNTHESIS ---
        print("\n[TEXT BUDDY] Synthesizing final artifact...")
        msgs = [{
            "role": "user", 
            "content": [{"type": "text", "text": "Generate the post. Stress sustainability and efficiency."}],
            "metadata": {"evidence_brief": evidence, "artifact_type": "linkedin_post"}
        }]
        final_artifact = await get_streamed_content(client, "http://localhost:8097/process", build_payload(msgs, session_id, "TextBuddyV2"))

        print("\n" + "="*50)
        print("FINAL LINKEDIN POST ARTIFACT:")
        print("="*50)
        print(final_artifact)
        print("="*50)

if __name__ == "__main__":
    asyncio.run(test_text_artifact_real())
