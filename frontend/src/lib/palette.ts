/**
 * The colour tokens, in JS.
 *
 * These mirror the custom properties declared in `src/index.css` and are the
 * single source of truth for anything that hands a colour to Leaflet: SVG
 * presentation attributes are set imperatively by Leaflet, so a `var(--token)`
 * string would not resolve there.
 *
 * Values come from the project's validated data-visualisation palette:
 *   - `series1..3` are the categorical identity slots (fixed order, never cycled)
 *   - `seq100..700` are the single-hue sequential ramp, light -> dark
 *   - `status*` are reserved for state and never used as a series colour
 *   - `pointer` paints point markers signal-red so they stand out on any
 *     basemap (the deliberate exception to the status rule: points are
 *     always locations of interest, never state)
 *
 * See README → "Colour system".
 */
export const PALETTE = {
  series1: '#2a78d6',
  series2: '#eb6834',
  series3: '#1baf7a',
  series1Stroke: '#184f95',
  series2Stroke: '#a8410f',
  series3Stroke: '#0f6f4d',
  /** Neutral treatment for a 4th+ layer: identity comes from the legend, not hue. */
  other: '#898781',
  accent: '#2a78d6',
  accentInk: '#1c5cab',
  ink: '#0b0b0b',
  ink2: '#52514e',
  ink3: '#898781',
  line: '#e1e0d9',
  lineStrong: '#c3c2b7',
  panel: '#fcfcfb',
  good: '#0ca30c',
  goodInk: '#006300',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
  /** Point-marker fill: signal red for notability on any basemap. */
  pointer: '#d03b3b',
  pointerStroke: '#8f1d1d',
} as const

/** Sequential ramp, light -> dark. Index 0 is the lightest step. */
export const SEQUENTIAL_BLUE = [
  '#cde2fb',
  '#9ec5f4',
  '#6da7ec',
  '#3987e5',
  '#256abf',
  '#184f95',
  '#0d366b',
] as const

/** Second sequential context, when two magnitudes appear at once. */
export const SEQUENTIAL_ORANGE = [
  '#fde3d5',
  '#f9c3a4',
  '#f4a074',
  '#eb6834',
  '#c94f1d',
  '#9c3a12',
  '#6d270a',
] as const

export type SequentialHue = 'blue' | 'orange'

export function sequentialRamp(hue: SequentialHue = 'blue'): readonly string[] {
  return hue === 'orange' ? SEQUENTIAL_ORANGE : SEQUENTIAL_BLUE
}

/**
 * Picks `count` steps spread across the ramp.
 *
 * A choropleth with 5 classes should not use steps 0-4 of a 7-step ramp — it
 * should span the range so the lightest class still means "lowest" and the
 * darkest "highest".
 */
export function sequentialSteps(count: number, hue: SequentialHue = 'blue'): string[] {
  const ramp = sequentialRamp(hue)
  if (count <= 0) return []
  if (count === 1) return [ramp[Math.floor(ramp.length / 2)]]
  const steps: string[] = []
  for (let i = 0; i < count; i++) {
    const index = Math.round((i / (count - 1)) * (ramp.length - 1))
    steps.push(ramp[index])
  }
  return steps
}

export function seriesColor(slot: number | undefined): string {
  if (slot === 1) return PALETTE.series1
  if (slot === 2) return PALETTE.series2
  if (slot === 3) return PALETTE.series3
  return PALETTE.other
}

export function seriesStroke(slot: number | undefined): string {
  if (slot === 1) return PALETTE.series1Stroke
  if (slot === 2) return PALETTE.series2Stroke
  if (slot === 3) return PALETTE.series3Stroke
  return PALETTE.ink2
}
