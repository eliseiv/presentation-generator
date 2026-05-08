"""
Turn a video (URL or local file) into a multimodal text context the outline
LLM can read: Whisper transcript of the audio plus a per-frame visual
description from gpt-4o vision.

Pipeline:
    1. Validate input (size cap, duration cap, SSRF guard for URLs).
    2. ffmpeg streams audio (mono, 64 kbps) to a temp .mp3 — no full download.
       In parallel, ffmpeg samples one frame every 10 s into a temp dir.
    3. Whisper API transcribes the .mp3 (verbose_json so we get timestamps).
    4. gpt-4o describes every sampled frame in one batched request
       (detail="low" for cost). Output is a list of `[timestamp] description`.
    5. Caller receives a single string blending audio and visual context.
"""

import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel

from services.safe_url import assert_url_is_safe
from utils.get_env import get_openai_api_key_env, get_temp_directory_env


# Hard caps to prevent runaway uploads / costs.
_MAX_VIDEO_DURATION_SEC = 30 * 60          # 30 min
_FRAME_SAMPLE_INTERVAL_SEC = 10            # 1 frame every 10 s
_MAX_FRAMES = 200                          # safety net (≈ 33 min @ 1/10s)
_AUDIO_BITRATE = "64k"
_AUDIO_SAMPLE_RATE = "16000"
_FRAME_WIDTH = 640                         # downscale frames before VLM
_VLM_MODEL = "gpt-4o"
_FFMPEG_TIMEOUT_SEC = 600                  # 10 min wall time for ffmpeg pulls

# Vision API token-per-minute limits cap how many frames we can send in one
# request. 15 frames @ detail=low ≈ 1300 input tokens including the prompt,
# which stays comfortably under tight 30K TPM tiers even when chunks run
# back-to-back.
_VLM_FRAMES_PER_BATCH = 15


class VideoContext(BaseModel):
    duration_sec: float | None
    audio_transcript: str
    visual_summary: str
    combined_context: str


def _temp_root() -> str:
    base = get_temp_directory_env() or tempfile.gettempdir()
    root = os.path.join(base, "video_transcribe", uuid.uuid4().hex)
    os.makedirs(root, exist_ok=True)
    return root


def _ffprobe_duration(source: str) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                source,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg synchronously and surface any non-zero exit as HTTPException."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_FFMPEG_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail=f"ffmpeg timed out after {_FFMPEG_TIMEOUT_SEC}s",
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="ffmpeg binary is not available on the server",
        ) from exc

    if result.returncode != 0:
        snippet = (result.stderr or result.stdout or "").strip()[-400:]
        raise HTTPException(
            status_code=502,
            detail=f"ffmpeg failed: {snippet}",
        )


def _extract_audio(source: str, output_path: str) -> None:
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            source,
            "-vn",
            "-ac",
            "1",
            "-ar",
            _AUDIO_SAMPLE_RATE,
            "-b:a",
            _AUDIO_BITRATE,
            "-f",
            "mp3",
            output_path,
        ]
    )


def _extract_frames(source: str, output_dir: str) -> list[str]:
    pattern = os.path.join(output_dir, "frame_%05d.jpg")
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            source,
            "-vf",
            f"fps=1/{_FRAME_SAMPLE_INTERVAL_SEC},scale={_FRAME_WIDTH}:-2",
            "-q:v",
            "5",
            pattern,
        ]
    )
    frames = sorted(Path(output_dir).glob("frame_*.jpg"))
    return [str(p) for p in frames[:_MAX_FRAMES]]


async def _whisper_transcribe(audio_path: str, language: str | None) -> str:
    api_key = get_openai_api_key_env()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is required for video transcription",
        )

    client = AsyncOpenAI(api_key=api_key)
    with open(audio_path, "rb") as f:
        result = await client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            language=_iso_639_1(language) if language else None,
        )

    segments = getattr(result, "segments", None) or []
    if not segments:
        return (getattr(result, "text", "") or "").strip()

    lines = []
    for seg in segments:
        start = float(getattr(seg, "start", 0.0) or 0.0)
        text = (getattr(seg, "text", "") or "").strip()
        if text:
            lines.append(f"[{_format_timestamp(start)}] {text}")
    return "\n".join(lines).strip()


async def _describe_frame_batch(
    client: AsyncOpenAI,
    frame_paths: list[str],
    start_index: int,
    language: str | None,
) -> str:
    """
    Describe one chunk of frames. `start_index` is the global frame number of
    the first frame in this chunk so timestamps stay correct across batches.
    """
    user_content: list[dict] = [
        {
            "type": "text",
            "text": (
                "You are looking at frames sampled from a video, one frame "
                f"every {_FRAME_SAMPLE_INTERVAL_SEC} seconds. In this batch "
                f"the first frame is at "
                f"{_format_timestamp(start_index * _FRAME_SAMPLE_INTERVAL_SEC)}, "
                f"the next at "
                f"{_format_timestamp((start_index + 1) * _FRAME_SAMPLE_INTERVAL_SEC)}, "
                "and so on. For each frame produce ONE concise sentence "
                "describing what is shown (subject, action, on-screen text). "
                "Output exactly one line per frame in the format "
                "`[HH:MM:SS] description`, in chronological order, no extra "
                "commentary."
                + (f" Use {language} for the descriptions." if language else "")
            ),
        }
    ]

    for path in frame_paths:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        user_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{encoded}",
                    "detail": "low",
                },
            }
        )

    response = await client.chat.completions.create(
        model=_VLM_MODEL,
        messages=[{"role": "user", "content": user_content}],
        max_tokens=40 * len(frame_paths) + 200,
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


async def _describe_frames(frame_paths: list[str], language: str | None) -> str:
    if not frame_paths:
        return ""

    api_key = get_openai_api_key_env()
    if not api_key:
        return ""

    client = AsyncOpenAI(api_key=api_key)

    chunks: list[str] = []
    for batch_start in range(0, len(frame_paths), _VLM_FRAMES_PER_BATCH):
        batch = frame_paths[batch_start : batch_start + _VLM_FRAMES_PER_BATCH]
        try:
            description = await _describe_frame_batch(
                client, batch, batch_start, language
            )
        except Exception as exc:  # rate limit, network, etc.
            print(
                f"[video_transcribe] frame batch {batch_start} "
                f"(size {len(batch)}) failed: {exc}"
            )
            continue
        if description:
            chunks.append(description)

    return "\n".join(chunks).strip()


def _format_timestamp(seconds: float) -> str:
    seconds = int(max(0.0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _iso_639_1(language: str | None) -> str | None:
    """Best-effort ISO-639-1 hint for Whisper. Whisper accepts e.g. 'ru'/'en'."""
    if not language:
        return None
    mapping = {
        "english": "en",
        "russian": "ru",
        "spanish": "es",
        "french": "fr",
        "german": "de",
        "italian": "it",
        "portuguese": "pt",
        "chinese": "zh",
        "japanese": "ja",
        "korean": "ko",
        "arabic": "ar",
        "hindi": "hi",
        "ukrainian": "uk",
        "turkish": "tr",
    }
    key = language.strip().lower()
    if key in mapping:
        return mapping[key]
    if len(key) == 2 and key.isalpha():
        return key
    return None


async def transcribe_video(
    source: str,
    *,
    is_url: bool,
    language: str | None = None,
) -> VideoContext:
    """
    Run the full audio + visual transcription pipeline.

    `source` is either an http(s) URL (when `is_url=True`) or an absolute path
    to a video file already on disk.
    """
    if is_url:
        assert_url_is_safe(source)

    duration = _ffprobe_duration(source)
    if duration is not None and duration > _MAX_VIDEO_DURATION_SEC:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Video duration {int(duration)}s exceeds the limit of "
                f"{_MAX_VIDEO_DURATION_SEC}s ({_MAX_VIDEO_DURATION_SEC // 60} min)."
            ),
        )
    if not is_url and not os.path.isfile(source):
        raise HTTPException(
            status_code=400,
            detail=f"Local video file not found: {source}",
        )

    work_dir = _temp_root()
    audio_path = os.path.join(work_dir, "audio.mp3")
    frames_dir = os.path.join(work_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    try:
        # Extract audio + sample frames in parallel; both are CPU/IO-bound
        # ffmpeg subprocesses, so run them in threads.
        audio_task = asyncio.to_thread(_extract_audio, source, audio_path)
        frames_task = asyncio.to_thread(_extract_frames, source, frames_dir)
        await audio_task
        frame_paths = await frames_task

        transcript_task = asyncio.create_task(
            _whisper_transcribe(audio_path, language)
        )
        frames_task_async = asyncio.create_task(
            _describe_frames(frame_paths, language)
        )
        audio_transcript, visual_summary = await asyncio.gather(
            transcript_task, frames_task_async
        )

        sections = []
        if audio_transcript:
            sections.append("=== Audio transcript ===\n" + audio_transcript)
        if visual_summary:
            sections.append("=== Visual frames ===\n" + visual_summary)
        if not sections:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Could not derive any audio or visual content from the "
                    "video. The file may be empty, silent, or unreadable."
                ),
            )

        return VideoContext(
            duration_sec=duration,
            audio_transcript=audio_transcript,
            visual_summary=visual_summary,
            combined_context="\n\n".join(sections),
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def is_video_filename(path_or_name: str) -> bool:
    return Path(path_or_name).suffix.lower() in {
        ".mp4",
        ".mov",
        ".m4v",
        ".mkv",
        ".webm",
        ".avi",
        ".mpeg",
        ".mpg",
        ".mp3",
        ".wav",
        ".m4a",
        ".aac",
        ".ogg",
        ".flac",
    }
