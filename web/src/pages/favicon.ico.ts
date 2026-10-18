// The icon fetchers ask for by path without reading the page: the mark at
// 32 and 16 in one file. The tab icon stays the SVG the head links.
import type { APIRoute } from 'astro'

import mark from '../../public/favicon.svg?raw'
import { FAVICON_SIZES, ico, iconPng } from '../lib/icons'

export const GET: APIRoute = () =>
  new Response(new Uint8Array(ico(FAVICON_SIZES.map((size) => iconPng(mark, size)))), { headers: { 'Content-Type': 'image/x-icon' } })
