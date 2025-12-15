# NBA Hate Tracker: Engineering Specification

**Document Type:** Engineering Implementation Spec  
**From:** Product Manager  
**To:** Senior Data Engineer  
**Date:** December 13, 2025  
**Version:** 1.1  
**Budget:** $200 USD (hard ceiling)

**Revision History:**
| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Dec 13, 2025 | Initial spec |
| 1.1 | Dec 13, 2025 | Updated tooling: uv, polars, Python 3.11; revised dependencies |

---

## Executive Summary

Build a sentiment analysis pipeline to answer: **"Who is r/NBA's most hated player?"**

**Data Source:** Historical Reddit archives (2024-25 NBA season + playoffs)  
**Classifier:** Claude Haiku 4.5 via Batch API  
**Infrastructure:** AWS (S3, Athena, DynamoDB, Lambda/Step Functions)  
**Output:** Ranked sentiment scores by player, segmented by team subreddit

This spec covers the complete implementation from data acquisition through serving layer.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LOCAL PROCESSING                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Academic Torrents ──► ZST Files ──► Streaming Decompress ──► Filter      │
│        (Download)         (Raw)         (zstandard)          (r/NBA only)  │
│                                                                             │
│                                              │                              │
│                                              ▼                              │
│                                    Filtered JSONL                           │
│                                    (~2M comments)                           │
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

### Source: Reddit Archive Dumps

**Location:** Academic Torrents / Arctic Shift  
**Format:** Zstandard-compressed NDJSON (.zst)  
**Window:** October 2024 – June 2025 (9 months)

**Files Required:**
```
RC_2024-10.zst  (Comments, October 2024)
RC_2024-11.zst  (Comments, November 2024)
RC_2024-12.zst  (Comments, December 2024)
RC_2025-01.zst  (Comments, January 2025)
RC_2025-02.zst  (Comments, February 2025)
RC_2025-03.zst  (Comments, March 2025)
RC_2025-04.zst  (Comments, April 2025)
RC_2025-05.zst  (Comments, May 2025)
RC_2025-06.zst  (Comments, June 2025)
```

**Alternative:** Per-subreddit dumps if available (smaller, pre-filtered)
- Check Arctic Shift for `nba_comments.zst` or similar

### Volume Estimates

| Metric | Estimate | Notes |
|--------|----------|-------|
| r/NBA daily comments | 15,000-50,000 | Higher during playoffs |
| Season duration | ~270 days | Oct 2024 - June 2025 |
| Total comments | 4-10M | Before filtering |
| After player-mention filter | 1-3M | Estimated 30-50% mention players |
| Target for processing | ~2M | Budget-constrained |

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
- `author_flair_text` / `author_flair_css_class`: Team affiliation
- `subreddit`: Filter criteria (nba, lakers, celtics, etc.)
- `created_utc`: Temporal analysis
- `score`: Engagement weighting (optional)

### Target Subreddits

**Primary:**
- `nba` (main subreddit, 16.9M members)

**Team Subreddits (30 total):**
```python
TEAM_SUBREDDITS = [
    # Atlantic
    "bostonceltics", "gonets", "nyknicks", "sixers", "torontoraptors",
    # Central
    "chicagobulls", "clevelandcavs", "detroitpistons", "pacers", "mkebucks",
    # Southeast
    "atlantahawks", "charlottehornets", "heat", "orlandomagic", "washingtonwizards",
    # Northwest
    "denvernuggets", "timberwolves", "thunder", "ripcity", "utahjazz",
    # Pacific
    "warriors", "laclippers", "lakers", "suns", "kings",
    # Southwest
    "mavericks", "rockets", "memphisgrizzlies", "nolapelicans", "nbaspurs"
]
```

---

## Implementation Phases

### Phase 1: Local Data Acquisition & Filtering
**Duration:** 1-2 sessions  
**Cost:** $0 (local compute only)

**Objectives:**
1. Download required ZST files from Academic Torrents
2. Implement streaming decompression pipeline
3. Filter for target subreddits
4. Validate data quality and volume
5. Implement optional player-mention pre-filter

**Technical Requirements:**

```python
# Critical: ZST decompression requires large window size
import zstandard
dctx = zstandard.ZstdDecompressor(max_window_size=2147483648)  # 2GB
```

**Deliverables:**
- `scripts/download_dumps.py` - Torrent/HTTP download automation
- `scripts/extract_filter.py` - Streaming ZST → filtered JSONL
- `data/filtered/` - Local filtered output (do not commit to git)
- Volume report: actual comment counts by subreddit and month

**Validation Checkpoint:**
- [ ] Successfully decompress at least one monthly dump
- [ ] Filter produces valid JSONL
- [ ] Count matches expected volume range (2-4M for r/NBA + team subs)
- [ ] Flairs are present in sufficient quantity (target: >60% coverage)

---

### Phase 2: Player-Mention Filtering (Optional Optimization)
**Duration:** 1 session  
**Cost:** $0

**Objective:** Reduce comment volume by filtering to player-mention only.

**Implementation:**
```python
# Player name patterns (expandable)
PLAYER_PATTERNS = {
    "lebron james": ["lebron", "bron", "lbj", "legoat", "lebum", "lemickey"],
    "stephen curry": ["curry", "steph", "chef curry", "wardell"],
    "kevin durant": ["durant", "kd", "slim reaper"],
    # ... top 50-100 active players
}

def mentions_player(comment_body: str) -> bool:
    """Check if comment mentions any tracked player."""
    body_lower = comment_body.lower()
    for player, aliases in PLAYER_PATTERNS.items():
        if any(alias in body_lower for alias in aliases):
            return True
    return False
```

**Trade-off Analysis:**
| Approach | Volume | Cost | Coverage |
|----------|--------|------|----------|
| All comments | ~4M | ~$400 | Complete |
| Player-mention only | ~1.5M | ~$150 | May miss context |
| Hybrid (sample + player) | ~2M | ~$200 | Balanced |

**Recommendation:** Implement filter, measure reduction ratio, decide based on actual numbers.

**Deliverables:**
- `utils/player_filter.py` - Player mention detection
- `config/players.yaml` - Player alias configuration
- Volume comparison report (filtered vs unfiltered)

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
    ├── top_subreddits (Map)          # {subreddit: score}
    └── updated_at (String)           # ISO timestamp
```

**Estimated Capacity:** ~500 items (active players) = Free Tier

**Deliverables:**
- `infrastructure/` - CloudFormation or Terraform templates
- `scripts/setup_aws.py` - Infrastructure provisioning script
- IAM policy documents
- Billing alert configuration ($50 threshold)

---

### Phase 4: Batch Processing Pipeline
**Duration:** 2-3 sessions  
**Cost:** ~$150-200 (primary expense)

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
        "content": "Analyze this NBA Reddit comment for sentiment...\n\nComment: \"LeBron is washed...\""
      }
    ]
  }
}
```

**Batch Size Constraints:**
- Max 10,000 requests per batch (or 32MB file size)
- 24-hour processing SLA
- 50% cost reduction vs synchronous API

**Processing Strategy:**
```
2M comments ÷ 10,000 per batch = 200 batch files
Submit in parallel (up to rate limits)
Monitor via batch status endpoint
Download results as completed
```

**Model Configuration (Configurable):**
```python
# config/model_config.yaml
sentiment_model:
  default: "claude-haiku-4-5-20251001"
  alternatives:
    - "claude-3-5-haiku-20241022"  # Cheaper fallback
  temperature: 0.0  # Deterministic classification
  max_tokens: 50    # Minimal output needed
```

**Prompt Template:**
```python
SENTIMENT_PROMPT = """Analyze this NBA Reddit comment for sentiment toward basketball players.

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
- `pipeline/batch_formatter.py` - Convert JSONL to batch format
- `pipeline/batch_submitter.py` - Submit batches to Anthropic API
- `pipeline/batch_monitor.py` - Track job status
- `pipeline/result_parser.py` - Parse and validate responses
- `config/model_config.yaml` - Model configuration

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
    "subreddit": pl.Utf8,
    "created_utc": pl.Datetime,
    "score": pl.Int32,
    "sentiment_label": pl.Utf8,           # positive/negative/neutral
    "sentiment_confidence": pl.Float32,
    "target_player": pl.Utf8,
    "year": pl.Int16,                      # Partition column
    "month": pl.Int8,                      # Partition column
}

# Write partitioned parquet
df.write_parquet(
    "s3://nba-hate-tracker-{id}/processed/sentiment/",
    compression="snappy",
    partition_by=["year", "month"],
)
```

**Athena Table Definition:**
```sql
CREATE EXTERNAL TABLE nba_sentiment (
    comment_id STRING,
    body STRING,
    author STRING,
    author_flair STRING,
    subreddit STRING,
    created_utc TIMESTAMP,
    score INT,
    sentiment_label STRING,
    sentiment_confidence FLOAT,
    target_player STRING
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

-- Most hated by team subreddit
SELECT 
    subreddit,
    target_player,
    COUNT(*) as mentions,
    AVG(...) as sentiment_score
FROM nba_sentiment
WHERE subreddit != 'nba'
GROUP BY subreddit, target_player
ORDER BY subreddit, sentiment_score ASC;

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
- `pipeline/parquet_writer.py` - Transform to Parquet with partitions
- `analytics/athena_tables.sql` - DDL statements
- `analytics/core_queries.sql` - Reusable aggregation queries
- `pipeline/dynamodb_loader.py` - Populate serving layer from Athena results

---

### Phase 6: Visualization & Serving (V1 Complete)
**Duration:** 1-2 sessions  
**Cost:** ~$0 (Streamlit Community Cloud free tier)

**Objectives:**
1. Build simple dashboard UI
2. Display player rankings
3. Show subreddit breakdown
4. Deploy to free hosting

**MVP Features:**
1. **Leaderboard:** Top 20 most hated players (table)
2. **Subreddit View:** Select team → see their most hated
3. **Player Detail:** Select player → sentiment breakdown by subreddit

**Tech Stack:**
- Streamlit (Python, simple, free hosting)
- Reads from DynamoDB (fast, cached)
- No backend server needed

**Deliverables:**
- `app/streamlit_app.py` - Main dashboard
- `app/components/` - Reusable UI components
- Deployment to Streamlit Community Cloud
- Public URL for sharing

---

## Cost Budget Breakdown

### One-Time Costs (Processing)

| Component | Calculation | Cost |
|-----------|-------------|------|
| Haiku 4.5 Input | 2M comments × 150 tokens × $0.50/MTok | $150 |
| Haiku 4.5 Output | 2M comments × 10 tokens × $2.50/MTok | $50 |
| **Subtotal (Inference)** | | **$200** |

**With Player-Mention Filter (50% reduction):**

| Component | Calculation | Cost |
|-----------|-------------|------|
| Haiku 4.5 Input | 1M comments × 150 tokens × $0.50/MTok | $75 |
| Haiku 4.5 Output | 1M comments × 10 tokens × $2.50/MTok | $25 |
| **Subtotal (Inference)** | | **$100** |

### Ongoing Monthly Costs (Post-Processing)

| Component | Specification | Monthly Cost |
|-----------|---------------|--------------|
| S3 Storage | ~2GB Standard | $0.05 |
| Athena Queries | ~100 queries/month, 50MB scanned each | $0.03 |
| DynamoDB | ~500 items, on-demand | Free Tier |
| Lambda | Minimal invocations | Free Tier |
| **Total Monthly** | | **< $0.10** |

### Budget Scenarios

| Scenario | Inference | Monthly | Year 1 Total |
|----------|-----------|---------|--------------|
| Full data (2M) | $200 | $1.20 | ~$201 |
| Filtered (1M) | $100 | $1.20 | ~$101 |
| **Recommendation** | Start filtered | | ~$100 |

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
    "zstandard>=0.22.0",
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

### Environment Setup
```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create project and install dependencies
uv sync

# Run scripts
uv run python scripts/extract_filter.py
```

### Project Structure
```
nba-hate-tracker/
├── config/
│   ├── model_config.yaml
│   ├── players.yaml
│   └── aws_config.yaml
├── scripts/
│   ├── download_dumps.py
│   ├── extract_filter.py
│   └── setup_aws.py
├── pipeline/
│   ├── __init__.py
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
│   ├── player_filter.py
│   └── zst_reader.py
├── app/
│   └── streamlit_app.py
├── tests/
│   ├── test_batch_formatter.py
│   ├── test_player_filter.py
│   └── test_sentiment.py
├── notebooks/
│   └── 01_eda_exploration.ipynb
├── infrastructure/
│   └── cloudformation.yaml
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
└── README.md
```

---

## Success Criteria

### Phase 1 Complete (Data Ready)
- [ ] Downloaded and extracted target months
- [ ] Filtered JSONL contains 2-4M r/NBA + team subreddit comments
- [ ] Flair coverage validated (>60%)
- [ ] Sample manually reviewed for quality

### Phase 4 Complete (Processing Done)
- [ ] All batches submitted and completed
- [ ] Results parsed with <1% error rate
- [ ] Cost tracked and within budget
- [ ] Sentiment distribution is reasonable (not all negative/positive)

### Phase 6 Complete (V1 Shipped)
- [ ] Dashboard accessible via public URL
- [ ] Leaderboard displays top 20 most hated
- [ ] Subreddit breakdown functional
- [ ] Posted to r/NBA for feedback

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Archive data unavailable | Check Arctic Shift as backup; fall back to available months |
| Budget overrun | Implement player-filter first; test with 1K sample before full run |
| Haiku accuracy degrades on real data | Sample 100 real comments, validate before full batch |
| AWS costs unexpected | Billing alerts at $50; use Free Tier aggressively |
| Low flair coverage | Adjust product scope; focus on r/NBA overall vs team breakdown |

---

## Next Immediate Steps

1. **Verify data availability:** Check Academic Torrents / Arctic Shift for Oct 2024 - June 2025 dumps
2. **Set up local environment:** Install uv, run `uv sync`, test decompression on one file
3. **Count actual volume:** How many r/NBA comments per month?
4. **Test player filter:** What's the reduction ratio?
5. **Sample batch test:** Send 100 comments to Haiku, validate results

---

## Questions for PM (Bring Back)

After initial data exploration:
1. Actual comment volume (does it match estimates?)
2. Flair coverage percentage
3. Player-filter reduction ratio
4. Any data quality issues discovered?

After batch processing:
1. Final cost vs budget
2. Sentiment distribution (sanity check)
3. Any model accuracy concerns on real data?

---

*End of specification. Build incrementally. Ship V1.*
