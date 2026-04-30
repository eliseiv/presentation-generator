import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, or_, select

from models.sql.async_presentation_generation_status import (
    AsyncPresentationGenerationTaskModel,
)
from models.sql.chat_history_message import ChatHistoryMessageModel
from models.sql.image_asset import ImageAsset
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from services.database import async_session_maker
from utils.get_env import (
    get_app_data_directory_env,
    get_cleanup_interval_seconds_env,
    get_cleanup_ttl_seconds_env,
)

logger = logging.getLogger(__name__)

DEFAULT_CLEANUP_TTL_SECONDS = 2 * 60 * 60
DEFAULT_CLEANUP_INTERVAL_SECONDS = 10 * 60
CLEANUP_DIRECTORIES = ("images", "exports", "uploads", "pptx-to-html")


def _positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def get_cleanup_ttl_seconds() -> int:
    return _positive_int(get_cleanup_ttl_seconds_env(), DEFAULT_CLEANUP_TTL_SECONDS)


def get_cleanup_interval_seconds() -> int:
    return _positive_int(
        get_cleanup_interval_seconds_env(),
        DEFAULT_CLEANUP_INTERVAL_SECONDS,
    )


def _safe_remove_path(path: str | os.PathLike[str]) -> None:
    try:
        path_obj = Path(path)
        if path_obj.is_dir():
            shutil.rmtree(path_obj, ignore_errors=True)
        elif path_obj.exists():
            path_obj.unlink(missing_ok=True)
    except Exception:
        logger.exception("Failed to remove expired path: %s", path)


def _cleanup_directory_by_mtime(directory: Path, cutoff_timestamp: float) -> int:
    if not directory.exists():
        return 0

    removed = 0
    for path in directory.rglob("*"):
        if not path.exists():
            continue
        if path.is_dir():
            continue
        try:
            if path.stat().st_mtime < cutoff_timestamp:
                _safe_remove_path(path)
                removed += 1
        except FileNotFoundError:
            continue
        except Exception:
            logger.exception("Failed to inspect path during cleanup: %s", path)

    # Remove empty nested directories after deleting old files.
    for path in sorted(
        (item for item in directory.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            path.rmdir()
        except OSError:
            pass

    return removed


async def cleanup_expired_app_data() -> None:
    ttl_seconds = get_cleanup_ttl_seconds()
    now_utc = datetime.now(timezone.utc)
    cutoff_aware = now_utc - timedelta(seconds=ttl_seconds)
    cutoff_naive = cutoff_aware.replace(tzinfo=None)
    cutoff_timestamp = cutoff_aware.timestamp()

    async with async_session_maker() as session:
        expired_presentation_ids = select(PresentationModel.id).where(
            PresentationModel.created_at < cutoff_aware
        )
        await session.execute(
            delete(SlideModel).where(SlideModel.presentation.in_(expired_presentation_ids))
        )
        await session.execute(
            delete(ChatHistoryMessageModel).where(
                or_(
                    ChatHistoryMessageModel.presentation_id.in_(
                        expired_presentation_ids
                    ),
                    ChatHistoryMessageModel.created_at < cutoff_aware,
                )
            )
        )
        await session.execute(
            delete(PresentationModel).where(PresentationModel.created_at < cutoff_aware)
        )
        await session.execute(
            delete(ImageAsset).where(ImageAsset.created_at < cutoff_aware)
        )
        await session.execute(
            delete(AsyncPresentationGenerationTaskModel).where(
                AsyncPresentationGenerationTaskModel.created_at < cutoff_naive
            )
        )
        await session.commit()

    app_data_directory = get_app_data_directory_env()
    if not app_data_directory:
        return

    app_data_path = Path(app_data_directory)
    removed_files = 0
    for directory_name in CLEANUP_DIRECTORIES:
        removed_files += _cleanup_directory_by_mtime(
            app_data_path / directory_name,
            cutoff_timestamp,
        )

    if removed_files:
        logger.info("Removed %s expired app_data files", removed_files)


async def periodic_cleanup_loop() -> None:
    while True:
        try:
            await cleanup_expired_app_data()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Periodic cleanup failed")

        await asyncio.sleep(get_cleanup_interval_seconds())
