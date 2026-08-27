"""Shared colour + type constants for the dashboard, so every chart draws
from the same fixed palette instead of Plotly's default qualitative rainbow.

Colour encodes taxonomy GROUP (7 values), not individual category (26) —
with that many categories a distinct hue each stops being readable at a
glance. One accent colour is reserved exclusively for spikes/alerts so it
carries meaning whenever it appears, instead of blending into a busy chart.
"""
from __future__ import annotations

# --- neutrals ---
BG = "#FFFFFF"
TEXT = "#1F2430"
TEXT_MUTED = "#6B7280"
BORDER = "#E5E7EB"
SURFACE = "#F7F8FA"

# --- accent: reserved for spikes / alerts only ---
ACCENT = "#E4572E"
ACCENT_SOFT = "#FDEEE9"  # background tint for alert cards/rows

# --- one fixed hue per taxonomy group, reused identically everywhere ---
GROUP_COLORS: dict[str, str] = {
    "Order & shipping": "#4C72B0",
    "Returns & refunds": "#55A868",
    "Product": "#8172B2",
    "Payments & billing": "#CCB974",
    "Account": "#64B5CD",
    "Loyalty": "#937860",
    "General": "#8C8C8C",
}

# --- type scale ---
FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
KPI_NUMBER_SIZE = "2.5rem"
KPI_NUMBER_WEIGHT = "700"
QUESTION_TITLE_SIZE = "1.1rem"
QUESTION_TITLE_WEIGHT = "600"
CAPTION_SIZE = "0.85rem"
CAPTION_WEIGHT = "400"

CUSTOM_CSS = f"""
<style>
html, body, [class*="css"] {{
    font-family: {FONT_FAMILY};
}}
.kpi-card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 1rem 1.25rem;
}}
.kpi-card.alert {{
    background: {ACCENT_SOFT};
    border-color: {ACCENT};
}}
.kpi-label {{
    font-size: {CAPTION_SIZE};
    font-weight: {CAPTION_WEIGHT};
    color: {TEXT_MUTED};
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 0.25rem;
}}
.kpi-number {{
    font-size: {KPI_NUMBER_SIZE};
    font-weight: {KPI_NUMBER_WEIGHT};
    color: {TEXT};
    line-height: 1.1;
}}
.kpi-card.alert .kpi-number {{
    color: {ACCENT};
}}
.kpi-delta {{
    font-size: {CAPTION_SIZE};
    color: {TEXT_MUTED};
    margin-top: 0.25rem;
}}
.question-title {{
    font-size: {QUESTION_TITLE_SIZE};
    font-weight: {QUESTION_TITLE_WEIGHT};
    color: {TEXT};
    margin-bottom: 0.5rem;
}}
.caption-text {{
    font-size: {CAPTION_SIZE};
    color: {TEXT_MUTED};
}}
</style>
"""


def group_color(group: str) -> str:
    return GROUP_COLORS.get(group, TEXT_MUTED)


def kpi_card_html(label: str, number: str, delta: str | None = None, alert: bool = False) -> str:
    css_class = "kpi-card alert" if alert else "kpi-card"
    delta_html = f'<div class="kpi-delta">{delta}</div>' if delta else ""
    return f"""
    <div class="{css_class}">
        <div class="kpi-label">{label}</div>
        <div class="kpi-number">{number}</div>
        {delta_html}
    </div>
    """
