// The three tiles over the rooms: the rise, and the two things that made
// it. The third takes heat, since it is the rooms' own tone moving.
import type { Tile } from '../lib/season'

export interface RoomTilesProps {
  tiles: readonly Tile[]
}

export function RoomTiles({ tiles }: RoomTilesProps) {
  return (
    <div className="tiles">
      {tiles.map((t) => (
        <div key={t.key} className={`tile${t.key === 'harsh' ? ' tile--harsh' : ''}`}>
          <span className="tile__n mono">
            {t.figure}
            {t.unit && <small> {t.unit}</small>}
          </span>
          <span className="tile__t">{t.title}</span>
          <span className="tile__s">{t.sub}</span>
        </div>
      ))}
    </div>
  )
}
