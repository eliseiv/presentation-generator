from fastapi import HTTPException

from constants.presentation import DEFAULT_TEMPLATES
from templates.presentation_layout import PresentationLayoutModel


GENERIC_SLIDE_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "title": {
            "type": "string",
            "minLength": 3,
            "maxLength": 80,
            "description": "Slide title",
        },
        "description": {
            "type": "string",
            "minLength": 10,
            "maxLength": 350,
            "description": "Main slide text",
        },
        "bulletPoints": {
            "type": "array",
            "minItems": 2,
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "title": {"type": "string", "maxLength": 80},
                    "body": {"type": "string", "maxLength": 220},
                    "description": {"type": "string", "maxLength": 220},
                    "icon": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "__icon_query__": {
                                "type": "string",
                                "description": "English icon search query",
                            }
                        },
                    },
                },
            },
        },
        "items": {
            "type": "array",
            "minItems": 2,
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "title": {"type": "string", "maxLength": 80},
                    "description": {"type": "string", "maxLength": 220},
                    "body": {"type": "string", "maxLength": 220},
                },
            },
        },
        "metrics": {
            "type": "array",
            "minItems": 2,
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "label": {"type": "string", "maxLength": 80},
                    "value": {"type": "string", "maxLength": 40},
                    "description": {"type": "string", "maxLength": 160},
                },
            },
        },
        "image": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "__image_prompt__": {
                    "type": "string",
                    "description": "English image generation prompt",
                }
            },
        },
    },
    "required": ["title", "description"],
}


DEFAULT_TEMPLATE_LAYOUTS = {
    "general": [
        ("general-intro-slide", "Intro Slide"),
        ("basic-info-slide", "Basic Info"),
        ("bullet-with-icons-slide", "Bullet With Icons"),
        ("chart-with-bullets-slide", "Chart With Bullets"),
        ("metrics-slide", "Metrics"),
        ("metrics-with-image-slide", "Metrics With Image"),
        ("numbered-bullets-slide", "Numbered Bullets"),
        ("quote-slide", "Quote"),
        ("table-info-slide", "Table Info"),
        ("team-slide", "Team"),
        ("table-of-contents-slide", "Table Of Contents"),
    ],
    "modern": [
        ("intro-pitchdeck-slide", "Intro Slide"),
        ("bullet-with-icons", "Bullet With Icons"),
        ("bullet-with-icons-description-grid", "Bullet Icons Grid"),
        ("chart-or-table-with-description", "Chart Or Table"),
        ("chart-with-metrics", "Chart With Metrics"),
        ("image-and-description", "Image And Description"),
        ("image-list-with-description", "Image List"),
        ("images-with-description", "Images With Description"),
        ("metrics-with-description-image", "Metrics With Description"),
        ("table-of-contents", "Table Of Contents"),
    ],
    "standard": [
        ("header-counter-two-column-image-text-slide", "Intro Slide"),
        ("chart-left-text-right-layout", "Chart Left Text Right"),
        ("header-bullets-image-split-slide", "Numbered Bullets With Image"),
        ("header-bullets-title-description-image-slide", "Icon Bullet Description"),
        ("header-smallbar-title-team-cards-slide", "Image List"),
        ("header-tagline-cards-grid-slide", "Metrics Description"),
        ("visual-metrics", "Visual Metrics"),
        ("table-of-contents-layout", "Table Of Contents"),
    ],
    "swift": [
        ("IntroSlideLayout", "Intro Slide Layout"),
        ("simple-bullet-points-layout", "Simple Bullet Points"),
        ("bullet-with-icons-title-description", "Bullets With Icons"),
        ("icon-bullet-list-description-slide", "Icon Bullet List"),
        ("image-list-description-slide", "Image List"),
        ("MetricsNumbers", "Metrics Numbers"),
        ("tableorChart", "Table Or Chart"),
        ("Timeline", "Timeline"),
        ("SwiftTableOfContents", "Table Of Contents"),
    ],
}


def _build_default_layout(layout_name: str) -> PresentationLayoutModel:
    layouts = DEFAULT_TEMPLATE_LAYOUTS.get(layout_name)
    if not layouts:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Template '{layout_name}' not found. "
                f"Available templates: {', '.join(DEFAULT_TEMPLATES)}"
            ),
        )

    return PresentationLayoutModel(
        name=layout_name,
        ordered=False,
        slides=[
            {
                "id": f"{layout_name}:{layout_id}",
                "name": name,
                "description": f"{name} layout for generated presentations.",
                "json_schema": GENERIC_SLIDE_SCHEMA,
            }
            for layout_id, name in layouts
        ],
    )


async def get_layout_by_name(layout_name: str) -> PresentationLayoutModel:
    normalized_layout_name = (layout_name or "general").strip()
    if normalized_layout_name.startswith("custom-"):
        raise HTTPException(
            status_code=404,
            detail="Custom templates are not available in backend-only mode.",
        )

    return _build_default_layout(normalized_layout_name)
