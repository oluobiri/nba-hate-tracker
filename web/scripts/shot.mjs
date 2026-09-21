/**
 * Screenshot one page of a running server with Playwright's Chromium.
 *   node scripts/shot.mjs <url> [out.png] [width] [height] [fullPage 0|1] [waitMs]
 * Prints console errors. Needs a server: `npm run dev` (4321) or `npm run build && npm run preview` (4321).
 */
import { chromium } from 'playwright'

const [, , url, out = 'shot.png', w = '1280', h = '900', full = '1', wait = '800'] = process.argv
if (!url) {
  console.error('usage: node scripts/shot.mjs <url> [out.png] [w] [h] [fullPage] [waitMs]')
  process.exit(1)
}
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: +w, height: +h } })
const errors = []
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(m.text().slice(0, 200))
})
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
await page.goto(url, { waitUntil: 'load' })
await page.waitForTimeout(+wait)
await page.screenshot({ path: out, fullPage: full === '1' })
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
console.log('saved', out, '| console errors:', errors.length ? errors : 'none', '| horizontal overflow px:', overflow)
await browser.close()
