"""
Per-presentation context for usage tracking.

`generate_presentation_handler` sets `presentation_id` (and the requester
`user_id`) on these ContextVars at the start of a generation; every
downstream LLM / image / audio call site reads them when recording usage.

ContextVars are propagated automatically across `await` boundaries inside
the same async task, so individual function signatures stay unchanged.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional


_PRESENTATION_ID: ContextVar[Optional[str]] = ContextVar(
    "presentation_id", default=None
)
_USER_ID: ContextVar[Optional[str]] = ContextVar("user_id", default=None)


def get_presentation_id() -> Optional[str]:
    return _PRESENTATION_ID.get()


def get_user_id() -> Optional[str]:
    return _USER_ID.get()


@contextmanager
def presentation_context(
    presentation_id: Optional[str],
    user_id: Optional[str],
) -> Iterator[None]:
    """
    Bind presentation_id / user_id for the duration of the `with` block.
    Restores the previous values on exit so nested or back-to-back
    generations in the same worker don't bleed into each other.
    """
    pid_token = _PRESENTATION_ID.set(presentation_id)
    uid_token = _USER_ID.set(user_id)
    try:
        yield
    finally:
        _PRESENTATION_ID.reset(pid_token)
        _USER_ID.reset(uid_token)
