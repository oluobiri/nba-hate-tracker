# NBA Hate Tracker: Streamlit Dashboard Specification

**Document Type:** Implementation Spec (Phase 6)  
**From:** Senior Data Engineer + PM  
**To:** Claude Code (Implementation Agent)  
**Date:** February 14, 2026  
**Version:** 1.2

---

## Overview

Build a multipage Streamlit dashboard to accompany an r/NBA Reddit post analyzing sentiment across 1.57M attributed comments from the 2024-25 NBA season. The dashboard is the interactive companion to an animated bar race chart (built separately in Flourish). Users arrive from a Reddit link, explore for 1-5 minutes, and leave with a finding to argue about.

**Headline finding:** Draymond Green is r/NBA's most hated player — 51.0% negative rate on 53,454 comments, named most hated by 23 of 30 fanbases.

**Deployment:** Streamlit Community Cloud (free tier)  
**Data:** Single precomputed JSON file (`data/dashboard/aggregates.json`, ~2MB)  
**Audience:** r/NBA users — mobile and desktop, short attention spans, want interaction not reading

---

## File Structure

```
app/
├── .streamlit/
│   └── config.toml               # Dark theme configuration
├── streamlit_app.py              # Entry point + Leaderboard (home page)
├── pages/
│   ├── 1_👥_Flair_View.py
│   ├── 2_🔍_Player_Detail.py
│   └── 3_ℹ️_About.py
└── utils/
    ├── __init__.py
    └── data.py                   # Cached data loading + shared helpers
```

**Rationale:**
- `streamlit_app.py` IS the leaderboard — no intro splash page. Users came for rankings; show them immediately.
- Numbered emoji prefixes control Streamlit's sidebar ordering.
- `utils/data.py` centralizes `st.cache_data` loading and shared filtering functions (threshold, metric formatting) so page files stay focused on layout.
- About/Methodology page is last in nav — users check credibility after seeing results.

---

## Data Schema

**Source:** `data/dashboard/aggregates.json`

The JSON contains 5 top-level keys. Load once via `st.cache_data`, convert views to Polars or Pandas DataFrames, filter in memory. For 111 players × 30 teams this is trivially fast.

### `player_overall` (list of 111 objects)
```json
{
  "attributed_player": "Draymond Green",
  "neg_count": 27289,
  "pos_count": 7731,
  "neu_count": 18434,
  "comment_count": 53454,
  "neg_rate": 0.5105,
  "pos_rate": 0.1446,
  "net_sentiment": -0.3659,
  "polarization": 0.6551
}
```

### `player_temporal` (list of ~4,391 objects)
```json
{
  "attributed_player": "Draymond Green",
  "week": "2024-10-07T00:00:00",
  "neg_count": 385,
  "pos_count": 112,
  "neu_count": 221,
  "comment_count": 718,
  "neg_rate": 0.5362,
  "pos_rate": 0.156,
  "net_sentiment": -0.3802,
  "polarization": 0.6922
}
```
*Note: Temporal data is NOT used in the dashboard (bar race chart owns that story). Included in JSON for completeness but can be ignored by the app.*

### `player_team` (list of ~3,279 objects)
Player-by-flair cross-tab. Each row = one player × one team fanbase.
```json
{
  "attributed_player": "Draymond Green",
  "team": "Minnesota Timberwolves",
  "neg_count": 1261,
  "pos_count": 162,
  "neu_count": 716,
  "comment_count": 2139,
  "neg_rate": 0.5895,
  "pos_rate": 0.0758,
  "net_sentiment": -0.5138,
  "polarization": 0.6652
}
```

### `team_overall` (list of 30 objects)
Fanbase-level aggregates — how each team's fans behave across all players.
```json
{
  "team": "Cleveland Cavaliers",
  "neg_count": 9921,
  "pos_count": 7431,
  "neu_count": 15291,
  "comment_count": 32643,
  "neg_rate": 0.3039,
  "pos_rate": 0.2276,
  "net_sentiment": -0.0763,
  "polarization": 0.5316,
  "abbreviation": "CLE",
  "conference": "East",
  "logo_url": "https://cdn.nba.com/logos/nba/1610612739/primary/L/logo.svg"
}
```

### `player_metadata` (dict keyed by player name, 111 entries)
```json
{
  "Bam Adebayo": {
    "team": "Miami Heat",
    "conference": "East",
    "player_id": 1628389,
    "headshot_url": "https://cdn.nba.com/headshots/nba/latest/1040x760/1628389.png",
    "logo_url": "https://cdn.nba.com/logos/nba/1610612748/primary/L/logo.svg"
  }
}
```

### `metadata` (single object)
```json
{
  "total_comments": 1934297,
  "usable_comments": 1886133,
  "excluded_comments": 48164,
  "attributed_comments": 1567722,
  "player_count": 111,
  "team_count": 30,
  "week_count": 40,
  "season": "2024-25",
  "generated_at": "2026-02-09T17:00:35.110293+00:00"
}
```

---

## Page Specifications

### Page 1: Leaderboard (Home — `streamlit_app.py`)

**Purpose:** Show ranked player sentiment with adjustable metric and volume threshold. This is what Reddit users came for.

#### Layout

```
┌─────────────────────────────────────────────────────┐
│  r/NBA Hate Tracker: 2024-25 Season                 │
│  1.57M comments analyzed across 111 players         │
├─────────────────────────────────────────────────────┤
│                                                     │
│  [Metric Selector]          [Threshold Slider]      │
│   neg_rate ▼                ──●────── 5,000         │
│                             "59 of 111 players"     │
│                                                     │
│  ┌───────────────────────────────────────────────┐  │
│  │ # │ 📷 │ Player          │ Metric │ Comments  │  │
│  │ 1 │ 🟤 │ Draymond Green  │ 51.0%  │ 53,454   │  │
│  │ 2 │ 🔵 │ Joel Embiid     │ 49.3%  │ 31,538   │  │
│  │ 3 │ 🔴 │ Ben Simmons     │ 45.6%  │ 11,123   │  │
│  │ ...                                           │  │
│  │20 │    │ Myles Turner    │ 37.4%  │  7,665   │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ── Volume vs. Hate Scatter ──────────────────────  │
│  [Interactive Plotly scatter plot]                   │
│  x: comment_count (log scale)                       │
│  y: neg_rate                                        │
│  hover: player name, team, all metrics              │
│  click: navigates to Player Detail via query param  │
└─────────────────────────────────────────────────────┘
```

#### Controls

**Metric Selector** (`st.selectbox`):
| Display Label | Column | Sort Direction | Format |
|---|---|---|---|
| Most Hated (Negative Rate) | `neg_rate` | descending | `XX.X%` |
| Most Loved (Positive Rate) | `pos_rate` | descending | `XX.X%` |
| Net Sentiment | `net_sentiment` | ascending (most negative first) | `+0.XXX` / `-0.XXX` |
| Most Polarizing | `polarization` | descending | `XX.X%` |

Default: **Most Hated (Negative Rate)**

**Threshold Slider** (`st.slider`):
- Range: 500 – 50,000
- Default: 5,000
- Step: 500
- Dynamic annotation below: `"{N} of 111 players shown"`
- **Rationale:** 5,000 is the median split (59 players). Below this, selection bias inflates rates for players only discussed in negative contexts (e.g., Bradley Beal's contract). Above this, diminishing returns — top 6 are identical at 5K and 10K.

**Show Top N** (`st.slider` or fixed):
- Default: 20
- Range: 10–50 (capped at available players after threshold)

#### Leaderboard Table

Each row displays:
- **Rank** (1-indexed)
- **Headshot** — Small thumbnail from `player_metadata[player].headshot_url`. Use `st.image` with ~40px width or render as HTML `<img>` in an `st.dataframe` custom column. If hotlink fails, degrade gracefully (show team logo or placeholder).
- **Player Name** — Plain text (st.dataframe does not support embedded links or widgets). Navigation to Player Detail is handled via the scatter plot click and a "Jump to player" selectbox below the table.
- **Team** — Short abbreviation from `player_metadata[player].team` or the team's abbreviation
- **Primary Metric** — The selected metric, formatted per table above
- **Comment Count** — Formatted with comma separator

#### Scatter Plot

Below the leaderboard table. Plotly Express scatter:
- **x-axis:** `comment_count` (log scale recommended — range spans 355 to 133,756)
- **y-axis:** The currently selected metric (default `neg_rate`)
- **Hover:** Player name, team, neg_rate, pos_rate, net_sentiment, comment_count
- **Color:** Optional — by conference (East/West) from `player_metadata`
- **Annotations:** Label outliers (Draymond, Luka, Jokic, Wembanyama) directly on chart
- **Click behavior:** On click, navigate to Player Detail with query param. Use `on_select="rerun"` with `custom_data=["attributed_player"]` to capture the player name from the clicked point.
- **Key insight this visualizes:** Luka generates the most raw negative comments (49.6K) but ranks middling in neg_rate (37.2%). Volume ≠ hate.

Only show players above the current threshold.

---

### Page 2: Flair View (`pages/1_👥_Flair_View.py`)

**Purpose:** "Pick your team, see your fanbase's profile." Personalized exploration — the most engaging page for r/NBA users who identify with a team.

#### Layout

```
┌─────────────────────────────────────────────────────┐
│  Your Fanbase's Sentiment Profile                   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  [Team Selector ▼]     [Team Logo]                  │
│   Golden State Warriors                             │
│                                                     │
│  ┌─────────────────┐  ┌─────────────────┐          │
│  │ 🔴 MOST HATED   │  │ 🟢 MOST LOVED   │          │
│  │                  │  │                  │          │
│  │ [Headshot]       │  │ [Headshot]       │          │
│  │ Dillon Brooks    │  │ Aaron Gordon     │          │
│  │ 62.8% neg_rate   │  │ 43.6% pos_rate   │          │
│  │ 441 comments     │  │ 346 comments     │          │
│  └─────────────────┘  └─────────────────┘          │
│                                                     │
│  ── Fanbase Baseline ─────────────────────────────  │
│  neg_rate: 30.4% │ pos_rate: 23.5% │ 86,813 total  │
│  Rank: #20 most negative of 30 fanbases             │
│                                                     │
│  ── Top 10 Most Hated by [Team] Fans ────────────  │
│  [Mini leaderboard table - same columns as home]    │
│                                                     │
│  ── Top 10 Most Loved by [Team] Fans ────────────  │
│  [Mini leaderboard table - pos_rate sorted]         │
│                                                     │
└─────────────────────────────────────────────────────┘
```

#### Controls

**Team Selector** (`st.selectbox`):
- All 30 teams, alphabetically sorted
- Default: None (show prompt "Select your team") or a sensible default like the largest fanbase (Lakers, 146K comments)
- On selection, entire page populates

#### Data Logic

**Most Hated / Most Loved Cards:**
- Filter `player_team` to selected team
- No hard threshold on comment count here (see design rationale below)
- Most Hated: highest `neg_rate` in filtered set
- Most Loved: highest `pos_rate` in filtered set
- Show headshot, player name, rate, and comment count
- Comment count serves as the confidence signal — users see "441 comments" and naturally discount thin cells

**Fanbase Baseline:**
- Pull from `team_overall` for the selected team
- Show overall neg_rate, pos_rate, total comments
- Rank among 30 fanbases by neg_rate (Brooklyn #1 most negative at 33.8%, OKC #30 least negative at 26.6%)

**Mini Leaderboards:**
- Filter `player_team` to selected team
- Top 10 by neg_rate, Top 10 by pos_rate
- Show: rank, headshot (small), player name, rate, comment count
- Comment count column is critical — it contextualizes thin cells without needing an arbitrary threshold

**Design rationale — no threshold in Flair View:**
The flair cross-tab at 200-comment minimum already filters to meaningful pairs. From the team's perspective, the rankings are stable even on thin cells because Draymond's dominance is so overwhelming. The comment count column lets users self-calibrate. Enforcing a hard threshold here would empty out small-market teams' leaderboards.

#### Navigation

Player names in the mini-leaderboards are plain text (same st.dataframe limitation). Add a "Jump to player" selectbox below each mini-leaderboard for navigation via query params.

---

### Page 3: Player Detail (`pages/2_🔍_Player_Detail.py`)

**Purpose:** Deep dive on a single player. "Who hates Draymond most? Who defends him?" Accessed via leaderboard click, flair view click, or direct search.

#### Layout

```
┌─────────────────────────────────────────────────────┐
│  Player Sentiment Profile                           │
├─────────────────────────────────────────────────────┤
│                                                     │
│  [Player Search/Select ▼]                           │
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │  [Large Headshot]   Draymond Green           │    │
│  │                     Golden State Warriors    │    │
│  │                                               │    │
│  │  neg_rate: 51.0%    pos_rate: 14.5%          │    │
│  │  net_sentiment: -0.366                        │    │
│  │  polarization: 65.5%                          │    │
│  │  comments: 53,454                             │    │
│  │                                               │    │
│  │  Rank: #1 most hated (of 59 at 5K threshold) │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  ── Sentiment Breakdown ────────────────────────    │
│  [Horizontal stacked bar: neg% | neu% | pos%]       │
│                                                     │
│  ── Which Fanbases Hate [Player] Most? ─────────    │
│  ┌────────────────────────────────────────────┐     │
│  │ Team              │ neg_rate │ Δ vs avg │ N  │     │
│  │ Utah Jazz          │ 63.6%   │ +12.6    │264 │     │
│  │ Houston Rockets    │ 62.6%   │ +11.6    │1855│     │
│  │ ...                                      │     │
│  └────────────────────────────────────────────┘     │
│                                                     │
│  ── Which Fanbases Defend [Player] Most? ───────    │
│  [Same table, sorted by lowest neg_rate / highest   │
│   pos_rate — home team defense effect surfaces]      │
│                                                     │
└─────────────────────────────────────────────────────┘
```

#### Controls

**Player Selector** (`st.selectbox` with search):
- All 111 players, searchable
- If `?player=` query param is set (from leaderboard/flair click), pre-populate the selector
- Default: Draymond Green (the headline finding)

#### Data Logic

**Player Card:**
- Pull from `player_overall` for selected player
- Headshot and team logo from `player_metadata`
- All four metrics displayed
- Rank computed dynamically at the 5,000 threshold (or current leaderboard threshold if carried via session state)

**Sentiment Breakdown:**
- Simple horizontal stacked bar (Plotly or native Streamlit): negative (red) | neutral (gray) | positive (green)
- Shows the three-way split visually

**Flair Breakdown Tables:**
- Filter `player_team` to selected player
- **Most hostile fanbases:** Sort by `neg_rate` descending, show top 10
- **Most friendly fanbases:** Sort by `neg_rate` ascending (or `pos_rate` descending), show top 10
- Columns: Team (with logo), neg_rate, pos_rate, comment_count, delta vs. player's overall rate
- **Delta column** ("Δ vs avg"): `fanbase_neg_rate - player_overall_neg_rate`. Positive = this fanbase hates them more than average. Negative = this fanbase is friendlier. This surfaces the home team defense effect (e.g., Warriors fans rate Draymond at ~35% neg vs. his 51% overall = -16 delta).
- **Threshold consideration:** Show comment count prominently. For the hostile table, optionally gray out or annotate rows below a minimum (e.g., 100 comments) rather than hiding them. For the friendly table, the home team's large cell usually dominates.

#### Query Parameter Integration

The key UX feature connecting pages:

```python
# On page load, check for query param
params = st.query_params
if "player" in params:
    selected_player = params["player"]
    # Set the selectbox default to this player
```

From the leaderboard scatter plot or table:
```python
# When user clicks a player row/point
st.query_params["player"] = player_name
st.switch_page("pages/2_🔍_Player_Detail.py")
```

From the flair view mini-leaderboard:
```python
# Same pattern — player name click triggers navigation
```

---

### Page 4: About / Methodology (`pages/3_ℹ️_About.py`)

**Purpose:** Credibility page. Users come here after seeing the data to check if the methodology is sound. Brief, non-technical, with optional expandable detail.

#### Content Sections

**Pipeline Summary** (always visible):
- "We collected 7M comments from r/NBA (Oct 2024 – Jun 2025) via Arctic Shift"
- "1.94M mentioned a tracked player → classified by Claude Haiku 4.5"  
- "1.57M attributed to 111 specific players for analysis"
- Simple funnel visual (could be a Mermaid diagram or styled metrics)

**What the metrics mean** (always visible):
| Metric | Plain English |
|---|---|
| Negative Rate | % of comments about this player that were negative |
| Positive Rate | % that were positive |
| Net Sentiment | (positive - negative) / total — ranges from -1 to +1 |
| Polarization | % of comments that were NOT neutral — high = strong opinions |

**Example classifications** (collapsible `st.expander`):
Show 2-3 real anonymized examples:
- A clearly negative comment → classified "negative"
- A clearly positive comment → classified "positive"  
- An ambiguous/neutral comment → classified "neutral"
This builds trust that the classifier isn't just keyword matching.

**Limitations** (collapsible `st.expander`):
- Classifier accuracy ~95% (validated against human labels)
- Comments without team flair (~40%) excluded from flair analysis
- Players with <5,000 comments may have unstable rates
- Sentiment ≠ hate — a factual criticism and a personal attack both register as "negative"

**Links:**
- GitHub repository
- Bar race chart (Flourish embed or link)
- Original r/NBA post

---

## Shared Utilities (`app/utils/data.py`)

```python
@st.cache_data
def load_data() -> dict:
    """Load aggregates.json once, return as dict of DataFrames."""
    # Returns: {
    #   "player_overall": pd.DataFrame or pl.DataFrame,
    #   "player_team": pd.DataFrame,
    #   "team_overall": pd.DataFrame,
    #   "player_metadata": dict,  # keep as dict, keyed by player name
    #   "metadata": dict,
    # }
    # Skip player_temporal — not used in dashboard

def filter_by_threshold(df, threshold: int) -> DataFrame:
    """Filter player_overall to players with comment_count >= threshold."""

def format_rate(value: float) -> str:
    """Format 0.5105 as '51.0%'"""

def format_sentiment(value: float) -> str:
    """Format -0.3659 as '-0.366' with sign"""

def get_player_rank(player: str, df: DataFrame, metric: str, threshold: int) -> int:
    """Compute a player's rank in the filtered+sorted leaderboard."""
```

**DataFrame choice:** Pandas is the pragmatic choice here. Streamlit's native `st.dataframe` and Plotly both integrate seamlessly with Pandas. Polars would require `.to_pandas()` conversions at every display boundary. For a 111-row dataset, there's zero performance argument for Polars. Use Pandas for the dashboard even though the pipeline uses Polars.

---

## Visual Design Notes

**Theme: Dark Mode**

Dark theme is mandatory — matches the bar race chart's dark background and how r/NBA users browse Reddit. Configure via `app/.streamlit/config.toml`:

```toml
[theme]
base = "dark"
primaryColor = "#E74C3C"              # Red accent (negative sentiment color)
backgroundColor = "#0E1117"            # Near-black background
secondaryBackgroundColor = "#1A1D23"   # Slightly lighter for cards/sidebar
textColor = "#FAFAFA"                  # Off-white text
```

Plotly charts inherit Streamlit's theme automatically via `st.plotly_chart`, so the scatter plot and stacked bars will match without extra config.

**Sentiment Color Palette:**
- Negative: `#E74C3C` (red)
- Positive: `#2ECC71` (green)  
- Neutral: `#95A5A6` (gray)
- These three colors are used in stacked bars, scatter plot annotations, and metric highlights. They must have sufficient contrast against the `#0E1117` background.

**Headshots:**
- Source: `cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png`
- Display small (~40-50px) in tables, larger (~120px) in player detail card
- Graceful degradation: if image fails to load, show team logo from `player_metadata[player].logo_url` or a generic silhouette
- Do NOT download/cache locally — accept hotlink dependency for V1

**Team Logos:**
- Source: `cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg`
- Available in both `team_overall[].logo_url` and `player_metadata[].logo_url`
- Use alongside team names for visual recognition

**Mobile Considerations:**
- Streamlit columns collapse on mobile — design single-column layouts where possible
- The leaderboard table is the critical mobile experience; ensure it doesn't require horizontal scroll
- Scatter plot will degrade (hover → tap, smaller labels) — acceptable
- Sidebar becomes hamburger menu on mobile — the team selector in Flair View should be in the main content area, NOT the sidebar

---

## Technical Notes

**Dependencies** (already in `pyproject.toml`):
- `plotly` (>=6.5.2) — scatter plot and interactive charts
- `streamlit` (>=1.52.1) — framework
- `pandas` (>=2.3.3) — dashboard DataFrames (Streamlit-native integration)

**Streamlit Cloud deployment:**
- Entry point: `app/streamlit_app.py`
- `aggregates.json` committed to repo under `data/dashboard/`
- Path resolution: `load_data()` lives in `app/utils/data.py`, so use `pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "dashboard" / "aggregates.json"` (3 parents: utils/ → app/ → repo root). Add a `.exists()` guard with `st.error()` for Streamlit Cloud debugging.
- No secrets needed (no API calls, no auth)

**Performance:**
- `st.cache_data` on `load_data()` — loads JSON once per session
- All filtering/sorting in memory — trivially fast for this data size
- No database, no API calls, no external dependencies at runtime except CDN image hotlinks

**Query Parameters (`st.query_params`):**
- `?player=Draymond+Green` → Player Detail page pre-selects this player
- `?team=Golden+State+Warriors` → Flair View pre-selects this team (optional, nice-to-have)
- URL-encode spaces as `+` or `%20`

---

## Development & Deployment

### Local Development

```bash
# Run locally — hot-reloads on file save
uv run streamlit run app/streamlit_app.py
# Opens localhost:8501 in browser
```

The development loop is: edit code → save → browser auto-refreshes (~1 second). No build step.

### File Structure Setup

Create before starting implementation:

```
app/
├── .streamlit/
│   └── config.toml              # Dark theme config (see Visual Design Notes)
├── streamlit_app.py
├── pages/
│   ├── 1_👥_Flair_View.py
│   ├── 2_🔍_Player_Detail.py
│   └── 3_ℹ️_About.py
└── utils/
    ├── __init__.py
    └── data.py
```

### Git Configuration

`data/dashboard/aggregates.json` (~2MB) must be committed to the repo for Streamlit Cloud to access it. The rest of `data/` stays gitignored. Add an exception:

```gitignore
# In .gitignore — add these lines
data/
!data/dashboard/
!data/dashboard/aggregates.json
```

Also commit `app/.streamlit/config.toml` for the dark theme to apply on Cloud.

### Streamlit Cloud Deployment

1. **Account:** Sign up at [share.streamlit.io](https://share.streamlit.io) with GitHub OAuth
2. **Connect repo:** Point to the GitHub repo, set entry file to `app/streamlit_app.py`
3. **Dependencies:** Streamlit Cloud reads `requirements.txt` at repo root (does not natively support `uv`/`pyproject.toml`). Generate a dashboard-only requirements file:

```bash
# Option A: Export full lockfile
uv export --format requirements-txt > requirements.txt

# Option B: Minimal dashboard-only file (faster Cloud installs)
# requirements.txt
# streamlit>=1.52.1
# plotly>=5.0.0
# pandas>=2.0.0
```

Option B is recommended — the pipeline dependencies (anthropic, polars, boto3, tqdm) aren't needed at runtime and slow down Cloud deployments.

4. **Secrets:** None required — no API keys, no auth. Public read-only app.
5. **Deploy early:** Don't wait until all pages are done. Deploy a working leaderboard skeleton after step 2 of implementation priority to catch path resolution or dependency issues immediately. Cloud auto-redeploys on each push to main.

### Path Resolution

The app loads data from `app/utils/data.py`, which needs to reach `data/dashboard/aggregates.json` at the repo root. From `app/utils/data.py`, that's 3 `.parent` calls:

```python
from pathlib import Path

# app/utils/data.py → app/utils/ → app/ → repo root
DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "dashboard" / "aggregates.json"
```

Add a `.exists()` guard so path misconfiguration surfaces immediately on Streamlit Cloud rather than failing silently.

---

## What's NOT in Scope

| Feature | Reason |
|---|---|
| Temporal trends / time series | Bar race chart owns that story |
| Raw data download | Invites nitpicking, GitHub serves the data-curious |
| Player vs. player comparison | Data doesn't support meaningful head-to-head |
| Multiple stacked filters | Builds analytics tool, not dashboard |
| Authentication / user accounts | Public read-only tool |
| Light mode toggle | Dark theme only — matches bar race chart aesthetic |

---

## Key Data Points for Hardcoded Callouts

These findings can be used for headlines, annotations, or callout boxes:

- **Draymond Green:** 51.0% neg_rate, 53,454 comments, 23/30 fanbases name him most hated
- **Joel Embiid:** Tied worst net sentiment (-0.366) but ~half Draymond's volume
- **Russell Westbrook:** Most polarizing (68.3%), but only #4 in hate. OKC fans rate him 24.2% neg — 21 points below his overall 45.2%
- **Ben Simmons:** Most hostile fanbases are Sixers (59.2%) and Nets — his two former teams
- **Victor Wembanyama:** Most loved by 9 fanbases, but they're all neutral fanbases with no direct connection
- **Luka Dončić:** Most raw negative comments (49.6K) but middling neg_rate (37.2%) — volume ≠ hate
- **Only 11 of 59 players** at the 5K threshold have positive net sentiment
- **Fanbase negativity** spans a narrow 7.2-point range (26.6%–33.8%) — player identity drives sentiment far more than team identity

---

## Implementation Priority

1. **`utils/data.py`** — Data loading and helpers (foundation everything depends on)
2. **`streamlit_app.py`** — Leaderboard with metric selector, threshold slider, table with headshots
3. **Scatter plot** — Add to leaderboard page below table
4. **`pages/2_🔍_Player_Detail.py`** — Player card + flair breakdown tables
5. **Query param wiring** — Connect leaderboard clicks → Player Detail
6. **`pages/1_👥_Flair_View.py`** — Team selector, most hated/loved cards, mini leaderboards
7. **`pages/3_ℹ️_About.py`** — Static content, metrics explainer, limitations
8. **Polish** — Mobile testing, graceful image fallbacks, annotation labels on scatter plot

---

*End of specification. Build it.*