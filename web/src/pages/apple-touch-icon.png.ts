// The home-screen icon iOS asks for: the mark on a full ink square, since
// iOS composites transparent corners onto black and rounds with its own radius.
import type { APIRoute } from 'astro'

import mark from '../../public/favicon.svg?raw'
import { PALETTE } from '../cards/palette'
import { TOUCH_ICON_SIZE, iconPng } from '../lib/icons'

export const GET: APIRoute = () =>
  new Response(new Uint8Array(iconPng(mark, TOUCH_ICON_SIZE, PALETTE.ink)), { headers: { 'Content-Type': 'image/png' } })
