"""Privacy-safe, session-correlated progress telemetry for the existing MCP flow.

The local web client reads these JSON records from the existing AgentCore log group.
No prompt, tool arguments, medical record, or model reasoning is emitted.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
from time import perf_counter
from typing import Any, Iterator


_session: ContextVar[str | None] = ContextVar("carecircle_progress_session", default=None)
_logger = logging.getLogger("carecircle")


@contextmanager
def progress_session(session_id: str | None) -> Iterator[None]:
    token = _session.set(session_id)
    try:
        yield
    finally:
        _session.reset(token)


def emit(component: str, operation: str, status: str, *, provider: str | None = None,
         latency_ms: float | None = None, message: str | None = None,
         kind: str | None = None) -> None:
    session_id = _session.get()
    if not session_id:
        return
    record: dict[str, Any] = {
        "event": "carecircle_progress", "session_id": session_id,
        "component": component, "operation": operation, "status": status,
    }
    if provider:
        record["provider"] = provider
    if kind:
        record["kind"] = kind
    if latency_ms is not None:
        record["latency_ms"] = round(latency_ms, 2)
    if message:
        record["message"] = message
    _logger.info(json.dumps(record))


def elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 2)
