// Walk every route in dist/ and hold the two invariants that cannot be
// unit-tested: zero console errors and no horizontal overflow. The style
// guide is also screenshotted as built, in grayscale and as a deuteranope.
import { readdirSync, statSync } from 'node:fs'
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
  await expect(page.locator('.lb__sentence')).toContainText('most discussed')
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
  await expect(page.locator('.lb__sentence .stamp--unofficial')).toBeVisible()
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
  await expect(page.locator('.exhibit__sent--pos').first()).toBeVisible()
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

// Edge states, one route each. The names are the data's, not a rule's.
test('a free agent has no roster line and still gets fans', async ({ page }) => {
  await page.goto('/player/chris-paul/', { waitUntil: 'networkidle' })
  await expect(page.locator('.pp__head .eyebrow')).toContainText('Free agent')
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
