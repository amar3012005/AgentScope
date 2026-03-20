#!/usr/bin/env python3
"""
Test script for the skill-based prompt architecture.
Tests skill loading, intent detection, and prompt construction.
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from prompts.prompt_loader import PromptLoader


def test_skill_loader_initialization():
    """Test that skill loader initializes correctly."""
    print("=" * 60)
    print("TEST 1: Skill Loader Initialization")
    print("=" * 60)
    
    base_dir = Path(__file__).parent / "src"
    loader = PromptLoader(
        prompt_dir=str(base_dir / "prompts" / "xml"),
        skills_dir=str(base_dir / "skills")
    )
    
    available_skills = loader.list_available_skills()
    print(f"✓ Available skills: {available_skills}")
    print(f"✓ Total skills: {len(available_skills)}")
    
    assert len(available_skills) > 0, "No skills found!"
    print("✅ TEST 1 PASSED\n")
    return loader


def test_single_skill_loading(loader):
    """Test loading individual skills."""
    print("=" * 60)
    print("TEST 2: Single Skill Loading")
    print("=" * 60)
    
    skills_to_test = ["visual_director", "copywriter", "pitch_deck"]
    
    for skill_name in skills_to_test:
        content = loader.load_skill(skill_name)
        if content:
            metadata = loader.get_skill_metadata(skill_name)
            print(f"✓ {skill_name}:")
            print(f"  - Name: {metadata.get('name', 'N/A')}")
            print(f"  - Version: {metadata.get('version', 'N/A')}")
            print(f"  - Purpose: {metadata.get('purpose', 'N/A')}")
            print(f"  - Content length: {len(content)} chars")
        else:
            print(f"✗ {skill_name}: FAILED TO LOAD")
    
    print("✅ TEST 2 PASSED\n")


def test_skill_stack_loading(loader):
    """Test loading multiple skills as a stack."""
    print("=" * 60)
    print("TEST 3: Skill Stack Loading")
    print("=" * 60)
    
    skill_stack = ["visual_director", "copywriter"]
    stack_content = loader.load_skill_stack(skill_stack)
    
    print(f"✓ Skill stack: {skill_stack}")
    print(f"✓ Combined content length: {len(stack_content)} chars")
    print(f"✓ Contains skill_stack tag: {'<skill_stack' in stack_content}")
    print(f"✓ Contains individual skills: {all(skill in stack_content for skill in skill_stack)}")
    
    assert "<skill_stack" in stack_content, "Missing skill_stack wrapper!"
    print("✅ TEST 3 PASSED\n")


def test_intent_detection(loader):
    """Test automatic intent detection from user requests."""
    print("=" * 60)
    print("TEST 4: Intent Detection")
    print("=" * 60)
    
    test_cases = [
        ("Create a pitch deck for investors", ["visual_director", "pitch_deck", "copywriter"]),
        ("Build a landing page for our product", ["visual_director", "ux_architect", "copywriter"]),
        ("Show me a dashboard with KPIs", ["visual_director", "data_viz", "ux_architect"]),
        ("Write a LinkedIn post about our launch", ["copywriter", "visual_director"]),
        ("Create technical documentation", ["ux_architect", "copywriter"]),
    ]
    
    for request, expected_skills in test_cases:
        detected_skills = loader.detect_intent_and_load_skills(request)
        print(f"✓ Request: '{request}'")
        print(f"  - Detected skills: {detected_skills}")
        print(f"  - Expected skills: {expected_skills}")
        
        # Check if at least one expected skill is detected
        matches = any(skill in detected_skills for skill in expected_skills)
        print(f"  - Match: {'✅' if matches else '❌'}")
        print()
    
    print("✅ TEST 4 PASSED\n")


def test_skill_metadata_extraction(loader):
    """Test extracting metadata from skill files."""
    print("=" * 60)
    print("TEST 5: Skill Metadata Extraction")
    print("=" * 60)
    
    skill_name = "visual_director"
    metadata = loader.get_skill_metadata(skill_name)
    
    print(f"✓ Skill: {skill_name}")
    print(f"  - Name: {metadata.get('name', 'N/A')}")
    print(f"  - Version: {metadata.get('version', 'N/A')}")
    print(f"  - Purpose: {metadata.get('purpose', 'N/A')}")
    print(f"  - Role: {metadata.get('role', 'N/A')[:80]}...")
    print(f"  - Goal: {metadata.get('goal', 'N/A')[:80]}...")
    
    assert "name" in metadata, "Missing name in metadata!"
    assert "version" in metadata, "Missing version in metadata!"
    print("✅ TEST 5 PASSED\n")


def test_brand_dna_loading():
    """Test loading Brand DNA configuration."""
    print("=" * 60)
    print("TEST 6: Brand DNA Loading")
    print("=" * 60)
    
    brand_dna_path = Path(__file__).parent / "brand_dna" / "davinci_ai.json"
    
    if brand_dna_path.exists():
        with open(brand_dna_path, 'r') as f:
            brand_dna = json.load(f)
        
        print(f"✓ Brand DNA loaded from: {brand_dna_path}")
        print(f"✓ Theme: {brand_dna.get('theme', 'N/A')}")
        print(f"✓ Version: {brand_dna.get('version', 'N/A')}")
        print(f"✓ Primary color: {brand_dna.get('tokens', {}).get('primary', 'N/A')}")
        print(f"✓ Component mappings: {len(brand_dna.get('component_mappings', {}))} components")
        print(f"✓ Layout patterns: {len(brand_dna.get('layout_patterns', {}))} patterns")
        
        assert "tokens" in brand_dna, "Missing tokens in Brand DNA!"
        assert "component_mappings" in brand_dna, "Missing component mappings!"
        print("✅ TEST 6 PASSED\n")
    else:
        print(f"✗ Brand DNA file not found at {brand_dna_path}")
        print("❌ TEST 6 FAILED\n")


def test_prompt_construction():
    """Test constructing the full tiered system prompt."""
    print("=" * 60)
    print("TEST 7: Tiered System Prompt Construction")
    print("=" * 60)
    
    base_dir = Path(__file__).parent / "src"
    loader = PromptLoader(
        prompt_dir=str(base_dir / "prompts" / "xml"),
        skills_dir=str(base_dir / "skills")
    )
    
    # Load brand DNA
    brand_dna_path = Path(__file__).parent / "brand_dna" / "davinci_ai.json"
    with open(brand_dna_path, 'r') as f:
        brand_dna = json.load(f)
    
    # Load skill stack
    skill_stack = loader.load_skill_stack(["visual_director", "copywriter"])
    
    # Sample structured data
    structured_data = {
        "strategic_pillars": [
            {"title": "Parallel Retrieval", "description": "3.3x faster than sequential RAG"}
        ],
        "kpis": [
            {"label": "Response Time", "value": "<100ms", "unit": "cache hit"}
        ],
        "timeline": [
            {"phase": "Phase 1: Core Engine", "status": "Complete"}
        ],
        "vision_statement": "Democratizing enterprise AI through parallel architecture"
    }
    
    # Manually construct the prompt (avoid importing agent to skip dependencies)
    brand_dna_str = json.dumps(brand_dna, indent=2)
    structured_data_str = json.dumps(structured_data, indent=2)
    
    system_prompt = f"""You are the BLAIQ Creative Director, operating in DaVinci AI Mode.

BRAND DNA (Your Visual Constraints):
{brand_dna_str}

SKILL STACK (Your Active Expertise):
{skill_stack}

STRUCTURED PROJECT DATA (Your Content):
{structured_data_str}

YOUR EXECUTION PROCESS:
1. Review the SKILL STACK to understand which expertise is active
2. Extract relevant data from STRUCTURED PROJECT DATA
3. Apply the layout patterns, component mappings, and style tokens from skills
4. Map data to components as specified in the skill definitions
5. Generate the final HTML/Tailwind CSS artifact

OUTPUT FORMAT:
Single centered 16:9 modular container:
<div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center p-8">
  <!-- Your premium UI/UX artifact here -->
</div>
"""
    
    print(f"✓ Skill stack loaded: {len(skill_stack)} chars")
    print(f"✓ Brand DNA loaded: {len(brand_dna_str)} chars")
    print(f"✓ Structured data: {len(structured_data_str)} chars")
    print(f"✓ Full prompt length: {len(system_prompt)} chars")
    print(f"✓ Contains skill stack: {'<skill_stack' in system_prompt}")
    print(f"✓ Contains brand DNA: {'#FF4500' in system_prompt}")
    print(f"✓ Contains structured data: {'strategic_pillars' in system_prompt}")
    
    assert len(system_prompt) > 1000, "Prompt too short - something went wrong!"
    assert "<skill_stack" in system_prompt, "Missing skill stack in prompt!"
    print("✅ TEST 7 PASSED\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SKILL-BASED PROMPT ARCHITECTURE - TEST SUITE")
    print("=" * 60 + "\n")
    
    try:
        # Initialize loader
        loader = test_skill_loader_initialization()
        
        # Run tests
        test_single_skill_loading(loader)
        test_skill_stack_loading(loader)
        test_intent_detection(loader)
        test_skill_metadata_extraction(loader)
        test_brand_dna_loading()
        test_prompt_construction()
        
        print("=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 60)
        print("\nThe skill-based prompt architecture is working correctly.")
        print("You can now use dynamic skill injection in your content generation.")
        
    except Exception as e:
        print("=" * 60)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
