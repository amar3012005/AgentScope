from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowSuspended(Exception):
    """Raised by SwarmEngine when oracle requires human input."""

    def __init__(self, session_id: str, question: str, options: list[str], why: str = "") -> None:
        self.session_id = session_id
        self.question = question
        self.options = options
        self.why = why
        super().__init__(f"HITL suspension [{session_id}]: {question[:80]}")


class SwarmSuspendedState(BaseModel):
    """State persisted to Redis when a swarm is suspended for HITL."""

    session_id: str
    goal: str
    artifact_family: str
    completed_results: dict[str, str] = Field(default_factory=dict)
    resume_from_role: str
    hitl_question: str
    hitl_options: list[str] = Field(default_factory=list)
    hitl_why: str = ""


class HITLResumeRequest(BaseModel):
    session_id: str
    answer: str
