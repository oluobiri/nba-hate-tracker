import { describe, expect, it } from 'vitest'

import type { PlayersRow } from '../data/types.gen'
import { ageOn, bioFacts, fmtBorn, fmtExperience, fmtHeight } from './bio'

const player: PlayersRow = {
  attributed_player: 'James Harden',
  slug: 'james-harden',
  roster_team: 'Cleveland Cavaliers',
  conference: 'East',
  player_id: 1,
  headshot_url: 'x',
  position: 'G',
  birth_date: '1989-08-26',
  experience: '16',
  school: 'Arizona State',
  jersey_number: '1',
  height: '6-5',
  weight: '220',
}

describe('bio formatting', () => {
  it('reads height, experience and birth date from the dimension strings', () => {
    expect(fmtHeight('6-11')).toBe('6′11″')
    expect(fmtExperience('R')).toBe('Rookie')
    expect(fmtExperience('1')).toBe('1 yr')
    expect(fmtExperience('12')).toBe('12 yrs')
    expect(fmtBorn('1989-08-26')).toBe('Aug 26, 1989')
  })

  it('counts whole years of age, birthday not yet reached or reached', () => {
    expect(ageOn('1989-08-26', '2026-08-25')).toBe(36)
    expect(ageOn('1989-08-26', '2026-08-26')).toBe(37)
    expect(ageOn('1989-08-26', '2026-09-23')).toBe(37)
  })
})

describe('bioFacts', () => {
  it('lists the facts in order', () => {
    expect(bioFacts(player, '2026-09-23').map((f) => `${f.label} ${f.value}`)).toEqual([
      'Height 6′5″',
      'Weight 220 lb',
      'Age 37',
      'Born Aug 26, 1989',
      'Experience 16 yrs',
      'From Arizona State',
    ])
  })

  it('leaves out what a free agent lacks', () => {
    const nobody = { ...player, height: null, weight: null, birth_date: null, experience: null, school: null }
    expect(bioFacts(nobody, '2026-09-23')).toEqual([])
  })
})
