"""About / Methodology — how the data was collected and processed.

Pipeline funnel, metric definitions, example classifications, limitations,
and external links.
"""

from __future__ import annotations

import streamlit as st

from utils.data import load_data

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="About — r/NBA Hate Tracker",
    page_icon="ℹ️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

data = load_data()
metadata = data["metadata"]

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("About / Methodology")
st.caption(
    "How we measured which NBA player r/NBA hates the most "
    f"({metadata['season']} season)"
)

# ---------------------------------------------------------------------------
# Pipeline funnel
# ---------------------------------------------------------------------------

st.subheader("Data Pipeline")

f1, f2, f3, f4 = st.columns(4)
f1.metric("Total Comments", f"{metadata['total_comments']:,}")
f2.metric("Usable Comments", f"{metadata['usable_comments']:,}")
f3.metric("Attributed to Players", f"{metadata['attributed_comments']:,}")
f4.metric("Players Tracked", f"{metadata['player_count']}")

st.markdown(
    f"""
1. **Collected** {metadata['total_comments']:,} comments from r/NBA
   (Oct 2024 – Jun 2025) via Arctic Shift
2. **Filtered** to {metadata['usable_comments']:,} usable comments
   ({metadata['excluded_comments']:,} excluded for length / bots / deleted)
3. **Classified** sentiment with Claude Haiku 4.5
   (negative / neutral / positive)
4. **Attributed** {metadata['attributed_comments']:,} comments to
   {metadata['player_count']} specific players across {metadata['week_count']} weeks
"""
)

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("What the Metrics Mean")

st.markdown(
    """
| Metric | Plain English |
|---|---|
| **Negative Rate** | % of comments about this player that were negative |
| **Positive Rate** | % of comments that were positive |
| **Net Sentiment** | (positive − negative) / total — ranges from −1 to +1 |
| **Polarization** | % of comments that were NOT neutral — high means strong opinions |
"""
)

# ---------------------------------------------------------------------------
# Example classifications
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Example Classifications")

with st.expander("See how the classifier works"):
    st.markdown(
        """
**Negative example:**
> "He's the dirtiest player in the league and shouldn't be allowed to play.
> Constant cheap shots and whining to the refs."

Classification: **Negative** — personal criticism with hostile tone.

---

**Positive example:**
> "His defense has been incredible this season. Best two-way player
> in the league and it's not even close."

Classification: **Positive** — admiration with superlative praise.

---

**Neutral example:**
> "He's averaging 22/8/5 on 45% shooting. Moved to the bench last week
> after the trade."

Classification: **Neutral** — factual stats and reporting, no opinion expressed.
"""
    )

# ---------------------------------------------------------------------------
# Limitations
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Limitations")

with st.expander("Known limitations and caveats"):
    st.markdown(
        """
- **Classifier accuracy ~95%** — validated against human labels on a
  500-comment sample. Edge cases (sarcasm, backhanded compliments) are
  the main failure mode.
- **Comments without team flair (~40%)** are excluded from the Flair View.
  Only flaired comments appear in the team-level cross-tabs.
- **Players with <5,000 comments** may have unstable rates — small samples
  are more sensitive to a single viral thread. The threshold slider on the
  Leaderboard lets you filter these out.
- **Sentiment ≠ hate** — a factual criticism ("he shot 2-15 last night")
  and a personal attack both register as "negative." The metric measures
  negativity of discourse, not pure hostility.
- **One season only** — results reflect the 2024-25 season. Player
  sentiment shifts with trades, injuries, and playoff performance.
"""
    )

# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Links")

st.markdown(
    """
- **GitHub:** [nba-hate-tracker repository](https://github.com/oluobiri/nba-hate-tracker)
- **Bar Race Chart:** Coming soon
- **r/NBA Post:** Coming soon
"""
)
