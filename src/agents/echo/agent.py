import asyncio
import json
import os
import socket
import logging
from contextlib import suppress
from typing import Any, Dict

import websockets
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from utils.logging_utils import configure_service_logging, log_flow

class ExecuteRequest(BaseModel):
    task: str
    payload: Dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="BLAIQ Echo Microagent", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WS_TASK: asyncio.Task | None = None


def _agent_name() -> str:
    return os.getenv("AGENT_NAME", "echo-agent")


configure_service_logging(_agent_name())
logger = logging.getLogger("blaiq-echo-agent")


def _core_ws_url() -> str:
    return os.getenv("AGENT_CORE_WS_URL", "ws://blaiq-core:6000/ws/agents/echo-agent")


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": _agent_name(),
        "status": "healthy",
        "mode": "rest+ws-worker",
        "host": socket.gethostname(),
    }


@app.post("/execute")
async def execute(req: ExecuteRequest) -> Dict[str, Any]:
    return {
        "agent": _agent_name(),
        "received_task": req.task,
        "payload": req.payload,
        "result": f"Echo from {_agent_name()} for task '{req.task}'",
    }


async def ws_worker() -> None:
    reconnect_delay = 2
    while True:
        url = _core_ws_url()
        try:
            log_flow(logger, "ws_connect_attempt", url=url)
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                log_flow(logger, "ws_connected", url=url)
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    if msg.get("type") != "task":
                        continue

                    request_id = msg.get("request_id")
                    task = msg.get("task")
                    payload = msg.get("payload") or {}

                    response = {
                        "type": "result",
                        "request_id": request_id,
                        "status": "ok",
                        "data": {
                            "agent": _agent_name(),
                            "received_task": task,
                            "payload": payload,
                            "result": f"WS echo completed for '{task}'",
                        },
                    }
                    await ws.send(json.dumps(response))
        except Exception as exc:
            log_flow(logger, "ws_connect_error", level="warning", url=url, error=str(exc)[:300])
            await asyncio.sleep(reconnect_delay)


@app.on_event("startup")
async def startup_event() -> None:
    global WS_TASK
    log_flow(logger, "service_start", agent=_agent_name(), ws_enabled=os.getenv("AGENT_ENABLE_WS", "true"))
    if os.getenv("AGENT_ENABLE_WS", "true").lower() == "true":
        WS_TASK = asyncio.create_task(ws_worker())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global WS_TASK
    log_flow(logger, "service_shutdown", agent=_agent_name())
    if WS_TASK:
        WS_TASK.cancel()
        with suppress(asyncio.CancelledError):
            await WS_TASK
