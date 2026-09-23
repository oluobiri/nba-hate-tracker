// First-party media: a headshot's WebP variants sit beside its original,
// named <id>-<width>.webp. The original URL comes from players.headshot_url.

export const HEADSHOT_WIDTHS = [180, 420, 840] as const

/** "…/203500.png" → "…/203500-180.webp 180w, …/203500-420.webp 420w". */
export function headshotSrcSet(url: string, widths: readonly number[] = [180, 420]): string {
  const stem = url.replace(/\.png$/, '')
  return widths.map((w) => `${stem}-${w}.webp ${w}w`).join(', ')
}
