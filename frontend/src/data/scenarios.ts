/**
 * Example queries surfaced in the query panel.
 *
 * These are UI content, not logic: they exist to show what the agent backend
 * can do and are grouped by the kind of reasoning each one demands. Clicking
 * one fills the composer; nothing here is special-cased downstream — every
 * example runs against the backend like typed input.
 */
export type ExampleTier = 'dataset' | 'spatial' | 'water-quality' | 'research'

export interface ExampleQuery {
  id: string
  text: string
  tier: ExampleTier
  /** One-line explanation of what the example demonstrates. */
  note: string
}

export const EXAMPLE_TIER_LABELS: Record<ExampleTier, string> = {
  dataset: 'Dataset',
  spatial: 'Spatial analysis',
  'water-quality': 'Water quality',
  research: 'Research context',
}

export const EXAMPLE_TIER_ORDER: ExampleTier[] = [
  'dataset',
  'spatial',
  'water-quality',
  'research',
]

export const EXAMPLE_QUERIES: ExampleQuery[] = [
  {
    id: 'ex-septic',
    text: 'Show septic systems in the available dataset.',
    tier: 'dataset',
    note: 'Lists the septic-system features from the county layer',
  },
  {
    id: 'ex-intersect',
    text: 'Find septic systems that intersect floodplain areas.',
    tier: 'spatial',
    note: 'Spatial intersection of two backend datasets',
  },
  {
    id: 'ex-buffer',
    text: 'Find septic systems within 2 km of floodplain areas.',
    tier: 'spatial',
    note: 'Buffers the floodplains, then intersects — a multi-step plan',
  },
  {
    id: 'ex-maumee',
    text: 'Summarize total phosphorus (TP) in the Maumee dataset.',
    tier: 'water-quality',
    note: 'Statistics over the NCWQR Maumee time series, 1975 to present',
  },
  {
    id: 'ex-pubs',
    text: 'What NCWQR publications discuss Maumee phosphorus loads?',
    tier: 'research',
    note: 'Searches the NCWQR publication index with source citations',
  },
  {
    id: 'ex-combined',
    text: 'Find septic systems near floodplain areas and summarize relevant NCWQR research.',
    tier: 'research',
    note: 'GIS analysis plus publication context in one answer',
  },
]

/** Error paths worth demonstrating, listed in the help panel. */
export interface DemoPath {
  query: string
  outcome: string
}

export const DEMO_ERROR_PATHS: DemoPath[] = [
  {
    query: 'Show hospitals in this area',
    outcome: 'Unsupported — no hospital dataset is registered',
  },
  {
    query: 'Show schools near floodplain areas',
    outcome: 'Unsupported — no school dataset is registered',
  },
  {
    query: 'asdfgh qwerty',
    outcome: 'Invalid geographic query — no dataset or operation could be identified',
  },
]
