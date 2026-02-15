"""Flair View — pick your team, see your fanbase's sentiment profile.

Shows most hated/loved player cards, fanbase baseline stats, and mini
leaderboards for the selected team's flair.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.data import (
    format_rate,
    get_player_rank,
    load_data,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Flair View — r/NBA Hate Tracker",
    page_icon="👥",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

data = load_data()
player_team = data["player_team"]
team_overall = data["team_overall"]
player_metadata = data["player_metadata"]
player_overall = data["player_overall"]

all_teams = sorted(team_overall["team"].tolist())

# ---------------------------------------------------------------------------
# Team selector
# ---------------------------------------------------------------------------

st.title("Your Fanbase's Sentiment Profile")

default_team = st.query_params.get("team", None)
default_idx = 0
if default_team and default_team in all_teams:
    default_idx = all_teams.index(default_team) + 1

team_options = ["Select your team..."] + all_teams
selected_team = st.selectbox(
    "Team",
    options=team_options,
    index=default_idx,
    key="team_select",
)

if selected_team == "Select your team...":
    st.info("Pick a team from the dropdown to explore your fanbase's sentiment.")
    st.stop()

# ---------------------------------------------------------------------------
# Filter data for selected team
# ---------------------------------------------------------------------------

team_flair_all = player_team[player_team["team"] == selected_team].copy()
team_row = team_overall[team_overall["team"] == selected_team].iloc[0]

# Filter to players at or above median comment count for this fanbase.
# Eliminates thin cells (e.g. 100% on 1 comment) while scaling naturally
# per fanbase — large fanbases keep more players than small ones.
median_cc = int(team_flair_all["comment_count"].median())
team_flair = team_flair_all[team_flair_all["comment_count"] >= median_cc].copy()

st.caption(
    f"Showing {len(team_flair)} of {len(team_flair_all)} players "
    f"(≥{median_cc} comments by this fanbase)"
)

# ---------------------------------------------------------------------------
# Most Hated / Most Loved cards
# ---------------------------------------------------------------------------

most_hated = team_flair.sort_values("neg_rate", ascending=False).iloc[0]
most_loved = team_flair.sort_values("pos_rate", ascending=False).iloc[0]


def _player_card(
    label: str,
    player_name: str,
    rate: float,
    rate_label: str,
    comments: int,
) -> None:
    """Render a bordered player card with headshot and stats.

    Args:
        label: Card header (e.g. "MOST HATED").
        player_name: Player display name.
        rate: Primary rate value (0-1).
        rate_label: Label for the rate metric.
        comments: Number of comments.
    """
    meta = player_metadata.get(player_name)
    headshot = meta.get("headshot_url") if meta else None

    with st.container(border=True):
        st.markdown(f"**{label}**")
        if headshot:
            st.image(headshot, width=120)
        st.markdown(f"### {player_name}")
        st.metric(rate_label, format_rate(rate))
        st.caption(f"{comments:,} comments")


col_hated, col_loved = st.columns(2)

with col_hated:
    _player_card(
        label="🔴 MOST HATED",
        player_name=most_hated["attributed_player"],
        rate=most_hated["neg_rate"],
        rate_label="Negative Rate",
        comments=int(most_hated["comment_count"]),
    )

with col_loved:
    _player_card(
        label="🟢 MOST LOVED",
        player_name=most_loved["attributed_player"],
        rate=most_loved["pos_rate"],
        rate_label="Positive Rate",
        comments=int(most_loved["comment_count"]),
    )

# ---------------------------------------------------------------------------
# Fanbase baseline
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Fanbase Baseline")

# Rank among 30 fanbases by neg_rate (most negative = rank 1)
neg_rank = get_player_rank(
    selected_team,
    team_overall.rename(columns={"team": "attributed_player"}),
    "neg_rate",
    ascending=False,
)

b1, b2, b3, b4 = st.columns(4)
b1.metric("Negative Rate", format_rate(team_row["neg_rate"]))
b2.metric("Positive Rate", format_rate(team_row["pos_rate"]))
b3.metric("Total Comments", f"{int(team_row['comment_count']):,}")
if neg_rank is not None:
    b4.metric("Negativity Rank", f"#{neg_rank} of 30")

# ---------------------------------------------------------------------------
# Most discussed bar chart
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader(f"Most Discussed Players by {selected_team} Fans")

top_discussed = (
    team_flair.sort_values("comment_count", ascending=False)
    .head(10)
    .sort_values("comment_count", ascending=True)  # ascending for horizontal bar
)

fig_discussed = px.bar(
    top_discussed,
    x="comment_count",
    y="attributed_player",
    orientation="h",
    labels={"comment_count": "Comments", "attributed_player": ""},
    text="comment_count",
)
fig_discussed.update_traces(
    marker_color="#3498DB",
    texttemplate="%{text:,}",
    textposition="outside",
)
fig_discussed.update_layout(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=400,
    margin=dict(l=0, r=40, t=0, b=0),
    xaxis=dict(visible=False),
    yaxis=dict(tickfont=dict(size=13)),
)

st.plotly_chart(fig_discussed, use_container_width=True)

# ---------------------------------------------------------------------------
# Mini leaderboards
# ---------------------------------------------------------------------------


def _mini_leaderboard(
    title: str,
    df_sorted: pd.DataFrame,
    metric_col: str,
    metric_label: str,
) -> None:
    """Render a top-10 mini leaderboard table with headshots.

    Args:
        title: Section header text.
        df_sorted: Pre-sorted DataFrame to take top 10 from.
        metric_col: Column name for the primary metric.
        metric_label: Display label for the metric column.
    """
    top10 = df_sorted.head(10).reset_index(drop=True).copy()
    top10.index = top10.index + 1
    top10.index.name = "Rank"

    # Join headshot URLs
    top10["headshot_url"] = top10["attributed_player"].map(
        lambda p: player_metadata.get(p, {}).get("headshot_url")
    )

    # Convert 0-1 rate to 0-100 for printf-style formatting
    display_col = f"{metric_col}_pct"
    top10[display_col] = top10[metric_col] * 100

    st.subheader(title)
    st.dataframe(
        top10,
        column_config={
            "headshot_url": st.column_config.ImageColumn("", width="small"),
            "attributed_player": st.column_config.TextColumn("Player"),
            display_col: st.column_config.NumberColumn(
                metric_label, format="%.1f%%"
            ),
            "comment_count": st.column_config.NumberColumn("Comments", format="%d"),
        },
        column_order=[
            "headshot_url",
            "attributed_player",
            display_col,
            "comment_count",
        ],
        hide_index=False,
        use_container_width=True,
    )


st.markdown("---")

_mini_leaderboard(
    f"Top 10 Most Hated by {selected_team} Fans",
    team_flair.sort_values("neg_rate", ascending=False),
    "neg_rate",
    "Neg Rate",
)

jump_hated = st.selectbox(
    "Jump to player detail",
    options=[""] + sorted(team_flair["attributed_player"].tolist()),
    index=0,
    key="jump_hated",
)
if jump_hated:
    st.query_params["player"] = jump_hated
    st.switch_page("pages/2_🔍_Player_Detail.py")

st.markdown("---")

_mini_leaderboard(
    f"Top 10 Most Loved by {selected_team} Fans",
    team_flair.sort_values("pos_rate", ascending=False),
    "pos_rate",
    "Pos Rate",
)

jump_loved = st.selectbox(
    "Jump to player detail",
    options=[""] + sorted(team_flair["attributed_player"].tolist()),
    index=0,
    key="jump_loved",
)
if jump_loved:
    st.query_params["player"] = jump_loved
    st.switch_page("pages/2_🔍_Player_Detail.py")
