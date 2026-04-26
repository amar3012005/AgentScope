"""
Contract enforcement mode for the runtime.

Controls whether contract violations log warnings (advisory) or raise
exceptions (enforced). Default: advisory for dev, enforced for CI/prod.

Usage::

    from agentscope_blaiq.contracts.enforcement import (
        EnforcementMode, get_enforcement_mode, set_enforcement_mode,
        enforcement_check,
    )

    set_enforcement_mode(EnforcementMode.ENFORCED)
    enforcement_check(ok=False, errors=["schema mismatch"], context="dispatch")
    # → raises ContractViolationError in enforced mode
    # → logs warning in advisory mode
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentscope_blaiq.contracts.dispatch import DispatchResult

logger = logging.getLogger("agentscope_blaiq.contracts.enforcement")


# ============================================================================
# Enum
# ============================================================================


class EnforcementMode(str, Enum):
    """Controls how contract violations are surfaced."""

    ADVISORY = "advisory"
    ENFORCED = "enforced"


# ============================================================================
# Exception
# ============================================================================


class ContractViolationError(Exception):
    """Raised in enforced mode when a contract check fails.

    Attributes:
        errors: List of individual violation descriptions.
        context: Human-readable label for where the violation occurred.
    """

    def __init__(self, errors: list[str], context: str) -> None:
        self.errors = errors
        self.context = context
        detail = "; ".join(errors)
        super().__init__(f"Contract violation [{context}]: {detail}")


# ============================================================================
# Module-level state
# ============================================================================

_current_mode: EnforcementMode = EnforcementMode.ADVISORY


def get_enforcement_mode() -> EnforcementMode:
    """Return the current enforcement mode."""
    return _current_mode


def set_enforcement_mode(mode: EnforcementMode) -> None:
    """Set the enforcement mode globally.

    Args:
        mode: The desired enforcement mode.
    """
    global _current_mode  # noqa: PLW0603 — module-level singleton by design
    _current_mode = mode
    logger.info("contract enforcement mode set to %s", mode.value)


def set_enforcement_from_settings() -> None:
    """Read from runtime config and set. Call at startup."""
    try:
        from agentscope_blaiq.runtime.config import settings

        mode = EnforcementMode(settings.contract_enforcement)
        set_enforcement_mode(mode)
    except Exception:  # noqa: BLE001 — keep default advisory on any failure
        pass


# ============================================================================
# Check functions
# ============================================================================


def enforcement_check(
    ok: bool,
    errors: list[str],
    *,
    context: str,
    warnings: list[str] | None = None,
) -> None:
    """Evaluate a contract check result under the current enforcement mode.

    In **ENFORCED** mode: if *ok* is ``False``, raises
    :class:`ContractViolationError` with the errors and context.

    In **ADVISORY** mode: if *ok* is ``False``, logs a warning; if
    *warnings* are present, logs them at info level.

    Always a no-op when *ok* is ``True`` and there are no warnings.

    Args:
        ok: Whether the contract check passed.
        errors: List of error descriptions (empty when ok is True).
        context: Human-readable label for where the check occurred
            (e.g. ``"dispatch agent=research workflow=wf-123"``).
        warnings: Optional list of non-fatal warning descriptions.
    """
    if ok and not warnings:
        return

    if not ok:
        if _current_mode is EnforcementMode.ENFORCED:
            raise ContractViolationError(errors=errors, context=context)
        logger.warning(
            "contract_violation [%s] errors=%s",
            context,
            errors,
        )

    if warnings:
        logger.info(
            "contract_warnings [%s] warnings=%s",
            context,
            warnings,
        )


def enforcement_guard(result: DispatchResult, *, context: str) -> None:
    """Convenience wrapper that calls :func:`enforcement_check` from a DispatchResult.

    Args:
        result: A :class:`~agentscope_blaiq.contracts.dispatch.DispatchResult`.
        context: Human-readable label for the check location.
    """
    enforcement_check(
        ok=result.ok,
        errors=result.errors,
        context=context,
        warnings=result.warnings,
    )
