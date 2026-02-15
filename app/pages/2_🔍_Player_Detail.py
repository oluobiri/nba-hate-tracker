"""Player Detail — deep dive on a single player's sentiment profile.

Shows player card, sentiment breakdown bar, and flair breakdown tables
(most hostile / most friendly fanbases).
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from utils.data import (
    SENTIMENT_COLORS,
    filter_by_threshold,
    format_rate,
    format_sentiment,
    get_player_rank,
    load_data,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Player Detail — r/NBA Hate Tracker",
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

data = load_data()
player_overall = data["player_overall"]
player_team = data["player_team"]
player_metadata = data["player_metadata"]
all_players = sorted(player_overall["attributed_player"].tolist())

# ---------------------------------------------------------------------------
# Player selector (with query param support)
# ---------------------------------------------------------------------------

st.title("Player Sentiment Profile")

default_player = st.query_params.get("player", "Draymond Green")
if default_player not in all_players:
    default_player = "Draymond Green"

selected_player = st.selectbox(
    "Search for a player",
    options=all_players,
    index=all_players.index(default_player),
    key="player_select",
)

# ---------------------------------------------------------------------------
# Player card
# ---------------------------------------------------------------------------

player_row = player_overall[
    player_overall["attributed_player"] == selected_player
].iloc[0]

meta = player_metadata.get(selected_player)
team_name = meta["team"] if meta else "Unknown"
headshot_url = meta.get("headshot_url") if meta else None

col_img, col_info = st.columns([1, 3])

with col_img:
    if headshot_url:
        st.image(headshot_url, width=180)

with col_info:
    st.subheader(f"{selected_player}")
    st.caption(team_name)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Negative Rate", format_rate(player_row["neg_rate"]))
    m2.metric("Positive Rate", format_rate(player_row["pos_rate"]))
    m3.metric("Net Sentiment", format_sentiment(player_row["net_sentiment"]))
    m4.metric("Polarization", format_rate(player_row["polarization"]))

    # Rank at 5K threshold
    filtered_5k = filter_by_threshold(player_overall, 5_000)
    rank = get_player_rank(
        selected_player, filtered_5k, "neg_rate", ascending=False
    )
    if rank is not None:
        st.caption(
            f"Rank: **#{rank}** most hated (of {len(filtered_5k)} players "
            f"at 5K threshold) · {player_row['comment_count']:,} comments"
        )
    else:
        st.caption(
            f"{player_row['comment_count']:,} comments "
            f"(below 5K threshold — unranked)"
        )

# ---------------------------------------------------------------------------
# Sentiment breakdown bar
# ---------------------------------------------------------------------------

st.subheader("Sentiment Breakdown")

neg_pct = player_row["neg_rate"] * 100
pos_pct = player_row["pos_rate"] * 100
neu_pct = 100 - neg_pct - pos_pct

fig = go.Figure()
for label, value, color in [
    ("Negative", neg_pct, SENTIMENT_COLORS["negative"]),
    ("Neutral", neu_pct, SENTIMENT_COLORS["neutral"]),
    ("Positive", pos_pct, SENTIMENT_COLORS["positive"]),
]:
    fig.add_trace(
        go.Bar(
            y=["Sentiment"],
            x=[value],
            name=label,
            orientation="h",
            marker_color=color,
            text=f"{value:.1f}%",
            textposition="inside",
            textfont=dict(size=14),
            hovertemplate=f"{label}: {value:.1f}%<extra></extra>",
        )
    )

fig.update_layout(
    barmode="stack",
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=100,
    margin=dict(l=0, r=0, t=0, b=0),
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    xaxis=dict(visible=False, range=[0, 100]),
    yaxis=dict(visible=False),
)

st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Flair breakdown tables
# ---------------------------------------------------------------------------

player_flair = player_team[
    player_team["attributed_player"] == selected_player
].copy()

if player_flair.empty:
    st.info("No flair breakdown data available for this player.")
    st.stop()

# Compute delta vs overall neg_rate
overall_neg_rate = player_row["neg_rate"]
player_flair["delta"] = player_flair["neg_rate"] - overall_neg_rate

# Join team logo URLs from team_overall
team_overall = data["team_overall"]
logo_map = team_overall.set_index("team")["logo_url"].to_dict()
player_flair["logo_url"] = player_flair["team"].map(logo_map)

# Most hostile fanbases
st.subheader(f"Which Fanbases Hate {selected_player} Most?")

hostile = (
    player_flair.sort_values("neg_rate", ascending=False)
    .head(10)
    .reset_index(drop=True)
    .copy()
)
hostile.index = hostile.index + 1
hostile.index.name = "Rank"

# Convert 0-1 rates to 0-100 for printf-style formatting
hostile["neg_rate_pct"] = hostile["neg_rate"] * 100
hostile["pos_rate_pct"] = hostile["pos_rate"] * 100
hostile["delta_pct"] = hostile["delta"] * 100

st.dataframe(
    hostile,
    column_config={
        "logo_url": st.column_config.ImageColumn("", width="small"),
        "team": st.column_config.TextColumn("Team"),
        "neg_rate_pct": st.column_config.NumberColumn(
            "Neg Rate", format="%.1f%%", help="Negative comment rate"
        ),
        "pos_rate_pct": st.column_config.NumberColumn(
            "Pos Rate", format="%.1f%%", help="Positive comment rate"
        ),
        "delta_pct": st.column_config.NumberColumn(
            "Δ vs Avg", format="%+.1f pp", help="Delta vs player's overall neg rate"
        ),
        "comment_count": st.column_config.NumberColumn("Comments", format="%d"),
    },
    column_order=[
        "logo_url", "team", "neg_rate_pct", "pos_rate_pct", "delta_pct", "comment_count",
    ],
    hide_index=False,
    use_container_width=True,
)

# Most friendly fanbases
st.subheader(f"Which Fanbases Defend {selected_player} Most?")

friendly = (
    player_flair.sort_values("neg_rate", ascending=True)
    .head(10)
    .reset_index(drop=True)
    .copy()
)
friendly.index = friendly.index + 1
friendly.index.name = "Rank"

friendly["neg_rate_pct"] = friendly["neg_rate"] * 100
friendly["pos_rate_pct"] = friendly["pos_rate"] * 100
friendly["delta_pct"] = friendly["delta"] * 100

st.dataframe(
    friendly,
    column_config={
        "logo_url": st.column_config.ImageColumn("", width="small"),
        "team": st.column_config.TextColumn("Team"),
        "neg_rate_pct": st.column_config.NumberColumn(
            "Neg Rate", format="%.1f%%", help="Negative comment rate"
        ),
        "pos_rate_pct": st.column_config.NumberColumn(
            "Pos Rate", format="%.1f%%", help="Positive comment rate"
        ),
        "delta_pct": st.column_config.NumberColumn(
            "Δ vs Avg", format="%+.1f pp", help="Delta vs player's overall neg rate"
        ),
        "comment_count": st.column_config.NumberColumn("Comments", format="%d"),
    },
    column_order=[
        "logo_url", "team", "neg_rate_pct", "pos_rate_pct", "delta_pct", "comment_count",
    ],
    hide_index=False,
    use_container_width=True,
)
