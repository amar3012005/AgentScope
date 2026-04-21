"""Code executor — In-container Python code execution with safety guards.

Runs analysis code directly in the BLAIQ container with:
- Import validation (block network, system access)
- Timeout enforcement
- Output capture
- Error handling
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agentscope_blaiq.contracts.evidence import CodeExecutionResult

logger = logging.getLogger(__name__)

# Timeout for code execution
_DEFAULT_TIMEOUT = 60  # seconds

# Forbidden imports (security)
_FORBIDDEN_IMPORTS = frozenset([
    "requests", "urllib3", "httpx", "aiohttp",  # No HTTP
    "socket",  # No networking
    "pymongo", "psycopg2", "mysql", "sqlite3",  # No direct DB
    "subprocess",  # No subprocess
    "pickle", "marshal",  # No unsafe serialization
    "shutil",  # No file system ops
])

# Dangerous patterns
_DANGEROUS_PATTERNS = [
    "os.system", "os.popen", "os.exec", "os.spawn",
    "subprocess.", "__import__", "eval(", "exec(",
    "compile(", "open(\"/", "open('/", "open(\"~", "open('/~",
]


class CodeExecutor:
    """In-container Python code execution with safety guards.

    Usage:
        executor = CodeExecutor(timeout=60)
        result = await executor.execute(
            code="print('Hello')",
            datasets={"data.csv": {...}},
        )
    """

    def __init__(
        self,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize code executor.

        Args:
            timeout: Maximum execution time in seconds
        """
        self.timeout = timeout
        logger.info("CodeExecutor initialized (in-container mode)")

    async def execute(
        self,
        code: str,
        datasets: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> CodeExecutionResult:
        """Execute Python code with safety guards.

        Args:
            code: Python code to execute
            datasets: Optional dict of datasets (as DataFrames or dicts)
            timeout: Override default timeout

        Returns:
            CodeExecutionResult with outputs and artifacts
        """
        timeout = timeout or self.timeout
        execution_id = hashlib.md5(code.encode()).hexdigest()[:12]
        start_time = time.time()

        logger.info("Starting code execution: %s", execution_id)

        # Validate code security
        is_valid, error_msg = self.validate_code(code)
        if not is_valid:
            return CodeExecutionResult(
                execution_id=execution_id,
                code=code,
                exit_code=-1,
                stdout="",
                stderr=f"Security validation failed: {error_msg}",
                execution_time_ms=int((time.time() - start_time) * 1000),
                error_type="SecurityValidation",
            )

        # Capture stdout/stderr
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                self._execute_code(code, datasets, stdout_buffer, stderr_buffer),
                timeout=timeout,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            return CodeExecutionResult(
                execution_id=execution_id,
                code=code,
                exit_code=0,
                stdout=stdout_buffer.getvalue(),
                stderr=stderr_buffer.getvalue(),
                execution_time_ms=execution_time_ms,
                memory_usage_bytes=0,
                artifacts=[],
            )

        except asyncio.TimeoutError:
            logger.error("Execution timeout: %s", execution_id)
            return CodeExecutionResult(
                execution_id=execution_id,
                code=code,
                exit_code=-1,
                stdout=stdout_buffer.getvalue(),
                stderr=f"Execution timeout after {timeout}s",
                execution_time_ms=timeout * 1000,
                error_type="TimeoutError",
            )

        except Exception as exc:
            logger.error("Execution error: %s - %s", execution_id, exc)
            return CodeExecutionResult(
                execution_id=execution_id,
                code=code,
                exit_code=-1,
                stdout=stdout_buffer.getvalue(),
                stderr=f"{type(exc).__name__}: {exc}",
                execution_time_ms=int((time.time() - start_time) * 1000),
                error_type=type(exc).__name__,
            )

    async def _execute_code(
        self,
        code: str,
        datasets: dict[str, Any] | None,
        stdout_buffer: io.StringIO,
        stderr_buffer: io.StringIO,
    ) -> None:
        """Execute code with captured output."""
        # Save original stdout/stderr
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        try:
            # Redirect output
            sys.stdout = stdout_buffer
            sys.stderr = stderr_buffer

            # Build execution context with restricted builtins
            context = {
                "__name__": "__main__",
                "__doc__": None,
                "__builtins__": self._get_safe_builtins(),
                # Data science libraries
                "pd": None,
                "np": None,
                "plt": None,
                "px": None,
                "sns": None,
                # Utilities
                "json": json,
                "datasets": datasets or {},
            }

            # Try to import data science libraries
            try:
                import pandas as pd
                context["pd"] = pd
            except ImportError:
                pass

            try:
                import numpy as np
                context["np"] = np
            except ImportError:
                pass

            try:
                import matplotlib.pyplot as plt
                context["plt"] = plt
            except ImportError:
                pass

            try:
                import plotly.express as px
                context["px"] = px
            except ImportError:
                pass

            try:
                import seaborn as sns
                context["sns"] = sns
            except ImportError:
                pass

            # Execute user code
            exec(code, context)

        finally:
            # Restore original stdout/stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr

    def _get_safe_builtins(self) -> dict:
        """Get a restricted set of builtins."""
        safe_builtins = {}

        # Allow safe builtins
        allowed = [
            "abs", "all", "any", "bool", "bytes", "chr", "complex",
            "dict", "dir", "divmod", "enumerate", "filter", "float",
            "frozenset", "getattr", "hasattr", "hash", "hex", "id",
            "int", "isinstance", "issubclass", "iter", "len", "list",
            "map", "max", "min", "next", "object", "oct", "ord",
            "pow", "print", "range", "repr", "reversed", "round",
            "set", "slice", "sorted", "str", "sum", "super", "tuple",
            "type", "zip", "True", "False", "None",
        ]

        import builtins
        for name in allowed:
            if hasattr(builtins, name):
                safe_builtins[name] = getattr(builtins, name)

        return safe_builtins

    def validate_code(self, code: str) -> tuple[bool, str]:
        """Validate code for security before execution.

        Returns:
            (is_valid, error_message)
        """
        # Check for forbidden imports
        for forbidden in _FORBIDDEN_IMPORTS:
            if f"import {forbidden}" in code or f"from {forbidden}" in code:
                return False, f"Forbidden import detected: {forbidden}"

        # Check for dangerous patterns
        for pattern in _DANGEROUS_PATTERNS:
            if pattern in code:
                return False, f"Dangerous pattern detected: {pattern}"

        return True, ""
