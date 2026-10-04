// Walk every route in dist/ and hold the two invariants that cannot be
// unit-tested: zero console errors and no horizontal overflow. The style
// guide is also screenshotted as built, in grayscale and as a deuteranope.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, type Page, test } from '@playwright/test'

const DIST = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../dist')
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'out')

function routes(dir: string, prefix = '/'): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name)
    if (statSync(full).isDirectory()) return routes(full, `${prefix}${name}/`)
    return name === 'index.html' ? [prefix] : []
  })
}

function watchErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
  })
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  return errors
}

const overflow = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)

const ROUTES = routes(DIST)
test('dist/ has the routes the site promises', () => {
  expect(ROUTES).toContain('/')
  expect(ROUTES).toContain('/styleguide/')
  expect(ROUTES.filter((r) => r.startsWith('/player/')).length).toBeGreaterThan(200)
  expect(ROUTES.filter((r) => r.startsWith('/fanbases/') && r !== '/fanbases/')).toHaveLength(30)
  // One route per curated recap, as config/<season>/recaps.yaml lists them.
  expect(ROUTES.filter((r) => r.startsWith('/recaps/') && r !== '/recaps/')).toHaveLength(10)
})

for (const route of ROUTES) {
  test(`walk ${route}`, async ({ page }) => {
    const errors = watchErrors(page)
    const res = await page.goto(route, { waitUntil: 'networkidle' })
    expect(res?.status()).toBe(200)
    expect(errors, `console errors on ${route}`).toEqual([])
    expect(await overflow(page), `horizontal overflow on ${route}`).toBeLessThanOrEqual(0)
  })
}

test('the header mark decodes', async ({ page }) => {
  // A malformed SVG is a broken image, not a console error; ask the image.
  await page.goto('/', { waitUntil: 'networkidle' })
  const mark = page.locator('.hdr__mark')
  await expect(mark).toBeVisible()
  expect(await mark.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
})

test('an unknown route serves the 404 page', async ({ page }) => {
  const errors = watchErrors(page)
  const res = await page.goto('/no-such-page/')
  expect(res?.status()).toBe(404)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('No such page')
  // The document's own 404 is the one error Chromium is allowed to log here.
  expect(errors.filter((e) => !/status of 404/.test(e))).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('the search combobox works by keyboard', async ({ page }) => {
  await page.goto('/season/', { waitUntil: 'networkidle' })
  const input = page.getByRole('combobox', { name: 'Search players' })
  await input.click()
  await input.pressSequentially('dray')
  await expect(input).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('option').first()).toContainText('Draymond Green')
  await input.press('Escape')
  await expect(input).toHaveAttribute('aria-expanded', 'false')
  await input.press('ArrowUp')
  await expect(input).toHaveAttribute('aria-expanded', 'true')
  await input.press('Enter')
  await page.waitForURL('**/player/draymond-green/')
})

for (const [mode, deficiency] of [
  ['normal', 'none'],
  ['grayscale', 'achromatopsia'],
  ['deuteranopia', 'deuteranopia'],
] as const) {
  test(`style guide screenshot, ${mode}`, async ({ page }, info) => {
    const cdp = await page.context().newCDPSession(page)
    await cdp.send('Emulation.setEmulatedVisionDeficiency', { type: deficiency })
    await page.goto('/styleguide/', { waitUntil: 'networkidle' })
    await page.screenshot({ path: path.join(OUT, `styleguide-${info.project.name}-${mode}.png`), fullPage: true })
  })
}

// The leaderboard: one island, its state in the URL.
test('a deep link shows its lens, and the tabs work by keyboard', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/?lens=volume', { waitUntil: 'networkidle' })
  await expect(page.getByRole('tab', { name: 'Volume' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.hero__sentence')).toContainText('most discussed')
  await expect(page.locator('html')).not.toHaveClass(/has-view/)
  await page.getByRole('tab', { name: 'Volume' }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('tab', { name: 'Polarization' })).toHaveAttribute('aria-selected', 'true')
  await expect(page).toHaveURL(/lens=polar/)
  await page.goBack()
  await expect(page.getByRole('tab', { name: 'Volume' })).toHaveAttribute('aria-selected', 'true')
  expect(errors).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('a custom threshold is stamped unofficial and draws hollow ranks', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/?n=500&all=1', { waitUntil: 'networkidle' })
  await expect(page.locator('.thr--custom .stamp--unofficial')).toBeVisible()
  await expect(page.locator('.hero__sentence .stamp--unofficial')).toBeVisible()
  expect(await page.locator('.rank--hollow').count()).toBeGreaterThan(0)
  expect(await page.locator('.row--ghost').count()).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Reset to official' }).click()
  await expect(page).not.toHaveURL(/n=/)
  await expect(page.locator('.thr--closed, .thr--open').first()).not.toHaveClass(/thr--custom/)
  expect(errors).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('the leaderboard controls are touch-sized', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  for (const name of ['Copy link', /^Show all/, 'Adjust']) {
    const box = await page.getByRole('button', { name }).boundingBox()
    expect(box?.height ?? 0, String(name)).toBeGreaterThanOrEqual(44)
  }
  for (const tab of await page.getByRole('tab').all()) expect((await tab.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
})

// The player page: two islands, their state in the URL, five sections behind a rail.
test('a receipts deep link shows its tab, and the tabs work by keyboard', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/player/james-harden/?tab=pos', { waitUntil: 'networkidle' })
  await expect(page.getByRole('tab', { name: /^Positive/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('html')).not.toHaveClass(/has-receipts-view/)
  await expect(page.locator('.rc .exhibit--pos').first()).toBeVisible()
  await page.getByRole('tab', { name: /^Positive/ }).focus()
  await page.keyboard.press('ArrowLeft')
  await expect(page.getByRole('tab', { name: /^Neutral/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page).toHaveURL(/tab=neu/)
  await page.goBack()
  await expect(page.getByRole('tab', { name: /^Positive/ })).toHaveAttribute('aria-selected', 'true')
  expect(errors).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('the receipts expand and collapse through the URL', async ({ page }) => {
  await page.goto('/player/james-harden/?tab=pos&all=1', { waitUntil: 'networkidle' })
  expect(await page.locator('.rc .exhibit').count()).toBeGreaterThan(3)
  await page.getByRole('button', { name: 'Show 3' }).click()
  await expect(page).not.toHaveURL(/all=/)
  expect(await page.locator('.rc .exhibit').count()).toBe(3)
})

test('the game log filters and expands through the URL', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/player/victor-wembanyama/?games=all&log=all#games', { waitUntil: 'networkidle' })
  await expect(page.getByRole('button', { name: /^All games/ })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('html')).not.toHaveClass(/has-games-view/)
  expect(await page.locator('.gt tbody tr').count()).toBeGreaterThan(10)
  await page.getByRole('button', { name: /^Games the room talked about/ }).click()
  await expect(page).not.toHaveURL(/games=/)
  await expect(page).toHaveURL(/#games$/)
  expect(errors).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('the rail marks the section in view', async ({ page }) => {
  await page.goto('/player/james-harden/', { waitUntil: 'networkidle' })
  await page.locator('#games').scrollIntoViewIfNeeded()
  await page.evaluate(() => window.scrollBy(0, 200))
  await expect(page.locator('.rail__link[href="#games"]')).toHaveAttribute('aria-current', 'location')
})

test('the player page controls are touch-sized', async ({ page }) => {
  await page.goto('/player/james-harden/', { waitUntil: 'networkidle' })
  const controls = [
    ...(await page.getByRole('tab').all()),
    ...(await page.locator('.rail__link').all()),
    ...(await page.locator('.pp__chip').all()),
    ...(await page.locator('.pp__pn-link').all()),
    page.getByRole('button', { name: /^Show all/ }).first(),
    page.getByRole('button', { name: /^All games/ }),
  ]
  for (const c of controls) expect((await c.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
})

test('a week of the timeline opens its readout on focus', async ({ page }) => {
  await page.goto('/player/james-harden/', { waitUntil: 'networkidle' })
  const week = page.locator('.tl__week').nth(20)
  await week.focus()
  await expect(week.locator('.tl__tip')).toBeVisible()
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

// The team page: no island; a rail, and a <details> under each list for the rest of it.
test('the team page controls are touch-sized', async ({ page }) => {
  await page.goto('/fanbases/lal/', { waitUntil: 'networkidle' })
  const controls = [
    ...(await page.locator('.rail__link').all()),
    ...(await page.locator('.tp__chip').all()),
    ...(await page.locator('.tp__pn-link').all()),
    ...(await page.locator('.tp__more summary').all()),
    ...(await page.locator('.gap__link').all()),
    ...(await page.locator('.tk__link').all()),
  ]
  for (const c of controls) expect((await c.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
})

test('show all opens the rest of a list on the same axis, with no script', async ({ browser }, info) => {
  const context = await browser.newContext({ javaScriptEnabled: false, viewport: info.project.use.viewport })
  const page = await context.newPage()
  await page.goto('/fanbases/lal/', { waitUntil: 'load' })
  const more = page.locator('#targets .tp__more').first()
  const summary = more.locator('summary')
  await expect(summary).toHaveText(/^Show all \d+$/)
  const total = Number(/\d+/.exec((await summary.textContent())!)![0])
  const shown = await page.locator('#targets .tp__list').first().locator('> .dd .dd__row').count()
  await expect(more.locator('.dd__row').first()).toBeHidden()
  await summary.click()
  await expect(more).toHaveAttribute('open', '')
  expect(await more.locator('.dd__row').count()).toBe(total - shown)
  await expect(more.locator('.dd__rank').first()).toHaveText(String(shown + 1))
  expect(await overflow(page)).toBeLessThanOrEqual(0)
  await context.close()
})

test('the team rail marks the section in view', async ({ page }) => {
  await page.goto('/fanbases/lal/', { waitUntil: 'networkidle' })
  await page.locator('#league').scrollIntoViewIfNeeded()
  await page.evaluate(() => window.scrollBy(0, 200))
  await expect(page.locator('.rail__link[href="#league"]')).toHaveAttribute('aria-current', 'location')
})

// Edge states, one route each. The names are the data's, not a rule's.
test('a free agent has no roster line and still gets fans', async ({ page }) => {
  await page.goto('/player/chris-paul/', { waitUntil: 'networkidle' })
  await expect(page.locator('.pp__id')).toContainText('Free agent')
  await expect(page.locator('#fans .pp__tile')).toHaveCount(2)
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('a player who never dressed gets a sentence, no table, no scatter', async ({ page }) => {
  await page.goto('/player/tyrese-haliburton/', { waitUntil: 'networkidle' })
  await expect(page.locator('#games')).toContainText('never dressed')
  await expect(page.locator('#games table')).toHaveCount(0)
  await expect(page.locator('#games .sc')).toHaveCount(0)
})

test('a player below the official minimum is banded unofficial with hollow ranks', async ({ page }) => {
  await page.goto('/player/reed-sheppard/', { waitUntil: 'networkidle' })
  await expect(page.locator('.note--rule .stamp--unofficial').first()).toBeVisible()
  expect(await page.locator('.pp__chip .rank--hollow').count()).toBe(4)
  expect(await page.locator('.pp__chip .rank:not(.rank--hollow)').count()).toBe(0)
})

test('a barely-mentioned player renders every section without a chart', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/player/bogdan-bogdanovic/', { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Bogdan')
  await expect(page.locator('#timeline .tl--empty')).toBeVisible()
  await expect(page.locator('#timeline svg')).toHaveCount(0)
  await expect(page.locator('#fans .dd')).toHaveCount(0)
  expect(errors).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('a thin receipt cell shows all it has, with no show-all', async ({ page }) => {
  await page.goto('/player/aaron-wiggins/', { waitUntil: 'networkidle' })
  expect(await page.locator('.rc .exhibit').count()).toBe(1)
  await expect(page.getByRole('button', { name: /^Show all/ })).toHaveCount(0)
})

test('a one-player roster is still a table, and two fanbases still rank', async ({ page }) => {
  await page.goto('/fanbases/bkn/', { waitUntil: 'networkidle' })
  expect(await page.locator('#own .gap tbody tr').count()).toBe(1)
  await expect(page.locator('#own .tp__lede')).toContainText('their one tracked player')
  expect(await page.locator('#league .dd').count()).toBe(2)
  await expect(page.locator('#league .tp__more')).toHaveCount(0)
})

test('the saltiest fanbase has no one above it', async ({ page }) => {
  await page.goto('/fanbases/sac/', { waitUntil: 'networkidle' })
  await expect(page.locator('.tp__verdict')).toContainText('The saltiest fanbase')
  await expect(page.locator('.tp__pn-link[rel="prev"]')).toHaveCount(0)
  await expect(page.locator('.tp__pn-link--none').first()).toContainText('Saltiest of')
})

test('the least salty fanbase has no one below it', async ({ page }) => {
  await page.goto('/fanbases/uta/', { waitUntil: 'networkidle' })
  await expect(page.locator('.tp__verdict')).toContainText('The least salty fanbase')
  await expect(page.locator('.tp__pn-link[rel="next"]')).toHaveCount(0)
  await expect(page.locator('.tp__pn-link--none').first()).toContainText('Least salty of')
})

test('a long team name wraps inside the team header', async ({ page }) => {
  await page.goto('/fanbases/por/', { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Blazers fans')
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

// The fanbases landing: the picker and two lists at every width; the grid island on
// desktop only, where it is the page's one island.
const GRID_ONLY = 'the grid is a desktop view'

// client:visible — the grid hydrates once it is in view, and a deep link's view stays
// hidden until then; every test that touches it scrolls there first and waits.
async function gridReady(page: Page): Promise<void> {
  await page.locator('.fg').scrollIntoViewIfNeeded()
  await expect(page.locator('astro-island[component-export="FanGrid"]')).not.toHaveAttribute('ssr', '')
}

test('every picker tile and every list row leads to a live team page', async ({ page }) => {
  await page.goto('/fanbases/', { waitUntil: 'networkidle' })
  const tiles = await page.locator('.pk__tile').evaluateAll((as) => as.map((a) => a.getAttribute('href')!))
  expect(tiles).toHaveLength(30)
  for (const h of tiles) expect(ROUTES).toContain(h)
  const rows = await page.locator('#grudges .dd__link, #flowers .dd__link').evaluateAll((as) => as.map((a) => a.getAttribute('href')!))
  expect(rows).toHaveLength(20)
  for (const h of rows) {
    expect(h).toMatch(/#targets$/)
    expect(ROUTES).toContain(h.replace(/#targets$/, ''))
  }
})

test('the landing controls are touch-sized', async ({ page }, info) => {
  await page.goto('/fanbases/', { waitUntil: 'networkidle' })
  for (const t of await page.locator('.pk__tile').all()) {
    const box = await t.boundingBox()
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44)
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
  const rows = await page.locator('.dd__link').all()
  const buttons = info.project.name === 'desktop' ? await page.locator('.fg__controls .btn').all() : []
  for (const c of [...rows, ...buttons]) expect((await c.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
})

test('a phone gets the picker and the lists, stacked, and a line in place of the grid', async ({ page }, info) => {
  test.skip(info.project.name !== 'phone', GRID_ONLY)
  await page.goto('/fanbases/?scale=raw', { waitUntil: 'networkidle' })
  await expect(page.locator('.fg')).toBeHidden()
  await expect(page.locator('.fl__phone')).toBeVisible()
  const [west, east] = await Promise.all((await page.locator('.pk__group').all()).map((g) => g.boundingBox()))
  expect(east!.y).toBeGreaterThanOrEqual(west!.y + west!.height)
  // Never hydrated: Astro drops an island's ssr attribute when it hydrates (internal, but stable).
  await expect(page.locator('astro-island[component-export="FanGrid"]')).toHaveAttribute('ssr', '')
})

test('a grid deep link renders that view with no flash, and Back returns to it', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', GRID_ONLY)
  const errors = watchErrors(page)
  await page.goto('/fanbases/?scale=raw', { waitUntil: 'networkidle' })
  await gridReady(page)
  await expect(page.locator('html')).not.toHaveClass(/has-grid-view/)
  const raw = page.getByRole('button', { name: 'Negative share' })
  await expect(raw).toHaveAttribute('aria-pressed', 'true')
  const figure = page.locator('.fg__cell--eg > span').first()
  await expect(figure).toHaveText(/%$/)
  await page.getByRole('button', { name: "Δ vs each roster's usual" }).click()
  await expect(page).not.toHaveURL(/scale=/)
  await expect(figure).toHaveText(/^[+-]?\d+$/)
  await page.goBack()
  await expect(raw).toHaveAttribute('aria-pressed', 'true')
  expect(errors).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('the minimum presets multiply the floor; the chosen one rides in the URL', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', GRID_ONLY)
  await page.goto('/fanbases/', { waitUntil: 'networkidle' })
  await gridReady(page)
  const presets = page.locator('.fg__group[aria-label="Minimum comments per cell"] .btn')
  await expect(presets.first()).toHaveAttribute('aria-pressed', 'true')
  const before = await page.locator('.fg__cell--under').count()
  const label = (await presets.nth(2).textContent())!.trim().replace(/,/g, '')
  await presets.nth(2).click()
  await expect(page).toHaveURL(new RegExp(`min=${label}`))
  expect(await page.locator('.fg__cell--under').count()).toBeGreaterThan(before)
  await presets.first().click()
  await expect(page).not.toHaveURL(/min=/)
})

test('the grid walks by arrow key, the tip opens on focus, the crosshair follows', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop', GRID_ONLY)
  await page.goto('/fanbases/', { waitUntil: 'networkidle' })
  await gridReady(page)
  const n = await page.locator('thead .fg__ch').count()
  const eg = page.locator('.fg__cell--eg')
  await eg.focus()
  await expect(eg.locator('.fg__tip')).toBeVisible()
  const c = Number(await eg.getAttribute('data-c'))
  await page.keyboard.press('ArrowRight')
  const next = page.locator('td:focus')
  // One column on, or two across the diagonal.
  expect([c + 1, c + 2]).toContain(Number(await next.getAttribute('data-c')))
  await expect(next.locator('.fg__tip')).toBeVisible()
  expect(await next.evaluate((td) => td.parentElement!.classList.contains('fg__row--x'))).toBe(true)
  await expect(page.locator('.fg__ch--x')).toHaveCount(1)
  await page.keyboard.press('End')
  expect([n - 1, n - 2]).toContain(Number(await page.locator('td:focus').getAttribute('data-c')))
  expect(await overflow(page)).toBeLessThanOrEqual(0)
  await page.locator('td[data-r="3"][data-c="5"]').hover()
  await expect(page.locator('tr.fg__row--x th')).toHaveCount(1)
  await expect(page.locator('thead .fg__ch').nth(5)).toHaveClass(/fg__ch--x/)
})

// The recaps index: the lead in the hero with one play link, the rest as rows;
// every link a live recap page, every target touch-sized.
test('the lead and every recap row lead to a live recap page', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/recaps/', { waitUntil: 'networkidle' })
  const play = page.locator('.hero__play')
  await expect(play).toHaveCount(1)
  const hrefs = await page.locator('.hero__play, .rr__link').evaluateAll((as) => as.map((a) => a.getAttribute('href')!))
  expect(hrefs).toHaveLength(10)
  for (const h of hrefs) expect(ROUTES).toContain(h)
  for (const c of [play, ...(await page.locator('.rr__link').all())]) expect((await c.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
  expect(errors).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test("the Recap chip on a player page's game rows leads to a live recap page", async ({ page }) => {
  const key = ROUTES.find((r) => r.startsWith('/recaps/') && r !== '/recaps/')!
  const slug = key.split('/')[2]!.replace(/^\d+-/, '')
  await page.goto(`/player/${slug}/?games=all&log=all#games`, { waitUntil: 'networkidle' })
  expect(await page.locator('.gt tbody tr').count()).toBeGreaterThan(10)
  const chips = page.locator('.gt__recap')
  expect(await chips.count()).toBeGreaterThan(0)
  for (const c of await chips.all()) {
    expect(ROUTES).toContain(await c.getAttribute('href'))
    expect((await c.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('a recap page carries its name, its quarters, its verdict and its season chart', async ({ page }) => {
  const route = ROUTES.find((r) => r.startsWith('/recaps/') && r !== '/recaps/')!
  await page.goto(route, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { level: 1 })).not.toBeEmpty()
  await expect(page.locator('.ps')).toHaveCount(1)
  await expect(page.locator('.vd')).toHaveCount(1)
  await expect(page.locator('.nt__svg')).toHaveCount(1)
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

// The replay: the site's first runtime fetch and its first playback island.
const RECAP = ROUTES.find((r) => r.startsWith('/recaps/') && r !== '/recaps/')!
const ready = (page: Page) => page.waitForSelector('.replay[data-status="ready"]', { timeout: 15_000 })
const clock = (page: Page) => page.getByTestId('bug-time').textContent()

test('the replay fetches its file same-origin, hydrates, and Watch runs the clock', async ({ page }) => {
  const errors = watchErrors(page)
  const fetched = page.waitForResponse((r) => r.url().endsWith('/data.json'))
  await page.goto(RECAP, { waitUntil: 'networkidle' })
  const res = await fetched
  expect(res.status()).toBe(200)
  expect(res.headers()['content-type']).toContain('json')
  console.log(`${RECAP}data.json: ${(await res.body()).length} bytes, content-encoding ${res.headers()['content-encoding'] ?? 'none'}`)
  await ready(page)
  await expect(page.getByTestId('bug-play')).toHaveAttribute('aria-label', 'Play')
  const before = await clock(page)
  await page.getByTestId('watch').click()
  await expect(page.getByTestId('bug-play')).toHaveAttribute('aria-label', 'Pause')
  // The first seconds are the pre-game beat; the clock moves once the tip lands.
  await page.waitForTimeout(3600)
  expect(await clock(page)).not.toBe(before)
  // Watch scrolled the stage to the top of the window, under the header.
  const top = await page.locator('.replay').evaluate((el) => el.getBoundingClientRect().top)
  expect(top).toBeLessThan(80)
  expect(await page.locator('.fc').count()).toBeGreaterThan(0)
  expect(errors).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('a replay deep link opens paused at its moment with no jump, and keeps its t', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto(`${RECAP}?t=600`, { waitUntil: 'networkidle' })
  await ready(page)
  await expect(page.getByTestId('watch')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.classList.contains('has-replay-view'))).toBe(false)
  await expect(page.getByTestId('bug-play')).toHaveAttribute('aria-label', 'Play')
  const at = await clock(page)
  expect(at).not.toBe('12:00')
  await page.waitForTimeout(500)
  expect(await clock(page)).toBe(at)
  expect(page.url()).toContain('t=600')
  expect(await page.getByTestId('flow').getAttribute('aria-valuenow')).not.toBe('0')
  expect(errors).toEqual([])
})

test('space and the arrows drive the replay and write t', async ({ page }) => {
  await page.goto(RECAP, { waitUntil: 'networkidle' })
  await ready(page)
  await page.locator('.replay').focus()
  await page.keyboard.press('Space')
  await expect(page.getByTestId('bug-play')).toHaveAttribute('aria-label', 'Pause')
  await page.keyboard.press('Space')
  await expect(page.getByTestId('bug-play')).toHaveAttribute('aria-label', 'Play')
  await page.waitForTimeout(300)
  expect(page.url()).toMatch(/[?&]t=\d+/)
  const before = Number(await page.getByTestId('flow').getAttribute('aria-valuenow'))
  await page.keyboard.press('ArrowRight')
  await page.waitForTimeout(100)
  expect(Number(await page.getByTestId('flow').getAttribute('aria-valuenow'))).toBeGreaterThan(before)
  await page.keyboard.press('Home')
  await page.waitForTimeout(300)
  expect(await page.getByTestId('flow').getAttribute('aria-valuenow')).toBe('0')
  expect(page.url()).toMatch(/[?&]t=0\b/)
})

test('the replay never autoplays, under reduced motion included', async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: 'reduce', viewport: { width: 1280, height: 900 } })
  const page = await ctx.newPage()
  await page.goto(RECAP, { waitUntil: 'networkidle' })
  await ready(page)
  await page.waitForTimeout(800)
  await expect(page.getByTestId('watch')).toBeVisible()
  await expect(page.getByTestId('bug-play')).toHaveAttribute('aria-label', 'Play')
  expect(await clock(page)).toBe('12:00')
  await ctx.close()
})

test('a phone gets the two tabs, the room capped, and the box in one column', async ({ page }, info) => {
  test.skip(info.project.name !== 'phone', 'the tabs exist only on a phone')
  await page.goto(`${RECAP}?t=1200`, { waitUntil: 'networkidle' })
  await ready(page)
  const tabs = page.getByRole('tab')
  await expect(tabs).toHaveCount(2)
  for (const t of await tabs.all()) expect((await t.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
  await expect(page.locator('.room')).toBeVisible()
  expect(await page.locator('.fc:visible').count()).toBeLessThanOrEqual(8)
  await tabs.nth(1).click()
  await expect(page.locator('.box')).toBeVisible()
  await expect(page.locator('.room')).toBeHidden()
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('every recap page links a live next recap', async ({ page }) => {
  for (const route of ROUTES.filter((r) => r.startsWith('/recaps/') && r !== '/recaps/')) {
    const html = readFileSync(path.join(DIST, route, 'index.html'), 'utf8')
    const next = html.match(/href="(\/recaps\/[^"]+\/)"[^>]*>Next recap:/)?.[1]
    expect(next, `next recap on ${route}`).toBeDefined()
    expect(ROUTES).toContain(next)
    expect(next).not.toBe(route)
  }
  await page.goto(RECAP)
})

// The race: one island on the week. It opens paused on the final week, which is the leaderboard.
const raceWeek = (page: Page) => page.getByTestId('race-week')
const racePlay = (page: Page) => page.getByTestId('race-play')
const raceNames = (page: Page) => page.locator('.race__rows .rrow__name').allTextContents()
const boardNames = async (page: Page) => (await page.locator('.lb__rows .row__name').allTextContents()).slice(0, 10)

test('the race opens paused on the final week, and its top ten is the leaderboard\'s', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/', { waitUntil: 'networkidle' })
  const hated = await boardNames(page)
  await page.goto('/?lens=pos', { waitUntil: 'networkidle' })
  await expect(page.getByRole('tab', { name: 'Most loved' })).toHaveAttribute('aria-selected', 'true')
  const loved = await boardNames(page)
  await page.goto('/race/', { waitUntil: 'networkidle' })
  await expect(racePlay(page)).toHaveText('▶ Play the season')
  await expect(raceWeek(page)).toHaveText(/^Season final · week (\d+) of \1$/)
  await expect(page.locator('.race__sentence')).toContainText("r/NBA's most hated player is")
  expect(await raceNames(page)).toEqual(hated)
  // No autoplay: a wait later it is still the final week.
  await page.waitForTimeout(1200)
  await expect(raceWeek(page)).toHaveText(/^Season final/)
  await page.getByRole('button', { name: 'Loved' }).click()
  await expect(page).toHaveURL(/mode=loved/)
  await expect.poll(() => raceNames(page)).toEqual(loved)
  expect(errors).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('play restarts the race from the first week, and only a pause writes the week', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/race/', { waitUntil: 'networkidle' })
  await racePlay(page).click()
  await expect(racePlay(page)).toHaveText('❚❚ Pause')
  await expect(raceWeek(page)).toHaveText(/week [123] of/)
  await expect(raceWeek(page)).toHaveText(/week 4 of/, { timeout: 6000 })
  expect(page.url()).not.toMatch(/[?&]w=/)
  await racePlay(page).click()
  await expect(racePlay(page)).toHaveText('▶ Play')
  await expect(page).toHaveURL(/[?&]w=\d+/)
  expect(errors).toEqual([])
})

test('a race deep link shows its frame with no flash, and Back returns to it', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto('/race/?mode=loved&by=count&w=21', { waitUntil: 'networkidle' })
  await expect(page.locator('html')).not.toHaveClass(/has-race-view/)
  await expect(raceWeek(page)).toHaveText(/week 22 of/)
  await expect(racePlay(page)).toHaveText('▶ Play')
  const count = page.getByRole('button', { name: 'Count' })
  await expect(page.getByRole('button', { name: 'Loved' })).toHaveAttribute('aria-pressed', 'true')
  await expect(count).toHaveAttribute('aria-pressed', 'true')
  const figure = page.locator('.rrow__val').first()
  await expect(figure).toHaveText(/^[\d,]+$/)
  await page.getByRole('button', { name: 'Rate' }).click()
  await expect(page).not.toHaveURL(/by=/)
  await expect(figure).toHaveText(/%$/)
  await page.goBack()
  await expect(count).toHaveAttribute('aria-pressed', 'true')
  await expect(raceWeek(page)).toHaveText(/week 22 of/)
  expect(errors).toEqual([])
  expect(await overflow(page)).toBeLessThanOrEqual(0)
})

test('a week past the season\'s end is the final week', async ({ page }) => {
  await page.goto('/race/?w=999', { waitUntil: 'networkidle' })
  await expect(page.locator('html')).not.toHaveClass(/has-race-view/)
  await expect(raceWeek(page)).toHaveText(/^Season final/)
})

test('space and the arrows drive the race', async ({ page }) => {
  await page.goto('/race/?w=10', { waitUntil: 'networkidle' })
  await expect(raceWeek(page)).toHaveText(/week 11 of/)
  await page.keyboard.press('ArrowRight')
  await expect(raceWeek(page)).toHaveText(/week 12 of/)
  await expect(page).toHaveURL(/[?&]w=11\b/)
  await page.keyboard.press('ArrowLeft')
  await expect(raceWeek(page)).toHaveText(/week 11 of/)
  await page.keyboard.press('Space')
  await expect(racePlay(page)).toHaveText('❚❚ Pause')
  await page.keyboard.press('Space')
  await expect(racePlay(page)).toHaveText('▶ Play')
  // A held space is one press: its repeats do not toggle.
  await page.keyboard.down('Space')
  await page.keyboard.down('Space')
  await page.keyboard.down('Space')
  await page.keyboard.up('Space')
  await expect(racePlay(page)).toHaveText('❚❚ Pause')
  await page.keyboard.press('Space')
})

test('under reduced motion the race steps: the figure lands with the week', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/race/?w=10', { waitUntil: 'networkidle' })
  await racePlay(page).click()
  await expect(raceWeek(page)).toHaveText(/week 12 of/, { timeout: 5000 })
  // The leader's row and the hero state one figure; a counting row would still be on its way.
  const [row, hero] = await page.evaluate(() => [document.querySelector('.rrow__val')?.textContent, document.querySelector('.race__fig b')?.textContent])
  expect(row).toBe(hero)
  await racePlay(page).click()
})

test('the race shows ten rows, and its controls are touch-sized', async ({ page }) => {
  await page.goto('/race/', { waitUntil: 'networkidle' })
  await expect(page.locator('.race__rows .rrow')).toHaveCount(10)
  for (const c of [...(await page.locator('.race .btn').all()), page.getByTestId('race-scrub')]) {
    const box = await c.boundingBox()
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44)
  }
})

test('the dock stays with the board: the tenth row, the first row and the play button share the window', async ({ page }) => {
  await page.goto('/race/', { waitUntil: 'networkidle' })
  await page.locator('.race__rows .rrow').last().scrollIntoViewIfNeeded()
  await expect(racePlay(page)).toBeInViewport({ ratio: 1 })
  await expect(page.getByTestId('race-scrub')).toBeInViewport({ ratio: 1 })
  // The dock is under the site header, not behind it.
  const [dock, header] = await Promise.all([page.locator('.race__dock').boundingBox(), page.locator('.hdr').boundingBox()])
  expect(dock!.y).toBeGreaterThanOrEqual(header!.y + header!.height - 1)
  await page.locator('.race__dock').evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 57))
  await expect(page.locator('.race__rows .rrow').first()).toBeInViewport({ ratio: 1 })
  await expect(page.locator('.race__rows .rrow').last()).toBeInViewport({ ratio: 1 })
})

// Share cards: every route names one, its own or the leaderboard's, and
// every card serves as a 1200 × 630 PNG at the address the meta gives.
const SITE = 'https://courtsentiment.com'
const OWN_CARD = /^\/(player\/[^/]+|fanbases\/[a-z]{3}|recaps\/[^/]+)\/$/
const meta = (html: string, key: string): string | null => html.match(new RegExp(`<meta (?:property|name)="${key}" content="([^"]*)"`))?.[1] ?? null

test('every route names a share card, and every card is a 1200 × 630 PNG', async ({ request }, info) => {
  test.skip(info.project.name !== 'desktop', 'the cards are the same at every width')
  test.setTimeout(120_000)
  const cards = new Set<string>()
  for (const route of ROUTES) {
    const html = readFileSync(path.join(DIST, route, 'index.html'), 'utf8')
    const og = meta(html, 'og:image')
    expect(og, `og:image on ${route}`).toBe(OWN_CARD.test(route) ? `${SITE}${route}card.png` : `${SITE}/card.png`)
    expect(meta(html, 'twitter:card'), `twitter:card on ${route}`).toBe('summary_large_image')
    expect(meta(html, 'og:url'), `og:url on ${route}`).toBe(`${SITE}${route}`)
    cards.add(new URL(og!).pathname)
  }
  expect(cards.size).toBeGreaterThan(250)
  for (const card of cards) {
    const res = await request.get(card)
    expect(res.status(), card).toBe(200)
    expect(res.headers()['content-type'], card).toMatch(/^image\/png/)
    const png = Buffer.from(await res.body())
    expect([png.readUInt32BE(16), png.readUInt32BE(20)], `size of ${card}`).toEqual([1200, 630])
  }
})
