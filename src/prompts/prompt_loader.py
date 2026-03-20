import os
import re
from typing import List, Optional
from pathlib import Path


class PromptLoader:
    """Loads and manages XML-based prompts and skills."""

    def __init__(self, prompt_dir: str = None, skills_dir: str = None):
        if not prompt_dir:
            # Default to current dir's /xml folder
            base = os.path.dirname(os.path.abspath(__file__))
            prompt_dir = os.path.join(base, "xml")
        
        if not skills_dir:
            # Default to src/skills folder
            base = os.path.dirname(os.path.abspath(__file__))
            skills_dir = os.path.join(base, "..", "skills")
        
        self.prompt_dir = prompt_dir
        self.skills_dir = skills_dir
        self._cache = {}

    def get_prompt_content(self, prompt_name: str) -> str:
        """Reads the raw XML content of a prompt file."""
        if prompt_name in self._cache:
            return self._cache[prompt_name]

        path = os.path.join(self.prompt_dir, f"{prompt_name}.xml")
        if not os.path.exists(path):
            return ""

        with open(path, "r") as f:
            content = f.read()
            self._cache[prompt_name] = content
            return content

    def load_planner_prompt(self) -> str:
        """Returns the content for the Strategic Planner."""
        return self.get_prompt_content("planner_prompt")

    def load_entity_prompt(self) -> str:
        """Returns the content for Entity Extraction."""
        return self.get_prompt_content("entity_prompt")

    def load_response_generator(self) -> str:
        """Returns the content for the Final BLAIQ Persona."""
        return self.get_prompt_content("response_generator")

    def load_template(self, template_name: str) -> str:
        """Loads a specific formatting template from the templates/ directory."""
        path = os.path.join(self.prompt_dir, "templates", f"{template_name.lower()}_formatter.xml")
        if not os.path.exists(path):
            return ""

        with open(path, "r") as f:
            return f.read()

    # ========================================================================
    # SKILL LOADING METHODS
    # ========================================================================
    
    def get_skill_path(self, skill_name: str) -> str:
        """Get the full path to a skill XML file."""
        return os.path.join(self.skills_dir, f"{skill_name}.xml")
    
    def load_skill(self, skill_name: str) -> str:
        """
        Load a single skill XML file by name.
        
        Args:
            skill_name: Name of the skill file (without .xml extension)
                       e.g., "visual_director", "copywriter", "pitch_deck"
        
        Returns:
            Raw XML content as string, or empty string if not found
        """
        cache_key = f"skill:{skill_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        path = self.get_skill_path(skill_name)
        if not os.path.exists(path):
            return ""
        
        with open(path, "r") as f:
            content = f.read()
            self._cache[cache_key] = content
            return content
    
    def load_skill_stack(self, skill_names: List[str]) -> str:
        """
        Load and compose multiple skills into a single XML block.
        
        Args:
            skill_names: List of skill names to load and combine
                        e.g., ["visual_director", "copywriter", "ux_architect"]
        
        Returns:
            Combined XML content with all skills wrapped in a <skill_stack> tag
        """
        if not skill_names:
            return ""
        
        # Check cache for this specific stack
        stack_key = f"skill_stack:{':'.join(sorted(skill_names))}"
        if stack_key in self._cache:
            return self._cache[stack_key]
        
        loaded_skills = []
        for skill_name in skill_names:
            skill_content = self.load_skill(skill_name)
            if skill_content:
                loaded_skills.append(skill_content)
        
        if not loaded_skills:
            return ""
        
        # Wrap in a skill_stack container for clear boundaries
        combined = "\n\n".join(loaded_skills)
        skill_stack = f"""<skill_stack count="{len(loaded_skills)}">
<!-- Multi-skill composition: {', '.join(skill_names)} -->
{combined}
</skill_stack>"""
        
        self._cache[stack_key] = skill_stack
        return skill_stack
    
    def list_available_skills(self) -> List[str]:
        """
        List all available skill files in the skills directory.
        
        Returns:
            List of skill names (without .xml extension)
        """
        if not os.path.exists(self.skills_dir):
            return []
        
        skills = []
        for file in os.listdir(self.skills_dir):
            if file.endswith(".xml"):
                skills.append(file[:-4])  # Remove .xml extension
        
        return sorted(skills)
    
    def get_skill_metadata(self, skill_name: str) -> dict:
        """
        Extract metadata from a skill XML file.
        
        Args:
            skill_name: Name of the skill
        
        Returns:
            Dictionary with skill metadata (name, version, purpose)
        """
        skill_content = self.load_skill(skill_name)
        if not skill_content:
            return {}
        
        metadata = {}
        
        # Extract <skill> tag attributes
        skill_tag_match = re.search(r'<skill\s+([^>]+)>', skill_content)
        if skill_tag_match:
            attributes = skill_tag_match.group(1)
            
            # Extract name
            name_match = re.search(r'name="([^"]+)"', attributes)
            if name_match:
                metadata["name"] = name_match.group(1)
            
            # Extract version
            version_match = re.search(r'version="([^"]+)"', attributes)
            if version_match:
                metadata["version"] = version_match.group(1)
            
            # Extract purpose
            purpose_match = re.search(r'purpose="([^"]+)"', attributes)
            if purpose_match:
                metadata["purpose"] = purpose_match.group(1)
        
        # Extract <meta> section content
        meta_match = re.search(r'<meta>(.*?)</meta>', skill_content, re.DOTALL)
        if meta_match:
            meta_content = meta_match.group(1)
            
            # Extract role
            role_match = re.search(r'<role>(.*?)</role>', meta_content, re.DOTALL)
            if role_match:
                metadata["role"] = role_match.group(1).strip()
            
            # Extract goal
            goal_match = re.search(r'<goal>(.*?)</goal>', meta_content, re.DOTALL)
            if goal_match:
                metadata["goal"] = goal_match.group(1).strip()
        
        return metadata
    
    def detect_intent_and_load_skills(self, user_request: str) -> List[str]:
        """
        Detect user intent from their request and return relevant skill names.
        
        This uses simple keyword matching. For production, replace with LLM-based intent classification.
        
        Args:
            user_request: The user's task/request string
        
        Returns:
            List of relevant skill names to load
        """
        request_lower = user_request.lower()
        skills_to_load = []
        
        # Pitch Deck / Presentation detection
        if any(term in request_lower for term in ["pitch deck", "presentation", "investor", "slide", "deck"]):
            skills_to_load.extend(["visual_director", "pitch_deck", "copywriter"])
        
        # Landing Page / Website detection
        elif any(term in request_lower for term in ["landing page", "website", "web page", "homepage"]):
            skills_to_load.extend(["visual_director", "ux_architect", "copywriter"])
        
        # Dashboard / Data visualization detection
        elif any(term in request_lower for term in ["dashboard", "metrics", "kpi", "data viz", "chart", "graph"]):
            skills_to_load.extend(["visual_director", "data_viz", "ux_architect"])
        
        # Social Media / Content detection
        elif any(term in request_lower for term in ["linkedin", "twitter", "social", "post", "article", "blog"]):
            skills_to_load.extend(["copywriter", "visual_director"])
        
        # Documentation / Technical detection
        elif any(term in request_lower for term in ["documentation", "api", "technical", "spec", "architecture"]):
            skills_to_load.extend(["ux_architect", "copywriter"])
        
        # Default: Visual + Copy for general content
        else:
            skills_to_load.extend(["visual_director", "copywriter"])
        
        # Always include UX Architect for interactive content
        if "interactive" in request_lower or "ui" in request_lower or "ux" in request_lower:
            if "ux_architect" not in skills_to_load:
                skills_to_load.append("ux_architect")
        
        return list(set(skills_to_load))  # Remove duplicates
