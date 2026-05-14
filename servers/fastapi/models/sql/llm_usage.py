from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String
from sqlmodel import Field, SQLModel

from utils.datetime_utils import get_current_utc_datetime


class LlmUsageEntry(SQLModel, table=True):
    """
    One row per upstream LLM / image / audio call. Lets us answer
    "how much did presentation X actually cost us in USD?" by joining on
    `presentation_id`, and "how much did model Y burn this month?" by
    grouping by `model`.

    Fields are union-shaped across call kinds (text/image/audio/vision):
    text rows fill prompt_tokens + completion_tokens; image rows fill
    image_count + image_quality; audio rows fill audio_seconds. Anything
    irrelevant for the row's kind stays NULL.
    """

    __tablename__ = "llm_usage_entries"

    id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    presentation_id: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True, index=True)
    )
    user_id: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True, index=True)
    )
    provider: str = Field(sa_column=Column(String, nullable=False, index=True))
    model: str = Field(sa_column=Column(String, nullable=False, index=True))
    kind: str = Field(
        sa_column=Column(String, nullable=False, index=True),
        description="text | image | audio | vision",
    )
    prompt_tokens: Optional[int] = Field(default=None)
    completion_tokens: Optional[int] = Field(default=None)
    total_tokens: Optional[int] = Field(default=None)
    image_count: Optional[int] = Field(default=None)
    image_quality: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    audio_seconds: Optional[float] = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    estimated_cost_usd: float = Field(sa_column=Column(Float, nullable=False, default=0.0))
    extra: Optional[dict] = Field(
        default=None, sa_column=Column("extra", JSON, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, default=get_current_utc_datetime
        ),
    )
