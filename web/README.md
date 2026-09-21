# web/ — the site

Astro (static output) + React islands + TypeScript, built from the published data contract:
`https://courtsentiment.com/data/season=<season>/` — `manifest.json`, `schema.json` and the parquets the
manifest registers. No parquet reaches the browser; every page is rendered at build.

## Run

```bash
nvm use                      # Node 22 (.nvmrc)
npm ci
npm run dev                  # http://localhost:4321/
npm run dev -- --host        # also on the LAN: open the printed URL on a phone
npm run build                # codegen --check, then astro build → dist/
npm run preview              # serve dist/ at :4321
```

Env is shell-only (`astro build` does not read `.env`):

| Variable | Default | Effect |
|---|---|---|
| `DATA_BASE` | `https://courtsentiment.com/data` | A URL uses the published layout; a path (e.g. `../data`) uses the repo's `data/<season>/dashboard/` |
| `SITE_INDEXABLE` | unset | Every page carries `noindex` unless this is `true`. Flipped in the deploy workflow on launch day |

## The contract

`src/data/schema.json` is the committed snapshot of the published `schema.json`; `src/data/types.gen.ts` is
generated from it and never edited. `npm run codegen` refreshes both from `DATA_BASE`. The build fails when the
types are stale (`codegen --check`), when the published schema differs from the snapshot (contract drift), or when
a table breaks an assertion in `src/data/assert.ts`: columns and dtypes, row counts, rates against counts, weekly
sums, Mondays, unique keys, every foreign key. Every rule number (official minimum, floors, formulas, corpus) is
read from the manifest; `src/no-literal-rules.test.ts` keeps them out of the code.

## Checks

```bash
npm run check                # astro check (TypeScript over .astro and .ts)
npm run lint                 # oxlint
npm test                     # vitest: lib/, data/, the type generator
npm run walk                 # Playwright over dist/ at 1280 and 400: zero console errors, no overflow
npm run shot -- <url> out.png [w] [h]   # one screenshot of a running server
```

The walk needs Chromium once: `npx playwright install chromium`. It writes screenshots of `/styleguide/` (normal,
grayscale, deuteranopia) to `walk/out/`. CI (`.github/workflows/web.yml`) runs check, lint, test, build and walk on
every PR touching `web/`; the pre-commit hook runs check, lint and test on commits touching `web/`.

## What ships

Static HTML per route (`<route>/index.html`, plus `404.html`). One island hydrates on every page: `PlayerSearch`
in the header, which carries the React runtime. Nothing else runs JavaScript. `/styleguide/` renders every core
component in every variant on real data; a colour, size or component change is made there once.
