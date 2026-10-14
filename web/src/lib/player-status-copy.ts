// Curated words for the players with no roster team at season end, joined
// at build by slug. lib/status fails the build when this list disagrees
// with the players table, so a stale entry never ships.

export type PlayerStatus = 'Retired' | 'Free agent' | 'Playing abroad'

export interface PlayerStatusCopy {
  /** Where "Free agent" would print: his status at season end. */
  status: PlayerStatus
  /** One sentence of what happened: the Games lede's close, or the whole lede when he never dressed. */
  text: string
}

export const PLAYER_STATUS: Readonly<Record<string, PlayerStatusCopy>> = {
  'chris-paul': { status: 'Retired', text: 'Chris Paul left the Clippers in December, was traded to Toronto and waived, and announced his retirement on Feb 13, 2026.' },
  'ben-simmons': { status: 'Free agent', text: 'Ben Simmons sat out the whole season with back and leg injuries, then agreed a one-year deal with Sacramento in September 2026.' },
  'lonzo-ball': { status: 'Free agent', text: 'Lonzo Ball was traded from Cleveland to Utah on Feb 4, waived the next day and cleared waivers unsigned.' },
  'jaden-ivey': { status: 'Free agent', text: 'Jaden Ivey was traded from Detroit to Chicago at the deadline, played four games, and was waived on Mar 30 for conduct detrimental to the team.' },
  'terry-rozier': { status: 'Free agent', text: 'Terry Rozier was arrested on Oct 23 on federal gambling charges and placed on league leave; Miami waived him on Apr 10, two days before the play-in.' },
  'patrick-beverley': { status: 'Playing abroad', text: 'Patrick Beverley last played in the NBA in 2023-24 and spent this season with PAOK in Greece.' },
  'malik-beasley': { status: 'Playing abroad', text: 'Malik Beasley went unsigned during a federal gambling investigation, played 17 games for Santurce in Puerto Rico, and pleaded not guilty on July 1.' },
}
