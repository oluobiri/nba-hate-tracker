// The header's bio strip from the player dimension. Every field is a
// string as published (height "6-11", weight "265", experience "12" or
// "R"); the formatting lives here, and a null field is left out.
import type { PlayersRow } from '../data/types.gen'

export interface BioFact {
  label: string
  value: string
}

/** Whole years between a "YYYY-MM-DD" birth date and a "YYYY-MM-DD" day. */
export function ageOn(birth: string, on: string): number {
  const b = new Date(Date.parse(birth))
  const d = new Date(Date.parse(on))
  let age = d.getUTCFullYear() - b.getUTCFullYear()
  if (d.getUTCMonth() < b.getUTCMonth() || (d.getUTCMonth() === b.getUTCMonth() && d.getUTCDate() < b.getUTCDate())) age--
  return age
}

/** "6-11" → 6′11″. */
export const fmtHeight = (h: string): string => {
  const [ft, inch] = h.split('-')
  return inch === undefined ? h : `${ft}′${inch}″`
}

/** "R" → Rookie, "1" → 1 yr, "12" → 12 yrs. */
export const fmtExperience = (e: string): string => (e === 'R' ? 'Rookie' : e === '1' ? '1 yr' : `${e} yrs`)

/** "1989-08-26" → Aug 26, 1989. */
export const fmtBorn = (d: string): string => new Date(Date.parse(d)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })

/** The strip's facts in order, skipping what the dimension does not have for him. */
export function bioFacts(p: PlayersRow, on: string): BioFact[] {
  const facts: (BioFact | null)[] = [
    p.height ? { label: 'Height', value: fmtHeight(p.height) } : null,
    p.weight ? { label: 'Weight', value: `${p.weight} lb` } : null,
    p.birth_date ? { label: 'Age', value: String(ageOn(p.birth_date, on)) } : null,
    p.birth_date ? { label: 'Born', value: fmtBorn(p.birth_date) } : null,
    p.experience ? { label: 'Experience', value: fmtExperience(p.experience) } : null,
    p.school ? { label: 'From', value: p.school } : null,
  ]
  return facts.filter((f): f is BioFact => f !== null)
}
