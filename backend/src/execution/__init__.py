"""Execution layer — guards, circuit breaker, PREPARE→CONFIRM→EXECUTE→AUDIT."""

from src.execution.circuit_breaker import CircuitOpenError, breaker
from src.execution.executor import ExecutionResult, PreparedAction, execute, prepare, reject
from src.execution.guards import (
    CredentialError,
    assert_no_credentials,
    scan_for_credentials,
    wrap_untrusted,
)

__all__ = [
    "CircuitOpenError",
    "CredentialError",
    "ExecutionResult",
    "PreparedAction",
    "assert_no_credentials",
    "breaker",
    "execute",
    "prepare",
    "reject",
    "scan_for_credentials",
    "wrap_untrusted",
]
