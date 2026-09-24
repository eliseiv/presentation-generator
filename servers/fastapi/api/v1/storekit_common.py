"""Shared helpers for the claude-ios StoreKit routes."""

from typing import Optional

from fastapi import HTTPException


def resolve_storekit_user_id(
    x_user_id: Optional[str],
    body_user_id: Optional[str],
) -> str:
    header = (x_user_id or "").strip()
    body = (body_user_id or "").strip()
    if header and body and header != body:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "user_mismatch",
                "message": "userId must match X-User-Id.",
            },
        )
    user_id = header or body
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "missing_user",
                "message": "X-User-Id header or userId is required.",
            },
        )
    return user_id
