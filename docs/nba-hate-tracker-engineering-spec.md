# NBA Hate Tracker: Engineering Specification

**Document Type:** Engineering Implementation Spec  
**From:** Product Manager  
**To:** Senior Data Engineer  
**Date:** January 2, 2025
**Version:** 2.0  
**Budget:** $300 USD (hard ceiling), $200 target

**Revision History:**
| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Dec 13, 2024 | Initial spec |
| 1.1 | Dec 13, 2024 | Updated tooling: uv, polars, Python 3.11 |
| 2.0 | Dec 29, 2024 | Phase 1 complete; updated with actuals; removed ZST/team subreddit scope |

---

## Executive Summary

Build a sentiment analysis pipeline to answer: **"Who is r/NBA's most hated player?"**

**Data Source:** Arctic Shift API (Reddit archives, 2024-25 NBA season + playoffs)  
**Classifier:** Claude Haiku 4.5 via Batch API  
**Infrastructure:** AWS (S3, Athena, DynamoDB)  
**Output:** Ranked sentiment scores by player, segmented by team flair

This spec covers the complete implementation from data acquisition through serving layer.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LOCAL PROCESSING                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Arctic Shift API ──► JSONL (Raw) ──► Cleaning ──► Filtering ──► JSONL    │
│        (Paginated)       7.04M           97.87%      (Phase 2)    (Final)  │
│                        comments         acceptance                          │
│                                                                             │
│                                              │                              │
│                                              ▼                              │
│                                    Filtered JSONL                           │
│                                   (~1.5M comments)                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              │ Upload
                                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS CLOUD                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   S3 (Raw)              Anthropic Batch API           S3 (Processed)        │
│   └── raw/               └── 50% discount             └── processed/        │
│       └── comments.jsonl     └── 24hr SLA                 └── sentiment.parquet
│                                                                             │
│              │                     │                          │             │
│              └──────────┬──────────┘                          │             │
│                         │                                     │             │
│                         ▼                                     ▼             │
│                  Step Functions                           Athena            │
│                  (Orchestration)                      (SQL Analytics)       │
│                                                              │              │
│                                                              ▼              │
│                                                         DynamoDB            │
│                                                    (Serving Layer)          │
│                                                    (~500 rows only)         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                                    ┌─────────────────┐
                                    │   Frontend UI   │
                                    │   (Streamlit)   │
                                    └─────────────────┘
```

---

## Data Specification

### Source: Arctic Shift API

**Endpoint:** `https://arctic-shift.photon-reddit.com/api/comments`  
**Format:** NDJSON (paginated API responses)  
**Window:** October 2024 – June 2025 (9 months)

### Actual Volume (Phase 1 Complete)

| Metric | Value | Notes |
|--------|-------|-------|
| Raw comments downloaded | 7,041,235 | Via Arctic Shift API |
| Cleaned comments | 6,891,163 | 97.87% acceptance rate |
| Date range | Oct 1, 2024 – Jun 30, 2025 | 272 days, zero gaps |
| Unique posts | 75,776 | For context attribution |
| Median comments/post | 15 | Good context propagation |

### Critical Finding: Player Mentions

| Metric | Value | Implication |
|--------|-------|-------------|
| Comments mentioning player | 22.4% | Need post context for remaining 77.6% |
| Flair coverage | 65% | Sufficient for team segmentation |
| Median comment length | 68 chars (~17 tokens) | Lower than estimated |

### Comment Data Structure

Each NDJSON line contains:
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

**Critical Fields for Sentiment Analysis:**
- `body`: Text to classify
- `author_flair_text` / `author_flair_css_class`: Team affiliation (65% coverage)
- `link_id`: Maps to post for context attribution
- `created_utc`: Temporal analysis
- `score`: Engagement weighting (optional)

### Target Scope

**In Scope (V1):**
- `r/nba` subreddit only (6.89M comments)
- 2024-25 season (Oct 2024 – Jun 2025)
- Team flair segmentation (30 teams via flair normalization)

**Out of Scope:**
- Individual team subreddits (removed from project scope)

---

## Implementation Phases

### Phase 1: Data Acquisition ✅ COMPLETE
**Duration:** 3 sessions  
**Cost:** $0

**Completed Deliverables:**
- `scripts/download_arctic_shift.py` — Paginated API download with resumability
- `scripts/clean_raw_comments.py` — Body validation, field extraction
- `notebooks/02_data_quality_report.ipynb` — EDA with key findings
- `data/raw/r_nba_comments.jsonl` — 12.7 GB, 7.04M comments
- `data/filtered/r_nba_cleaned.jsonl` — 2.4 GB, 6.89M comments

**Key Findings:**
- Only 22.4% of comments explicitly mention players
- 65% flair coverage (sufficient for segmentation)
- Zero data gaps across 272-day range
- Post context required for sentiment attribution

---

### Phase 2: Posts Download & Filtering Pipeline
**Duration:** 2-3 sessions  
**Cost:** $0

**Objectives:**
1. Download r/nba posts from Arctic Shift API (~75K posts)
2. Refactor codebase for Phase 2+ complexity
3. Build comment processing pipeline with composable filters
4. Determine filtering strategy to hit $200-300 budget
5. EDA on posts data to answer open questions

**Open Questions (to answer via EDA):**
- What % of posts mention a player in the title?
- What % of posts are game threads vs. discussion?
- What filtering strategy achieves budget with adequate coverage?

**Deliverables:**
- `pipeline/arctic_shift.py` — Reusable API client for comments and posts
- `pipeline/processors.py` — CommentPipeline with chainable filters
- `data/raw/r_nba_posts.jsonl` — Post titles for context
- Filtering strategy recommendation with cost projection

**Target Structure:**
```
├── scripts/                    # CLI entry points
│   ├── download_comments.py
│   ├── download_posts.py
│   └── process_comments.py
├── pipeline/                   # Data processing components
│   ├── arctic_shift.py         # ArcticShiftClient
│   ├── processors.py           # CommentPipeline, filters
│   └── batch.py                # Claude API batch job (Phase 4)
├── utils/                      # Pure utilities
│   ├── constants.py
│   └── formatting.py
```

**Checkpoint:** Report back with filtering strategy, actual cost projection, and go/no-go recommendation.

---

### Phase 3: AWS Infrastructure Setup
**Duration:** 1 session  
**Cost:** ~$0 (setup only, Free Tier eligible)

**Objectives:**
1. Create S3 buckets with proper structure
2. Set up IAM roles and policies
3. Configure Athena workgroup
4. Create DynamoDB table for serving layer
5. Set billing alerts

**S3 Bucket Structure:**
```
s3://nba-hate-tracker-{your-id}/
├── raw/
│   └── comments/
│       └── season_2024_25.jsonl
├── batches/
│   ├── requests/
│   │   └── batch_001.jsonl
│   └── responses/
│       └── batch_001_results.jsonl
├── processed/
│   └── sentiment/
│       ├── year=2024/
│       │   └── month=10/
│       │       └── data.parquet
│       └── year=2025/
│           └── month=06/
│               └── data.parquet
└── analytics/
    └── athena-results/
```

**DynamoDB Table Design:**
```
Table: PlayerSentiment
├── Partition Key: player_name (String)
├── Sort Key: season (String)  # e.g., "2024-25"
└── Attributes:
    ├── sentiment_score (Number)      # -1.0 to 1.0
    ├── mention_count (Number)
    ├── negative_count (Number)
    ├── positive_count (Number)
    ├── neutral_count (Number)
    ├── top_flairs (Map)              # {flair: score}
    └── updated_at (String)           # ISO timestamp
```

**Estimated Capacity:** ~500 items (active players) = Free Tier

**Deliverables:**
- `infrastructure/` — CloudFormation or Terraform templates
- `scripts/setup_aws.py` — Infrastructure provisioning script
- IAM policy documents
- Billing alert configuration ($100 threshold)

---

### Phase 4: Batch Processing Pipeline
**Duration:** 2-3 sessions  
**Cost:** $150-250 (primary expense)

**Objectives:**
1. Format data for Anthropic Batch API
2. Submit batch jobs
3. Monitor and retrieve results
4. Parse and validate responses
5. Transform to analytics-ready format

**Batch API Request Format:**
```json
{
  "custom_id": "comment_abc123",
  "params": {
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 100,
    "messages": [
      {
        "role": "user",
        "content": "Analyze this NBA Reddit comment for sentiment...\n\nPost: \"[Post Game Thread] Lakers defeat Celtics\"\nComment: \"LeBron is washed...\""
      }
    ]
  }
}
```

**Batch Size Constraints:**
- Max 10,000 requests per batch (or 32MB file size)
- 24-hour processing SLA
- 50% cost reduction vs synchronous API

**Model Configuration:**
```yaml
# config/model_config.yaml
sentiment_model:
  default: "claude-haiku-4-5-20251001"
  temperature: 0.0  # Deterministic classification
  max_tokens: 50    # Minimal output needed
```

**Prompt Template:**
```python
SENTIMENT_PROMPT = """Analyze this NBA Reddit comment for sentiment toward basketball players.

Post Title: "{post_title}"
Comment: "{comment_text}"

Respond in JSON format:
{{
  "sentiment": "positive" | "negative" | "neutral",
  "confidence": 0.0-1.0,
  "target_player": "Player Name" | null,
  "reasoning": "Brief explanation"
}}

Consider:
- Sports slang ("nasty", "disgusting" = positive for great plays)
- Sarcasm is common in r/NBA
- Nicknames (LeBron = LeGoat, LeBum, The King, etc.)
"""
```

**Deliverables:**
- `pipeline/batch_formatter.py` — Convert JSONL to batch format
- `pipeline/batch_submitter.py` — Submit batches to Anthropic API
- `pipeline/batch_monitor.py` — Track job status
- `pipeline/result_parser.py` — Parse and validate responses
- `config/model_config.yaml` — Model configuration

**Validation Checkpoint:**
- [ ] Test batch with 100 comments before full run
- [ ] Validate response parsing handles all edge cases
- [ ] Cost tracking matches projections

---

### Phase 5: Analytics Layer
**Duration:** 1-2 sessions  
**Cost:** ~$0.10/month (S3 + Athena queries)

**Objectives:**
1. Transform results to Parquet format
2. Create Athena table definitions
3. Build aggregation queries
4. Populate DynamoDB serving layer

**Parquet Schema (using Polars):**
```python
import polars as pl

SENTIMENT_SCHEMA = {
    "comment_id": pl.Utf8,
    "body": pl.Utf8,
    "author": pl.Utf8,
    "author_flair": pl.Utf8,
    "created_utc": pl.Datetime,
    "score": pl.Int32,
    "sentiment_label": pl.Utf8,           # positive/negative/neutral
    "sentiment_confidence": pl.Float32,
    "target_player": pl.Utf8,
    "post_title": pl.Utf8,
    "year": pl.Int16,                      # Partition column
    "month": pl.Int8,                      # Partition column
}
```

**Athena Table Definition:**
```sql
CREATE EXTERNAL TABLE nba_sentiment (
    comment_id STRING,
    body STRING,
    author STRING,
    author_flair STRING,
    created_utc TIMESTAMP,
    score INT,
    sentiment_label STRING,
    sentiment_confidence FLOAT,
    target_player STRING,
    post_title STRING
)
PARTITIONED BY (year INT, month INT)
STORED AS PARQUET
LOCATION 's3://nba-hate-tracker-{id}/processed/sentiment/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
```

**Core Analytics Queries:**

```sql
-- Most hated players overall
SELECT 
    target_player,
    COUNT(*) as mention_count,
    AVG(CASE 
        WHEN sentiment_label = 'negative' THEN -1
        WHEN sentiment_label = 'positive' THEN 1
        ELSE 0
    END) as sentiment_score,
    SUM(CASE WHEN sentiment_label = 'negative' THEN 1 ELSE 0 END) as negative_count
FROM nba_sentiment
WHERE target_player IS NOT NULL
GROUP BY target_player
ORDER BY sentiment_score ASC
LIMIT 20;

-- Most hated by team flair
SELECT 
    author_flair,
    target_player,
    COUNT(*) as mentions,
    AVG(...) as sentiment_score
FROM nba_sentiment
WHERE author_flair IS NOT NULL
GROUP BY author_flair, target_player
ORDER BY author_flair, sentiment_score ASC;

-- Sentiment over time (for trending)
SELECT 
    target_player,
    DATE_TRUNC('week', created_utc) as week,
    AVG(...) as weekly_sentiment
FROM nba_sentiment
WHERE target_player = 'LeBron James'
GROUP BY 1, 2
ORDER BY week;
```

**Deliverables:**
- `pipeline/parquet_writer.py` — Transform to Parquet with partitions
- `analytics/athena_tables.sql` — DDL statements
- `analytics/core_queries.sql` — Reusable aggregation queries
- `pipeline/dynamodb_loader.py` — Populate serving layer from Athena results

---

### Phase 6: Visualization & Serving (V1 Complete)
**Duration:** 1-2 sessions  
**Cost:** ~$0 (Streamlit Community Cloud free tier)

**Objectives:**
1. Build simple dashboard UI
2. Display player rankings
3. Show flair-based breakdown
4. Deploy to free hosting

**MVP Features:**
1. **Leaderboard:** Top 20 most hated players (table)
2. **Flair View:** Select team flair → see their most hated
3. **Player Detail:** Select player → sentiment breakdown by flair

**Tech Stack:**
- Streamlit (Python, simple, free hosting)
- Reads from DynamoDB (fast, cached)
- No backend server needed

**Deliverables:**
- `app/streamlit_app.py` — Main dashboard
- `app/components/` — Reusable UI components
- Deployment to Streamlit Community Cloud
- Public URL for sharing

---

## Cost Budget Breakdown

### Cost Projections (from Phase 1 EDA)

| Strategy | Comments | Estimated Cost | Coverage |
|----------|----------|----------------|----------|
| All comments (no filter) | 6.89M | $786 | 100% |
| Player mention only | 1.54M | $176 | 22% |
| Post context + filters | TBD | Target: $200-300 | TBD |

**Budget:** $300 hard ceiling, $200 target

### Ongoing Monthly Costs (Post-Processing)

| Component | Specification | Monthly Cost |
|-----------|---------------|--------------|
| S3 Storage | ~2GB Standard | $0.05 |
| Athena Queries | ~100 queries/month, 50MB scanned each | $0.03 |
| DynamoDB | ~500 items, on-demand | Free Tier |
| **Total Monthly** | | **< $0.10** |

### Budget Scenarios

| Scenario | Inference | Monthly | Year 1 Total |
|----------|-----------|---------|--------------|
| Player mention only (1.5M) | ~$176 | $1.20 | ~$177 |
| Post context + filters (TBD) | ~$200-300 | $1.20 | ~$250-350 |

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
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
S3_BUCKET=nba-hate-tracker-{id}
DYNAMODB_TABLE=PlayerSentiment
DATA_DIR=/path/to/data
```

### Python Dependencies
```toml
# pyproject.toml

[project]
name = "nba-hate-tracker"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "boto3>=1.34.0",
    "polars>=1.0.0",
    "requests>=2.31.0",
    "tqdm>=4.66.0",
    "streamlit>=1.30.0",
    "pyyaml>=6.0.0",
    "python-dotenv>=1.0.0",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "ruff>=0.1.0",
    "jupyter>=1.0.0",
]
```

### Project Structure
```
nba-hate-tracker/
├── config/
│   ├── model_config.yaml
│   ├── players.yaml
│   └── aws_config.yaml
├── scripts/
│   ├── download_comments.py
│   ├── download_posts.py
│   └── process_comments.py
├── pipeline/
│   ├── __init__.py
│   ├── arctic_shift.py
│   ├── processors.py
│   ├── batch_formatter.py
│   ├── batch_submitter.py
│   ├── batch_monitor.py
│   ├── result_parser.py
│   ├── parquet_writer.py
│   └── dynamodb_loader.py
├── analytics/
│   ├── athena_tables.sql
│   └── core_queries.sql
├── utils/
│   ├── __init__.py
│   ├── constants.py
│   └── formatting.py
├── app/
│   └── streamlit_app.py
├── tests/
│   ├── conftest.py
│   └── unit/
├── notebooks/
│   └── 02_data_quality_report.ipynb
├── docs/
│   └── refactor-session-handoff.md
├── infrastructure/
│   └── cloudformation.yaml
├── data/                        # Not committed
│   ├── raw/
│   │   ├── r_nba_comments.jsonl
│   │   └── r_nba_posts.jsonl
│   └── filtered/
│       └── r_nba_cleaned.jsonl
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
└── README.md
```

---

## Success Criteria

### Phase 1 Complete ✅
- [x] Downloaded r/nba comments via Arctic Shift API
- [x] Cleaned JSONL contains 6.89M comments
- [x] Flair coverage validated (65%)
- [x] EDA completed with key findings documented

### Phase 2 Complete (Target)
- [ ] Posts downloaded (~75K)
- [ ] EDA on posts completed
- [ ] Filtering strategy determined
- [ ] Cost projection confirmed within budget
- [ ] Processing pipeline tested

### Phase 4 Complete (Target)
- [ ] All batches submitted and completed
- [ ] Results parsed with <1% error rate
- [ ] Cost tracked and within $300 ceiling
- [ ] Sentiment distribution is reasonable

### Phase 6 Complete (V1 Shipped)
- [ ] Dashboard accessible via public URL
- [ ] Leaderboard displays top 20 most hated
- [ ] Flair breakdown functional
- [ ] Posted to r/NBA for feedback

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Budget overrun on Claude API | Medium | High | Aggressive filtering; test on 1K sample first |
| Flair normalization complexity | Low | Medium | 92/100 top flairs map cleanly; regex handles rest |
| Post context insufficient | Low | Medium | 75K posts × 15 median comments = good coverage |
| AWS costs unexpected | Low | Medium | Billing alerts at $100; use Free Tier aggressively |

---

## Checkpoints

**Phase 2 → PM:**
1. Posts EDA results (player mention % in titles, game thread split)
2. Recommended filtering strategy
3. Confirmed cost projection
4. Go/no-go on classification spend

**Phase 4 → PM:**
1. Final cost vs budget
2. Sentiment distribution (sanity check)
3. Any model accuracy concerns on real data

---

*End of specification. Build incrementally. Ship V1.*