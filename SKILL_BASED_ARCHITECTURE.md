# 🎨 God-Level UI/UX Skill-Based Prompt Architecture

## Overview

This architecture transforms BLAIQ content generation from "AI-generated text" to **premium DaVinci AI artifacts** through modular, XML-defined skill injection.

By separating expertise (skills) from prompts (tasks), we enable Claude 4.5 Sonnet to focus on execution without getting lost in monolithic instruction walls.

---

## 🏗 Architecture

### Tiered Prompt Structure

```
┌─────────────────────────────────────────────────────────────┐
│  TIER 1: PERSONA                                            │
│  Strategic Creative Director (Base identity, interview)     │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 2: SKILLS (XML Injection)                             │
│  visual_director, copywriter, ux_architect, data_viz, etc. │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 3: CONTEXT                                            │
│  GraphRAG Intelligence (project data, metrics, phases)      │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 4: CONSTRAINTS                                        │
│  Brand DNA (davinci_ai.json tokens, colors, typography)     │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  OUTPUT: Premium React/Tailwind UI                          │
│  Bento Grids, Glassmorphism, Cyber-Technical Aesthetic      │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 File Structure

```
src/
├── skills/                          # XML Skill definitions
│   ├── visual_director.xml          # Layout, composition, visual hierarchy
│   ├── copywriter.xml               # Voice, tone, messaging frameworks
│   ├── ux_architect.xml             # Interaction patterns, UX flows
│   ├── data_viz.xml                 # Charts, graphs, data representation
│   └── pitch_deck.xml               # Slide composition, narrative flow
│
├── prompts/
│   └── prompt_loader.py             # Skill loading logic
│
└── agents/
    └── content_creator/
        └── agent.py                 # Refactored with skill injection

brand_dna/
└── davinci_ai.json                  # Brand constraints + component mappings
```

---

## 🎯 Skills System

### What Are Skills?

Skills are XML files that define specialized expertise for the AI. Each skill contains:

- **Instructions**: Core directives and priorities
- **Patterns**: Reusable UI/layout patterns
- **Component Mappings**: How to map data → UI components
- **Style Tokens**: Tailwind classes for that domain
- **Quality Checklist**: Validation criteria

### Available Skills

| Skill | Purpose | Key Features |
|-------|---------|--------------|
| `visual_director` | Premium visual composition | Bento grids, glassmorphism, typography hierarchy |
| `copywriter` | Brand voice & messaging | DaVinci AI voice, messaging frameworks, copy patterns |
| `ux_architect` | Interaction design | Hover states, animations, accessibility, responsive |
| `data_viz` | Data visualization | Charts, graphs, stat cards, animations |
| `pitch_deck` | Investor presentations | Slide templates, narrative frameworks, investor psychology |

### Example: visual_director.xml

```xml
<skill name="Visual-Director" version="1.0" purpose="Premium UI/UX visual composition">
  <meta>
    <role>You are the Visual Director - a master of digital composition.</role>
    <goal>Transform structured data into breathtaking visual artifacts.</goal>
  </meta>

  <instructions>
    <rule priority="1">Every output must feel like a premium masterpiece.</rule>
    <rule priority="2">Think in 2D planes: Treat the screen as a canvas.</rule>
    <rule priority="3">Apply Bento Grid philosophy.</rule>
    <rule priority="4">Glassmorphism is mandatory.</rule>
  </instructions>

  <layout_patterns>
    <pattern name="Bento-Grid">
      <structure>grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6</structure>
      <card_base>p-6 rounded-xl border border-white/10 bg-white/5 backdrop-blur-md</card_base>
    </pattern>
  </layout_patterns>

  <component_mappings>
    <component name="PhaseCard">
      <structure>p-6 rounded-xl border border-white/10 bg-white/5 backdrop-blur-md</structure>
      <content>
        - Phase title (text-lg font-bold)
        - Status indicator (colored dot)
        - Description (text-white/70)
      </content>
    </component>
  </component_mappings>
</skill>
```

---

## 🔧 How It Works

### 1. Intent Detection

When a user requests content, the system detects the intent and loads relevant skills:

```python
# User request
request = "Create a pitch deck for investors"

# Intent detection
skills = loader.detect_intent_and_load_skills(request)
# Returns: ["visual_director", "pitch_deck", "copywriter"]
```

### 2. Skill Stack Loading

Multiple skills are composed into a single XML stack:

```python
skill_stack_xml = loader.load_skill_stack(["visual_director", "pitch_deck"])
```

### 3. Tiered Prompt Construction

The system prompt is built with all 4 tiers:

```python
from agents.content_creator.agent import build_tiered_system_prompt

system_prompt = build_tiered_system_prompt(
    skill_stack_xml=skill_stack_xml,
    structured_data=project_data,
    brand_dna=brand_dna
)
```

### 4. Content Generation

The LLM receives the complete prompt and generates premium UI:

```python
html_artifact = await generate_design(
    structured_data=data,
    user_request=request,
    skill_names=["visual_director", "pitch_deck"]
)
```

---

## 🎨 Brand DNA

The `davinci_ai.json` file defines visual constraints:

```json
{
  "theme": "Dark Mode / Cyber-Technical",
  "tokens": {
    "primary": "#FF4500",
    "background": "#0a0a0a",
    "surface": "#0d0d0d"
  },
  "typography": {
    "headings": "Bebas Neue, sans-serif",
    "body": "Space Grotesk, monospace"
  },
  "component_mappings": {
    "PhaseCard": { ... },
    "InsightCard": { ... },
    "StatBox": { ... }
  }
}
```

---

## 📝 Usage Examples

### Example 1: Pitch Deck Generation

```python
# Request
task = "Create a pitch deck for our Series A"

# Auto-detected skills
skills = ["visual_director", "pitch_deck", "copywriter"]

# Output
- Slide 1: Hero statement with vision
- Slide 2: Problem slide with pain points
- Slide 3: Solution slide with value prop
- Slide 4: Market size (TAM/SAM/SOM)
- Slide 5: Product roadmap
- Slide 6: Traction metrics
- Slide 7: Team
- Slide 8: Ask
```

### Example 2: Dashboard Creation

```python
# Request
task = "Show me a dashboard with our KPIs"

# Auto-detected skills
skills = ["visual_director", "data_viz", "ux_architect"]

# Output
- Bento grid layout
- StatBox components for each KPI
- Interactive hover states
- Responsive design
- Chart visualizations
```

### Example 3: Explicit Skill Override

```python
# Manually specify skills
payload = {
    "task": "Create content",
    "skills": ["copywriter", "visual_director"]  # Explicit override
}
```

---

## 🧪 Testing

Run the test suite:

```bash
python test_skill_architecture.py
```

Tests cover:
1. ✅ Skill loader initialization
2. ✅ Single skill loading
3. ✅ Skill stack composition
4. ✅ Intent detection
5. ✅ Metadata extraction
6. ✅ Brand DNA loading
7. ✅ Full prompt construction

---

## 🎯 Intent Detection Mapping

| User Request Keywords | Detected Skills |
|----------------------|-----------------|
| "pitch deck", "investor", "slide" | visual_director, pitch_deck, copywriter |
| "landing page", "website" | visual_director, ux_architect, copywriter |
| "dashboard", "KPI", "metrics" | visual_director, data_viz, ux_architect |
| "LinkedIn", "social", "post" | copywriter, visual_director |
| "documentation", "API", "technical" | ux_architect, copywriter |

---

## 🚀 Benefits

### Before (Monolithic Prompts)

```
❌ Wall of text instructions
❌ Mixed persona + context + constraints
❌ No reusability
❌ Hard to update
❌ Generic AI output
```

### After (Skill-Based Architecture)

```
✅ Modular XML skills
✅ Clean tiered separation
✅ Reusable expertise
✅ Easy to add new skills
✅ Premium DaVinci AI artifacts
```

---

## 📚 Adding New Skills

1. Create new XML file in `src/skills/`:

```xml
<skill name="Your-Skill" version="1.0" purpose="What it does">
  <meta>
    <role>Your role definition</role>
    <goal>Your goal</goal>
  </meta>
  
  <instructions>
    <rule priority="1">Your core rules</rule>
  </instructions>
  
  <layout_patterns>
    <pattern name="Your-Pattern">
      <structure>Tailwind classes</structure>
    </pattern>
  </layout_patterns>
  
  <component_mappings>
    <component name="YourComponent">
      <structure>HTML structure</structure>
    </component>
  </component_mappings>
</skill>
```

2. Update intent detection in `prompt_loader.py`:

```python
def detect_intent_and_load_skills(self, user_request: str) -> List[str]:
    if "your-keyword" in request_lower:
        skills_to_load.append("your_skill")
```

3. Test with the test suite

---

## 🎨 Quality Standards

Every skill must ensure:

- ✅ **Premium Feel**: Output feels bespoke, not generic AI
- ✅ **Glassmorphism**: Consistent use of `backdrop-blur-md bg-white/5`
- ✅ **Typography**: Strict hierarchy with `tracking-tighter`
- ✅ **Borders**: 1px technical borders for cyber-aesthetic
- ✅ **Whitespace**: Ample padding/margins signaling luxury
- ✅ **Color Strategy**: Primary `#FF4500` for emphasis
- ✅ **Responsive**: Mobile-first with `md:` and `lg:` breakpoints
- ✅ **Accessibility**: WCAG 2.1 AA compliance

---

## 🔮 Future Enhancements

- [ ] LLM-based intent classification (vs. keyword matching)
- [ ] Skill versioning and rollback
- [ ] A/B testing for skill combinations
- [ ] Skill marketplace (community-contributed skills)
- [ ] Visual skill editor UI
- [ ] Skill dependency graphs
- [ ] Performance benchmarking per skill

---

## 📖 Related Documentation

- `ARCHITECTURE.md` - GraphRAG system architecture
- `API_ENDPOINTS.md` - API reference
- `brand_dna/davinci_ai.json` - Brand constraints
- `src/skills/*.xml` - Individual skill definitions

---

**Built with ❤️ for DaVinci AI-quality content generation**
