import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { BASEMAPS, INITIAL_VIEW } from '@/data/basemaps'
import { PLACES } from '@/data/places'
import { toFeatures } from '@/lib/geo'
import { useQueryState } from '@/state/QueryProvider'
import { useMapState } from '@/state/MapProvider'
import type { BoundingBox, LatLng } from '@/types/geospatial'
import type { MapController } from '@/hooks/mapController'
import { buildLabelLayer, buildPlacesLayer, buildResultLayer, restyleResultLayer } from './mapLayers'
import { MapControls } from './MapControls'
import { MapLegend } from './MapLegend'
import { MapStatusBar } from './MapStatusBar'
import { MapEmptyState } from './MapEmptyState'

/**
 * The map surface.
 *
 * Leaflet is used imperatively rather than through a React wrapper: the layers
 * are large GeoJSON collections that should be diffed by identity, not
 * re-rendered by React, and the controller interface below is what the rest of
 * the app uses to drive the view.
 *
 * Future map input (click a county, draw a polygon, select a region) belongs
 * here as another map event handler plus a field on `MapController` — the
 * `QueryContext` type in `types/geospatial.ts` is where that data would be
 * attached to a query.
 */

const DATASET_VIEW = { center: INITIAL_VIEW.center, zoom: INITIAL_VIEW.zoom }
const FIT_OPTIONS: L.FitBoundsOptions = { padding: [36, 36], maxZoom: 11 }
const LABEL_ZOOM_THRESHOLD = 7
const LABEL_FEATURE_LIMIT = 60

export function MapCanvas() {
  const { run, isRunning } = useQueryState().query
  const {
    preferences,
    basemap,
    registerController,
    setFullscreenState,
    isFullscreen,
  } = useMapState()

  const shellRef = useRef<HTMLDivElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const tileLayerRef = useRef<L.TileLayer | null>(null)
  // `FeatureGroup` rather than `LayerGroup`: only the former can report its own
  // bounds, which is what "fit to results" needs.
  const resultsGroupRef = useRef<L.FeatureGroup | null>(null)
  const labelsGroupRef = useRef<L.LayerGroup | null>(null)
  const placesGroupRef = useRef<L.LayerGroup | null>(null)
  const resultLayersRef = useRef(new Map<string, L.Layer>())
  const fittedKeyRef = useRef<string | null>(null)

  const [mapReady, setMapReady] = useState(false)
  const [zoom, setZoom] = useState(DATASET_VIEW.zoom)
  const [center, setCenter] = useState<LatLng>(DATASET_VIEW.center)
  const [picked, setPicked] = useState<LatLng | null>(null)

  const { results } = run
  const hasResults = results.length > 0

  // --- map creation (once) ------------------------------------------------
  useEffect(() => {
    const container = containerRef.current
    if (!container || mapRef.current) return

    const map = L.map(container, {
      zoomControl: false,
      attributionControl: false,
      // Canvas rendering keeps several hundred polygons interactive without
      // creating a DOM node per feature.
      preferCanvas: true,
      minZoom: 3,
      maxZoom: 18,
      zoomSnap: 0.5,
      wheelPxPerZoomLevel: 90,
      worldCopyJump: true,
    })
    map.setView([DATASET_VIEW.center.lat, DATASET_VIEW.center.lng], DATASET_VIEW.zoom)

    L.control.attribution({ position: 'bottomleft', prefix: false }).addTo(map)

    map.createPane('countyLabels')
    const labelPane = map.getPane('countyLabels')
    if (labelPane) {
      labelPane.style.zIndex = '460'
      labelPane.style.pointerEvents = 'none'
    }

    resultsGroupRef.current = L.featureGroup().addTo(map)
    labelsGroupRef.current = L.layerGroup().addTo(map)
    placesGroupRef.current = L.layerGroup().addTo(map)

    const syncView = () => {
      setZoom(map.getZoom())
      const mapCenter = map.getCenter()
      setCenter({ lat: mapCenter.lat, lng: mapCenter.lng })
    }
    map.on('zoomend moveend', syncView)
    // Leaflet types the handler as `(event: LeafletEvent) => void`, so the mouse
    // event is narrowed here rather than annotated on the parameter.
    map.on('click', (event: L.LeafletEvent) => {
      const { latlng } = event as L.LeafletMouseEvent
      setPicked({ lat: latlng.lat, lng: latlng.lng })
    })
    syncView()

    mapRef.current = map
    setMapReady(true)

    return () => {
      map.off()
      map.remove()
      mapRef.current = null
      resultsGroupRef.current = null
      labelsGroupRef.current = null
      placesGroupRef.current = null
      resultLayersRef.current.clear()
      setMapReady(false)
    }
  }, [])

  // --- basemap ------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const definition = BASEMAPS[basemap.id]
    if (tileLayerRef.current) {
      map.removeLayer(tileLayerRef.current)
    }
    const layer = L.tileLayer(definition.url, {
      attribution: definition.attribution,
      maxZoom: definition.maxZoom,
      subdomains: 'abcd',
      detectRetina: true,
      crossOrigin: true,
    })
    layer.addTo(map)
    layer.bringToBack()
    tileLayerRef.current = layer
    return () => {
      layer.remove()
      tileLayerRef.current = null
    }
  }, [basemap.id, mapReady])

  // --- result layers ------------------------------------------------------
  useEffect(() => {
    const group = resultsGroupRef.current
    if (!group || !mapReady) return

    group.clearLayers()
    resultLayersRef.current.clear()

    if (preferences.visibility.results) {
      for (const result of results) {
        const layer = buildResultLayer(result, {
          opacityMultiplier: preferences.resultOpacity,
          // Tooltips belong to the layers that answer the query; a buffer ring
          // or a reference marker does not need one.
          withTooltips: result.metadata?.role !== 'context',
        })
        resultLayersRef.current.set(result.id, layer)
        group.addLayer(layer)
      }
    }
  }, [results, mapReady, preferences.visibility.results, preferences.resultOpacity])

  // --- fit once per result set -------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    const group = resultsGroupRef.current
    if (!map || !group || !mapReady) return

    const fitKey = run.queryId ? `${run.queryId}:${results.length}` : null
    if (!fitKey || fitKey === fittedKeyRef.current) return
    if (!preferences.visibility.results) return

    const bounds = group.getBounds()
    if (bounds.isValid()) {
      map.fitBounds(bounds, FIT_OPTIONS)
      fittedKeyRef.current = fitKey
    }
  }, [run.queryId, results.length, mapReady, preferences.visibility.results])

  // --- county labels ------------------------------------------------------
  const labelFeatures = useMemo(() => {
    const primary = results.find((result) => result.metadata?.role !== 'context')
    return primary ? toFeatures(primary.data).length : 0
  }, [results])

  const showLabels =
    preferences.visibility.labels &&
    hasResults &&
    (zoom >= LABEL_ZOOM_THRESHOLD || labelFeatures <= LABEL_FEATURE_LIMIT)

  useEffect(() => {
    const group = labelsGroupRef.current
    if (!group || !mapReady) return
    group.clearLayers()
    if (!showLabels) return
    for (const result of results) {
      if (result.metadata?.role === 'context') continue
      group.addLayer(buildLabelLayer(result))
    }
  }, [showLabels, results, mapReady])

  // --- reference places ---------------------------------------------------
  useEffect(() => {
    const group = placesGroupRef.current
    if (!group || !mapReady) return
    group.clearLayers()
    if (!preferences.visibility.places) return
    group.addLayer(buildPlacesLayer(PLACES))
  }, [preferences.visibility.places, mapReady])

  // --- fullscreen ---------------------------------------------------------
  const toggleFullscreen = useCallback(() => {
    const shell = shellRef.current
    if (!shell) return
    if (document.fullscreenElement === shell) {
      void document.exitFullscreen()
    } else {
      void shell.requestFullscreen?.().catch(() => {
        // Denied (e.g. not user-initiated): leave the layout as-is.
      })
    }
  }, [])

  useEffect(() => {
    function onFullscreenChange() {
      const shell = shellRef.current
      const active = document.fullscreenElement != null && document.fullscreenElement === shell
      setFullscreenState(active)
      // Leaflet caches the container size; let the browser finish laying out.
      window.setTimeout(() => mapRef.current?.invalidateSize(), 60)
    }
    document.addEventListener('fullscreenchange', onFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange)
  }, [setFullscreenState])

  // --- keep Leaflet in step with container size ---------------------------
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const observer = new ResizeObserver(() => {
      mapRef.current?.invalidateSize()
    })
    observer.observe(container)
    return () => observer.disconnect()
  }, [])

  // --- controller ---------------------------------------------------------
  useEffect(() => {
    if (!mapReady) return
    const controller: MapController = {
      zoomIn: () => mapRef.current?.zoomIn(),
      zoomOut: () => mapRef.current?.zoomOut(),
      resetView: () => {
        const map = mapRef.current
        if (!map) return
        map.setView([DATASET_VIEW.center.lat, DATASET_VIEW.center.lng], DATASET_VIEW.zoom)
        fittedKeyRef.current = null
      },
      fitResults: () => {
        const map = mapRef.current
        const group = resultsGroupRef.current
        if (!map || !group) return
        const bounds = group.getBounds()
        if (bounds.isValid()) map.fitBounds(bounds, FIT_OPTIONS)
      },
      toggleFullscreen,
      getBounds: (): BoundingBox | null => {
        const map = mapRef.current
        if (!map) return null
        const bounds = map.getBounds()
        return {
          west: bounds.getWest(),
          south: bounds.getSouth(),
          east: bounds.getEast(),
          north: bounds.getNorth(),
        }
      },
      getCenter: (): LatLng | null => {
        const map = mapRef.current
        if (!map) return null
        const mapCenter = map.getCenter()
        return { lat: mapCenter.lat, lng: mapCenter.lng }
      },
      getZoom: () => mapRef.current?.getZoom() ?? null,
      hasResults: () => (resultsGroupRef.current?.getLayers().length ?? 0) > 0,
    }
    registerController(controller)
    return () => registerController(null)
  }, [mapReady, registerController, toggleFullscreen])

  // --- restyle only when opacity changes ---------------------------------
  useEffect(() => {
    for (const result of results) {
      const layer = resultLayersRef.current.get(result.id)
      if (layer) restyleResultLayer(layer, result, preferences.resultOpacity)
    }
    // Rebuilding is handled by the result-layer effect; this only re-applies
    // opacity so dragging the slider does not tear down the layers.
  }, [preferences.resultOpacity, results])

  const featureCount = results.reduce((sum, result) => {
    if (result.metadata?.role === 'context') return sum
    return sum + (result.metadata?.count ?? toFeatures(result.data).length)
  }, 0)

  const showEmptyState = !hasResults && !isRunning && run.status !== 'failed'

  return (
    <div ref={shellRef} className="map-shell relative h-full w-full overflow-hidden bg-panel-sunken">
      <div ref={containerRef} className="absolute inset-0 z-0" aria-label="Geographic map" role="application" />

      <div className="pointer-events-none absolute inset-0 z-[1000]">
        <MapControls />
        <MapStatusBar
          zoom={zoom}
          center={center}
          picked={picked}
          featureCount={featureCount}
          datasetLabel={run.dataset}
          onClearPicked={() => setPicked(null)}
        />
        <div className="pointer-events-auto absolute bottom-6 right-3 max-h-[45%] w-56">
          <MapLegend results={results} visible={preferences.visibility.results} />
        </div>
        {showEmptyState ? <MapEmptyState /> : null}
      </div>

      <span className="sr-only" aria-live="polite">
        {hasResults
          ? `${featureCount} features displayed on the map`
          : isRunning
            ? 'Query in progress'
            : 'No results displayed'}
        {isFullscreen ? ' (fullscreen)' : ''}
      </span>
    </div>
  )
}
