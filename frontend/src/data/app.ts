/**
 * Application identity and the copy that describes how the system behaves.
 *
 * Kept out of the components so the wording lives next to the scenario data
 * rather than being scattered through JSX.
 */
export const APP_NAME = 'Geoscope'
export const APP_DESCRIPTOR = 'Geospatial AI'

/** Keyboard shortcuts, listed in the help panel. */
export const SHORTCUTS: Array<{ keys: string; action: string }> = [
  { keys: 'Enter', action: 'Run the query' },
  { keys: 'Shift + Enter', action: 'New line in the composer' },
  { keys: 'Ctrl / ⌘ + Enter', action: 'Run the query from anywhere in the text' },
  { keys: 'Esc', action: 'Close dialogs and popovers' },
]

/** What the interface does and does not do today, stated plainly. */
export const CAPABILITY_NOTES: Array<{ label: string; detail: string }> = [
  {
    label: 'Every answer comes from the agent backend',
    detail:
      'Queries run against septic-system, floodplain, Maumee water-quality, and NCWQR publication sources through the backend tools. Nothing on screen is simulated.',
  },
  {
    label: 'The map is an output surface',
    detail:
      'Queries are asked in natural language. The map draws what comes back; it is not required for input.',
  },
  {
    label: 'History is local',
    detail:
      'Past queries are stored in this browser only. Result geometry is kept in memory for the session and never persisted.',
  },
]
