# NBA Hate Tracker: Engineering Specification

**Document Type:** Engineering Implementation Spec  
**From:** Product Manager  
**To:** Senior Data Engineer  
**Date:** February 7, 2026  
**Version:** 2.2  
**Budget:** $200 target, $300 ceiling

**Revision History:**
| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Dec 13, 2024 | Initial spec |
| 1.1 | Dec 13, 2024 | Updated tooling: uv, polars, Python 3.11 |
| 2.0 | Dec 29, 2024 | Phase 1 complete; updated with actuals; removed ZST/team subreddit scope |
| 2.1 | Jan 28, 2026 | AWS removed; Phase 2-3 complete; Phase 4 detailed |
| 2.2 | Feb 4, 2026 | Phase 4 complete with actuals; final cost $254.20 |

---

## Executive Summary

Build a sentiment analysis pipeline to answer: **"Who is r/NBA's most hated player?"**

**Data Source:** Arctic Shift API (Reddit archives, 2024-25 NBA season + playoffs)  
**Classifier:** Claude Haiku 4.5 via Batch API  
**Infrastructure:** Local processing + Streamlit Cloud  
**Output:** Ranked sentiment scores by player, segmented by team flair

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LOCAL PROCESSING                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Arctic Shift API                                                          │
│       │                                                                     │
│       │  download_arctic_shift.py (Phase 1)                                 │
│       ▼                                                                     │
│   data/raw/r_nba_comments.jsonl (7.04M comments, 12.7GB)                    │
│       │                                                                     │
│       │  clean_raw_comments.py (Phase 1)                                    │
│       ▼                                                                     │
│   data/filtered/r_nba_cleaned.jsonl (6.89M comments, 2.4GB)                 │
│       │                                                                     │
│       │  filter_player_mentions.py (Phase 2)                                │
│       ▼                                                                     │
│   data/filtered/r_nba_player_mentions.jsonl (1.94M comments, 891MB)         │
│       │                                                                     │
│       │  prepare_batches.py (Phase 4)                                       │
│       ▼                                                                     │
│   data/batches/requests/                                                    │
│       ├── batch_001.jsonl (100K requests)                                   │
│       ├── batch_002.jsonl                                                   │
│       └── ... batch_020.jsonl                                               │
│       │                                                                     │
│       │  submit_batches.py + run_batches.sh (Phase 4)                       │
│       ▼                                                                     │
│   ┌─────────────────────────────────────────┐                               │
│   │      Anthropic Batch API (external)     │                               │
│   │      ~1 hour processing per batch       │                               │
│   │      50% cost reduction vs sync         │                               │
│   └─────────────────────────────────────────┘                               │
│       │                                                                     │
│       │  collect_results.py (Phase 4)                                       │
│       ▼                                                                     │
│   data/batches/responses/                                                   │
│       ├── batch_001_results.jsonl                                           │
│       └── ...                                                               │
│       │                                                                     │
│       │  parse + join with original comments                                │
│       ▼                                                                     │
│   data/processed/sentiment.parquet (1.93M rows)                             │
│       │                                                                     │
│       │  aggregate_sentiment.py (Phase 5)                                   │
│       ▼                                                                     │
│   data/dashboard/aggregates.json                                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                                    ┌─────────────────┐
                                    │ Streamlit Cloud │
                                    │   (free tier)   │
                                    └─────────────────┘
```

---

## Data Specification

### Source: Arctic Shift API

**Endpoint:** `https://arctic-shift.photon-reddit.com/api/comments`  
**Format:** NDJSON (paginated API responses)  
**Window:** October 2024 – June 2025 (9 months)

### Volume Summary (Phase 4 Complete)

| Stage | Comments | Notes |
|-------|----------|-------|
| Raw downloaded | 7,041,235 | Via Arctic Shift API |
| Cleaned | 6,891,163 | 97.87% acceptance |
| Player-mention filtered | 1,939,290 | 28% of cleaned |
| Successfully classified | 1,934,297 | 99.74% success |
| Usable sentiment data | 1,886,133 | 97.25% of filtered |

### Sentiment Distribution (Actual)

| Sentiment | Count | Percentage |
|-----------|-------|------------|
| Neutral | 848,702 | 44% |
| Negative | 609,499 | 31% |
| Positive | 427,932 | 22% |
| Error | 48,164 | 2.5% |

### Data Structures

**Raw Comment (from Arctic Shift API):**
```json
{
  "id": "abc123",
  "body": "LeBron is washed, can't believe we traded for him",
  "author": "username",
  "author_flair_text": "Lakers",
  "author_flair_css_class": "lakers",
  "subreddit": "nba",
  "created_utc": 1709251200,
  "score": 42,
  "controversiality": 0,
  "parent_id": "t1_xyz789",
  "link_id": "t3_post123"
}
```

**Sentiment Output (`data/processed/sentiment.parquet`):**
```
comment_id: string
body: string
author: string
author_flair_text: string (nullable) — team flair
author_flair_css_class: string (nullable)
created_utc: int64 — Unix timestamp
score: int64 — Reddit upvotes/downvotes
mentioned_players: list[string] — players mentioned in comment
sentiment: string — pos|neg|neu|error
confidence: float — 0.0 to 1.0
sentiment_player: string (nullable) — player the sentiment targets
input_tokens: int64
output_tokens: int64
```

---

## Implementation Phases

### Phase 1: Data Acquisition ✅ COMPLETE
**Duration:** 3 sessions  
**Cost:** $0

**Deliverables:**
- `scripts/download_arctic_shift.py` — Paginated API download with resumability
- `scripts/clean_raw_comments.py` — Body validation, field extraction
- `notebooks/02_data_quality_report.ipynb` — EDA with key findings
- `data/raw/r_nba_comments.jsonl` — 12.7 GB, 7.04M comments
- `data/filtered/r_nba_cleaned.jsonl` — 2.4 GB, 6.89M comments

---

### Phase 2: Filtering Pipeline ✅ COMPLETE
**Duration:** 4 sessions  
**Cost:** $0

**Deliverables:**
- `config/players.yaml` — Player aliases with strict matching rules
- `pipeline/processors.py` — CommentPipeline with chainable filters
- `scripts/filter_player_mentions.py` — Player mention extraction
- `notebooks/04_cost_analysis.ipynb` — Prompt optimization, token estimates
- `data/filtered/r_nba_player_mentions.jsonl` — 1.94M comments, 891MB

**Key Decision:** Post context attribution rejected. Player-mention filtering on comment body only.

---

### Phase 3: Path Consolidation ✅ COMPLETE
**Duration:** 15 minutes  
**Cost:** $0

**Deliverables:**
- `utils/paths.py` — Centralized path getters
- Directory structure defined in constants

---

### Phase 4: Batch Processing Pipeline ✅ COMPLETE
**Duration:** Multi-day (~18 hours processing time)  
**Cost:** $254.20

**Actual Results:**

| Metric | Value |
|--------|-------|
| Total comments submitted | 1,939,290 |
| Successfully processed | 1,934,297 (99.74%) |
| API failures | 4,993 (0.26%) |
| Parse errors | 48,164 (2.49%) |
| Usable sentiment data | 1,886,133 (97.25%) |
| Input tokens | 248,544,398 |
| Output tokens | 51,969,967 |
| Total cost | $254.20 |
| Batches | 20 (100K each) |

**Issues Encountered:**
1. **Multi-player array responses** — Model returned arrays for multi-player comments; fixed in `parse_response()`
2. **Rate limiting** — Tier 1 limited to 1-2 concurrent batches; created `run_batches.sh` orchestration
3. **Credit exhaustion** — 4,993 requests failed mid-batch; added credits, accepted as acceptable loss
4. **SDK error structure** — Nested error objects required fix in `download_results()`

**Deliverables:**
- `pipeline/batch.py` — Core batch functions (prompt, parsing, cost calculation)
- `scripts/prepare_batches.py` — Generate batch request files
- `scripts/submit_batches.py` — Submit with state tracking
- `scripts/collect_results.py` — Poll, download, parse, write parquet
- `scripts/run_batches.sh` — Orchestration script for rate limit handling
- `data/batches/state.json` — Submission state
- `data/processed/sentiment.parquet` — Final classified output (1.93M rows)
- `data/batches/failed_requests.jsonl` — API failures log

---

### Phase 5: Analytics & Aggregation ⬅️ CURRENT
**Duration:** 1-2 sessions  
**Cost:** $0

**Objectives:**
1. Aggregate sentiment by player
2. Segment by team flair
3. Compute rankings and metrics
4. Export dashboard-ready JSON

**Core Aggregations:**
- Most hated players (overall sentiment score)
- Sentiment by team flair ("What do Lakers fans think of LeBron?")
- Mention volume vs sentiment (popular ≠ hated)
- Confidence distribution (quality check)

**Deliverables:**
- `scripts/aggregate_sentiment.py` — Compute aggregations
- `data/dashboard/aggregates.json` — Precomputed metrics for Streamlit

---

### Phase 6: Dashboard & Deployment
**Duration:** 1-2 sessions  
**Cost:** $0 (Streamlit Cloud free tier)

**Objectives:**
1. Build simple dashboard UI
2. Display player rankings
3. Show flair-based breakdown
4. Deploy to Streamlit Cloud

**MVP Features:**
1. **Leaderboard:** Top 20 most hated players
2. **Flair View:** Select team flair → see their most hated
3. **Player Detail:** Select player → sentiment breakdown by flair

**Deliverables:**
- `app/streamlit_app.py` — Main dashboard
- Deployment to Streamlit Community Cloud
- Public URL for r/NBA post

---

## Cost Budget

### Final Spend

| Phase | Cost |
|-------|------|
| Phase 1-3 | $0 |
| Phase 4 (Batch API) | $254.20 |
| Phase 5-6 | $0 |
| **Total** | **$254.20** |

| Metric | Value |
|--------|-------|
| Target | $200 |
| Actual | $254.20 |
| Ceiling | $300 |
| Headroom | $45.80 |

**Status:** Over target by $54.20, under ceiling by $45.80. Acceptable.

### Ongoing Costs

| Component | Monthly Cost |
|-----------|--------------|
| Streamlit Cloud | $0 (free tier) |
| Data storage | $0 (local) |
| **Total** | **$0** |

---

## Technical Configuration

### Runtime Requirements

| Component | Requirement |
|-----------|-------------|
| Python | >= 3.11 |
| Package Manager | `uv` |
| DataFrame Library | `polars` |

### Environment Variables
```bash
# .env (do not commit)
ANTHROPIC_API_KEY=sk-ant-...
DATA_DIR=/path/to/data
```

### Project Structure
```
nba-hate-tracker/
├── .claude/
│   ├── agents/
│   │   ├── code-reviewer.md
│   │   └── nba-superfan.md
│   ├── commands/
│   │   └── commit-check.md
│   ├── rules/
│   │   ├── git.md
│   │   ├── python.md
│   │   └── testing.md
│   └── CLAUDE.md
├── .github/
│   ├── ISSUE_TEMPLATES/
│   │   ├── bug.md
│   │   ├── feature.md
│   │   └── refactor.md
│   └── PULL_REQUEST_TEMPLATE.md
├── config/
│   ├── players.yaml
│   └── teams.yaml
├── scripts/
│   ├── download_arctic_shift.py
│   ├── clean_raw_comments.py
│   ├── filter_player_mentions.py
│   ├── prepare_batches.py
│   ├── submit_batches.py
│   ├── collect_results.py
│   ├── run_batches.sh
│   └── aggregate_sentiment.py
├── pipeline/
│   ├── __init__.py
│   ├── arctic_shift.py
│   ├── processors.py
│   └── batch.py
├── utils/
│   ├── __init__.py
│   ├── constants.py
│   ├── formatting.py
│   ├── paths.py
│   └── player_config.py
├── app/
│   └── streamlit_app.py
├── tests/
│   ├── conftest.py
│   └── unit/
│     ├── __init__.py
│     ├── test_arctic_shift.py
│     ├── test_batch.py
│     ├── test_extract_filter.py
│     ├── test_formatting.py
│     ├── test_player_config.py
│     ├── test_player_matcher.py
│     └── test_processors.py
├── notebooks/
│   ├── 01_classifier_validation.ipynb
│   ├── 02_data_quality_report.ipynb
│   ├── 03_posts_context_evaluation.ipynb
│   ├── 04_cost_analysis.ipynb
│   └── 05_sentiment_results_analysis.ipynb
├── docs/
│   ├── refactor-session-handoff.md
│   └── aws-decision.md
├── data/                        # Not committed
│   ├── raw/
│   ├── filtered/
│   │   ├── r_nba_cleaned.jsonl
│   │   └── r_nba_player_mentions.jsonl
│   ├── batches/
│   │   ├── requests/
│   │   ├── responses/
│   │   ├── state.json
│   │   └── failed_requests.jsonl
│   ├── processed/
│   │   └── sentiment.parquet
│   └── dashboard/
│       └── aggregates.json
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
└── README.md
```

---

## Success Criteria

### Phase 1-4 Complete ✅
- [x] Downloaded r/nba comments via Arctic Shift API
- [x] Cleaned to 6.89M comments
- [x] Filtered to 1.94M player-mention comments
- [x] Cost optimized from $1,156 → $254 (78% reduction from naive estimate)
- [x] All 20 batches submitted and completed
- [x] 97.25% usable sentiment data
- [x] Actual cost ($254.20) within $300 ceiling
- [x] `sentiment.parquet` generated

### Phase 5 Complete (Target)
- [ ] Player rankings computed
- [ ] Flair-based segmentation complete
- [ ] `aggregates.json` generated for dashboard

### Phase 6 Complete (V1 Shipped)
- [ ] Dashboard accessible via public URL
- [ ] Leaderboard displays top 20 most hated
- [ ] Flair breakdown functional
- [ ] Posted to r/NBA

---

## Key Learnings (Phase 4)

1. **Pilot first, always** — $13 pilot caught multi-player array issue before committing $250
2. **API limits aren't always documented** — Concurrent batch limits weren't in rate limits UI
3. **Bash orchestration is legitimate** — Shell scripts for pipeline orchestration is standard practice
4. **Atomic state writes pay off** — Temp file + `os.replace()` prevented corruption during 18-hour run
5. **Pre-paid vs post-paid** — Verify billing model before assuming you can run now and pay later

---

## Checkpoints

**Phase 5 → PM:**
1. Who is the most hated player?
2. Any surprising findings in the data?
3. Flair segmentation working?

**Phase 6 → PM:**
1. Dashboard URL
2. r/NBA post draft

---

*End of specification. Ship V1.*