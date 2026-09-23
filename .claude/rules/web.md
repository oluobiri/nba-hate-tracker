---
paths:
  - "web/**"
---
# Web Conventions

Loads for work under `web/`. Commands, the contract and the checks are in `web/README.md`;
the design brief is `docs/internal/ux-review.md`.

- **Generated, never edited:** `src/data/types.gen.ts` and `src/data/schema.json` move as a
  pair via `npm run codegen`; the build fails on stale types.
- **No literal rule numbers.** The official minimum, floors, formulas and corpus figures are
  read from the manifest; `src/no-literal-rules.test.ts` fails the build on `5,000` or `0.9`.
  Figures quoted in the brief are examples, never copied.
- **Rates from counts.** Re-aggregate with `sumCounts`, then take the rate; never average
  rates. `src/lib/metrics.ts` is the only place a formula lives.
- **Loader boundary:** INT64 → `number`, DATE and TIMESTAMP → ISO strings, once, in
  `src/data/rows.ts`. Nothing downstream handles a `Date` or a `bigint`.
- **HTML first.** A `client:*` directive needs browser state as its reason, sits on the
  region's wrapper rather than a leaf, and one island covers one interactive region. The
  list of islands is pinned by `src/islands.test.ts`.
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
  and 400.
- **Where a rule is checkable, write the test, not the paragraph.** `no-literal-rules` and
  `islands` are the models.
- **A page composes in its frontmatter.** `getSeason()` once, joins done there, and every
  island receives plain props: counts plus the strings it renders, rule numbers by name.
  Page layout CSS lives in the page's scoped `<style>`; an island's layout CSS is a
  stylesheet the island imports, since scoped styles never reach React-rendered markup.
- **URL state through `useViewState`** (`useSyncExternalStore` over the query string): the
  first render is the default view on both server and client, and a deep link takes over
  after hydration. Slider drags write with `replace`, everything else pushes.
- **A new component lands with its style-guide section in the same commit**, its awkward
  cases chosen by rule from live data. Look at `dist/` before the next component.
- **Gate:** the pre-commit hook runs check, lint and vitest for any staged `web/` file;
  build and walk run in CI. Commit scope is `web`.
