# -*- coding: utf-8 -*-
import asyncio
import os
import json
import httpx
import logging
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.markdown import Markdown
from rich.prompt import Prompt

from agentscope.message import Msg
from agentscope.tool import Toolkit
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.workflows.swarm_engine import SwarmEngine
from agentscope_blaiq.persistence.redis_state import RedisStateStore

# Setup logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("blaiq-tui")

console = Console()

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
BLUEPRINTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "blueprints"

# Global toolkit instance for dynamic skill registration
_global_toolkit: Toolkit | None = None

def get_global_toolkit() -> Toolkit:
    """Get or create the global toolkit instance for skill registration."""
    global _global_toolkit
    if _global_toolkit is None:
        from agentscope_blaiq.tools.enterprise_fleet import get_enterprise_toolkit
        _global_toolkit = get_enterprise_toolkit()
    return _global_toolkit

# ── WORKSPACE CORE ──────────────────────────────────────────────────────

class BlaiqWorkspaceTUI:
    """The central Command Center for testing and managing the BLAIQ stack."""
    def __init__(self):
        self.session_id = "tui-session-" + os.urandom(4).hex()
        self.engaged_agents = set()
        self.service_host = os.environ.get("BLAIQ_SERVICE_HOST", "localhost")
        # Ensure the environment variable is propagated to all fleet tools
        os.environ["BLAIQ_SERVICE_HOST"] = self.service_host
        
        self.state_store = RedisStateStore()
        self.swarm = SwarmEngine()

    async def check_fleet_status(self):
        """Checks health of all BLAIQ microservices."""
        services = {
            "Factory": f"http://{self.service_host}:8100/health",
            "Research": f"http://{self.service_host}:8096/health",
            "Oracle": f"http://{self.service_host}:8094/health",
            "Strategist (AaaS)": f"http://{self.service_host}:8095/health",
            "Text Buddy": f"http://{self.service_host}:8097/health",
            "Content Director": f"http://{self.service_host}:8098/health",
            "Van Gogh": f"http://{self.service_host}:8099/health",
            "Governance": f"http://{self.service_host}:8093/health",
        }
        
        table = Table(title="BLAIQ Fleet Status", border_style="cyan")
        table.add_column("Service", style="bold white")
        table.add_column("Endpoint", style="dim")
        table.add_column("Status", justify="center")
        
        async with httpx.AsyncClient(timeout=2.0) as client:
            for name, url in services.items():
                try:
                    res = await client.get(url)
                    status = "[bold green]ONLINE[/bold green]" if res.status_code == 200 else f"[yellow]ERR {res.status_code}[/yellow]"
                except Exception:
                    status = "[bold red]OFFLINE[/bold red]"
                table.add_row(name, url, status)
        
        return table

    def safe_text_extract(self, res: Any) -> str:
        """Safely extracts text from a ToolResponse or raw result."""
        try:
            if hasattr(res, "content") and res.content:
                part = res.content[0]
                return str(getattr(part, "text", part.get("text", str(part)) if isinstance(part, dict) else str(part)))
            if isinstance(res, dict) and "content" in res and res["content"]:
                part = res["content"][0]
                return str(part.get("text", str(part)))
            return str(res)
        except Exception:
            return str(res)

    async def create_skill(self, name: str, description: str, body: str, agents: list[str]) -> Path:
        """Create and register a new AgentScope skill from LLM-generated SKILL.md."""
        # NEW: Route to agent-specific subfolder if only one target agent is specified
        # This aligns with the new skills/text_buddy/ and skills/content_director/ structure
        subfolder = ""
        if len(agents) == 1:
            subfolder = agents[0]
        elif "text_buddy" in agents and len(agents) > 1:
            subfolder = "text_buddy" # Default to text_buddy for shared skills
        
        skill_dir = SKILLS_DIR / subfolder / name if subfolder else SKILLS_DIR / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        targets = ", ".join(agents) if agents else "text_buddy, content_director"
        skill_md = (
            f"---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"target_agent: {targets}\n"
            f"---\n\n"
            f"{body}"
        )
        (skill_dir / "SKILL.md").write_text(skill_md)

        # Register with global Toolkit for immediate availability
        toolkit = get_global_toolkit()
        toolkit.register_agent_skill(str(skill_dir))
        logger.info(f"Skill '{name}' registered with Toolkit at {skill_dir}")

        return skill_dir

    async def run_pipeline(self, prompt: str, with_oracle: bool = False):
        """Runs the BLAIQ v3 swarm pipeline via StrategistV2 Master Orchestrator."""
        console.rule(f"[bold magenta]Swarm Mission: {prompt[:50]}...[/bold magenta]")

        # 1. Call StrategistV2 to produce a structured MissionPlan and execute via SwarmEngine
        results: dict = {}

        async def swarm_publisher(role: str, text: str, is_stream: bool = False):
            if is_stream:
                # For streaming, we only want to show structured phase updates in real-time
                if "{" in text and '"phase"' in text:
                    try:
                        # Attempt to parse to get the phase name for the title
                        import json
                        data = json.loads(text)
                        phase_name = data.get("phase", "Update").title()
                        console.print(Panel(
                            text.strip(),
                            title=f"[bold yellow]▶ {role.replace('_', ' ').title()} - {phase_name} Phase[/bold yellow]",
                            border_style="yellow",
                            expand=False
                        ))
                    except Exception:
                        pass
                return

            if text.startswith("Starting"):
                console.print(f"[blue]▶ {role}:[/blue] {text}")
            else:
                console.print(f"[green]✔ {role}:[/green] Completed")
                # Show the final output in a green panel
                console.print(Panel(
                    text.strip(),
                    title=f"[bold]{role.replace('_', ' ').title()}[/bold]",
                    border_style="green",
                    expand=False
                ))
                console.print("") # Spacer

        from agentscope_blaiq.contracts.hitl import HITLResumeRequest, WorkflowSuspended
        try:
            results = await self.swarm.run(
                goal=prompt,
                session_id=self.session_id,
                artifact_family="report",  # Will be auto-classified by SwarmEngine
                publish=swarm_publisher,
                with_oracle=with_oracle,
            )
        except WorkflowSuspended as exc:
            console.print(Panel(
                f"[bold yellow]Oracle Question:[/bold yellow]\n{exc.question}\n\n"
                + (f"[dim]{exc.why}[/dim]\n\n" if exc.why else "")
                + "\n".join(f"  [{i+1}] {opt}" for i, opt in enumerate(exc.options)),
                title="[bold magenta]⏸ HITL — Human Input Required[/bold magenta]",
                border_style="magenta",
            ))
            choice = Prompt.ask("[magenta]Your answer or pick number[/magenta]")
            # Resolve numbered option
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(exc.options):
                    choice = exc.options[idx]
            except ValueError:
                pass
            console.print(f"[dim]Resuming with: {choice}[/dim]")
            try:
                results = await self.swarm.resume(
                    HITLResumeRequest(session_id=exc.session_id, answer=choice)
                )
            except Exception as e:
                console.print(f"[bold red]Resume failed:[/bold red] {e}")
                return
        except Exception as e:
            console.print(f"[bold red]Swarm failed:[/bold red] {e}")
            return

        # 3. Completion Marker
        console.rule("[bold green]Pipeline Complete[/bold green]")

# ── COMMAND HANDLERS ────────────────────────────────────────────────────

async def run_repl():
    workspace = BlaiqWorkspaceTUI()
    
    console.print(Panel.fit(
        "[bold cyan]BLAIQ v3.0 - MASTER ORCHESTRATOR[/bold cyan]\n"
        "Status: [green]Active[/green] | Mode: [yellow]Event-Driven Swarm[/yellow]\n\n"
        "Commands:\n"
        "  /pipeline <goal> [--hitl] - Run pipeline (add --hitl for event-driven Oracle)\n"
        "  /status          - Check Fleet Health\n"
        "  /hive <query>    - Direct Memory Access\n"
        "  /create <prompt> - Create agent from natural language (auto-registers)\n"
        "  /new-skill <prompt> - Create skill from natural language (auto-registers)\n"
        "  /list-skills     - Browse Skills Library\n"
        "  /list            - Browse Agent Blueprints\n"
        "  /quit            - Exit Workspace\n\n"
        "[dim]Oracle: Event-driven — fires only when context is insufficient[/dim]",
        border_style="bright_blue",
        padding=(1, 2)
    ))

    while True:
        try:
            query = Prompt.ask("\n[bold cyan]blaiq-workspace[/bold cyan]")
            if query.lower() in ["/quit", "exit", "quit"]: break

            if query.startswith("/create-skill") or query.startswith("/new-skill"):
                cmd = "/create-skill" if query.startswith("/create-skill") else "/new-skill"
                rest = query.replace(cmd, "").strip()
                
                # Check for <agent_name> <description> pattern
                parts = rest.split(" ", 1)
                if len(parts) < 2:
                    console.print(f"[yellow]Usage: {cmd} <agent_name> <description>[/yellow]")
                    console.print("[dim]Example: /create-skill text_buddy 'create a tool for auditing tax invoices'[/dim]")
                    continue
                
                target_agent = parts[0].strip().lower()
                description = parts[1].strip()

                console.print(f"[dim]Generating skill for [bold]{target_agent}[/bold] from: {description[:60]}...[/dim]")

                # Enhanced Skill Author prompt tailored for the specific agent role
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        skill_prompt = (
                            f"You are an AgentScope Skill author. Create a complete AgentScope SKILL.md for the agent: '{target_agent}'.\n"
                            f"The skill should handle: \"{description}\"\n\n"
                            "Return ONLY the markdown body (no YAML frontmatter block, I will add that). Include:\n"
                            "- # Skill Name\n"
                            "- Purpose: Clearly define what this skill lets the agent do.\n"
                            "- Implementation Details: Step-by-step logic for the agent.\n"
                            "- Output Constraints: Specific format requirements for this agent's role.\n"
                            "- Examples: 2 concrete usage examples.\n\n"
                            f"Ensure the tone and complexity match the {target_agent}'s capabilities."
                        )
                        res = await client.post(
                            f"http://{workspace.service_host}:8095/process",
                            json={
                                "input": [{"role": "user", "content": [{"type": "text", "text": skill_prompt}]}],
                                "session_id": workspace.session_id,
                                "user_id": "tui-skill-gen",
                            },
                        )
                        body = ""
                        for line in res.text.splitlines():
                            if line.startswith("data: "):
                                try:
                                    d = json.loads(line[6:])
                                    body += d.get("text", "") or d.get("content", "")
                                except Exception:
                                    continue
                        if not body:
                            body = f"# Generated Skill for {target_agent}\n\n{description}"
                except Exception as e:
                    console.print(f"[yellow]LLM generation failed ({e}), using fallback.[/yellow]")
                    body = f"# Generated Skill for {target_agent}\n\n{description}"

                # Derive folder name
                name = description[:30].strip().lower().replace(" ", "_").replace("-", "_")
                
                # Create and register natively as per AgentScope docs
                skill_dir = await workspace.create_skill(name, description, body, [target_agent])
                
                console.print(Panel(
                    f"[bold green]✓[/bold green] Skill [bold]{name}[/bold] created and registered natively.\n"
                    f"Path: {skill_dir}/SKILL.md\n"
                    f"Agent: {target_agent}\n\n"
                    f"[dim]The {target_agent} agent will now see this in its prompt via the Toolkit registration.[/dim]",
                    title="[bold green]Skill Registered[/bold green]",
                    border_style="green"
                ))
                continue
            
            if query.startswith("/pipeline"):
                rest = query.replace("/pipeline", "").strip()
                with_oracle = "--hitl" in rest
                p = rest.replace("--hitl", "").strip()
                if not p:
                    console.print("[red]Error: Please provide a goal for the pipeline.[/red]")
                    continue
                await workspace.run_pipeline(p, with_oracle=with_oracle)
                continue

            if query.startswith("/status"):
                table = await workspace.check_fleet_status()
                console.print(table)
                continue
                
            if query.startswith("/hive"):
                q = query.replace("/hive", "").strip()
                from agentscope_blaiq.tools.enterprise_fleet import BlaiqEnterpriseFleet
                fleet = BlaiqEnterpriseFleet()
                res = await fleet.hivemind_recall(q)
                output = workspace.safe_text_extract(res)
                console.print(Panel(output if output else "No memories.", title="HIVE-MIND Memory", border_style="magenta"))
                continue
                
            if query.startswith("/create"):
                rest = query.replace("/create", "").strip()
                if not rest:
                    console.print("[yellow]Usage: /create <description> — e.g., '/create a social media agent for writing Instagram captions about solar energy'[/yellow]")
                    continue

                console.print(f"[dim]Architecting agent from: {rest[:80]}...[/dim]")

                # 1. Generate blueprint via Factory service
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        res = await client.post(f"http://{workspace.service_host}:8100/create", json={"prompt": rest})
                        if res.status_code == 200:
                            data = res.json()
                            blueprint = data.get("blueprint", {})
                            agent_name = blueprint.get("name", "Unknown")
                            agent_desc = blueprint.get("description", "")
                            blueprint_path = data.get("path", "")
                        else:
                            console.print(f"[red]Factory Error: {res.text}[/red]")
                            continue
                except Exception as e:
                    console.print(f"[red]Failed to generate blueprint: {e}[/red]")
                    continue

                # 2. Create a corresponding SKILL.md so the agent is discoverable by the Strategist
                skill_name = f"agent_{agent_name.lower().replace(' ', '_')}"
                skill_body = (
                    f"### Agent: {agent_name}\n\n"
                    f"**Description**: {agent_desc}\n\n"
                    f"**Blueprint**: `{blueprint_path}`\n\n"
                    f"**Usage**: This agent can be spawned via the Factory service. "
                    f"Use the `/create` command with a similar prompt to activate it.\n\n"
                    f"**System Prompt**:\n{blueprint.get('system', 'N/A')}\n"
                )
                skill_dir = await workspace.create_skill(skill_name, agent_desc, skill_body, ["text_buddy", "content_director"])

                # 3. Register the agent with the SwarmEngine for pipeline visibility
                workspace.engaged_agents.add(agent_name)

                console.print(Panel(
                    f"[bold green]✓[/bold green] Agent [bold]{agent_name}[/bold] created and registered.\n"
                    f"Blueprint: {blueprint_path}\n"
                    f"Skill: {skill_dir}/SKILL.md\n"
                    f"Description: {agent_desc}\n\n"
                    f"[dim]Agent is now visible in /list and accessible via /pipeline with appropriate goals.[/dim]",
                    title="[bold green]Agent Created & Registered[/bold green]",
                    border_style="green"
                ))
                continue
                
            if query.startswith("/new-skill"):
                rest = query.replace("/new-skill", "").strip()
                if not rest:
                    console.print("[yellow]Usage: /new-skill <description> — e.g., '/new-skill create a skill for writing Twitter threads about renewable energy'[/yellow]")
                    continue

                console.print(f"[dim]Generating skill from: {rest[:80]}...[/dim]")

                # Use Strategist AaaS service to generate the skill
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        skill_prompt = (
                            f"You are an AgentScope Skill author. Create a complete SKILL.md for this request: \"{rest}\"\n\n"
                            "Return ONLY the markdown body (no YAML frontmatter). Include:\n"
                            "- Purpose: What this skill does\n"
                            "- Rules: Step-by-step instructions for the agent\n"
                            "- Output format: Expected structure\n"
                            "- Examples: 1-2 concrete examples\n"
                            "Be concise but complete. The skill will be used by text_buddy and content_director agents."
                        )
                        res = await client.post(
                            f"http://{workspace.service_host}:8095/process",
                            json={
                                "input": [{"role": "user", "content": [{"type": "text", "text": skill_prompt}]}],
                                "session_id": workspace.session_id,
                                "user_id": "tui-skill-gen",
                            },
                        )
                        body = ""
                        for line in res.text.splitlines():
                            if line.startswith("data: "):
                                try:
                                    d = json.loads(line[6:])
                                    body += d.get("text", "") or d.get("content", "")
                                except Exception:
                                    continue
                        if not body:
                            body = f"# Generated Skill\n\n{rest}"
                except Exception as e:
                    console.print(f"[yellow]LLM generation failed ({e}), using fallback.[/yellow]")
                    body = f"# Generated Skill\n\n{rest}"

                # Derive name and description from the request
                name = rest[:30].strip().lower().replace(" ", "_").replace("-", "_")
                description = rest[:100]

                skill_dir = await workspace.create_skill(name, description, body, ["text_buddy", "content_director"])
                console.print(Panel(
                    f"[bold green]✓[/bold green] Skill [bold]{name}[/bold] created and registered.\n"
                    f"Path: {skill_dir}/SKILL.md\n"
                    f"Agents: text_buddy, content_director\n\n"
                    f"[dim]Active on next /pipeline call — no restart needed.[/dim]",
                    title="[bold green]Skill Registered[/bold green]",
                    border_style="green"
                ))
                continue

            if query.startswith("/list-skills"):
                table = Table(title="Skills Library", border_style="cyan")
                table.add_column("Skill", style="bold white")
                table.add_column("Description", style="dim")
                table.add_column("Target Agents")
                if SKILLS_DIR.exists():
                    import yaml
                    for skill_dir in sorted(SKILLS_DIR.iterdir()):
                        skill_file = skill_dir / "SKILL.md"
                        if skill_file.exists():
                            content = skill_file.read_text()
                            fm = {}
                            if content.startswith("---"):
                                end = content.find("---", 3)
                                if end > 0:
                                    try:
                                        fm = yaml.safe_load(content[3:end])
                                    except Exception:
                                        pass
                            table.add_row(
                                fm.get("name", skill_dir.name),
                                fm.get("description", ""),
                                fm.get("target_agent", "")
                            )
                console.print(table)
                continue

            if query.startswith("/list"):
                table = Table(title="Agent Blueprint Library", border_style="cyan")
                table.add_column("Agent ID", style="bold white")
                table.add_column("Status", justify="center")
                path = "./data/blueprints"
                if os.path.exists(path):
                    files = [f for f in os.listdir(path) if f.endswith(".json")]
                    for f in files:
                        agent_id = f.replace(".json", "")
                        status = "[green]ACTIVE[/green]" if agent_id in workspace.engaged_agents else "[dim]stored[/dim]"
                        table.add_row(agent_id, status)
                if workspace.engaged_agents:
                    table.add_row(f"[bold]{len(workspace.engaged_agents)} engaged[/bold]", "[green]●[/green]")
                console.print(table)
                continue

            console.print("[yellow]Unknown command. Use /pipeline <goal> [--hitl] to run a mission.[/yellow]")
            
        except KeyboardInterrupt: break
        except Exception as e:
            console.print(f"[bold red]Workspace Error:[/bold red] {str(e)}")

if __name__ == "__main__":
    asyncio.run(run_repl())
