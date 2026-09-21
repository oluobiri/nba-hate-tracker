// Site-wide constants: identity, navigation and the pre-launch switch.
// Rule numbers never live here; they come from the manifest.

export const SITE_NAME = 'Court Sentiment'
export const SITE_URL = 'https://courtsentiment.com'
export const SITE_DESCRIPTION = "Who is r/NBA's most hated player? Every comment, classified."

export const SEASONS = ['2025-26'] as const
export type Season = (typeof SEASONS)[number]
export const CURRENT_SEASON: Season = '2025-26'

// Every page carries noindex until launch day flips this in the deploy env.
export const SITE_INDEXABLE = process.env.SITE_INDEXABLE === 'true'

export interface NavItem {
  label: string
  href: string
}

export const NAV: readonly NavItem[] = [
  { label: 'Leaderboard', href: '/' },
  { label: 'Fanbases', href: '/fanbases/' },
  { label: 'Season', href: '/season/' },
  { label: 'The Race', href: '/race/' },
  { label: 'Recaps', href: '/recaps/' },
  { label: 'How it works', href: '/how-it-works/' },
]

export const GITHUB_URL = 'https://github.com/oluobiri/nba-hate-tracker'
export const LINKEDIN_URL = 'https://www.linkedin.com/in/oluobiri/'
export const AUTHOR = 'Olu Obiri'
