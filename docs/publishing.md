# Publishing

How a season's dashboard drop reaches `https://courtsentiment.com/data/season=<season>/` and the media drop reaches `https://courtsentiment.com/media/`, what sits behind those URLs, and how to run, verify, and undo a publish.

## The published surface

One hostname, split by path, over two private buckets and one CloudFront distribution. The S3 key is the public path.

| Path | Origin | Contents |
|---|---|---|
| `/` (default) | `courtsentiment-web` | The site, deployed by the workflow below. A CloudFront Function rewrites directory requests to `index.html`. |
| `/data/*` | `courtsentiment-data` | The published data contract: one `season=<season>/` prefix per season holding the manifest, the schema and its parquets. |
| `/media/*` | `courtsentiment-data` | First-party images: headshots and logos, key = `media/<name>`. |

- Both buckets block all public access at the account and bucket level. CloudFront reads them through one Origin Access Control; each bucket policy grants the CloudFront service principal `GetObject` and `ListBucket` conditioned on the distribution ARN. `ListBucket` is what makes a missing key a 404 rather than a 403.
- The data bucket is versioned and uses SSE-S3. A single-PUT object's ETag is therefore its MD5, which the publish step relies on.
- All three behaviors use the managed CachingOptimized policy, redirect HTTP to HTTPS, and compress. A distribution-wide custom error maps 404 to `/404.html`, so a missing data key returns that HTML body with a 404 status.
- DNS is a Route 53 zone the registrar delegates to; the ACM certificate covers the apex and `www`, validated by two CNAMEs that must stay in the zone for renewal.

### Identities

| Role | Assumed by | May |
|---|---|---|
| `courtsentiment-data-publish` | the owner's IAM user, MFA required | list the data bucket; put and delete under `data/*` and `media/*`; create and read invalidations on the distribution |
| `github-courtsentiment-web-deploy` | GitHub Actions via OIDC, `main` only | list, put, delete on the web bucket; invalidate. Nothing on the data bucket. |

The publish role cannot read objects. The bucket listing (keys and ETags) is its only view of remote state, and the public URL is the only way to confirm a drop.

The CLI profile `courtsentiment-publish` in `~/.aws/config` names the publish role, the source profile, and the MFA device. boto3 prompts for a code on the first call of each run.

## The publish step

`scripts/publish_dashboard.py` is the entry point; `pipeline/publish.py` holds the logic; `config/publish.yaml` names the bucket, the data and media prefixes, distribution, base URL, and profile. The file holds no credentials.

The upload set is `manifest.json`, `schema.json` and exactly the files the manifest's table registry names. Nothing else in the dashboard directory ships, and a season without a manifest cannot be published.

A run, in order:

1. **Pre-flight**, before any write. The manifest's `season` matches the flag and its `schema_version` matches the contract. Every registered parquet exists, carries the same `schema_version` stamp, has the registry's row count, and is under 8 MiB (each object is one PUT held in memory; the cap flags a table that has outgrown the contract). `schema.json` equals what the running code generates, so a file from an older checkout never ships. Any failure aborts with nothing touched.
2. **Diff** the set against the bucket listing under `data/season=<season>/`. An object whose MD5 equals the remote ETag is skipped, so the bucket's version history records real changes only. Remote keys the registry does not name are marked for deletion.
3. **Write**: parquets in registry order, then the schema, then the manifest, each with its own headers.
4. **Delete** stale keys, after the manifest lands, so an old manifest's tables stay readable until the new one is in place.
5. **Invalidate** `/data/season=<season>/*` and wait for completion.
6. **Verify**: fetch the public manifest over HTTPS and require its `generated_at` to equal the local one.

`--dry-run` stops after step 2 and prints the plan. It still lists the bucket, so it still prompts for MFA. A run that changes nothing skips the invalidation and still verifies.

Objects are overwritten in place, so for the seconds an upload takes the old manifest sits over new tables. Manifest-last guards the opposite order only. The drop is small enough that the window is seconds, and a rebuild with identical tables uploads just the manifest, so it is usually zero. Content-versioned paths are the remedy if that ever matters.

| Object | Content-Type | Cache-Control |
|---|---|---|
| `*.parquet` | `application/vnd.apache.parquet` | `public, max-age=86400` |
| `manifest.json`, `schema.json` | `application/json` | `public, max-age=300` |

## The media drop

`scripts/publish_media.py` is the entry point, over the same logic module. The images are the league's; the repository never holds them, and `scripts/fetch_media.py` fetches them into the gitignored `data/media/` (season-independent) and derives the variants.

Naming, relative to the media root; the S3 key is `media/` plus the name, and the site builds its `srcset` from the id alone:

| Name | What |
|---|---|
| `headshots/<player_id>.png` | The original, 1040x760 |
| `headshots/<player_id>-<width>.webp` | WebP with alpha at widths 180, 420, 840 |
| `logos/<team_id>.svg` | The primary logo, untouched |

The upload set is exactly the names the dimension tables' ids imply: the union of `player_id` from `players.parquet` and `team_id` from `teams.parquet` across every season under `config/`. A season with no dashboard yet contributes nothing; a season with one table but not the other aborts; no contributing season at all aborts, since an empty set would plan deleting every media key. Nothing in the media directory ships unless a table names its id.

A run, in order: **pre-flight** (every expected file present and under 8 MiB, every failure listed at once); **diff** against the listing under `media/`; **write** in name order; **delete** keys the set no longer names; **invalidate** `/media/*`; **verify** by a HEAD of every key through the public origin, requiring a 200 and the object's Content-Type. There is no manifest to compare, so the public state is the assertion. `--dry-run` stops after the diff.

| Object | Content-Type | Cache-Control |
|---|---|---|
| `*.png` | `image/png` | `public, max-age=604800` |
| `*.webp` | `image/webp` | `public, max-age=604800` |
| `*.svg` | `image/svg+xml` | `public, max-age=604800` |

Keys are overwritten in place, so a version is never part of the name; a week bounds a returning visitor's staleness, and the invalidation clears the edge on every drop.

The tables point at these URLs (`headshot_url`, `logo_url` are first-party literals in config), so the order across the two drops matters: media first, then rebuild, then the season. A roster change is `fetch_media`, then `publish_media`, then the season publish. After a fetch, scan the headshots for duplicate bodies: the CDN substituting a generic silhouette is the one failure the byte sniff cannot catch.

```bash
# 1. Plan. Reads the bucket; writes nothing.
uv run python -m scripts.publish_media --dry-run

# 2. Publish. Ends with every public URL verified, or exits 1.
uv run python -m scripts.publish_media

# 3. Confirm by hand.
curl -sI https://courtsentiment.com/media/headshots/203500-180.webp
curl -sI https://courtsentiment.com/media/logos/1610612737.svg
```

## The site deploy

`.github/workflows/deploy-web.yml` builds `web/` and syncs `web/dist/` to the web bucket. It runs on a push to `main` that touches `web/` or the workflow itself, and by hand (`workflow_dispatch`). Nothing else writes to that bucket.

- **Identity:** GitHub Actions assumes `github-courtsentiment-web-deploy` through OIDC. The job holds `id-token: write` and `contents: read`, nothing else, and no long-lived key exists. The role ARN is the repository secret `AWS_WEB_DEPLOY_ROLE_ARN` (it carries the account id; the repository is public). Bucket and distribution are literals in the workflow.
- **Build:** `npm ci`, then `npm run build` against the published contract, the same bytes a visitor's build would read. `SITE_INDEXABLE` is set in the workflow file; every page is `noindex` until it says `true`, so that line is the launch switch.
- **Sync**, three passes, so no page at the origin ever references a missing asset: hashed assets under `_astro/` first, without delete; then everything else, with delete, which removes stale routes; then `_astro/` again with delete, which uploads nothing and prunes the assets no page names any more. A visitor holding a page cached in the five minutes before a deploy can miss one pruned asset until that copy expires; the short page lifetime bounds it.
- **Invalidate** `/*` and wait for completion.
- **Verify** through the public origin, failing the job on any miss: `/`, one route and `/404.html` return 200, an unknown route 404, and the headers on the index, a stylesheet and a font are the ones below.

One run at a time (a concurrency group, no cancellation): two close merges queue rather than race the deletes.

| Object | Cache-Control |
|---|---|
| `_astro/*` (hashed) | `public, max-age=31536000, immutable` |
| everything else | `public, max-age=300` |

Content types are guessed from the extension by the sync, except `.woff2`, whose guess varies by machine and is set explicitly; the verify step checks a stylesheet and a font.

### Running it by hand

After a season publish. The pages carry the numbers, so a new drop is invisible until the site is rebuilt against it:

```bash
gh workflow run deploy-web
gh run watch
```

The same applies after a media drop that changed ids. The job runs on the `main` ref only, matching the role's trust policy; a dispatch from any other branch is skipped.

## Runbook

Build the season first (`scripts.aggregate_sentiment`), then:

```bash
# 1. Plan. Reads the bucket; writes nothing.
uv run python -m scripts.publish_dashboard --season 2025-26 --dry-run

# 2. Publish. Ends with the public manifest verified, or exits 1.
uv run python -m scripts.publish_dashboard --season 2025-26

# 3. Confirm by hand.
curl -sI https://courtsentiment.com/data/season=2025-26/manifest.json
curl -sI https://courtsentiment.com/data/season=2025-26/schema.json
curl -sI https://courtsentiment.com/data/season=2025-26/player_overall.parquet
duckdb -c "SELECT attributed_player, neg_rate
           FROM read_parquet('https://courtsentiment.com/data/season=2025-26/player_overall.parquet')
           ORDER BY neg_rate DESC LIMIT 5"
```

Expect a 200 with the content type and cache policy from the table above, and `accept-ranges: bytes` on the parquet (range requests let remote readers fetch the footer first).

A rebuilt season with identical tables plans as one upload (the manifest, whose `generated_at` changed) and the rest skipped. `schema.json` carries no timestamp, so it is skipped too unless the contract itself changed.

## Rolling back

The simplest rollback is forward: check out the build you want, rebuild the season locally, and publish it. The publish step's diff makes that a small drop, and the version history stays linear.

The data bucket also keeps every version of every object, so a single object can be restored from an earlier version. Copying a version needs read on the source object, which the publish role does not have by design; run these under your own user credentials (the default profile), then invalidate under the publish role:

```bash
aws s3api list-object-versions \
  --bucket courtsentiment-data --prefix data/season=2025-26/manifest.json \
  --query 'Versions[].[VersionId,LastModified,IsLatest]'

aws s3api copy-object \
  --bucket courtsentiment-data --key data/season=2025-26/manifest.json \
  --copy-source "courtsentiment-data/data/season=2025-26/manifest.json?versionId=<id>" \
  --content-type application/json --cache-control "public, max-age=300" \
  --metadata-directive REPLACE
# schema.json rolls back the same way, with the same headers, if the contract changed.

aws cloudfront create-invalidation --profile courtsentiment-publish \
  --distribution-id E2X7LKN4E54XA2 --paths "/data/season=2025-26/*"
```

Restore the tables before the manifest, for the same reason the publish step writes them first. The copy is a new version of the object, so the history records the rollback too.

Media keys are versioned the same way. The same copy recipe restores one, with its image content type and `public, max-age=604800`, followed by an invalidation of `/media/*`.

## When the repository is renamed

The GitHub OIDC trust policy on `github-courtsentiment-web-deploy` pins the subject to the repository path (`repo:<owner>/<repo>:ref:refs/heads/main`). Edit it in the same change as the rename or the site deploy stops authenticating. The workflow itself carries no repository name. The publish role and `config/publish.yaml` do not reference the repository.

## Checking DNS and TLS

```bash
# What the world resolves (bypasses any local resolver)
curl -s 'https://dns.google/resolve?name=courtsentiment.com&type=A'

# Talk to the distribution directly while a local resolver is stale
curl -sI --connect-to courtsentiment.com:443:d1knzu0p8v41lg.cloudfront.net:443 \
  https://courtsentiment.com/data/season=2025-26/manifest.json

# Direct bucket URLs must stay closed
curl -sI https://courtsentiment-data.s3.us-east-1.amazonaws.com/data/season=2025-26/manifest.json  # 403
```
