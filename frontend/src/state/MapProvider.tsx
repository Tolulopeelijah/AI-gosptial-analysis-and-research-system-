import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { BASEMAPS, DEFAULT_BASEMAP } from '@/data/basemaps'
import { NOOP_MAP_CONTROLLER, type MapController } from '@/hooks/mapController'
import type { BasemapDefinition, BasemapId, LayerVisibility, MapPreferences } from '@/types/map'

/**
 * Map preferences (persisted) plus the imperative command channel.
 *
 * The Leaflet instance lives inside the map component; everything outside it
 * talks to the map through the registered `MapController`. That keeps the map
 * library out of every other component and makes a future map interaction
 * (draw a polygon, click a county) another method on the same interface.
 */

const STORAGE_KEY = 'geoscope.map.v1'

const DEFAULT_PREFERENCES: MapPreferences = {
  basemap: DEFAULT_BASEMAP,
  visibility: { results: true, labels: false, places: true },
  resultOpacity: 1,
}

function readStoredPreferences(): MapPreferences {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_PREFERENCES
    const parsed = JSON.parse(raw) as Partial<MapPreferences>
    const basemap =
      parsed.basemap && parsed.basemap in BASEMAPS ? parsed.basemap : DEFAULT_PREFERENCES.basemap
    return {
      basemap,
      visibility: { ...DEFAULT_PREFERENCES.visibility, ...parsed.visibility },
      resultOpacity:
        typeof parsed.resultOpacity === 'number'
          ? Math.min(1, Math.max(0.15, parsed.resultOpacity))
          : DEFAULT_PREFERENCES.resultOpacity,
    }
  } catch {
    return DEFAULT_PREFERENCES
  }
}

export interface MapContextValue {
  preferences: MapPreferences
  basemap: BasemapDefinition
  setBasemap: (id: BasemapId) => void
  setResultOpacity: (value: number) => void
  toggleLayer: (layer: keyof LayerVisibility) => void
  setLayerVisibility: (layer: keyof LayerVisibility, visible: boolean) => void
  resetPreferences: () => void

  /** Called by the map component on mount and unmount. */
  registerController: (controller: MapController | null) => void
  isFullscreen: boolean
  setFullscreenState: (value: boolean) => void

  /* Commands — safe to call before the map exists; they no-op until it does. */
  zoomIn: () => void
  zoomOut: () => void
  resetView: () => void
  fitResults: () => void
  toggleFullscreen: () => void
  getBounds: MapController['getBounds']
  getCenter: MapController['getCenter']
  getZoom: MapController['getZoom']
  hasResults: () => boolean
}

const MapContext = createContext<MapContextValue | null>(null)

export function MapProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<MapPreferences>(() =>
    typeof window === 'undefined' ? DEFAULT_PREFERENCES : readStoredPreferences(),
  )
  const [isFullscreen, setIsFullscreen] = useState(false)
  const controllerRef = useRef<MapController>(NOOP_MAP_CONTROLLER)
  const [controllerReady, setControllerReady] = useState(false)

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences))
    } catch {
      // Preferences are a convenience; storage failures are not fatal.
    }
  }, [preferences])

  const registerController = useCallback((controller: MapController | null) => {
    controllerRef.current = controller ?? NOOP_MAP_CONTROLLER
    setControllerReady(controller != null)
  }, [])

  const setBasemap = useCallback((id: BasemapId) => {
    setPreferences((current) => ({ ...current, basemap: id }))
  }, [])

  const setResultOpacity = useCallback((value: number) => {
    setPreferences((current) => ({
      ...current,
      resultOpacity: Math.min(1, Math.max(0.15, value)),
    }))
  }, [])

  const toggleLayer = useCallback((layer: keyof LayerVisibility) => {
    setPreferences((current) => ({
      ...current,
      visibility: { ...current.visibility, [layer]: !current.visibility[layer] },
    }))
  }, [])

  const setLayerVisibility = useCallback((layer: keyof LayerVisibility, visible: boolean) => {
    setPreferences((current) => ({
      ...current,
      visibility: { ...current.visibility, [layer]: visible },
    }))
  }, [])

  const resetPreferences = useCallback(() => setPreferences(DEFAULT_PREFERENCES), [])

  const value = useMemo<MapContextValue>(() => {
    const call = <T,>(fn: (controller: MapController) => T, fallback: T): T =>
      controllerReady ? fn(controllerRef.current) : fallback

    return {
      preferences,
      basemap: BASEMAPS[preferences.basemap],
      setBasemap,
      setResultOpacity,
      toggleLayer,
      setLayerVisibility,
      resetPreferences,
      registerController,
      isFullscreen,
      setFullscreenState: setIsFullscreen,
      zoomIn: () => call((c) => c.zoomIn(), undefined),
      zoomOut: () => call((c) => c.zoomOut(), undefined),
      resetView: () => call((c) => c.resetView(), undefined),
      fitResults: () => call((c) => c.fitResults(), undefined),
      toggleFullscreen: () => call((c) => c.toggleFullscreen(), undefined),
      getBounds: () => call((c) => c.getBounds(), null),
      getCenter: () => call((c) => c.getCenter(), null),
      getZoom: () => call((c) => c.getZoom(), null),
      hasResults: () => call((c) => c.hasResults(), false),
    }
  }, [
    preferences,
    controllerReady,
    setBasemap,
    setResultOpacity,
    toggleLayer,
    setLayerVisibility,
    resetPreferences,
    registerController,
    isFullscreen,
  ])

  return <MapContext.Provider value={value}>{children}</MapContext.Provider>
}

export function useMapState(): MapContextValue {
  const value = useContext(MapContext)
  if (!value) throw new Error('useMapState must be used inside <MapProvider>')
  return value
}
