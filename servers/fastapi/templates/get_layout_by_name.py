import json
import os

import aiohttp
from fastapi import HTTPException

from constants.presentation import DEFAULT_TEMPLATES
from templates.presentation_layout import PresentationLayoutModel


# Layouts whose name/id contains any of these terms are excluded from the
# auto-pick pool — they only make sense when the user explicitly asks for a
# table of contents. Keep this list small: charts/tables/metrics make decks
# richer when the topic warrants them.
TOC_EXCLUSION_TERMS = ("table-of-contents", "tableofcontents", "toc")


def _get_internal_nextjs_url() -> str:
    """
    Return the base URL used to reach the Next.js layout schema endpoint.

    Inside the production Docker image, FastAPI and Next.js share localhost and
    nginx (port 80) proxies `/` to Next.js. Outside the image, callers can set
    INTERNAL_NEXTJS_URL or NEXT_PUBLIC_URL to override this.
    """
    for env_name in ("INTERNAL_NEXTJS_URL", "NEXT_PUBLIC_URL"):
        value = (os.getenv(env_name) or "").strip()
        if value:
            return value.rstrip("/")
    return "http://127.0.0.1"


async def _get_layout_from_next_schema(layout_name: str) -> PresentationLayoutModel:
    base_url = _get_internal_nextjs_url()
    url = f"{base_url}/api/template?group={layout_name}"
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise HTTPException(
                        status_code=404,
                        detail=f"Template '{layout_name}' not found: {error_text}",
                    )
                layout_json = json.loads(await response.text())
    except aiohttp.ClientError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Cannot reach Next.js layout service at {base_url}. "
                f"Layout schemas live in the Next.js server — make sure it is "
                f"running (Docker `presenton-backend` container starts it via "
                f"start.js, or set INTERNAL_NEXTJS_URL to a reachable Next.js). "
                f"Underlying error: {exc}"
            ),
        ) from exc

    return _filter_layouts_for_api(PresentationLayoutModel(**layout_json))


def _filter_layouts_for_api(layout: PresentationLayoutModel) -> PresentationLayoutModel:
    """
    Drop layouts that are only useful when the request explicitly asks for them.

    We previously stripped charts/metrics/tables outright — that turned every
    deck into a wall of bullet-only slides. The current behaviour only filters
    Table-of-Contents layouts; the structure builder inserts a TOC slide
    deliberately when `include_table_of_contents` is set.
    """
    filtered_slides = []
    for slide in layout.slides:
        slide_id = (slide.id or "").lower().replace("_", "-")
        if any(term in slide_id for term in TOC_EXCLUSION_TERMS):
            continue
        filtered_slides.append(slide)

    if len(filtered_slides) >= 3:
        layout.slides = filtered_slides

    return layout


async def get_layout_by_name(layout_name: str) -> PresentationLayoutModel:
    normalized_layout_name = (layout_name or "general").strip()
    if normalized_layout_name.startswith("custom-"):
        raise HTTPException(
            status_code=404,
            detail="Custom templates are not available in backend-only mode.",
        )

    if normalized_layout_name not in DEFAULT_TEMPLATES:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Template '{normalized_layout_name}' not found. "
                f"Available templates: {', '.join(DEFAULT_TEMPLATES)}"
            ),
        )

    return await _get_layout_from_next_schema(normalized_layout_name)
