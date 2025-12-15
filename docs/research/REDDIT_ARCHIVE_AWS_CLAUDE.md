# Building an AWS NBA sentiment pipeline from Reddit archives

For a data engineer processing Reddit r/NBA archives through Claude Haiku classification, the most cost-effective approach combines **Academic Torrents per-subreddit downloads** (available through December 2024), **local Python streaming decompression** of ZST files, **Claude 3 Haiku Batch API** at **$25 per million comments**, and **DynamoDB's Always Free tier** for storage. A complete NBA season (~11-13 million comments) can be processed for **$80-150 total** using this architecture, with a minimal portfolio demo achievable for under $30.

---

## Reddit archive sources have diverged since 2023

The Reddit data landscape split after Reddit's 2023 API changes ended Pushshift's public access. Two primary sources now serve researchers: **Academic Torrents** hosts the historical Pushshift archive through December 2024, while **Arctic Shift** actively collects new data through October 2025.

**Academic Torrents remains the best option for r/NBA specifically** because it offers per-subreddit files. The torrent at `academictorrents.com/details/1614740ac8c94505e4ecb9d88be8bed7b6afddd4` contains the top 40,000 subreddits as individual files, allowing you to download only `nba_comments.zst` and `nba_submissions.zst` rather than the full **3.28 TB archive**. Most torrent clients (qBittorrent, Transmission) support selective file downloading.

The file naming convention follows a simple pattern: `{subreddit}_comments.zst` and `{subreddit}_submissions.zst` for per-subreddit archives, or `RC_YYYY-MM.zst` (comments) and `RS_YYYY-MM.zst` (submissions) for monthly full dumps. Team subreddits like r/lakers, r/bostonceltics, and r/warriors are all included in the top 40k set.

| Source | Latest Data | Best For | Access Method |
|--------|-------------|----------|---------------|
| Academic Torrents (per-subreddit) | Dec 2024 | Downloading specific subreddits | Torrent selective download |
| Arctic Shift Download Tool | Oct 2025 | Date-range specific exports | arctic-shift.photon-reddit.com/download-tool |
| Arctic Shift API | Oct 2025 | Programmatic queries | REST API with JSON responses |

For r/NBA data volume, FiveThirtyEight analysis indicates **11-13 million comments per 10-month NBA season**, making it Reddit's third most active community. Compressed, this translates to approximately **1-2 GB per season** in ZST format, expanding to **6-10 GB** when decompressed.

---

## NDJSON structure preserves author flairs and threading context

Each line in Reddit comment dumps is a complete JSON object. The critical fields for sentiment analysis include:

```json
{
  "id": "abc123",
  "body": "LeBron is the GOAT, no question",
  "author": "hoops_fan_42",
  "author_flair_text": "Lakers",
  "created_utc": 1640000000,
  "score": 127,
  "subreddit": "nba",
  "link_id": "t3_xyz789",
  "parent_id": "t1_def456"
}
```

**Author flairs are preserved** in `author_flair_text`, which is valuable for analyzing sentiment by team affiliation. The `created_utc` field provides Unix timestamps for temporal analysis, while `link_id` and `parent_id` enable thread reconstruction if needed.

Submission files (RS_*) differ by containing `title` and `selftext` instead of `body`, plus metadata like `num_comments` and `link_flair_text` for post categorization.

**Data quality considerations**: Deleted content appears as `[deleted]` in the body field (user deletion) or `[removed]` (moderator removal). Scores represent point-in-time snapshots at archival, not final values. The `retrieved_on` timestamp indicates when data was captured. Malformed JSON lines occur at roughly **0.01-0.1%** frequency, requiring try/except handling during parsing.

---

## Processing ZST files requires the critical max_window_size parameter

Reddit archives use Zstandard compression with an unusually large window size. Without proper configuration, decompression fails with `Frame requires too much memory for decoding`. The solution is straightforward but essential:

```python
import zstandard
import io
import json

def stream_reddit_comments(file_path, target_subreddits=None):
    """Memory-efficient streaming of Reddit ZST dumps."""
    target_set = {s.lower() for s in target_subreddits} if target_subreddits else None
    
    with open(file_path, 'rb') as fh:
        # CRITICAL: max_window_size must be 2^31 for Reddit dumps
        dctx = zstandard.ZstdDecompressor(max_window_size=2147483648)
        with dctx.stream_reader(fh) as reader:
            text_stream = io.TextIOWrapper(reader, encoding='utf-8')
            for line in text_stream:
                try:
                    obj = json.loads(line)
                    if target_set is None or obj.get('subreddit', '').lower() in target_set:
                        yield obj
                except json.JSONDecodeError:
                    continue

# Usage: filter for NBA-related subreddits
nba_subreddits = {'nba', 'lakers', 'bostonceltics', 'warriors', 'heat'}
for comment in stream_reddit_comments('RC_2024-01.zst', nba_subreddits):
    print(comment['author'], comment['body'][:100])
```

**Performance benchmarks** on typical hardware show **50,000-200,000 records per second** for streaming with JSON parsing, dropping to **30,000-100,000 records per second** with filtering logic. A 15GB compressed monthly dump processes in **10-30 minutes** depending on filter complexity. Memory usage remains constant at approximately **2-3 GB** (the window size plus buffers) regardless of file size.

For multi-file processing, parallelize at the file level using Python's `ProcessPoolExecutor`, as the zstandard library doesn't support multi-threaded decompression internally.

---

## Claude Haiku Batch API cuts classification costs by 50%

Anthropic's Message Batches API processes up to **10,000 requests per batch** with automatic **50% token price reduction**. Most batches complete in under one hour, with a maximum 24-hour processing window.

### Current pricing (December 2024)

| Model | Standard Input | Standard Output | Batch Input | Batch Output |
|-------|---------------|-----------------|-------------|--------------|
| Claude 3 Haiku | $0.25/MTok | $1.25/MTok | $0.125/MTok | $0.625/MTok |
| Claude 3.5 Haiku | $0.80/MTok | $4.00/MTok | $0.40/MTok | $2.00/MTok |

### Cost to classify 1 million comments

Assuming ~100 input tokens per comment (including prompt) and ~20 output tokens for structured classification:

| Configuration | Total Cost |
|---------------|------------|
| **Claude 3 Haiku + Batch** | **$25** |
| Claude 3.5 Haiku + Batch | $80 |
| Claude 3.5 Haiku Standard | $160 |

**Implementation pattern for batch classification:**

```python
import anthropic

client = anthropic.Anthropic()

def create_classification_batch(comments, batch_id_prefix):
    """Create batch request for sentiment classification."""
    requests = []
    for i, comment in enumerate(comments[:10000]):  # Max 10K per batch
        requests.append({
            "custom_id": f"{batch_id_prefix}-{i}",
            "params": {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 50,
                "temperature": 0,  # Deterministic classification
                "messages": [{
                    "role": "user",
                    "content": f"""Classify this NBA Reddit comment's sentiment.
Respond with JSON: {{"sentiment": "positive|negative|neutral", "confidence": 0.0-1.0}}

Comment: {comment['body'][:400]}"""
                }]
            }
        })
    
    return client.messages.batches.create(requests=requests)
```

**Rate limits by tier** determine throughput for synchronous calls: Tier 1 ($5 deposit) allows 50 RPM and 50,000 input tokens per minute. For processing millions of comments, the Batch API eliminates rate limit concerns entirely—submit batches and poll for completion.

**Token optimization strategies**: Truncate comments to ~400 characters (sentiment rarely requires full text), filter out comments under 10 characters or containing only URLs, and batch multiple short comments into single prompts when comment length permits.

---

## AWS storage decision depends on query patterns and free tier strategy

For a portfolio project processing 500K-2M sentiment-scored records, **DynamoDB's Always Free tier** offers the most cost-effective path, while **S3 + Athena** provides the cheapest analytics capability.

### Storage comparison at portfolio scale

| Solution | Monthly Cost | Free Tier | Best Query Pattern |
|----------|-------------|-----------|-------------------|
| **DynamoDB On-Demand** | $0.50-3.00 | ✅ 25GB perpetual | Real-time API, key-based lookups |
| **S3 + Athena** | $0.50-2.00 | ✅ S3 only (12mo) | Ad-hoc SQL analytics |
| **RDS PostgreSQL** | $0 → $15-25 | ✅ 12 months | Complex JOINs, SQL familiarity |
| **Timestream** | $5-20+ | ❌ None | Overkill for this scale |

**DynamoDB schema for time-series sentiment:**

```
Partition Key: DATE#2024-01-15
Sort Key: 1705312800#abc123  (timestamp#comment_id)

GSI1 (Sentiment queries):
  PK: SENTIMENT#positive
  SK: 1705312800#abc123

GSI2 (Author queries):
  PK: AUTHOR#hoops_fan_42
  SK: 1705312800
```

This design supports efficient queries by date range, sentiment category, and author while staying within the **25GB Always Free storage limit** for typical season datasets.

**S3 cost reference**: Storing 100GB for one year costs **$27.60** in S3 Standard or **$1.19** in Glacier Deep Archive. For processed Parquet files with active querying, **S3 Intelligent-Tiering** automatically optimizes costs based on access patterns.

**Athena pricing**: $5 per TB scanned. With properly partitioned Parquet files (by year/month/day), a typical sentiment query scanning 10GB costs **$0.05**. Columnar format reduces scanned data by 60-90% compared to raw JSON.

---

## Recommended architecture balances portfolio value and cost

The optimal approach for a data engineering portfolio project combines local preprocessing with AWS serverless components:

```
┌──────────────────────────────────────────────────────────────┐
│                    LOCAL PREPROCESSING                        │
│  Academic Torrents → Download nba_comments.zst               │
│  Python zstandard streaming → Filter + clean JSONL           │
│  Output: 1-2GB filtered data                                 │
└──────────────────────────────────────────────────────────────┘
                              │ Upload (FREE)
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    S3 RAW LAYER                              │
│  s3://bucket/raw/nba-comments/2023-24-season.jsonl          │
└──────────────────────────────────────────────────────────────┘
                              │ S3 Event Trigger
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              STEP FUNCTIONS ORCHESTRATION                    │
│  1. Lambda: Chunk data into 10K-record batches              │
│  2. Lambda: Submit to Claude Batch API                      │
│  3. Lambda: Poll for completion                             │
│  4. Lambda: Parse results, write to DynamoDB                │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    STORAGE LAYER                             │
│  DynamoDB: Classification results (Always Free 25GB)        │
│  S3 Processed: Parquet for Athena analytics                 │
└──────────────────────────────────────────────────────────────┘
```

**Why this architecture**: Step Functions demonstrates workflow orchestration skills, Lambda shows serverless compute patterns, DynamoDB proves NoSQL design capability, and S3+Athena exhibits data lake fundamentals—all within free tier limits for ongoing costs.

### Cost breakdown for processing one NBA season

| Scenario | Claude API | AWS Services | Total |
|----------|-----------|--------------|-------|
| **Sample demo (100K comments)** | $2.50 | $0 (free tier) | **~$3** |
| **Full season (12M comments, Claude 3 Haiku)** | $25-30 | $2-5 | **~$30-35** |
| **Full season (12M comments, Claude 3.5 Haiku)** | $80-100 | $2-5 | **~$85-105** |

**Free tier components that apply**:
- Lambda: 1M requests + 400K GB-seconds/month (perpetual)
- DynamoDB: 25GB storage + 25 RCU/WCU (perpetual)
- Step Functions: 4,000 state transitions/month (perpetual)
- S3: 5GB storage + 20K GET requests (12 months)

---

## Specific numbers for project planning

| Metric | Value |
|--------|-------|
| r/NBA comments per season | 11-13 million |
| Compressed archive size per season | 1-2 GB (ZST) |
| Decompressed size per season | 6-10 GB (JSONL) |
| Processing speed (streaming + filtering) | 50,000-100,000 records/sec |
| Claude 3 Haiku cost per 1M comments (batch) | $25 |
| Claude 3.5 Haiku cost per 1M comments (batch) | $80 |
| S3 Standard storage for 100GB/year | $27.60 |
| DynamoDB Always Free storage | 25GB perpetual |
| Minimum viable monthly AWS cost | $0-5 |
| Full pipeline one-time cost | $30-150 |

---

## Practical implementation checklist

**Data acquisition**:
1. Download torrent from Academic Torrents per-subreddit archive
2. Select only `nba_comments.zst` (and optionally team subreddits)
3. Alternatively, use Arctic Shift download tool for specific date ranges

**Local processing**:
1. Install `zstandard` library (`pip install zstandard`)
2. Stream decompress with `max_window_size=2147483648`
3. Filter by created_utc for season date ranges
4. Output cleaned JSONL with fields: id, body, author, author_flair_text, created_utc, score

**AWS setup**:
1. Create S3 bucket with Intelligent-Tiering lifecycle policy
2. Configure DynamoDB table with date-based partition key and GSI for sentiment
3. Deploy Lambda functions for chunking, API calls, and result processing
4. Create Step Functions state machine for orchestration
5. Add CloudWatch dashboard for monitoring

**Classification pipeline**:
1. Split data into 10K-comment batches
2. Submit to Claude Batch API with temperature=0
3. Poll for completion (typically <1 hour)
4. Parse structured JSON responses
5. Write to DynamoDB and S3 Parquet simultaneously

This architecture demonstrates production-ready patterns while staying within practical cost constraints for a portfolio project, with the flexibility to scale for larger analyses when needed.