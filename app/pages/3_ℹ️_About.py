"""About / Methodology — how the data was collected and processed.

Pipeline funnel, metric definitions, example classifications, limitations,
and external links.
"""

from __future__ import annotations

from pathlib import Path

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

st.title("How It Works")

# ---------------------------------------------------------------------------
# Pipeline funnel
# ---------------------------------------------------------------------------

st.subheader("Data Pipeline")

# Architecture diagram — app/pages/ → app/ → repo root → docs/assets/
arch_path = Path(__file__).resolve().parent.parent.parent / "docs" / "assets" / "architecture.svg"
if arch_path.exists():
    st.image(str(arch_path), use_container_width=True)

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
   ({metadata['excluded_comments']:,} excluded due to classification errors)
3. **Classified** sentiment with Claude Haiku 4.5
   (negative / neutral / positive)
4. **Attributed** {metadata['attributed_comments']:,} comments to
   {metadata['player_count']} specific players across {metadata['week_count']} weeks
"""
)

with st.expander("Pipeline details"):
    st.markdown(
        """
- **Raw scale:** Started from ~7 million r/NBA comments (12.7 GB),
  filtered to 1.9M that mention specific players.
- **Sentiment distribution:** 32% negative, 45% neutral, 23% positive —
  roughly one in three player-related comments is negative.
- **Classifier:** Claude Haiku 4.5 via the Anthropic Batch API.
  Total cost: $254 for the full season.
- **Attribution rate:** 83% of usable comments were matched to a specific
  player; the remaining 17% mentioned multiple players ambiguously.
"""
    )

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("What the Metrics Mean")

st.markdown(
    """
| Metric | Plain English | What it captures |
|---|---|---|
| **Negative Rate** | % of comments about this player that were negative | Pure hate concentration — "how toxic is the conversation?" |
| **Positive Rate** | % of comments that were positive | Pure love concentration — "how much praise?" |
| **Net Sentiment** | (positive − negative) / total — ranges from −1 to +1 | Balance of opinion — rewards not being hated as much as being loved |
| **Polarization** | % of comments that were NOT neutral — high means strong opinions | Strength of reaction regardless of direction |

> **Why four metrics?** They tell different stories. Alex Caruso ranks
> 3rd in Positive Rate (36%) but only 7th in Net Sentiment — because
> he's also frequently criticized. OG Anunoby is the reverse: 10th in
> Positive Rate but 3rd in Net Sentiment because almost nobody dislikes
> him. Positive Rate measures "being loved," Net Sentiment measures
> "not being hated."
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
> "I won't believe Luka will ever take care of his body until he actually
> starts doing it. Nothing he has ever done shows he will."

→ **Negative** (0.85) · Luka Dončić — personal criticism of player behavior.

---

> "Curry is absolutely disgusting from three"

→ **Positive** (0.90) · Stephen Curry — "disgusting" is praise in basketball slang.

---

> "Harden got cooked on defense again"

→ **Negative** (0.85) · James Harden — "cooked" = badly beaten.

---

> "I hate how good Jokic is"

→ **Positive** (0.80) · Nikola Jokić — grudging respect, not actual criticism.

---

> "He's averaging 22/8/5 on 45% shooting. Moved to the bench last week
> after the trade."

→ **Neutral** (0.70) · no player — factual stats, no opinion expressed.

---

> "Great defense from Harden as usual"

→ **Negative** (0.75) · James Harden — sarcasm detected.
"""
    )

# ---------------------------------------------------------------------------
# Player attribution
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Player Attribution")

st.markdown(
    """
Each comment is matched to a single player using a four-step process.
"""
)

with st.expander("How comments get attributed to players"):
    st.markdown(
        """
1. **Mention detection** — scan for player names and aliases
   (e.g., "LeBron", "Bron", "Westbrick" → Russell Westbrook)
   using word-boundary matching to avoid false positives
   ("AD" matches but "advertisement" doesn't).
2. **Single mention** — if only one player is mentioned, attribute directly.
3. **Multi-player disambiguation** — if multiple players are mentioned,
   the classifier's `"p"` field identifies which player the sentiment
   targets. Example:

> "LeBron passed to Curry who missed the open three"

Mentions: LeBron James, Stephen Curry · Sentiment targets: **Stephen Curry**

4. **Ambiguous → discarded** — if the classifier can't resolve a specific
   player, the comment is excluded from player-level stats (~17% of usable
   comments).
"""
    )

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("The Prompt")

with st.expander("Production prompt sent to Claude Haiku 4.5"):
    st.code(
        'Classify sentiment toward NBA players.\n'
        "Slang: nasty/sick/filthy=positive, "
        "washed/brick/fraud/cooked=negative, GOAT=positive.\n"
        "\n"
        "Comment: {comment_body}\n"
        "\n"
        'Respond ONLY with JSON: '
        '{"s":"pos|neg|neu","c":0.0-1.0,"p":"Player Name"|null}',
        language=None,
    )

# ---------------------------------------------------------------------------
# Limitations
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Limitations")

with st.expander("Known limitations and caveats"):
    st.markdown(
        """
- **Classifier accuracy ~96%** — validated against human labels on a
  500-comment sample. Edge cases include sarcasm, backhanded compliments,
  and idiom misreads (e.g., "Towns going to town on us" classified as
  negative when it's actually praise).
- **Comments without team flair (~40%)** are excluded from the Flair View.
  Of flaired comments, 92.5% were successfully mapped to one of 30
  NBA teams.
- **Players with <5,000 comments** may have unstable rates — small samples
  are more sensitive to a single viral thread. The threshold slider on the
  Leaderboard lets you filter these out.
- **Sentiment ≠ hate** — a factual criticism ("he shot 2-15 last night")
  and a personal attack both register as "negative." The metric measures
  negativity of discourse, not pure hostility.
- **Equal weighting** — every comment counts the same regardless of
  Reddit score. A comment with 500 upvotes has the same weight as one
  with 1 upvote. This avoids popularity bias but means viral threads
  don't carry extra influence.
- **One season only** — results reflect the 2024-25 season. Player
  sentiment shifts with trades, injuries, and playoff performance.
"""
    )

# ---------------------------------------------------------------------------
# Key Findings
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("What the Data Reveals About r/NBA")

st.markdown(
    """
- **r/NBA skews negative.** At the 5,000-comment threshold, only 11 of
  59 qualifying players have a positive net sentiment. The most extreme
  negative score (−0.366) is roughly 1.7× as extreme as the most
  positive (+0.217). The forum's ceiling for negativity far exceeds
  its ceiling for praise.
- **Hate is universal, love is local.** Draymond Green is the most
  hated player for 22 of 30 fanbases. No single player is the most
  loved for more than 9. Fanbases agree on who to dislike but fragment
  on who to celebrate.
- **Fanbase identity is a weak predictor.** The most negative fanbase
  (Brooklyn, 33.8%) and the least negative (OKC, 26.6%) are only
  7.2 percentage points apart. Which player is being discussed matters
  far more than which fanbase is speaking.
"""
)

# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Links")

st.markdown(
    """
⭐ **Star the project on GitHub** 
[![GitHub stars](https://img.shields.io/github/stars/oluobiri/nba-hate-tracker?style=social)](https://github.com/oluobiri/nba-hate-tracker)

- **r/NBA Post:** Coming soon
- **Built by:** [Olu Obiri](https://www.linkedin.com/in/oluobiri/)
"""
)
