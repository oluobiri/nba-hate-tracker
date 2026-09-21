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
