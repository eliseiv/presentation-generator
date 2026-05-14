"""
Track real upstream-provider spend (OpenAI / Google / etc) per presentation.

Every LLM / image / audio call site asks this module to log what it just
did. The module:

1. Estimates the USD cost using a baked-in price table (covers the models
   this codebase actually calls — gpt-4.1, gpt-4o, whisper-1, gpt-image-1.5,
   dall-e-3, gemini-2.5-flash-image, etc.). Unknown models record with
   `estimated_cost_usd = 0` instead of crashing.
2. Reads `presentation_id` and `user_id` from the per-request ContextVar
   set by `generate_presentation_handler`, so call sites don't need new
   function arguments.
3. Inserts an `LlmUsageEntry` row in its own short transaction.

Aggregation helpers (`get_presentation_cost`, `get_cost_summary`) read
this table and shape it for the admin cost endpoints.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select

from models.sql.llm_usage import LlmUsageEntry
from services.database import async_session_maker
from services.llm_cost_context import get_presentation_id, get_user_id

logger = logging.getLogger(__name__)


# Prices in USD. Token prices are per **1 million tokens** (the unit
# OpenAI publishes). Image and audio prices are per call / per minute as
# noted. Numbers reflect public pricing as of 2026-05; tweak by editing
# this table or by passing an explicit `cost_usd_override` to record_*.
_TEXT_PRICES_USD_PER_M = {
    "gpt-4.1": {"input": 2.0, "output": 8.0},
    "gpt-4.1-mini": {"input": 0.4, "output": 1.6},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
}

# Image generation prices are per image at a given quality.
_IMAGE_PRICES_USD_PER_IMAGE = {
    "dall-e-3": {"standard": 0.04, "hd": 0.08},
    "gpt-image-1": {"low": 0.011, "medium": 0.042, "high": 0.167},
    "gpt-image-1.5": {"low": 0.011, "medium": 0.042, "high": 0.167},
    "gpt-image-2": {"low": 0.011, "medium": 0.042, "high": 0.167},
    "gemini-2.5-flash-image": {"default": 0.04},
    "gemini-3-pro-image-preview": {"default": 0.10},
}

# Whisper: per minute of audio.
_AUDIO_PRICE_USD_PER_MIN = {
    "whisper-1": 0.006,
}


def compute_text_cost(
    model: str, prompt_tokens: int, completion_tokens: int
) -> float:
    pricing = _TEXT_PRICES_USD_PER_M.get(model)
    if not pricing:
        return 0.0
    return (
        (prompt_tokens or 0) * pricing["input"] / 1_000_000.0
        + (completion_tokens or 0) * pricing["output"] / 1_000_000.0
    )


def compute_image_cost(model: str, quality: Optional[str], count: int) -> float:
    pricing = _IMAGE_PRICES_USD_PER_IMAGE.get(model)
    if not pricing:
        return 0.0
    if quality and quality in pricing:
        per_image = pricing[quality]
    else:
        per_image = next(iter(pricing.values()))
    return per_image * max(count, 0)


def compute_audio_cost(model: str, audio_seconds: float) -> float:
    rate = _AUDIO_PRICE_USD_PER_MIN.get(model)
    if not rate:
        return 0.0
    return rate * max(audio_seconds, 0.0) / 60.0


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_usage_field(usage_obj: Any, *names: str) -> Optional[int]:
    """
    OpenAI native SDK names fields `prompt_tokens`/`completion_tokens`,
    llmai wraps them as `input_tokens`/`output_tokens`. Accept either.
    """
    if usage_obj is None:
        return None
    for name in names:
        value = getattr(usage_obj, name, None)
        if value is None and isinstance(usage_obj, dict):
            value = usage_obj.get(name)
        if value is not None:
            coerced = _coerce_int(value)
            if coerced is not None:
                return coerced
    return None


def _extract_text_usage(usage_obj: Any) -> tuple[Optional[int], Optional[int], Optional[int]]:
    if usage_obj is None:
        return None, None, None
    prompt = _read_usage_field(usage_obj, "prompt_tokens", "input_tokens")
    completion = _read_usage_field(usage_obj, "completion_tokens", "output_tokens")
    total = _read_usage_field(usage_obj, "total_tokens")
    if total is None and (prompt is not None or completion is not None):
        total = (prompt or 0) + (completion or 0)
    return prompt, completion, total


async def _insert_entry(entry: LlmUsageEntry) -> None:
    try:
        async with async_session_maker() as session:
            session.add(entry)
            await session.commit()
    except Exception:
        # Usage tracking must never break a working generation.
        logger.exception("Failed to record llm_usage_entry")


async def record_text_usage(
    *,
    provider: str,
    model: str,
    usage: Any,
    kind: str = "text",
    extra: Optional[dict] = None,
    cost_usd_override: Optional[float] = None,
) -> None:
    prompt, completion, total = _extract_text_usage(usage)
    cost = (
        cost_usd_override
        if cost_usd_override is not None
        else compute_text_cost(model, prompt or 0, completion or 0)
    )
    entry = LlmUsageEntry(
        presentation_id=get_presentation_id(),
        user_id=get_user_id(),
        provider=provider,
        model=model,
        kind=kind,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        estimated_cost_usd=float(cost or 0.0),
        extra=extra,
    )
    await _insert_entry(entry)


async def record_image_usage(
    *,
    provider: str,
    model: str,
    quality: Optional[str] = None,
    count: int = 1,
    extra: Optional[dict] = None,
    cost_usd_override: Optional[float] = None,
) -> None:
    cost = (
        cost_usd_override
        if cost_usd_override is not None
        else compute_image_cost(model, quality, count)
    )
    entry = LlmUsageEntry(
        presentation_id=get_presentation_id(),
        user_id=get_user_id(),
        provider=provider,
        model=model,
        kind="image",
        image_count=count,
        image_quality=quality,
        estimated_cost_usd=float(cost or 0.0),
        extra=extra,
    )
    await _insert_entry(entry)


async def record_audio_usage(
    *,
    provider: str,
    model: str,
    audio_seconds: float,
    extra: Optional[dict] = None,
    cost_usd_override: Optional[float] = None,
) -> None:
    cost = (
        cost_usd_override
        if cost_usd_override is not None
        else compute_audio_cost(model, audio_seconds)
    )
    entry = LlmUsageEntry(
        presentation_id=get_presentation_id(),
        user_id=get_user_id(),
        provider=provider,
        model=model,
        kind="audio",
        audio_seconds=float(audio_seconds or 0.0),
        estimated_cost_usd=float(cost or 0.0),
        extra=extra,
    )
    await _insert_entry(entry)


# ---------- Aggregation -----------------------------------------------------


def _group_by_kind(rows: list[LlmUsageEntry]) -> dict:
    breakdown: dict[str, dict] = {}
    for row in rows:
        bucket = breakdown.setdefault(
            row.kind,
            {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "image_count": 0,
                "audio_seconds": 0.0,
                "cost_usd": 0.0,
                "models": {},
            },
        )
        bucket["calls"] += 1
        bucket["prompt_tokens"] += row.prompt_tokens or 0
        bucket["completion_tokens"] += row.completion_tokens or 0
        bucket["total_tokens"] += row.total_tokens or 0
        bucket["image_count"] += row.image_count or 0
        bucket["audio_seconds"] += row.audio_seconds or 0.0
        bucket["cost_usd"] += row.estimated_cost_usd or 0.0
        model_bucket = bucket["models"].setdefault(
            row.model, {"calls": 0, "cost_usd": 0.0}
        )
        model_bucket["calls"] += 1
        model_bucket["cost_usd"] += row.estimated_cost_usd or 0.0
    # Round costs for readability — full precision still in DB.
    for kind_bucket in breakdown.values():
        kind_bucket["cost_usd"] = round(kind_bucket["cost_usd"], 6)
        kind_bucket["audio_seconds"] = round(kind_bucket["audio_seconds"], 3)
        for model_bucket in kind_bucket["models"].values():
            model_bucket["cost_usd"] = round(model_bucket["cost_usd"], 6)
    return breakdown


async def get_presentation_cost(presentation_id: str) -> dict:
    async with async_session_maker() as session:
        result = await session.execute(
            select(LlmUsageEntry)
            .where(LlmUsageEntry.presentation_id == presentation_id)
            .order_by(LlmUsageEntry.created_at)
        )
        rows: list[LlmUsageEntry] = list(result.scalars().all())

    total_cost = round(sum(r.estimated_cost_usd or 0.0 for r in rows), 6)
    return {
        "presentation_id": presentation_id,
        "calls": len(rows),
        "total_cost_usd": total_cost,
        "by_kind": _group_by_kind(rows),
    }


async def get_cost_summary(
    *,
    user_id: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> dict:
    async with async_session_maker() as session:
        stmt = select(LlmUsageEntry)
        if user_id:
            stmt = stmt.where(LlmUsageEntry.user_id == user_id)
        if since:
            stmt = stmt.where(LlmUsageEntry.created_at >= since)
        if until:
            stmt = stmt.where(LlmUsageEntry.created_at <= until)
        result = await session.execute(stmt)
        rows: list[LlmUsageEntry] = list(result.scalars().all())

    presentations: dict[str, float] = {}
    for r in rows:
        if r.presentation_id is None:
            continue
        presentations[r.presentation_id] = (
            presentations.get(r.presentation_id, 0.0)
            + (r.estimated_cost_usd or 0.0)
        )

    total_cost = round(sum(r.estimated_cost_usd or 0.0 for r in rows), 6)
    return {
        "filters": {
            "user_id": user_id,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
        "calls": len(rows),
        "presentations": len(presentations),
        "total_cost_usd": total_cost,
        "average_cost_per_presentation_usd": (
            round(total_cost / len(presentations), 6) if presentations else 0.0
        ),
        "by_kind": _group_by_kind(rows),
    }
