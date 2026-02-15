"""Leaderboard — home page of the NBA Hate Tracker dashboard.

Ranked player sentiment with adjustable metric, volume threshold, and
interactive scatter plot. Entry point: ``streamlit run app/streamlit_app.py``.
"""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from utils.data import (
    METRIC_CONFIG,
    enrich_with_metadata,
    filter_by_threshold,
    format_rate,
    format_sentiment,
    load_data,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="r/NBA Hate Tracker",
    page_icon="🏀",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

data = load_data()
player_overall = data["player_overall"]
player_metadata = data["player_metadata"]
metadata = data["metadata"]

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("r/NBA Hate Tracker: " + metadata["season"] + " Season")
st.caption(
    f"{metadata['attributed_comments']:,} comments analyzed across "
    f"{metadata['player_count']} players"
)

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

col_metric, col_threshold, col_topn = st.columns([2, 2, 1])

with col_metric:
    selected_metric_label = st.selectbox(
        "Metric",
        options=list(METRIC_CONFIG.keys()),
        index=0,
    )

metric_cfg = METRIC_CONFIG[selected_metric_label]
metric_col = metric_cfg["column"]
metric_ascending = metric_cfg["ascending"]
metric_fmt = metric_cfg["format"]

with col_threshold:
    threshold = st.slider(
        "Minimum comments",
        min_value=500,
        max_value=50_000,
        value=5_000,
        step=500,
    )

filtered = filter_by_threshold(player_overall, threshold)
enriched = enrich_with_metadata(filtered, player_metadata)

with col_threshold:
    st.caption(f"{len(enriched)} of {metadata['player_count']} players shown")

with col_topn:
    max_n = min(50, len(enriched))
    top_n = st.slider(
        "Show top N",
        min_value=10,
        max_value=max(10, max_n),
        value=min(20, max_n),
    )

# ---------------------------------------------------------------------------
# Podium — top 3 visual hook
# ---------------------------------------------------------------------------

_fmt = format_rate if metric_fmt == "rate" else format_sentiment
top3 = (
    enriched.sort_values(metric_col, ascending=metric_ascending)
    .head(3)
    .reset_index(drop=True)
)

# Display order: #2 (left), #1 (center), #3 (right)
_podium_order = [(1, "🥈", 80), (0, "🥇", 120), (2, "🥉", 80)]
podium_cols = st.columns(3)
for col, (rank_idx, medal, img_width) in zip(podium_cols, _podium_order):
    if rank_idx >= len(top3):
        continue
    row = top3.iloc[rank_idx]
    with col:
        with st.container(border=True):
            headshot = row.get("headshot_url")
            if headshot:
                st.image(headshot, width=img_width)
            st.markdown(f"**{medal} {row['attributed_player']}**")
            st.markdown(f"### {_fmt(row[metric_col])}")

# ---------------------------------------------------------------------------
# Leaderboard table
# ---------------------------------------------------------------------------

leaderboard = (
    enriched.sort_values(metric_col, ascending=metric_ascending)
    .head(top_n)
    .reset_index(drop=True)
)
leaderboard.index = leaderboard.index + 1
leaderboard.index.name = "Rank"

# Build display-friendly metric column
if metric_fmt == "rate":
    number_format = "%.1f%%"
    leaderboard["metric_display"] = leaderboard[metric_col] * 100
else:
    number_format = "%+.3f"
    leaderboard["metric_display"] = leaderboard[metric_col]

st.dataframe(
    leaderboard,
    column_config={
        "headshot_url": st.column_config.ImageColumn("", width="small"),
        "attributed_player": st.column_config.TextColumn("Player"),
        "team": st.column_config.TextColumn("Team"),
        "metric_display": st.column_config.NumberColumn(
            selected_metric_label,
            format=number_format,
        ),
        "comment_count": st.column_config.NumberColumn(
            "Comments",
            format="%d",
        ),
    },
    column_order=[
        "headshot_url",
        "attributed_player",
        "team",
        "metric_display",
        "comment_count",
    ],
    hide_index=False,
    use_container_width=True,
    height=min(35 * top_n + 38, 800),
)

# ---------------------------------------------------------------------------
# Scatter plot
# ---------------------------------------------------------------------------

st.subheader("Volume vs. Sentiment")

scatter_df = enrich_with_metadata(filtered, player_metadata).copy()

fig = px.scatter(
    scatter_df,
    x="comment_count",
    y=metric_col,
    color="conference",
    color_discrete_map={"East": "#3498DB", "West": "#E67E22"},
    hover_name="attributed_player",
    hover_data={
        "team": True,
        "neg_rate": ":.1%",
        "pos_rate": ":.1%",
        "net_sentiment": ":+.3f",
        "comment_count": ":,",
        "conference": False,
    },
    log_x=True,
    labels={
        "comment_count": "Comment Count",
        metric_col: selected_metric_label,
    },
)

# Annotate outliers
outliers = ["Draymond Green", "Luka Dončić", "Nikola Jokić", "Victor Wembanyama"]
for name in outliers:
    row = scatter_df[scatter_df["attributed_player"] == name]
    if row.empty:
        continue
    fig.add_annotation(
        x=row["comment_count"].iloc[0],
        y=row[metric_col].iloc[0],
        text=name.split()[-1],  # Last name only
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowcolor="#FAFAFA",
        font=dict(size=11, color="#FAFAFA"),
        ax=20,
        ay=-25,
    )

fig.update_layout(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=500,
    legend=dict(title="Conference"),
    xaxis=dict(
        fixedrange=True,
        tickvals=[500, 1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000],
        ticktext=["500", "1K", "2.5K", "5K", "10K", "25K", "50K", "100K"],
    ),
    yaxis=dict(
        fixedrange=True,
        tickformat=".0%",
    ),
)

event = st.plotly_chart(
    fig,
    use_container_width=True,
    on_select="rerun",
    key="scatter",
)

# Handle scatter click → navigate to player detail.
# Streamlit's on_select doesn't reliably pass customdata, so look up
# the player by matching the clicked point's x coordinate (comment_count
# is unique per player in the filtered set).
if event and event.selection and event.selection.points:
    pt = event.selection.points[0]
    match = scatter_df[scatter_df["comment_count"] == pt["x"]]
    if not match.empty:
        st.query_params["player"] = match.iloc[0]["attributed_player"]
        st.switch_page("pages/2_🔍_Player_Detail.py")
