// Number formatting for labels. Percentages are given as fractions.

export const fmtPct = (v: number, dp = 1): string => `${(100 * v).toFixed(dp)}%`
export const fmtInt = (v: number): string => v.toLocaleString('en-US')
export const fmtSigned = (v: number, dp = 1): string => `${v > 0 ? '+' : ''}${(100 * v).toFixed(dp)}`

/** 1 → "1st", 2 → "2nd", 3 → "3rd", 11 → "11th", 22 → "22nd". */
export function ordinal(n: number): string {
  const mod100 = n % 100
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`
  const suffix = { 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] ?? 'th'
  return `${n}${suffix}`
}
