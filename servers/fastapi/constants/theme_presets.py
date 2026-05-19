"""
Preset color palettes for generated presentations.

These dicts mirror the schema that `PdfMakerPage.applyTheme()` in the
Next.js renderer reads — every shape change here must stay compatible
with that function. The renderer sets CSS variables `--background-color`,
`--background-text`, `--primary-color`, `--primary-text`, `--card-color`,
`--stroke`, and `--graph-0..9` from `theme.data.colors.*` and a single
font from `theme.data.fonts.textFont.*`. Slide templates pull those
variables with sensible fallbacks (`var(--background-color, #ffffff)`),
so adding or removing keys here won't break rendering — only colors that
appear in BOTH this dict and the template's `var()` calls will swap.
"""

LIGHT_THEME = {
    "id": "preset-light",
    "name": "Light",
    "description": "Default light theme with purple accent.",
    "data": {
        "colors": {
            "primary": "#9333ea",
            "background": "#ffffff",
            "card": "#f8fafc",
            "stroke": "#e5e7eb",
            "primary_text": "#ffffff",
            "background_text": "#111827",
            "graph_0": "#9333ea",
            "graph_1": "#7c3aed",
            "graph_2": "#6d28d9",
            "graph_3": "#5b21b6",
            "graph_4": "#4c1d95",
            "graph_5": "#a855f7",
            "graph_6": "#c084fc",
            "graph_7": "#d8b4fe",
            "graph_8": "#e9d5ff",
            "graph_9": "#f3e8ff",
        },
        # `fonts` is intentionally omitted: every slide template embeds its
        # own <link rel="stylesheet"> to Google Fonts (Poppins). Duplicating
        # the font request through `useFontLoader` makes Puppeteer wait for
        # an extra stylesheet download and previously triggered 120 s
        # navigation timeouts on the rendering subprocess.
    },
}


DARK_THEME = {
    "id": "preset-dark",
    "name": "Dark",
    "description": "Dark slate background with purple accent.",
    "data": {
        "colors": {
            "primary": "#a78bfa",
            "background": "#0f172a",
            "card": "#1e293b",
            "stroke": "#334155",
            "primary_text": "#0f172a",
            "background_text": "#f1f5f9",
            "graph_0": "#a78bfa",
            "graph_1": "#8b5cf6",
            "graph_2": "#7c3aed",
            "graph_3": "#6d28d9",
            "graph_4": "#5b21b6",
            "graph_5": "#c4b5fd",
            "graph_6": "#ddd6fe",
            "graph_7": "#ede9fe",
            "graph_8": "#f5f3ff",
            "graph_9": "#faf5ff",
        },
    },
}


THEME_PRESETS = {
    "light": LIGHT_THEME,
    "dark": DARK_THEME,
}


def get_theme_preset(name: str | None) -> dict:
    """
    Return the canonical preset dict for `name`. Falls back to the light
    preset when `name` is None or unknown, so a missing / wrong value
    never blocks generation.
    """
    if not name:
        return LIGHT_THEME
    return THEME_PRESETS.get(name.strip().lower(), LIGHT_THEME)
