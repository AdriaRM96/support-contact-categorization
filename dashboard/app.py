"""NovaCart support contact categorisation dashboard.

Built for one reader: a NovaCart ops manager checking in between meetings.
Three questions answered at a glance, no drilling down required:
    1. What's driving contacts right now?
    2. Is anything spiking?
    3. Is the triage -> final pipeline healthy?
Everything else (time series detail, disagreement pairs, raw filters) is
one click away in the "Filters & drill-down" section below.

Local-first: reads a classified ticket export (CSV) produced by
notebooks/03_build_classified_export.ipynb — no GCP project required.

Run with:
    streamlit run app.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from theme import ACCENT, CUSTOM_CSS, GROUP_COLORS, kpi_card_html

DEFAULT_DATA_PATH = Path(__file__).parent.parent / "outputs" / "tickets_classified.csv"
SPIKE_MIN_PCT_CHANGE = 30  # % week-over-week increase to flag as a spike
SPIKE_MIN_VOLUME = 5  # ignore tiny categories where a 30% swing is just noise
HEALTHY_AGREEMENT_THRESHOLD = 0.85  # below this, the pipeline-health tile turns to the accent colour

st.set_page_config(page_title="NovaCart Support Contacts", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


@st.cache_data
def load_data(path: Path) -> pd.DataFrame:
    # TODO (Phase 4): if a deployed BigQuery pipeline is available, swap this
    # for a `pandas_gbq.read_gbq(...)` call behind a BQ_DATASET env var,
    # gated by whether GCP_PROJECT_ID is set — everything below reads from
    # a plain DataFrame so the rest of the app doesn't need to change.
    df = pd.read_csv(path, parse_dates=["created_at", "updated_at"])
    df["date"] = df["created_at"].dt.date
    df["week"] = df["created_at"].dt.to_period("W").apply(lambda p: p.start_time.date())
    # For "what kind of issue is this" purposes, prefer the final category
    # once it exists (it's authoritative); fall back to triage for tickets
    # still open.
    df["category"] = df["predicted_category_final"].fillna(df["predicted_category_triage"])
    df["group"] = df["predicted_group_final"].fillna(df["predicted_group_triage"])
    return df


if not DEFAULT_DATA_PATH.exists():
    st.error(
        f"No classified export found at `{DEFAULT_DATA_PATH}`. "
        "Run notebooks/03_build_classified_export.ipynb first to generate it."
    )
    st.stop()

df = load_data(DEFAULT_DATA_PATH)

st.title("NovaCart — Support Contact Categorisation")
st.markdown(
    '<p class="caption-text">Simulated Zendesk-style ticket stream, classified by the two-stage pipeline '
    "(triage on the first message, final classification on ticket close).</p>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Filters & drill-down (collapsed by default — headline view needs none of this)
# ---------------------------------------------------------------------------
with st.expander("Filters & drill-down", expanded=False):
    min_date, max_date = df["date"].min(), df["date"].max()
    date_range = st.date_input(
        "Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = min_date, max_date

    channels = st.multiselect(
        "Channel", options=sorted(df["via_channel"].unique()), default=sorted(df["via_channel"].unique())
    )
    groups_selected = st.multiselect(
        "Group", options=sorted(df["group"].dropna().unique()), default=sorted(df["group"].dropna().unique())
    )
    statuses = st.multiselect(
        "Status", options=sorted(df["status"].unique()), default=sorted(df["status"].unique())
    )

mask = (
    (df["date"] >= start_date)
    & (df["date"] <= end_date)
    & (df["via_channel"].isin(channels))
    & (df["group"].isin(groups_selected))
    & (df["status"].isin(statuses))
)
filtered = df[mask]

if filtered.empty:
    st.info("No tickets match the current filters. Widen the date range or filters above to see data.")
    st.stop()

# ---------------------------------------------------------------------------
# Headline KPIs — the one bold moment on the page
# ---------------------------------------------------------------------------
weeks_sorted = sorted(filtered["week"].unique())
latest_week = weeks_sorted[-1]
prior_week = weeks_sorted[-2] if len(weeks_sorted) >= 2 else None

this_week_count = int((filtered["week"] == latest_week).sum())
prior_week_count = int((filtered["week"] == prior_week).sum()) if prior_week else None
if prior_week_count:
    week_delta_pct = (this_week_count - prior_week_count) / prior_week_count * 100
    week_delta_str = f"{'▲' if week_delta_pct >= 0 else '▼'} {abs(week_delta_pct):.0f}% vs prior week"
else:
    week_delta_str = "no prior week to compare"

# Spike detection: categories whose latest-week volume rose sharply.
weekly_cat = filtered.groupby(["week", "category"]).size().reset_index(name="contacts")
spikes = pd.DataFrame()
if prior_week:
    pivot = weekly_cat.pivot(index="category", columns="week", values="contacts").fillna(0)
    trend = pd.DataFrame({"prior_week": pivot.get(prior_week, 0), "latest_week": pivot.get(latest_week, 0)})
    trend["change"] = trend["latest_week"] - trend["prior_week"]
    trend["pct_change"] = (trend["change"] / trend["prior_week"].replace(0, pd.NA)) * 100
    spikes = trend[
        (trend["pct_change"] >= SPIKE_MIN_PCT_CHANGE) & (trend["latest_week"] >= SPIKE_MIN_VOLUME)
    ].sort_values("pct_change", ascending=False)

n_spikes = len(spikes)

# Pipeline health: triage/final agreement rate on closed tickets.
closed_filtered = filtered[filtered["predicted_category_final"].notna()]
agreement_rate = 1 - closed_filtered["category_disagreement"].mean() if len(closed_filtered) else None

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(
        kpi_card_html("Contacts this week", f"{this_week_count:,}", week_delta_str),
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        kpi_card_html(
            "Spiking categories",
            str(n_spikes),
            "week-over-week volume jump" if n_spikes else "nothing unusual this week",
            alert=n_spikes > 0,
        ),
        unsafe_allow_html=True,
    )
with col3:
    if agreement_rate is not None:
        healthy = agreement_rate >= HEALTHY_AGREEMENT_THRESHOLD
        st.markdown(
            kpi_card_html(
                "Pipeline health",
                f"{agreement_rate:.0%}",
                "triage/final agreement" + ("" if healthy else " — below target"),
                alert=not healthy,
            ),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(kpi_card_html("Pipeline health", "n/a", "no closed tickets in range"), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Question 1: what's driving contacts — the dominant middle panel
# ---------------------------------------------------------------------------
st.markdown('<div class="question-title">Which issues are driving contacts this week?</div>', unsafe_allow_html=True)

week_df = filtered[filtered["week"] == latest_week]
if week_df.empty:
    st.info("No contacts recorded for the most recent week in range.")
else:
    cat_counts = (
        week_df.groupby(["group", "category"]).size().reset_index(name="contacts").sort_values("contacts", ascending=False)
    )
    fig = px.bar(
        cat_counts, x="contacts", y="category", color="group", orientation="h",
        color_discrete_map=GROUP_COLORS,
        height=650,
    )
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        plot_bgcolor="white", paper_bgcolor="white",
        legend_title_text="Group",
        margin=dict(l=0, r=0, t=10, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Question 2: what's spiking — secondary panel, only shown when relevant
# ---------------------------------------------------------------------------
st.markdown('<div class="question-title">Which categories are trending up?</div>', unsafe_allow_html=True)
if n_spikes:
    spike_display = spikes.reset_index().rename(columns={"index": "category"})
    spike_display["pct_change"] = spike_display["pct_change"].map(lambda v: f"+{v:.0f}%")

    def _highlight_spike(row):
        return [f"background-color: {ACCENT}22"] * len(row)

    st.dataframe(
        spike_display[["category", "prior_week", "latest_week", "pct_change"]].style.apply(_highlight_spike, axis=1),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No category spiked more than 30% week-over-week — nothing urgent to flag.")

st.divider()

# ---------------------------------------------------------------------------
# Drill-down: time series, category totals across the full range, disagreement detail
# ---------------------------------------------------------------------------
with st.expander("More detail: time series, full breakdown, disagreement cases", expanded=False):
    st.markdown("**Contact volume over time**")
    tab_daily, tab_weekly = st.tabs(["Daily", "Weekly"])
    with tab_daily:
        daily = filtered.groupby(["date", "group"]).size().reset_index(name="contacts")
        fig = px.bar(daily, x="date", y="contacts", color="group", color_discrete_map=GROUP_COLORS)
        fig.update_layout(plot_bgcolor="white", paper_bgcolor="white", margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)
    with tab_weekly:
        weekly = filtered.groupby(["week", "group"]).size().reset_index(name="contacts")
        fig = px.bar(weekly, x="week", y="contacts", color="group", color_discrete_map=GROUP_COLORS)
        fig.update_layout(plot_bgcolor="white", paper_bgcolor="white", margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Category totals across the full filtered range**")
    cat_counts_all = (
        filtered.groupby(["group", "category"]).size().reset_index(name="contacts").sort_values("contacts", ascending=False)
    )
    fig = px.bar(
        cat_counts_all, x="contacts", y="category", color="group", orientation="h",
        color_discrete_map=GROUP_COLORS, height=700,
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, plot_bgcolor="white", paper_bgcolor="white", margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Triage vs. final classification disagreement**")
    st.markdown(
        '<p class="caption-text">Cases where the first-message triage category didn\'t match the full-thread '
        "final category — worth watching in its own right, not just noise.</p>",
        unsafe_allow_html=True,
    )
    if len(closed_filtered):
        pair_counts = (
            closed_filtered[closed_filtered["category_disagreement"]]
            .groupby(["predicted_category_triage", "predicted_category_final"])
            .size()
            .reset_index(name="count")
            .sort_values("count", ascending=False)
        )
        if len(pair_counts):
            st.markdown("*Most common triage → final disagreements*")
            st.dataframe(pair_counts, use_container_width=True, hide_index=True)

            st.markdown("*Sample disagreement tickets*")
            sample = (
                closed_filtered[closed_filtered["category_disagreement"]][
                    ["id", "subject", "predicted_category_triage", "predicted_category_final", "created_at"]
                ]
                .sort_values("created_at", ascending=False)
                .head(20)
            )
            st.dataframe(sample, use_container_width=True, hide_index=True)
        else:
            st.info("No disagreement cases in the current filter.")
    else:
        st.info("No closed, final-classified tickets in the current filter.")
