import react from '@astrojs/react'
import { defineConfig } from 'astro/config'

// Static output, one index.html per route: what the CloudFront directory
// rewrite expects. Trailing slashes are enforced in dev for parity.
export default defineConfig({
  site: 'https://courtsentiment.com',
  output: 'static',
  trailingSlash: 'always',
  integrations: [react()],
})
