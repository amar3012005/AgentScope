from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_BASE_URL = os.environ.get("BLAIQ_BACKEND_URL", "http://127.0.0.1:8090").rstrip("/")
DEFAULT_TENANT_ID = os.environ.get("BLAIQ_TENANT_ID", "default")
CREATE_AGENT_ROLES = ("text_buddy", "content_director", "vangogh", "research", "governance", "strategist", "hitl")


def _strip_data_prefix(payload: str) -> str:
    value = payload.strip()
    while value.startswith("data:"):
        value = value[5:].lstrip()
    return value


def _extract_event_payload(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    payload = _strip_data_prefix(line)
    if not payload or payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _prompt(label: str, default: str | None = None, *, allow_empty: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if allow_empty:
            return ""


def _yes_no(label: str, *, default: bool = True) -> bool:
    default_label = "Y/n" if default else "y/N"
    raw = input(f"{label} [{default_label}]: ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def _comma_list(label: str, defaults: list[str]) -> list[str]:
    default_text = ", ".join(defaults)
    raw = _prompt(label, default_text, allow_empty=True)
    if not raw.strip():
        return list(defaults)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class StreamResult:
    thread_id: str | None = None
    blocked: bool = False
    blocked_questions: list[dict[str, Any]] | None = None


class BlaiqTUIClient:
    def __init__(self, base_url: str, tenant_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.client = httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0))
        self.last_thread_id: str | None = None

    def close(self) -> None:
        self.client.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def check_ready(self) -> dict[str, Any]:
        response = self.client.get(self._url("/readyz"))
        response.raise_for_status()
        return response.json()

    def list_live_agents(self) -> dict[str, Any]:
        response = self.client.get(self._url("/api/v1/agents/live"))
        response.raise_for_status()
        return response.json()

    def list_custom_agents(self) -> dict[str, Any]:
        response = self.client.get(self._url("/api/v1/agents/custom/list"))
        response.raise_for_status()
        return response.json()

    def contracts_snapshot(self) -> dict[str, Any]:
        response = self.client.get(self._url("/api/v1/contracts/snapshot"))
        response.raise_for_status()
        return response.json()

    def validate_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(self._url("/api/v1/contracts/validate"), json=spec)
        response.raise_for_status()
        return response.json()

    def register_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(self._url("/api/v1/agents/custom/register"), json=spec)
        response.raise_for_status()
        return response.json()

    def draft_agent(self, description: str) -> dict[str, Any]:
        response = self.client.post(
            self._url("/api/v1/agents/custom/draft"),
            json={"description": description},
        )
        response.raise_for_status()
        return response.json()

    def workflow_status(self, thread_id: str) -> dict[str, Any]:
        response = self.client.get(
            self._url(f"/api/v1/workflows/{thread_id}/status"),
            params={"tenant_id": self.tenant_id},
        )
        response.raise_for_status()
        return response.json()

    def _stream(self, path: str, body: dict[str, Any]) -> StreamResult:
        payload = {"tenant_id": self.tenant_id, **body}
        result = StreamResult()
        with self.client.stream(
            "POST",
            self._url(path),
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                event = _extract_event_payload(line)
                if event is None:
                    continue
                result.thread_id = event.get("thread_id") or result.thread_id
                self._render_event(event)
                if event.get("type") == "workflow_blocked":
                    result.blocked = True
                    result.blocked_questions = list(event.get("data", {}).get("questions") or [])
        if result.thread_id:
            self.last_thread_id = result.thread_id
        return result

    def submit(self, user_query: str, *, analysis_mode: str = "standard") -> StreamResult:
        return self._stream(
            "/api/v1/workflows/submit",
            {"user_query": user_query, "analysis_mode": analysis_mode},
        )

    def resume(self, thread_id: str, answers: dict[str, str]) -> StreamResult:
        return self._stream(
            "/api/v1/workflows/resume",
            {"thread_id": thread_id, "answers": answers},
        )

    @staticmethod
    def _render_event(event: dict[str, Any]) -> None:
        event_type = event.get("type", "event")
        agent = event.get("agent_name", "system")
        data = event.get("data") or {}

        if event_type == "agent_log":
            message = data.get("message") or ""
            if message:
                print(f"[{agent}] {message}")
            return
        if event_type == "workflow_blocked":
            print(f"[HITL] {data.get('prompt_headline') or 'Clarification needed'}")
            intro = data.get("prompt_intro")
            if intro:
                print(intro)
            for question in data.get("questions") or []:
                print(f" - {question.get('requirement_id')}: {question.get('question')}")
            return
        if event_type == "workflow_complete":
            print("[system] Workflow complete.")
            final_answer = data.get("final_answer")
            if final_answer:
                print(final_answer)
            return
        if event_type == "workflow_error":
            print(f"[error] {data.get('error_message') or 'Workflow error'}")
            return
        print(f"[{agent}] {event_type}")


def _base_spec_from_role(snapshot: dict[str, Any], role: str) -> dict[str, Any]:
    agents = snapshot.get("agents") or {}
    harness = agents.get(role)
    if not harness:
        raise ValueError(f"Role '{role}' is not available in the contract snapshot.")
    return {
        "role": role,
        "input_schema": harness.get("input_schema") or {"type": "object", "properties": {}},
        "output_schema": harness.get("output_schema") or {"type": "object", "properties": {}},
        "allowed_tools": list(harness.get("allowed_tools") or []),
        "allowed_workflows": list(harness.get("allowed_workflows") or []),
        "artifact_family": (harness.get("artifact_families") or [None])[0],
    }


def create_agent_wizard(client: BlaiqTUIClient, role: str | None = None) -> None:
    # Step 1: Get natural language description
    if role:
        description = role  # user typed @create_agent <description>
    else:
        description = _prompt("Describe what your agent should do")
    if not description.strip():
        print("No description provided. Aborting.")
        return

    # Step 2: LLM extracts spec from description
    print("\nAnalyzing your request...")
    try:
        draft_result = client.draft_agent(description)
    except Exception as exc:
        print(f"Failed to draft agent: {exc}")
        return

    if not draft_result.get("ok") or not draft_result.get("spec"):
        print(f"Could not extract agent spec: {draft_result.get('error', 'unknown error')}")
        return

    spec = draft_result["spec"]
    missing = draft_result.get("missing_info") or []

    # Step 3: Show what was extracted
    print(f"\n--- Extracted Agent Spec ---")
    print(f"  ID:          {spec.get('agent_id')}")
    print(f"  Name:        {spec.get('display_name')}")
    print(f"  Role:        {spec.get('role')}")
    print(f"  Model:       {spec.get('model_hint')}")
    print(f"  Tools:       {', '.join(spec.get('allowed_tools', []))}")
    print(f"  Workflows:   {', '.join(spec.get('allowed_workflows', []))}")
    print(f"  Tags:        {', '.join(spec.get('tags', []))}")
    prompt_preview = (spec.get("prompt") or "")[:120]
    print(f"  Prompt:      {prompt_preview}...")

    # Step 4: HITL — ask for missing info
    if missing:
        print(f"\nI need a few more details:")
        for item in missing:
            answer = _prompt(f"  {item}")
            if answer:
                # Append to prompt
                spec["prompt"] = spec.get("prompt", "") + f"\n{item}: {answer}"

    # Step 5: Let user tweak any field
    print()
    if _yes_no("Want to edit any field before registering?", default=False):
        spec["agent_id"] = _prompt("Agent ID", spec.get("agent_id", ""))
        spec["display_name"] = _prompt("Display name", spec.get("display_name", ""))
        spec["prompt"] = _prompt("System prompt", spec.get("prompt", ""))
        spec["model_hint"] = _prompt("Model hint", spec.get("model_hint", "sonnet"))

    # Step 6: Validate
    print("\nValidating...")
    # Ensure required fields for CustomAgentSpec
    spec.setdefault("max_iterations", 6)
    spec.setdefault("timeout_seconds", 120)
    spec.pop("missing_info", None)

    validation = client.validate_spec(spec)
    if not validation.get("ok"):
        print(f"\nValidation failed:")
        for err in validation.get("errors", []):
            print(f"  - {err}")

        if _yes_no("Try to fix and retry?", default=True):
            # Let user fix the issues
            for err in validation.get("errors", []):
                if "tool" in err.lower():
                    spec["allowed_tools"] = _comma_list("Allowed tools (comma-separated)", spec.get("allowed_tools", []))
                elif "workflow" in err.lower():
                    spec["allowed_workflows"] = _comma_list("Allowed workflows (comma-separated)", spec.get("allowed_workflows", []))
                elif "prompt" in err.lower():
                    spec["prompt"] = _prompt("System prompt (min 20 chars)", spec.get("prompt", ""))

            validation = client.validate_spec(spec)
            if not validation.get("ok"):
                print("Still invalid. Aborting.")
                print(json.dumps(validation, indent=2))
                return
        else:
            return

    print("Validation passed!")

    # Step 7: Register
    if not _yes_no("Register this agent?"):
        print("Cancelled.")
        return

    registered = client.register_spec(spec)
    print(json.dumps(registered, indent=2))


def _collect_hitl_answers(questions: list[dict[str, Any]]) -> dict[str, str]:
    answers: dict[str, str] = {}
    for question in questions:
        requirement_id = question.get("requirement_id") or question.get("id") or "answer"
        prompt = question.get("question") or requirement_id
        answers[requirement_id] = _prompt(prompt)
    return answers


def repl(client: BlaiqTUIClient) -> None:
    print(f"BLAIQ TUI connected to {client.base_url} (tenant={client.tenant_id})")
    print("Commands: /help, /agents, /custom, /status <thread_id>, /resume <thread_id>, @create_agent, /quit")

    while True:
        try:
            raw = input("blaiq> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        if raw in {"/quit", "/exit"}:
            break
        if raw == "/help":
            print("Plain text submits a workflow. Use @create_agent to launch the custom-agent wizard.")
            continue
        if raw == "/agents":
            print(json.dumps(client.list_live_agents(), indent=2))
            continue
        if raw == "/custom":
            print(json.dumps(client.list_custom_agents(), indent=2))
            continue
        if raw.startswith("/status "):
            _, thread_id = raw.split(maxsplit=1)
            print(json.dumps(client.workflow_status(thread_id), indent=2))
            continue
        if raw.startswith("/resume "):
            _, thread_id = raw.split(maxsplit=1)
            answers = {"resume": _prompt("Resume note", "Continue")}
            client.resume(thread_id, answers)
            continue
        if raw.startswith("@create_agent"):
            parts = raw.split(maxsplit=1)
            create_agent_wizard(client, parts[1].strip() if len(parts) > 1 else None)
            continue

        result = client.submit(raw)
        if result.blocked and result.thread_id and result.blocked_questions:
            answers = _collect_hitl_answers(result.blocked_questions)
            client.resume(result.thread_id, answers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Terminal UI for AgentScope-BLAIQ.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("repl")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("query")
    run_parser.add_argument("--analysis-mode", default="standard")

    ready_parser = subparsers.add_parser("ready")
    ready_parser.add_argument("--json", action="store_true")

    subparsers.add_parser("agents")
    subparsers.add_parser("custom")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("thread_id")

    create_parser = subparsers.add_parser("create-agent")
    create_parser.add_argument("--role", default="text_buddy")

    args = parser.parse_args(argv)
    command = args.command or "repl"
    client = BlaiqTUIClient(args.base_url, args.tenant_id)
    try:
        if command == "ready":
            payload = client.check_ready()
            print(json.dumps(payload, indent=2) if args.json else payload.get("status", "unknown"))
            return 0
        if command == "agents":
            print(json.dumps(client.list_live_agents(), indent=2))
            return 0
        if command == "custom":
            print(json.dumps(client.list_custom_agents(), indent=2))
            return 0
        if command == "status":
            print(json.dumps(client.workflow_status(args.thread_id), indent=2))
            return 0
        if command == "create-agent":
            create_agent_wizard(client, args.role)
            return 0
        if command == "run":
            result = client.submit(args.query, analysis_mode=args.analysis_mode)
            if result.blocked and result.thread_id and result.blocked_questions:
                answers = _collect_hitl_answers(result.blocked_questions)
                client.resume(result.thread_id, answers)
            return 0

        repl(client)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
