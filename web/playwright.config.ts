import { defineConfig, devices } from '@playwright/test'

// The walk: every built page at desktop and phone width, served by astro preview.
export default defineConfig({
  testDir: 'walk',
  outputDir: 'walk/out/results',
  fullyParallel: true,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  timeout: 15_000,
  webServer: {
    command: 'npx astro preview --port 4321',
    url: 'http://localhost:4321/',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  use: {
    baseURL: 'http://localhost:4321/',
    ...devices['Desktop Chrome'],
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 900 } } },
    { name: 'phone', use: { viewport: { width: 400, height: 800 } } },
  ],
})
