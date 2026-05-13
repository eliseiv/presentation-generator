"""
Billing primitives — wallet, ledger, and Adapty subscription state.

All mutating helpers either accept an existing AsyncSession (so they can
be composed with other DB work in one transaction) or open a fresh one
via `async_session_maker`.

The wallet is single-currency (one integer column on `users`). Every
mutation is paired with an append-only TokenLedgerEntry so we can audit
"how much did user X spend on presentation Y" and so we can dedupe
inbound Adapty webhooks by event_id.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, update

from models.sql.token_ledger import TokenLedgerEntry
from models.sql.user import UserModel
from services.database import async_session_maker
from utils.datetime_utils import get_current_utc_datetime
from utils.get_env import (
    get_subscription_tokens_grant_env,
    get_token_cost_per_generation_env,
)

logger = logging.getLogger(__name__)


def get_token_cost_per_generation() -> int:
    raw = (get_token_cost_per_generation_env() or "1").strip()
    try:
        cost = int(raw)
    except ValueError:
        cost = 1
    return max(cost, 0)


def get_subscription_tokens_grant() -> int:
    raw = (get_subscription_tokens_grant_env() or "100").strip()
    try:
        grant = int(raw)
    except ValueError:
        grant = 100
    return max(grant, 0)


def compute_generation_cost(request: Any) -> int:
    """
    v1 pricing — flat per-generation. The function takes the request so
    callers can swap in shape-aware pricing later without touching the
    debit call sites.
    """
    return get_token_cost_per_generation()


async def get_or_create_user(session: AsyncSession, user_id: str) -> UserModel:
    user_id = (user_id or "").strip()
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="X-User-Id header is required.",
        )

    user = await session.get(UserModel, user_id)
    if user is not None:
        return user

    user = UserModel(id=user_id)
    session.add(user)
    session.add(
        TokenLedgerEntry(
            user_id=user_id,
            delta=0,
            balance_after=0,
            reason=TokenLedgerEntry.REASON_SIGNUP,
        )
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        # Another concurrent request may have just inserted the same user;
        # fetch fresh and continue.
        user = await session.get(UserModel, user_id)
        if user is None:
            raise
        return user

    await session.refresh(user)
    return user


async def _record_ledger(
    session: AsyncSession,
    *,
    user_id: str,
    delta: int,
    balance_after: int,
    reason: str,
    reference_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> TokenLedgerEntry:
    entry = TokenLedgerEntry(
        user_id=user_id,
        delta=delta,
        balance_after=balance_after,
        reason=reason,
        reference_id=reference_id,
        entry_metadata=metadata,
    )
    session.add(entry)
    return entry


async def debit_for_generation(
    session: AsyncSession,
    *,
    user_id: str,
    presentation_id: str,
    cost: int,
    metadata: Optional[dict] = None,
) -> int:
    """
    Atomically subtract `cost` from the user's balance. Raises 402 if the
    balance is insufficient, 400 if the user is unknown (the caller is
    expected to call `get_or_create_user` first), and returns the new
    balance on success.
    """
    if cost <= 0:
        # Nothing to debit — still log a zero-delta row so audits are
        # straightforward when pricing changes.
        user = await session.get(UserModel, user_id)
        if user is None:
            raise HTTPException(status_code=400, detail="Unknown user.")
        await _record_ledger(
            session,
            user_id=user_id,
            delta=0,
            balance_after=user.tokens,
            reason=TokenLedgerEntry.REASON_GENERATION_DEBIT,
            reference_id=presentation_id,
            metadata=metadata,
        )
        await session.commit()
        return user.tokens

    # Conditional update — only succeeds if the user still has enough.
    result = await session.execute(
        update(UserModel)
        .where(UserModel.id == user_id)
        .where(UserModel.tokens >= cost)
        .values(tokens=UserModel.tokens - cost, updated_at=get_current_utc_datetime())
    )
    if (result.rowcount or 0) == 0:
        # Either the user is missing or the balance is too low.
        user = await session.get(UserModel, user_id)
        balance = user.tokens if user is not None else 0
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_tokens",
                "balance": balance,
                "required": cost,
            },
        )

    refreshed = await session.get(UserModel, user_id)
    if refreshed is None:
        # Practically unreachable — the UPDATE just hit this row.
        raise HTTPException(status_code=500, detail="User vanished during debit.")
    await _record_ledger(
        session,
        user_id=user_id,
        delta=-cost,
        balance_after=refreshed.tokens,
        reason=TokenLedgerEntry.REASON_GENERATION_DEBIT,
        reference_id=presentation_id,
        metadata=metadata,
    )
    await session.commit()
    return refreshed.tokens


async def refund_generation(
    *,
    user_id: str,
    presentation_id: str,
    reason_note: Optional[str] = None,
) -> None:
    """
    Reverse a previous `debit_for_generation`. Opens its own session so it
    can be called from error-handling paths where the original session is
    already rolled back. Idempotent: if a refund row for this presentation
    already exists, do nothing.
    """
    async with async_session_maker() as session:
        existing_refund = await session.execute(
            select(TokenLedgerEntry).where(
                TokenLedgerEntry.user_id == user_id,
                TokenLedgerEntry.reference_id == presentation_id,
                TokenLedgerEntry.reason == TokenLedgerEntry.REASON_GENERATION_REFUND,
            )
        )
        if existing_refund.scalars().first() is not None:
            return

        debit_result = await session.execute(
            select(TokenLedgerEntry).where(
                TokenLedgerEntry.user_id == user_id,
                TokenLedgerEntry.reference_id == presentation_id,
                TokenLedgerEntry.reason == TokenLedgerEntry.REASON_GENERATION_DEBIT,
            )
        )
        debit_row = debit_result.scalars().first()
        if debit_row is None:
            # Nothing to refund — caller may have failed before debit.
            return

        refund_amount = -debit_row.delta  # delta was negative
        if refund_amount <= 0:
            return

        await session.execute(
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(
                tokens=UserModel.tokens + refund_amount,
                updated_at=get_current_utc_datetime(),
            )
        )
        refreshed = await session.get(UserModel, user_id)
        if refreshed is None:
            await session.rollback()
            return
        await _record_ledger(
            session,
            user_id=user_id,
            delta=refund_amount,
            balance_after=refreshed.tokens,
            reason=TokenLedgerEntry.REASON_GENERATION_REFUND,
            reference_id=presentation_id,
            metadata={"note": reason_note} if reason_note else None,
        )
        await session.commit()


async def admin_credit(
    *,
    user_id: str,
    amount: int,
    note: Optional[str] = None,
) -> int:
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be > 0.")

    async with async_session_maker() as session:
        await get_or_create_user(session, user_id)
        await session.execute(
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(
                tokens=UserModel.tokens + amount,
                updated_at=get_current_utc_datetime(),
            )
        )
        refreshed = await session.get(UserModel, user_id)
        if refreshed is None:
            raise HTTPException(status_code=500, detail="User vanished.")
        await _record_ledger(
            session,
            user_id=user_id,
            delta=amount,
            balance_after=refreshed.tokens,
            reason=TokenLedgerEntry.REASON_ADMIN_CREDIT,
            metadata={"note": note} if note else None,
        )
        await session.commit()
        return refreshed.tokens


# ----- Adapty webhook handling -----------------------------------------------

_ADAPTY_EVENT_REASONS = {
    "subscription_started": TokenLedgerEntry.REASON_ADAPTY_SUBSCRIPTION_STARTED,
    "subscription_renewed": TokenLedgerEntry.REASON_ADAPTY_SUBSCRIPTION_RENEWED,
    "subscription_cancelled": TokenLedgerEntry.REASON_ADAPTY_SUBSCRIPTION_CANCELLED,
    "subscription_expired": TokenLedgerEntry.REASON_ADAPTY_SUBSCRIPTION_EXPIRED,
}


def _extract_adapty_fields(payload: dict) -> dict:
    """
    Adapty event payloads are versioned. We dig out the bits we need
    defensively so a missing field returns None rather than raising.

    Reference (truncated for the cases we care about):
      payload = {
        "event_id": "<uuid>",
        "event_type": "subscription_started",
        "event_created_at": "...",
        "profile": {
            "customer_user_id": "u-1",
            "profile_id": "...",
            "subscriptions": {...},
        },
        "event_properties": {...},
      }
    """
    event_id = payload.get("event_id") or payload.get("id")
    event_type = (payload.get("event_type") or "").strip().lower()
    profile = payload.get("profile") or {}
    customer_user_id = (
        payload.get("customer_user_id")
        or profile.get("customer_user_id")
        or payload.get("user_id")
    )
    adapty_profile_id = profile.get("profile_id") or payload.get("profile_id")

    expires_at_raw = None
    event_props = payload.get("event_properties") or {}
    for source in (event_props, profile):
        for key in ("expires_at", "subscription_expires_at"):
            if isinstance(source.get(key), str):
                expires_at_raw = source[key]
                break
        if expires_at_raw:
            break

    expires_at: Optional[datetime] = None
    if expires_at_raw:
        try:
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        except ValueError:
            expires_at = None

    return {
        "event_id": event_id,
        "event_type": event_type,
        "customer_user_id": customer_user_id,
        "adapty_profile_id": adapty_profile_id,
        "expires_at": expires_at,
    }


async def apply_adapty_event(payload: dict) -> dict:
    """
    Process a single Adapty webhook payload. Returns a small JSON-friendly
    dict the route handler can echo back for visibility.

    Idempotent on `event_id`: if we have already inserted a ledger row
    with this event_id as reference_id, we skip without modifying state.
    Unknown event types are logged and treated as no-ops (return ok so
    Adapty does not retry forever).
    """
    fields = _extract_adapty_fields(payload)
    event_id = fields["event_id"]
    event_type = fields["event_type"]
    user_id = fields["customer_user_id"]

    if not event_id:
        raise HTTPException(status_code=400, detail="event_id is required.")
    if event_type not in _ADAPTY_EVENT_REASONS:
        logger.info(
            "Adapty webhook: ignoring event_type=%s (event_id=%s)",
            event_type or "<empty>",
            event_id,
        )
        return {"status": "ignored", "event_type": event_type}
    if not user_id:
        raise HTTPException(status_code=400, detail="customer_user_id is required.")

    reason = _ADAPTY_EVENT_REASONS[event_type]
    grant_tokens = get_subscription_tokens_grant() if event_type in (
        "subscription_started",
        "subscription_renewed",
    ) else 0

    async with async_session_maker() as session:
        # Idempotency: have we already logged this event_id?
        existing = await session.execute(
            select(TokenLedgerEntry).where(
                TokenLedgerEntry.reference_id == event_id,
                TokenLedgerEntry.reason.in_(list(_ADAPTY_EVENT_REASONS.values())),
            )
        )
        if existing.scalars().first() is not None:
            return {"status": "duplicate", "event_id": event_id}

        await get_or_create_user(session, user_id)

        # Update subscription flag + grant tokens atomically.
        subscription_active = event_type in (
            "subscription_started",
            "subscription_renewed",
        )
        values: dict = {
            "subscription": subscription_active,
            "updated_at": get_current_utc_datetime(),
        }
        if fields["adapty_profile_id"]:
            values["adapty_profile_id"] = fields["adapty_profile_id"]
        if fields["expires_at"]:
            values["subscription_expires_at"] = fields["expires_at"]
        if grant_tokens:
            values["tokens"] = UserModel.tokens + grant_tokens

        await session.execute(
            update(UserModel).where(UserModel.id == user_id).values(**values)
        )
        refreshed = await session.get(UserModel, user_id)
        if refreshed is None:
            await session.rollback()
            raise HTTPException(status_code=500, detail="User vanished.")

        await _record_ledger(
            session,
            user_id=user_id,
            delta=grant_tokens,
            balance_after=refreshed.tokens,
            reason=reason,
            reference_id=event_id,
            metadata={"event_type": event_type, "payload": payload},
        )
        await session.commit()

        return {
            "status": "applied",
            "event_id": event_id,
            "event_type": event_type,
            "subscription": refreshed.subscription,
            "tokens": refreshed.tokens,
        }
