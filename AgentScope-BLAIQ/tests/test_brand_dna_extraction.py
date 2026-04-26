import pytest
import asyncio
import json
from uuid import uuid4
from unittest.mock import AsyncMock, patch, ANY
from agentscope_blaiq.persistence.models import UploadRecord
from agentscope_blaiq.persistence.repositories import BrandDnaRepository, UploadRepository
from agentscope_blaiq.app.brand_dna_service import BrandDnaExtractionService
from agentscope_blaiq.runtime.config import settings

@pytest.mark.asyncio
async def test_brand_dna_extraction_flow_mocked():
    # Setup mocks
    session = AsyncMock()
    repo = BrandDnaRepository(session)
    upload_repo = UploadRepository(session)
    
    tenant_id = "test-tenant"
    job_id = str(uuid4())
    upload_id = str(uuid4())
    
    # Mock upload record
    upload = UploadRecord(
        upload_id=upload_id,
        tenant_id=tenant_id,
        filename="brand_guide.png",
        storage_path="/tmp/brand_guide.png",
        content_type="image/png"
    )

    upload_repo.get_by_upload_id = AsyncMock(return_value=upload)
    repo.update_job = AsyncMock()

    service = BrandDnaExtractionService(tenant_id, repo, upload_repo)
    
    # Mock litellm.acompletion
    mock_visual_response = AsyncMock()
    mock_visual_response.choices = [AsyncMock()]
    mock_visual_response.choices[0].message.content = json.dumps({
        "artifact_summary": {
            "artifact_type": "image",
            "likely_purpose": "brand asset",
            "analysis_scope": "single image",
            "page_roles": ["cover"],
            "confidence": 0.9,
            "evidence_summary": "High-contrast brand image."
        },
        "brand_core": {
            "tone_axes": {
                "formal_informal": 0.4,
                "minimal_expressive": 0.8,
                "premium_accessible": 0.5,
                "corporate_editorial": 0.7,
                "technical_human": 0.5,
                "playful_serious": 0.6
            },
            "brand_keywords": ["bold", "geometric"],
            "core_identity_traits": ["high contrast"],
            "contextual_or_campaign_traits": ["poster layout"],
            "uncertain_traits": [],
            "confidence": 0.87,
            "evidence_summary": "Dominant bold geometric language."
        },
        "visual_system": {
            "palette": {
                "primary": ["#000000"],
                "secondary": ["#FFFFFF"],
                "neutrals": [],
                "accent": ["#FF0000"],
                "usage_rules": ["Use high contrast pairings"],
                "confidence": 0.92,
                "evidence_summary": "Black and white with red accent."
            },
            "typography": {
                "font_candidates": [{"name": "Arial", "role": "display"}],
                "hierarchy_rules": ["Oversized display headline"],
                "style_rules": ["Use bold headings"],
                "fallback_descriptors": ["neo-grotesk sans"],
                "confidence": 0.65,
                "evidence_summary": "Likely sans display type."
            },
            "composition": {
                "layout_archetype": "poster",
                "grid_style": "modular",
                "alignment_bias": "edge-anchored",
                "density": "sparse",
                "negative_space_strategy": "large negative space",
                "focal_element_strategy": "single anchor",
                "scale_behavior": "oversized focal form",
                "confidence": 0.88,
                "evidence_summary": "Single dominant object with negative space."
            },
            "shape_language": {
                "geometry": ["orthogonal"],
                "corner_style": "hard",
                "stroke_style": "solid",
                "motifs": ["oversized numeral"],
                "confidence": 0.83,
                "evidence_summary": "Geometric poster motif."
            }
        },
        "artifact_patterns": [],
        "design_recipes": {
            "hero": ["Use one dominant focal form"],
            "social": ["Keep copy minimal"],
            "presentation_cover": [],
            "landing_page": [],
            "marketing_banner": [],
            "confidence": 0.79,
            "evidence_summary": "Reusable poster logic."
        },
        "guardrails": {
            "must_preserve": ["high contrast"],
            "should_prefer": ["geometric restraint"],
            "use_sparingly": ["rotated text"],
            "avoid": ["soft gradients"],
            "forbidden_patterns": ["generic pastel UI"],
            "confidence": 0.85,
            "evidence_summary": "Preserve contrast and hierarchy."
        },
        "provenance": {
            "source_pages_or_regions": ["center glyph"],
            "notes": []
        }
    })
    
    # Use path for file read mock
    with patch("pathlib.Path.stat") as mock_stat, \
         patch("builtins.open", patch("io.BytesIO", return_value=b"fake-image-content")), \
         patch("agentscope_blaiq.app.brand_dna_service.litellm.acompletion") as mock_completion, \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.write_text"), \
         patch("agentscope_blaiq.app.brand_dna_service.BrandDnaExtractionService._encode_image", return_value="base64str"):
        
        mock_stat.return_value.st_size = 1000
        mock_completion.side_effect = [mock_visual_response]
        settings.openai_api_key = "test-key"
        settings.openai_api_base_url = "https://example.com/v1"
        
        # Run service
        await service.run_extraction(job_id, [upload_id])
        
        repo.update_job.assert_any_call(job_id, intermediate_json=ANY, result_json=ANY, progress=55)
        repo.update_job.assert_any_call(job_id, status="succeeded", progress=100, result_json=ANY)

        final_call = repo.update_job.await_args_list[-1]
        final_payload = json.loads(final_call.kwargs["result_json"])
        assert final_payload["schema_version"] == "brand-dna/v2"
        assert final_payload["compiled"]["theme"] == "bold"
        assert final_payload["layers"]["normalized"]["keywords"] == ["bold", "geometric"]
        assert "modular" in final_payload["layers"]["designer_handoff"]["hard_constraints"]["composition_rules"]
        assert final_payload["tokens"]["primary"] == "#000000"
        assert "# DESIGN.md for bold" in final_payload["design_readme"]
        assert "## VLM Extraction Instructions" in final_payload["design_readme"]
        
        print("Integration flow verified (mocked LLM)")

if __name__ == "__main__":
    asyncio.run(test_brand_dna_extraction_flow_mocked())
