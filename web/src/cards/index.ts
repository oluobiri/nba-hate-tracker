// A card's PNG from its model: the mark is bundled in, the subject's image
// is read once per build; the headshot is grayscaled, the logo stays in colour.
import mark from '../../public/favicon.svg?raw'
import { readMedia } from './assets'
import { Frame } from './frame'
import type { Card } from './model'
import { renderCard } from './render'

const MARK = `data:image/svg+xml;base64,${Buffer.from(mark).toString('base64')}`

/** Render one card to PNG bytes. */
export async function buildCard(card: Card): Promise<Uint8Array<ArrayBuffer>> {
  const image = await readMedia(card.image)
  return new Uint8Array(await renderCard(Frame({ card, mark: MARK, image }), card.kind === 'team' ? [] : [image]))
}
