"""Minimal Result type for expected failures.

Use for flow that is *expected* to fail (post not found, IG challenge
required) so callers handle it explicitly instead of catching exceptions.
Reserve real exceptions for the genuinely exceptional.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    POST_NOT_FOUND = "post_not_found"
    CHALLENGE_REQUIRED = "challenge_required"
    LOGIN_REQUIRED = "login_required"
    RATE_LIMITED = "rate_limited"
    SEND_BLOCKED = "send_blocked"  # IG action-block on DM sending — must stop
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

    @property
    def is_ok(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class Err:
    code: ErrorCode
    message: str = ""

    @property
    def is_ok(self) -> bool:
        return False


type Result[T] = Ok[T] | Err
