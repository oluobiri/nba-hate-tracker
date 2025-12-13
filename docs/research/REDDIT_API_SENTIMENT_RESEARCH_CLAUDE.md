# Building NBA sentiment analysis from Reddit data

Reddit's **100 requests per minute** rate limit and **1,000-item hard cap** on listings define the core constraints for any NBA sentiment analysis project. The good news: PRAW handles rate limiting automatically, and for ongoing collection, streaming bypasses the historical cap entirely. The bad news: accessing pre-2025 data now requires downloading **3.4 TB of archived dumps** from Academic Torrents since Pushshift's public API was terminated in mid-2023. For sentiment modeling, **twitter-roberta-base-sentiment-latest** outperforms VADER on Reddit's sarcasm-heavy text, though you'll want an irony detection pre-filter given r/NBA's culture.

## Reddit API rate limits and the 1,000-item ceiling

The official Reddit API provides **100 queries per minute** for OAuth-authenticated applications, averaged over a 10-minute window (allowing bursts up to 600 requests per 10 minutes). Monitor these response headers for rate limit status:

```python
X-Ratelimit-Used       # Requests used in current period
X-Ratelimit-Remaining  # Requests remaining
X-Ratelimit-Reset      # Seconds until period resets
```

The **1,000-item listing cap** applies to all standard endpoints (`/new`, `/hot`, `/top`, user histories, search results) regardless of pagination. This isn't a bug—Reddit's API was "built with live content consumption in mind, not bulk historical access." You cannot query by date range through the official API.

**Practical workarounds:**
- **Streaming** (`subreddit.stream.comments()`) captures new content continuously, building historical data over time
- **Multiple sort orders** (combining `/new`, `/top`, `/hot`) return different 1,000-item sets
- **Direct ID access** works regardless of age—if you have a post/comment ID, you can fetch it

PRAW (current stable version **7.8.1**) handles pagination and rate limiting automatically. Initialize with a proper User-Agent or face severe throttling:

```python
import praw

reddit = praw.Reddit(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
    user_agent="python:nba_sentiment:v1.0 (by /u/your_username)"
)

# Stream comments continuously (bypasses 1000-item cap for new data)
for comment in reddit.subreddit("nba").stream.comments():
    process(comment)
```

The critical gotcha for comment collection is **MoreComments** objects—placeholders for unexpanded reply threads. Without handling these, you'll miss nested conversations:

```python
submission = reddit.submission(id="abc123")
submission.comments.replace_more(limit=32)  # Expand hidden threads (each = 1 API call)
all_comments = submission.comments.list()   # Flattened list
```

## Historical data access fundamentally changed in 2023

**Pushshift**, which powered most Reddit research for a decade (cited in **1,700+ academic papers**), had its public API terminated in June 2023 following Reddit's API pricing changes. Limited access remains for verified moderators only through r/pushshiftrequest.

**Academic Torrents is now the primary source** for historical Reddit data. The main dataset covers June 2005 through December 2024:

| Dataset | Size | Format | Coverage |
|---------|------|--------|----------|
| Full Reddit archive | ~3.4 TB | Zstandard-compressed NDJSON | 2005-2024 |
| Per-subreddit files | Varies | Same format | Top 40,000 subreddits |
| Monthly structure | ~10-50 GB/month | RC_YYYY-MM.zst (comments), RS_YYYY-MM.zst (submissions) | Monthly archives |

Processing requires the `zstandard` Python library. Tools available at github.com/Watchful1/PushshiftDumps. **Arctic Shift** (arctic-shift.photon-reddit.com) continues collecting new data post-Pushshift and offers a search interface plus downloads for specific subreddits.

**Legal considerations**: Reddit's May 2024 Public Content Policy formally restricts data access without an agreement. For academic/non-commercial research, Reddit states this is "OK provided you use it exclusively for academic purposes and don't redistribute." Reddit has actively litigated against companies scraping for AI training (Anthropic, Perplexity) but has not enforced against individual researchers using archived dumps. Store data responsibly and honor deletion requests—Reddit's terms require removing user content within 48 hours when deleted from the platform.

## Comment data structure and what you'll actually get

Each Reddit comment includes these fields relevant for sentiment analysis:

```python
{
    'id': 'xyz789',                           # Unique identifier
    'body': 'Comment text...',                # Raw markdown (what you analyze)
    'author': 'username',                     # Or None if deleted
    'score': 42,                              # Upvotes minus downvotes (fuzzed)
    'controversiality': 0,                    # Binary: 0=normal, 1=controversial
    'created_utc': 1702500000,                # Unix timestamp (always UTC)
    'parent_id': 't1_abc123',                 # t1_=comment parent, t3_=post
    'link_id': 't3_submission_id',            # Original post
    'author_flair_text': 'Lakers',            # Team affiliation (critical for NBA)
    'author_flair_css_class': 'lakers',       # CSS identifier
    'edited': False,                          # Or timestamp if edited
    'gilded': 0,                              # Awards received
}
```

**Score fuzzing** is critical to understand: Reddit intentionally adds noise to vote counts to combat manipulation. The general magnitude is accurate, but specific numbers vary ±2-5 points on refresh. The `controversiality` flag (binary) is more reliable for identifying divisive content. For sentiment analysis, use scores for relative ranking within time windows rather than absolute values.

**Deleted/removed content patterns:**

| Scenario | author | body | Meaning |
|----------|--------|------|---------|
| User deleted | `[deleted]` | `[deleted]` | User removed their comment |
| Mod removed | Original author | `[removed]` | Moderator action |
| Account deleted | `[deleted]` | Original text remains | Account gone, content preserved |

## Sentiment analysis approaches that work for Reddit

Traditional sentiment tools struggle with Reddit. A 2025 study comparing VADER, TextBlob, and BERT on Reddit data found massive discrepancies: VADER classified 55% of content as positive while BERT found only 30% positive. The gap comes from **sarcasm prevalence**—Reddit's "/s" tag culture means positive words frequently convey negative sentiment.

**Recommended multi-stage pipeline:**

**Stage 1: Sarcasm pre-filter** using `cardiffnlp/twitter-roberta-base-irony`. This flags potentially sarcastic comments before sentiment classification, allowing you to treat them separately or invert their sentiment scores.

**Stage 2: Sentiment classification** with `cardiffnlp/twitter-roberta-base-sentiment-latest`. Trained on **124 million tweets**, it handles informal language, emojis, and social media conventions that break lexicon-based tools. Implementation:

```python
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from scipy.special import softmax

MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"
tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSequenceClassification.from_pretrained(MODEL)

def preprocess(text):
    tokens = []
    for t in text.split():
        t = '@user' if t.startswith('@') else t
        t = 'http' if t.startswith('http') else t
        tokens.append(t)
    return " ".join(tokens)

def get_sentiment(text):
    encoded = tokenizer(preprocess(text), return_tensors='pt', truncation=True)
    scores = softmax(model(**encoded)[0][0].detach().numpy())
    return {'negative': scores[0], 'neutral': scores[1], 'positive': scores[2]}
```

**VADER** remains useful for quick baseline analysis—it's fast, requires no GPU, and handles social media conventions like emoticons and ALL CAPS. But expect **~60-70% accuracy** versus human annotation on Reddit, with a positive skew.

**NBA-specific language challenges** require custom handling. Player nicknames carry embedded sentiment: "LeBum" and "LeMickey" are negative, "LeGoat" is positive, yet all refer to LeBron James. "Mickey Mouse ring" sarcastically diminishes the 2020 championship. Build a supplementary lexicon mapping these terms, and leverage user flair (team affiliation) as context—the same play described as "smart foul" by one fanbase becomes "dirty play" to another.

## The r/NBA ecosystem and all 30 team subreddits

r/NBA has approximately **16.9 million subscribers**, making it the **#1 sports subreddit** and one of Reddit's most active communities overall. Activity peaks during playoffs (Finals Game 7 threads can exceed **50,000 comments**, sometimes requiring overflow threads), trade deadline "F5 season," and breaking news.

**Thread types vary dramatically in data quality:**

| Thread Type | Comment Volume | Sentiment Quality | Notes |
|-------------|---------------|-------------------|-------|
| Game Threads | 500-50,000 | Low-Medium | Real-time noise, emojis, hot takes |
| Post-Game Threads | Thousands | Medium-High | More thoughtful analysis |
| News Threads | High | Medium | Reactive, emotional |
| OC Analysis | Low | High | Detailed, analytical content |

**Flair extraction** is essential for team-level sentiment analysis. Approximately **80% of r/NBA comments** come from users with team flairs. Extract via `comment.author_flair_text` (returns team name or custom text) or `comment.author_flair_css_class` (returns standardized identifiers like "lakers" or "celtics"). Watch for "bandwagon" flairs during playoffs—research shows ~18% of playoff team flairs are bandwagon fans.

**All 30 team subreddits** (naming inconsistencies flagged):

- **Atlantic**: r/bostonceltics, r/GoNets ⚠️, r/NYKnicks, r/sixers, r/torontoraptors
- **Central**: r/chicagobulls, r/clevelandcavs, r/DetroitPistons, r/pacers, r/MkeBucks
- **Southeast**: r/AtlantaHawks, r/CharlotteHornets, r/heat, r/OrlandoMagic, r/washingtonwizards
- **Northwest**: r/denvernuggets, r/timberwolves, r/Thunder, r/ripcity ⚠️, r/UtahJazz
- **Pacific**: r/warriors, r/LAClippers, r/lakers, r/suns, r/kings
- **Southwest**: r/Mavericks, r/rockets, r/memphisgrizzlies, r/NOLAPelicans, r/NBASpurs ⚠️

Largest legitimate communities: r/lakers (~200K), r/bostonceltics (~180K), r/torontoraptors (~200K). Note that r/warriors shows ~475K subscribers but this is inflated by a 2017 Reddit app bug.

## Production pipeline recommendations

**Database**: PostgreSQL with this schema handles Reddit's semi-structured data well:

```sql
CREATE TABLE reddit_comments (
    id VARCHAR(20) PRIMARY KEY,
    link_id VARCHAR(20) NOT NULL,
    parent_id VARCHAR(20) NOT NULL,
    author VARCHAR(50),
    body TEXT,
    score INTEGER,
    controversiality SMALLINT,
    created_utc TIMESTAMP WITH TIME ZONE NOT NULL,
    subreddit VARCHAR(50) NOT NULL,
    author_flair_text VARCHAR(100),
    sentiment_score FLOAT,
    sentiment_label VARCHAR(20),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_created_utc ON reddit_comments(created_utc);
CREATE INDEX idx_subreddit ON reddit_comments(subreddit);
CREATE INDEX idx_link_id ON reddit_comments(link_id);
```

**Storage estimate**: ~3 KB per comment with indexes. 1 million comments ≈ 3 GB.

**Incremental loading strategy**: Track `created_utc` of your most recent fetch. For ongoing collection, streaming is more reliable than polling:

```python
def stream_with_checkpoint(subreddit_name: str, checkpoint_file: str):
    last_id = load_checkpoint(checkpoint_file)
    
    for comment in reddit.subreddit(subreddit_name).stream.comments():
        if should_skip(comment.id, last_id):
            continue
        
        store_comment(comment)
        save_checkpoint(checkpoint_file, comment.id)
```

**Critical pitfalls to avoid:**
- Running multiple processes with the same OAuth credentials (shares single rate limit bucket)
- Ignoring MoreComments objects (misses 30-60% of nested replies)
- Using default User-Agent strings (triggers aggressive throttling)
- Storing `body_html` when you only need `body` (doubles storage requirements)
- Assuming score values are exact (they're fuzzed ±2-5 points)

## What changed recently and what to watch

**2023 changes still affecting pipelines:**
- Pushshift public API terminated (June 2023)
- NSFW content completely blocked from third-party API access (July 2023)
- Free tier preserved at 100 QPM for non-commercial use
- Commercial use now requires paid tier ($0.24 per 1,000 calls) and Reddit approval

**2024-2025 developments:**
- Arctic Shift emerged as primary Pushshift successor
- Academic Torrents archives extended through December 2024
- Reddit signed licensing deals with OpenAI and Google ($60M annually for Google)
- Active litigation against AI companies scraping without permission

**Likely future changes:** Reddit has signaled continued tightening of data access. The free API tier could face further restrictions. Build your pipeline to handle potential authentication changes, and consider whether real-time streaming (building your own historical archive) provides more stability than depending on third-party archives.