// The way into a fanbase: every team as a tile, one group per conference,
// alphabetical inside. The picker is a control; the lists below it rank.
// Logos are in colour here, the one place on the site: they stand alone,
// with no team name beside them for gray to defer to.
import type { PickerGroup } from '../lib/league'

export interface TeamPickerProps {
  groups: readonly PickerGroup[]
  /** Style guide only: the abbreviation of a tile drawn in its focused state. */
  demoFocus?: string
}

export function TeamPicker({ groups, demoFocus }: TeamPickerProps) {
  return (
    <nav className="pk" aria-label="Fanbases">
      {groups.map((g) => (
        <section key={g.conference} className="pk__group" aria-labelledby={`pk-${g.conference.toLowerCase()}`}>
          <h3 id={`pk-${g.conference.toLowerCase()}`} className="pk__head">
            {g.conference}
          </h3>
          <ul className="pk__tiles">
            {g.teams.map((t) => (
              <li key={t.abbr}>
                <a className={`pk__tile${t.abbr === demoFocus ? ' pk__tile--focus' : ''}`} href={t.href}>
                  <img className="pk__logo" src={t.logo} alt="" width="40" height="40" decoding="async" />
                  <span className="pk__abbr mono" aria-hidden="true">
                    {t.abbr}
                  </span>
                  <span className="visually-hidden">{t.name}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </nav>
  )
}
