import { describe, expect, it } from 'vitest'

import type { PlayerStatusCopy } from './player-status-copy'
import { checkStatusCopy, gamesLede, playerStatus, teamLine } from './status'

const COPY: Readonly<Record<string, PlayerStatusCopy>> = {
  'gone-guy': { status: 'Retired', text: 'Gone Guy retired on Feb 13.' },
  'loose-guy': { status: 'Free agent', text: 'Loose Guy was waived in March.' },
}
const gone = { attributed_player: 'Gone Guy', slug: 'gone-guy', roster_team: null }
const loose = { attributed_player: 'Loose Guy', slug: 'loose-guy', roster_team: null }
const rostered = { attributed_player: 'Roster Guy', slug: 'roster-guy', roster_team: 'Boston Celtics' }
const ABBR = new Map([['Boston Celtics', 'BOS']])
const never = () => 'Never dressed.'

describe('playerStatus', () => {
  it('reads the entry without a roster team and null on a roster', () => {
    expect(playerStatus(gone, COPY)).toEqual(COPY['gone-guy'])
    expect(playerStatus(rostered, COPY)).toBeNull()
  })

  it('fails an unlisted player without a roster team, naming him', () => {
    expect(() => playerStatus({ ...rostered, roster_team: null }, COPY)).toThrow(/Roster Guy has no roster team and no entry/)
  })

  it('fails a listed player who has a roster team', () => {
    expect(() => playerStatus({ ...gone, roster_team: 'Boston Celtics' }, COPY)).toThrow(/Gone Guy is listed as Retired but has a roster team/)
  })
})

describe('checkStatusCopy', () => {
  it('passes when the table and the copy agree both ways', () => {
    expect(() => checkStatusCopy([gone, loose, rostered], COPY)).not.toThrow()
  })

  it('fails a listed slug no player has', () => {
    expect(() => checkStatusCopy([gone, rostered], COPY)).toThrow(/loose-guy is listed but no player has that slug/)
  })

  it('fails the first player the copy disagrees with', () => {
    expect(() => checkStatusCopy([gone, { ...rostered, roster_team: null }], COPY)).toThrow(/Roster Guy/)
  })
})

describe('teamLine', () => {
  it('prints the abbreviation on a roster and the status off one', () => {
    expect(teamLine(rostered, ABBR, COPY)).toBe('BOS')
    expect(teamLine(gone, ABBR, COPY)).toBe('Retired')
    expect(teamLine(loose, ABBR, COPY)).toBe('Free agent')
  })

  it('falls back to the team name when no abbreviation is known', () => {
    expect(teamLine({ ...rostered, roster_team: 'Seattle SuperSonics' }, ABBR, COPY)).toBe('Seattle SuperSonics')
  })
})

describe('gamesLede', () => {
  it('closes a dressed summary with what happened, and leaves a rostered summary alone', () => {
    expect(gamesLede('Talked in 10 games.', COPY['gone-guy']!, never)).toBe('Talked in 10 games. Gone Guy retired on Feb 13.')
    expect(gamesLede('Talked in 10 games.', null, never)).toBe('Talked in 10 games.')
  })

  it('stands alone when he never dressed, and keeps the never-dressed sentence for a rostered player', () => {
    expect(gamesLede(null, COPY['loose-guy']!, never)).toBe('Loose Guy was waived in March.')
    expect(gamesLede(null, null, never)).toBe('Never dressed.')
  })
})
