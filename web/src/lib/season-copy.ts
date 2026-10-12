// Curated words for the season page, joined to the data at build. An entry
// names a night by its date; lib/season fails the build when the data no
// longer supports what the words claim, so a stale note never ships.

export interface NightNoteCopy {
  /** "YYYY-MM-DD", the Eastern game night the event fell on. */
  day: string
  /** The note's head, after the date. */
  title: string
  /** One sentence on what happened, as the play-by-play archive records it. */
  text: string
}

/** The harshest stretch's cause: this night, and the day after harsher still. */
export const HARSHEST_NOTE: NightNoteCopy = { day: '2026-02-27', title: 'Dort ejected', text: "Dort's Flagrant 2 on Jokić." }
