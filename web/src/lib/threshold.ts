// The threshold slider's stops: round numbers, log-spaced, from a floor to
// the largest n on the board. The official minimum is always a stop, so
// "Reset to official" lands on the track. Bounds arrive from the caller.

const MANTISSAS = [1, 1.5, 2, 3, 5, 7]

/** Ascending stops within [floor, maxN], the floor and `official` included. */
export function thresholdStops(floor: number, maxN: number, official: number): number[] {
  const stops = new Set<number>()
  for (let exp = 1; exp <= 7; exp++) {
    for (const m of MANTISSAS) {
      const v = Math.round(m * 10 ** exp)
      if (v >= floor && v <= maxN) stops.add(v)
    }
  }
  stops.add(floor)
  if (official >= floor && official <= maxN) stops.add(official)
  return [...stops].toSorted((a, b) => a - b)
}

/** The stop nearest to n; ties go to the lower stop. */
export function snapThreshold(n: number, stops: readonly number[]): number {
  let best = stops[0] ?? n
  for (const s of stops) if (Math.abs(s - n) < Math.abs(best - n)) best = s
  return best
}

/** The labelled stops: the floor, the official minimum, the last stop, and every power of ten between. */
export function thresholdTicks(stops: readonly number[], official: number): number[] {
  const first = stops[0]
  const last = stops.at(-1)
  if (first === undefined || last === undefined) return []
  const ticks = new Set<number>([first, last])
  if (stops.includes(official)) ticks.add(official)
  for (const s of stops) if (Number.isInteger(Math.log10(s))) ticks.add(s)
  return [...ticks].toSorted((a, b) => a - b)
}
