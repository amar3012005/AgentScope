# -*- coding: utf-8 -*-
import asyncio
import os
import json
import httpx
import logging
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
from agentscope_blaiq.runtime.agent_base import BaseAgent
from agentscope_blaiq.agents.strategic.agent import StrategicAgent
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.workflows.swarm_engine import SwarmEngine
from agentscope_blaiq.persistence.redis_state import RedisStateStore

# Setup logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("blaiq-tui")

console = Console()

SKILLS_DIR = Path(__file__).resolve().parent / "skills"

# ── WORKSPACE CORE ──────────────────────────────────────────────────────

class BlaiqWorkspaceTUI:
    """The central Command Center for testing and managing the BLAIQ stack."""
    def __init__(self):
        self.strategist = StrategicAgent(
            name="Strategist",
            role="strategic",
            sys_prompt="You are the BLAIQ Strategist. Orchestrate missions using the specialist fleet."
        )
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
            "Factory": f"http://{self.service_host}:8100/api/v1/health",
            "Research": f"http://{self.service_host}:8091/api/v1/health",
            "Oracle": f"http://{self.service_host}:8092/api/v1/health",
            "Strategist (AaaS)": f"http://{self.service_host}:8095/api/v1/health",
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
        """Create a new AgentScope skill from LLM-generated SKILL.md."""
        skill_dir = SKILLS_DIR / name
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
        return skill_dir

    async def run_pipeline(self, prompt: str, with_oracle: bool = False):
        """Runs the BLAIQ v3 swarm pipeline via MsgHub + ServiceProxyAgents."""
        console.rule(f"[bold magenta]Swarm Mission: {prompt[:50]}...[/bold magenta]")

        # 1. Classify artifact_family with a cheap LLM call
        artifact_family = "report"
        with Progress(SpinnerColumn(), TextColumn("[cyan]Classifying mission..."), console=console) as prog:
            task = prog.add_task("Classify", total=1)
            try:
                classifier_prompt = (
                    f"### CLASSIFICATION TASK\n"
                    f"User Goal: \"{prompt}\"\n\n"
                    "Classify this goal into exactly ONE of the following families. "
                    "## TASK:\n"
                    "Identify the artifact family for this mission. Output ONLY the keyword.\n\n"
                    "## CRITICAL RULES:\n"
                    "1. If the user mentions 'poster', 'pitch deck', 'presentation', 'landing page', or 'brochure', you MUST choose a VISUAL keyword.\n"
                    "2. Do NOT choose 'report' if the user asks for a visual or creative asset.\n"
                    "3. Choose 'report' only for data-heavy, text-only summaries or financial analysis.\n\n"
                    "KEYWORDS: pitch_deck, keynote, poster, brochure, one_pager, landing_page, "
                    "report, finance_analysis, custom, email, invoice, letter, memo, "
                    "proposal, social_post, summary"
                )
                async with httpx.AsyncClient(timeout=30.0) as client:
                    host = os.environ.get("BLAIQ_SERVICE_HOST", "localhost")
                    res = await client.post(
                        f"http://{host}:8095/process",
                        json={
                            "input": [{"role": "user", "content": [{"type": "text", "text": classifier_prompt}]}],
                            "session_id": self.session_id,
                            "user_id": "tui-classifier",
                        },
                    )
                    raw_text = ""
                    for line in res.text.splitlines():
                        if line.startswith("data: "):
                            try:
                                d = json.loads(line[6:])
                                raw_text += d.get("text", "") or d.get("content", "")
                            except Exception:
                                continue
                    
                    # Robust Parsing: Search the whole response for any valid keyword
                    valid = {
                        "pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page",
                        "report", "finance_analysis", "custom", "email", "invoice", "letter",
                        "memo", "proposal", "social_post", "summary",
                    }
                    cleaned_raw = raw_text.lower()
                    for word in valid:
                        if word in cleaned_raw or word.replace("_", " ") in cleaned_raw:
                            artifact_family = word
                            break
            except Exception:
                pass
            prog.update(task, completed=1)

        console.print(f"[dim]Artifact family: [bold]{artifact_family}[/bold][/dim]")

        # 2. Run swarm — proxies call AaaS containers, MsgHub broadcasts context
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
                artifact_family=artifact_family,
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

    async def run_mission(self, user_input: str):
        """Executes an autonomous mission."""
        console.rule(f"[bold cyan]Mission: {user_input[:50]}...[/bold cyan]")
        with Live(Panel("Strategist is reasoning...", title="Orchestration Flow", border_style="yellow"), refresh_per_second=4) as live:
            response = await self.strategist.reply(Msg(name="User", content=user_input, role="user"))
            live.update(Panel(Markdown(response.content), title="[bold green]Final Synthesis[/bold green]", border_style="green"))

# ── COMMAND HANDLERS ────────────────────────────────────────────────────

async def run_repl():
    workspace = BlaiqWorkspaceTUI()
    
    console.print(Panel.fit(
        "[bold cyan]BLAIQ v2.2 - PIPELINE COMMAND CENTER[/bold cyan]\n"
        "Status: [green]Active[/green] | Mode: [yellow]Sequential & Strategic[/yellow]\n\n"
        "Commands:\n"
        "  /pipeline <goal> [--hitl] - Run pipeline (add --hitl for event-driven Oracle)\n"
        "  /status          - Check Fleet Health\n"
        "  /hive <query>    - Direct Memory Access\n"
        "  /create <prompt> - Birth a new Specialist\n"
        "  /new-skill [name] - Register a new AgentScope Skill\n"
        "  /list-skills     - Browse Skills Library\n"
        "  /list            - Browse Blueprint Library\n"
        "  /quit            - Exit Workspace\n\n"
        "[dim]Oracle: Event-driven — fires only when context is insufficient[/dim]",
        border_style="bright_blue",
        padding=(1, 2)
    ))

    while True:
        try:
            query = Prompt.ask("\n[bold cyan]blaiq-workspace[/bold cyan]")
            if query.lower() in ["/quit", "exit", "quit"]: break
            
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
                prompt = query.replace("/create", "").strip()
                async with httpx.AsyncClient(timeout=60.0) as client:
                    res = await client.post(f"http://{workspace.service_host}:8100/create", json={"prompt": prompt})
                    if res.status_code == 200:
                        data = res.json()
                        console.print(Panel(f"Agent [bold]{data['blueprint']['name']}[/bold] saved.", title="Factory Success", border_style="green"))
                    else:
                        console.print(f"[red]Factory Error: {res.text}[/red]")
                continue
                
            if query.startswith("/new-skill"):
                args = query.replace("/new-skill", "").strip().split()
                name = args[0] if args else Prompt.ask("[cyan]Skill name[/cyan] (e.g. 'linkedin_post')")
                name = name.strip().lower().replace(" ", "_").replace("-", "_")
                agents_input = Prompt.ask(
                    "[cyan]Target agents[/cyan] (comma-separated, or Enter for all)",
                    default="text_buddy,content_director"
                )
                agents = [a.strip() for a in agents_input.split(",") if a.strip()]
                description = Prompt.ask("[cyan]Short description[/cyan]")
                console.print("[dim]Generating skill content via LLM...[/dim]")
                try:
                    from litellm import acompletion
                    gen_resp = await acompletion(
                        model=os.environ.get("LITELLM_API_BASE_URL") and os.environ.get("LITELLM_PRE_MODEL") or "gemini/gemini-2.5-flash",
                        messages=[
                            {"role": "system", "content": (
                                "You are an AgentScope Skill author. Write the BODY of a SKILL.md file. "
                                "Do NOT include YAML frontmatter — only the markdown body. "
                                "Include: purpose, rules, output format, examples. Be concise but complete."
                            )},
                            {"role": "user", "content": (
                                f"Skill name: {name}\n"
                                f"Description: {description}\n"
                                f"Target agents: {', '.join(agents)}\n\n"
                                "Write the skill body markdown now."
                            )},
                        ],
                        max_tokens=1500,
                        timeout=30,
                    )
                    body = gen_resp.choices[0].message.content or ""
                except Exception as e:
                    console.print(f"[yellow]LLM generation failed ({e}), using description as body.[/yellow]")
                    body = f"# {name.replace('_', ' ').title()}\n\n{description}\n"

                skill_dir = await workspace.create_skill(name, description, body, agents)
                console.print(Panel(
                    f"[bold green]✓[/bold green] Skill [bold]{name}[/bold] created.\n"
                    f"Path: {skill_dir}/SKILL.md\n"
                    f"Agents: {', '.join(agents)}\n\n"
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
                path = "./data/blueprints"
                files = [f for f in os.listdir(path) if f.endswith(".json")]
                table = Table(title="Blueprint Library")
                table.add_column("Agent ID")
                for f in files: table.add_row(f.replace(".json", ""))
                console.print(table)
                continue

            await workspace.run_mission(query)
            
        except KeyboardInterrupt: break
        except Exception as e:
            console.print(f"[bold red]Workspace Error:[/bold red] {str(e)}")

if __name__ == "__main__":
    asyncio.run(run_repl())
