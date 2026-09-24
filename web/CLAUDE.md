<!-- Loads when Claude reads a file under web/; the root .claude/CLAUDE.md carries the everyday
commands. A line belongs here when the next page's session would get it wrong without it: page
specs live in docs/internal/ux-review.md and the tickets, and anything a test pins is named, not
restated. A human-facing web/README.md comes with the stable site. -->

# web/ — the site

Astro (static output) + React islands + TypeScript, built from the published data contract:
`https://courtsentiment.com/data/season=<season>/` — `manifest.json`, `schema.json` and the
parquets the manifest registers. No parquet reaches the browser; every page is rendered at build.
The design brief is `docs/internal/ux-review.md` (local only, not committed).

## Map

```
src/
├── pages/        → one .astro per route; see "A page composes in its frontmatter"
├── components/   → .tsx (in an island, or static HTML without a directive) / .astro (shell only)
├── lib/          → pure logic and sentences, each with a colocated .test.ts
├── data/         → the contract boundary: env → load → rows → assert
│                   schema.json + types.gen.ts are generated, never edited
├── styles/       → tokens.css + components.css (reviewed on /styleguide/); per-region sheets for islands
├── layouts/      → Base.astro (head, nav, footer, noindex)
└── *.test.ts     → repo-wide guards: islands, no-literal-rules, mark, site
scripts/          → codegen.ts (schema.json → types.gen.ts), precommit.sh, shot.mjs
walk/             → Playwright over dist/; screenshots to walk/out/
public/           → favicon.svg (the mark; its colours pinned to tokens.css by src/mark.test.ts)
```

## Commands

The everyday set is in the root CLAUDE.md. Beyond it:

```bash
nvm use && npm ci                        # Node 22 (.nvmrc)
npm run dev -- --host                    # also on the LAN: open the printed URL on a phone
npm run preview                          # serve dist/ at :4321
npm run shot -- <url> out.png [w] [h]    # one screenshot of a running server
npx playwright install chromium          # once, before the first walk
```

Env is shell-only (`astro build` does not read `.env`):

| Variable | Default | Effect |
|---|---|---|
| `DATA_BASE` | `https://courtsentiment.com/data` | A URL uses the published layout; a path (e.g. `../data`) uses the repo's `data/<season>/dashboard/` |
| `SITE_INDEXABLE` | unset | Every page carries `noindex` unless this is `true`. Flipped in the deploy workflow on launch day |

## The contract

`src/data/schema.json` is the committed snapshot of the published `schema.json`;
`src/data/types.gen.ts` is generated from it. `npm run codegen` refreshes both from `DATA_BASE`.
The build fails when the types are stale (`codegen --check`), when the published schema differs
from the snapshot (contract drift, `load.ts`), or when a table breaks an assertion in
`src/data/assert.ts`: columns and dtypes, row counts, rates against counts, weekly sums, Mondays,
unique keys, every foreign key.

## Conventions

- **No literal rule numbers.** The official minimum, floors, formulas and corpus figures are
  read from the manifest. `src/no-literal-rules.test.ts` fails vitest on `5,000` or `0.9`; the
  floors collide with ordinary integers and are checked by eye. Figures quoted in the brief are
  examples, never copied.
- **Rates from counts.** Re-aggregate with `sumCounts`, then take the rate; never average
  rates. Every sentiment rate is computed in `src/lib/metrics.ts`.
- **Loader boundary:** INT64 → `number`, DATE and TIMESTAMP → ISO strings, once, in
  `src/data/rows.ts`. Rows never carry a `Date` or a `bigint`; a `Date` exists only briefly,
  for UTC formatting.
- **HTML first.** A `client:*` directive needs browser state as its reason, sits on the
  region's wrapper rather than a leaf, and one island covers one interactive region. The
  list of islands is pinned by `src/islands.test.ts`; adding one means adding it there.
- **`.astro` for shell that never lives inside an island; `.tsx` for anything that renders
  inside one.** A `.tsx` component without a directive renders to static HTML.
- **Colour, size and component changes** happen in `src/styles/tokens.css` and
  `components.css` and are reviewed on `/styleguide/`, never per page. One job per colour:
  heat negative, ice positive, bone and neu for neutral and interaction, `--hl` method only.
- **Sentiment order** is negative → neutral → positive everywhere. Code names follow the
  product: no `Hate*` components.
- **Cross-page state lives in the query string** via `src/lib/url.ts`; defaults come from
  the manifest so short links serialise short.
- **Charts are SVG rendered at build.** No chart library.
- **Motion lives inside islands only** (`motion/react`), wrapped in `MotionConfig
  reducedMotion="user"`; static regions animate with CSS transitions, which the global
  reduced-motion rule already stops. A lens switch keeps every row's identity (`layout`).
- **Judge output from `dist/`** (`npm run build && npm run preview`), not the dev server.
  The walk asserts zero console errors and no horizontal overflow on every route at 1280
  and 400, and screenshots `/styleguide/` in normal, grayscale and deuteranopia.
- **Where a rule is checkable, write the test, not the paragraph.** `no-literal-rules` and
  `islands` are the models.
- **A page composes in its frontmatter.** `getSeason()` (memoized), joins done there, and
  every island receives plain props: counts plus the strings it renders, rule numbers by name.
  Page layout CSS lives in the page's scoped `<style>`; an island's layout CSS is a
  stylesheet the island imports, since scoped styles never reach React-rendered markup.
- **URL state through `useViewState`** (`useSyncExternalStore` over the query string): the
  first render is the default view on both server and client, and a deep link takes over
  after hydration. Slider drags write with `replace`, everything else pushes.
- **A new component lands with its style-guide section in the same commit**, its awkward
  cases chosen by rule from live data. Look at `dist/` before the next component.

## Gate

The pre-commit hook runs check, lint and vitest for any staged `web/` file (this one
included); CI (`.github/workflows/web.yml`, every PR, a required check on `main` alongside
`python`) adds build and walk. Commit scope is `web`.
