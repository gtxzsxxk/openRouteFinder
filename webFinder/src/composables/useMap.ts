import { ref, watch, type Ref } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { RouteResult, Runway, RunwayThreshold, RouteSegment } from '@/types'

const STYLE_LIGHT = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'
const STYLE_DARK = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

interface TransitionData {
  name: string
  points: { name: string; lat: number; lon: number }[]
}

interface ProcedureData {
  name: string
  runway: string
  points: { name: string; lat: number; lon: number }[]
  transitions: TransitionData[]
}

function isDarkMode() {
  const htmlTheme = document.documentElement.getAttribute('data-theme')
  if (htmlTheme === 'dark') return true
  if (htmlTheme === 'light') return false
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function useMap(
  containerRef: Ref<HTMLElement | null>,
  routeResult: Ref<RouteResult | null>,
  selectedSID: Ref<ProcedureData | null>,
  selectedSTAR: Ref<ProcedureData | null>,
  selectedSIDTransition: Ref<TransitionData | null>,
  selectedSTARTransition: Ref<TransitionData | null>,
  routeSegments: Ref<RouteSegment[]>,
) {
  const map = ref<any>(null)
  const isMapReady = ref(false)
  const isUpdating = ref(false)
  const pendingUpdate = ref(false)
  const updateTimer = ref<ReturnType<typeof setTimeout> | null>(null)
  const currentStyle = ref(isDarkMode() ? STYLE_DARK : STYLE_LIGHT)

  function getColors() {
    const dark = isDarkMode()
    const style = getComputedStyle(document.documentElement)
    return {
      route: style.getPropertyValue('--color-route-line').trim() || (dark ? '#5eead4' : '#14b8a6'),
      routeGlow: style.getPropertyValue('--color-route-line').trim() || (dark ? '#5eead4' : '#14b8a6'),
      endpoint: style.getPropertyValue('--color-accent').trim() || (dark ? '#14b8a6' : '#0d9488'),
      midpoint: style.getPropertyValue('--color-route-line').trim() || (dark ? '#5eead4' : '#14b8a6'),
      sid: style.getPropertyValue('--color-sid-line').trim() || (dark ? '#34d399' : '#059669'),
      star: style.getPropertyValue('--color-star-line').trim() || (dark ? '#fbbf24' : '#d97706'),
      stroke: dark ? '#0c0a09' : '#ffffff',
      textHalo: dark ? '#0c0a09' : '#ffffff',
    }
  }

  function initMap() {
    if (!containerRef.value) return

    map.value = new maplibregl.Map({
      container: containerRef.value,
      style: currentStyle.value,
      center: [113.22, 28.19],
      zoom: 4,
    })

    map.value.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.value.addControl(new maplibregl.ScaleControl(), 'bottom-left')

    map.value.on('load', () => {
      isMapReady.value = true
      updateMap()
    })

    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onMediaChange = (e: MediaQueryListEvent | MediaQueryList) => {
      if (document.documentElement.getAttribute('data-theme')) return
      const newStyle = e.matches ? STYLE_DARK : STYLE_LIGHT
      if (newStyle !== currentStyle.value && map.value) {
        currentStyle.value = newStyle
        map.value.setStyle(newStyle)
        map.value.once('styledata', () => {
          updateMap()
        })
      }
    }
    if (mq.addEventListener) {
      mq.addEventListener('change', onMediaChange)
    } else if ((mq as any).addListener) {
      (mq as any).addListener(onMediaChange)
    }

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
          const newDark = isDarkMode()
          const newStyle = newDark ? STYLE_DARK : STYLE_LIGHT
          if (newStyle !== currentStyle.value && map.value) {
            currentStyle.value = newStyle
            map.value.setStyle(newStyle)
            map.value.once('styledata', () => {
              updateMap()
            })
          }
        }
      }
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  }

  function safeRemoveLayer(m: any, id: string) {
    if (m.getLayer(id)) {
      try {
        m.removeLayer(id)
      } catch {
        // ignore
      }
    }
  }

  function safeRemoveSource(m: any, id: string) {
    if (m.getSource(id)) {
      try {
        m.removeSource(id)
      } catch {
        // ignore: source may still be referenced
      }
    }
  }

  // Explicit list of all application layer and source IDs.
  // Used to ensure complete cleanup on every update.
  const APP_LAYERS = [
    'route-glow', 'route-line', 'route-segment-labels', 'all-points', 'all-labels',
    'sid-line', 'sid-labels', 'sid-active-runway',
    'star-line', 'star-labels', 'star-active-runway',
    'runways', 'runway-labels', 'runway-ends', 'runway-end-labels',
  ]
  const APP_SOURCES = [
    'route', 'route-segments', 'all-points',
    'sid', 'sid-points', 'star', 'star-points',
    'runways', 'runway-ends',
    'sid-active-runway', 'star-active-runway',
  ]

  function _clearMapLayers(m: any) {
    for (const id of APP_LAYERS) {
      safeRemoveLayer(m, id)
    }
    for (const id of APP_SOURCES) {
      safeRemoveSource(m, id)
    }
  }

  // Compute midpoint on great-circle path between two lat/lon points
  function midpoint(lat1: number, lon1: number, lat2: number, lon2: number): [number, number] {
    const dLon = (lon2 - lon1) * Math.PI / 180
    const lat1r = lat1 * Math.PI / 180
    const lat2r = lat2 * Math.PI / 180
    const lon1r = lon1 * Math.PI / 180

    const Bx = Math.cos(lat2r) * Math.cos(dLon)
    const By = Math.cos(lat2r) * Math.sin(dLon)

    const midLat = Math.atan2(
      Math.sin(lat1r) + Math.sin(lat2r),
      Math.sqrt((Math.cos(lat1r) + Bx) ** 2 + By ** 2)
    )
    const midLon = lon1r + Math.atan2(By, Math.cos(lat1r) + Bx)

    return [midLon * 180 / Math.PI, midLat * 180 / Math.PI]
  }

  // Compute a point along runway heading at given distance (in meters) using ENU conversion
  function pointAlongHeading(end: RunwayThreshold, distanceMeters: number, reverse = false): [number, number] {
    const headingRad = (end.heading * Math.PI) / 180
    const dir = reverse ? -1 : 1
    const dNorth = distanceMeters * Math.cos(headingRad) * dir
    const dEast = distanceMeters * Math.sin(headingRad) * dir
    // Meters per degree at this latitude
    const metersPerDegLat = 111320
    const metersPerDegLon = 111320 * Math.cos((end.lat * Math.PI) / 180)
    const dLat = dNorth / metersPerDegLat
    const dLon = dEast / metersPerDegLon
    return [end.lon + dLon, end.lat + dLat]
  }

  // Find a runway end by its designation (e.g., "36L")
  function findRunwayEnd(runways: Runway[] | undefined, runwayName: string): RunwayThreshold | null {
    if (!runways || runwayName === 'ALL') return null
    for (const rwy of runways) {
      for (const end of rwy.thresholds) {
        if (end.name === runwayName) {
          return end
        }
      }
    }
    return null
  }

  // Find the opposite runway end (e.g., "36L" -> "18R")
  function findOppositeRunwayEnd(runways: Runway[] | undefined, runwayName: string): RunwayThreshold | null {
    if (!runways || runwayName === 'ALL') return null
    for (const rwy of runways) {
      for (const end of rwy.thresholds) {
        if (end.name === runwayName) {
          const other = rwy.thresholds.find(t => t.name !== runwayName)
          return other || end
        }
      }
    }
    return null
  }

  function updateMap() {
    if (!map.value || !isMapReady.value || !routeResult.value) return
    if (isUpdating.value) {
      pendingUpdate.value = true
      return
    }

    do {
      pendingUpdate.value = false
      isUpdating.value = true

      try {
        const m = map.value
        const nodes = routeResult.value.nodes
          if (nodes.length === 0) {
          // Clear everything even when there are no nodes
          _clearMapLayers(m)
          return
        }

        const c = getColors()

        _clearMapLayers(m)

      const origRunways = routeResult.value.origRunways || []
      const destRunways = routeResult.value.destRunways || []

      const runwayFeatures = []
      const endFeatures = []
      for (const rwy of [...origRunways, ...destRunways]) {
        if (rwy.thresholds.length >= 2) {
          runwayFeatures.push({
            type: 'Feature' as const,
            geometry: {
              type: 'LineString' as const,
              coordinates: rwy.thresholds.map(t => [t.lon, t.lat]),
            },
            properties: { name: rwy.name, length: rwy.length, width: rwy.width },
          })
        } else if (rwy.thresholds.length === 1) {
          const end = rwy.thresholds[0]
          const [endLon, endLat] = pointAlongHeading(end, 300, false)
          runwayFeatures.push({
            type: 'Feature' as const,
            geometry: {
              type: 'LineString' as const,
              coordinates: [
                [end.lon, end.lat],
                [endLon, endLat],
              ],
            },
            properties: { name: rwy.name, length: rwy.length, width: rwy.width },
          })
        }
        for (const end of rwy.thresholds) {
          endFeatures.push({
            type: 'Feature' as const,
            geometry: { type: 'Point' as const, coordinates: [end.lon, end.lat] },
            properties: { name: end.name, runway: rwy.name },
          })
        }
      }

      if (runwayFeatures.length > 0) {
        m.addSource('runways', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: runwayFeatures },
        })
        m.addLayer({
          id: 'runways',
          type: 'line',
          source: 'runways',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: {
            'line-color': '#6b7280',
            'line-width': 2,
            'line-opacity': 0.7,
          },
        })
        m.addLayer({
          id: 'runway-labels',
          type: 'symbol',
          source: 'runways',
          layout: {
            'text-field': ['get', 'name'],
            'text-offset': [0, 0.8],
            'text-anchor': 'top',
            'text-size': 9,
            'text-font': ['Open Sans Regular'],
          },
          paint: {
            'text-color': '#9ca3af',
            'text-halo-color': c.textHalo,
            'text-halo-width': 1,
          },
        })
      }

      if (endFeatures.length > 0) {
        m.addSource('runway-ends', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: endFeatures },
        })
        m.addLayer({
          id: 'runway-ends',
          type: 'circle',
          source: 'runway-ends',
          paint: {
            'circle-radius': 3,
            'circle-color': '#6b7280',
            'circle-stroke-width': 1,
            'circle-stroke-color': c.stroke,
            'circle-opacity': 0.8,
          },
        })
        m.addLayer({
          id: 'runway-end-labels',
          type: 'symbol',
          source: 'runway-ends',
          layout: {
            'text-field': ['get', 'name'],
            'text-offset': [0, -1.2],
            'text-anchor': 'bottom',
            'text-size': 8,
            'text-font': ['Open Sans Regular'],
          },
          paint: {
            'text-color': '#9ca3af',
            'text-halo-color': c.textHalo,
            'text-halo-width': 1,
          },
        })
      }

      // Build route coordinates excluding SID/STAR procedure points.
      // SID/STAR segments are drawn separately as dashed lines.
      // sidRouteNodeName / starRouteNodeName are the actual nodes in the
      // route that belong to the procedure; they may differ from the
      // procedure key (sidNodeName / starNodeName) when A* routes through
      // the interior of a procedure rather than its anchor point.
      const sidRouteName = routeResult.value?.sidRouteNodeName || routeResult.value?.sidNodeName
      const starRouteName = routeResult.value?.starRouteNodeName || routeResult.value?.starNodeName
      const sidIdx = nodes.findIndex(n => n.name === sidRouteName)
      const starIdx = nodes.findIndex(n => n.name === starRouteName)

      // Route point features: exclude SID/STAR internal points so the map only
      // shows the user-selected procedure points, not the A* route's internal ones.
      const routeFeatures = nodes
        .map((n, i) => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [n.lon, n.lat] },
          properties: {
            name: n.name,
            isEndpoint: i === 0 || i === nodes.length - 1,
            isSidStar: false,
          },
        }))
        .filter((_f, i) => {
          // Keep endpoints (airports) always
          if (i === 0 || i === nodes.length - 1) return true
          // Exclude SID internal points (before sidNodeName)
          if (sidIdx >= 0 && i < sidIdx) return false
          // Exclude STAR internal points (after starNodeName)
          if (starIdx >= 0 && i > starIdx) return false
          return true
        })

      const routeCoords = routeFeatures
        .filter(f => !f.properties.isEndpoint)
        .map(f => f.geometry.coordinates)

      if (routeCoords.length > 0) {
        m.addSource('route', {
          type: 'geojson',
          data: {
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: routeCoords },
            properties: {},
          },
        })
        m.addLayer({
          id: 'route-glow',
          type: 'line',
          source: 'route',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: {
            'line-color': c.routeGlow,
            'line-width': 8,
            'line-opacity': 0.3,
            'line-blur': 4,
          },
        })
        m.addLayer({
          id: 'route-line',
          type: 'line',
          source: 'route',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: {
            'line-color': c.route,
            'line-width': 3,
          },
        })
      }

      // Route segment labels (airway names)
      const segmentFeatures: any[] = []
      for (const seg of routeSegments.value) {
        const fromNode = nodes.find(n => n.name === seg.from)
        const toNode = nodes.find(n => n.name === seg.to)
        if (!fromNode || !toNode) continue
        const [midLon, midLat] = midpoint(fromNode.lat, fromNode.lon, toNode.lat, toNode.lon)
        segmentFeatures.push({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [midLon, midLat] },
          properties: { airway: seg.airway },
        })
      }

      if (segmentFeatures.length > 0) {
        m.addSource('route-segments', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: segmentFeatures },
        })
        m.addLayer({
          id: 'route-segment-labels',
          type: 'symbol',
          source: 'route-segments',
          layout: {
            'text-field': ['get', 'airway'],
            'text-size': 10,
            'text-font': ['Open Sans Regular'],
          },
          paint: {
            'text-color': c.route,
            'text-halo-color': c.textHalo,
            'text-halo-width': 2,
          },
        })
      }

      // --- SID ---
      let sidFeatures: any[] = []
      if (selectedSID.value) {
        const sidPoints = selectedSID.value.points
        // SID starts at the opposite end of the departure runway
        // (aircraft takes off along the runway and exits at the far end)
        const sidEnd = findOppositeRunwayEnd(origRunways, selectedSID.value.runway)
        const sidStart = sidEnd
          ? [sidEnd.lon, sidEnd.lat]
          : [nodes[0].lon, nodes[0].lat]

        let sidRawCoords: number[][] = [sidStart]

        // Main SID points (airport->network order)
        sidRawCoords.push(...sidPoints.map(p => [p.lon, p.lat]))

        // Transition segment points
        if (selectedSIDTransition.value) {
          const transPoints = selectedSIDTransition.value.points
          const mainNames = new Set(sidPoints.map(p => p.name))
          // For transition-only procedures, the transition's first point is not
          // in the main points (each option is a full runway->network path).
          // In that case, replace the main path with the transition path.
          if (transPoints.length > 0 && !mainNames.has(transPoints[0].name)) {
            sidRawCoords = [sidStart]
            sidRawCoords.push(...transPoints.map(p => [p.lon, p.lat]))
          } else {
            // Normal case: append non-overlapping transition points after main points
            for (const tp of transPoints) {
              if (!mainNames.has(tp.name)) {
                sidRawCoords.push([tp.lon, tp.lat])
              }
            }
          }
        }

        const sidCoords = sidRawCoords

        m.addSource('sid', {
          type: 'geojson',
          data: {
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: sidCoords },
            properties: { name: selectedSID.value.name },
          },
        })
        m.addLayer({
          id: 'sid-line',
          type: 'line',
          source: 'sid',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: {
            'line-color': c.sid,
            'line-width': 2,
            'line-dasharray': [4, 2],
          },
        })

        // Determine which points to display: if transition replaces the main
        // path, show transition points instead of main points.
        let displayedSidPoints = sidPoints
        if (selectedSIDTransition.value) {
          const transPoints = selectedSIDTransition.value.points
          const mainNames = new Set(sidPoints.map(p => p.name))
          if (transPoints.length > 0 && !mainNames.has(transPoints[0].name)) {
            displayedSidPoints = transPoints
          }
        }

        sidFeatures = displayedSidPoints.map(p => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
          properties: { name: p.name, isEndpoint: false, isSidStar: true, kind: 'SID' },
        }))

        if (sidFeatures.length > 0) {
          m.addSource('sid-points', {
            type: 'geojson',
            data: {
              type: 'FeatureCollection',
              features: sidFeatures,
            },
          })
          m.addLayer({
            id: 'sid-labels',
            type: 'symbol',
            source: 'sid-points',
            layout: {
              'text-field': ['get', 'name'],
              'text-offset': [0, -1.2],
              'text-anchor': 'bottom',
              'text-size': 10,
              'text-font': ['Open Sans Regular'],
            },
            paint: {
              'text-color': c.sid,
              'text-halo-color': c.textHalo,
              'text-halo-width': 2,
            },
          })
        }

        if (sidEnd) {
          m.addSource('sid-active-runway', {
            type: 'geojson',
            data: {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [sidEnd.lon, sidEnd.lat] },
              properties: { name: sidEnd.name },
            },
          })
          m.addLayer({
            id: 'sid-active-runway',
            type: 'circle',
            source: 'sid-active-runway',
            paint: {
              'circle-radius': 6,
              'circle-color': c.sid,
              'circle-stroke-width': 2,
              'circle-stroke-color': c.stroke,
            },
          })
        }
      }

      // --- STAR ---
      let starFeatures: any[] = []
      if (selectedSTAR.value) {
        const starPoints = selectedSTAR.value.points
        const starEnd = findRunwayEnd(destRunways, selectedSTAR.value.runway)
        const starEndCoords = starEnd
          ? [starEnd.lon, starEnd.lat]
          : [nodes[nodes.length - 1].lon, nodes[nodes.length - 1].lat]

        // Main STAR points (network->airport order)
        const mainNames = new Set(starPoints.map(p => p.name))
        const routeNodeNames = new Set(nodes.map(n => n.name))

        // Transition segment points (network->airport order)
        let starRawCoords: number[][] = []
        if (selectedSTARTransition.value) {
          const transPoints = selectedSTARTransition.value.points
          // For transition-only procedures, the transition's last point is not
          // in the main points (each option is a full network->runway path).
          // In that case, replace the main path with the transition path.
          if (transPoints.length > 0 && !mainNames.has(transPoints[transPoints.length - 1].name)) {
            starRawCoords = [...transPoints.map(p => [p.lon, p.lat])]
          } else {
            // Normal case: prepend non-overlapping transition points before main points,
            // but only from the first point that also appears in the route.
            // This prevents visual forks when the route takes an airway shortcut
            // into the transition at a midpoint (e.g., EHF->LHS instead of EHF->ARVIN).
            let startIdx = 0
            for (let i = 0; i < transPoints.length; i++) {
              if (routeNodeNames.has(transPoints[i].name)) {
                startIdx = i
                break
              }
            }
            const transitionCoords: number[][] = []
            for (let i = startIdx; i < transPoints.length; i++) {
              if (!mainNames.has(transPoints[i].name)) {
                transitionCoords.push([transPoints[i].lon, transPoints[i].lat])
              }
            }
            starRawCoords = [...transitionCoords, ...starPoints.map(p => [p.lon, p.lat])]
          }
        } else {
          starRawCoords = [...starPoints.map(p => [p.lon, p.lat])]
        }

        // Connect directly to runway end
        starRawCoords.push(starEndCoords)
        const starCoords = starRawCoords

        m.addSource('star', {
          type: 'geojson',
          data: {
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: starCoords },
            properties: { name: selectedSTAR.value.name },
          },
        })
        m.addLayer({
          id: 'star-line',
          type: 'line',
          source: 'star',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: {
            'line-color': c.star,
            'line-width': 2,
            'line-dasharray': [4, 2],
          },
        })

        if (starEnd) {
          m.addSource('star-active-runway', {
            type: 'geojson',
            data: {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [starEnd.lon, starEnd.lat] },
              properties: { name: starEnd.name },
            },
          })
          m.addLayer({
            id: 'star-active-runway',
            type: 'circle',
            source: 'star-active-runway',
            paint: {
              'circle-radius': 6,
              'circle-color': c.star,
              'circle-stroke-width': 2,
              'circle-stroke-color': c.stroke,
            },
          })
        }

        // Determine which points to display: if transition replaces the main
        // path, show transition points instead of main points.
        let displayedStarPoints = starPoints
        if (selectedSTARTransition.value) {
          const transPoints = selectedSTARTransition.value.points
          const mainNames = new Set(starPoints.map(p => p.name))
          if (transPoints.length > 0 && !mainNames.has(transPoints[transPoints.length - 1].name)) {
            displayedStarPoints = transPoints
          } else {
            let startIdx = 0
            for (let i = 0; i < transPoints.length; i++) {
              if (routeNodeNames.has(transPoints[i].name)) {
                startIdx = i
                break
              }
            }
            const visibleTransPoints = []
            for (let i = startIdx; i < transPoints.length; i++) {
              if (!mainNames.has(transPoints[i].name)) {
                visibleTransPoints.push(transPoints[i])
              }
            }
            displayedStarPoints = [...visibleTransPoints, ...starPoints]
          }
        }

        starFeatures = displayedStarPoints.map(p => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
          properties: { name: p.name, isEndpoint: false, isSidStar: true, kind: 'STAR' },
        }))

        if (starFeatures.length > 0) {
          m.addSource('star-points', {
            type: 'geojson',
            data: {
              type: 'FeatureCollection',
              features: starFeatures,
            },
          })
          m.addLayer({
            id: 'star-labels',
            type: 'symbol',
            source: 'star-points',
            layout: {
              'text-field': ['get', 'name'],
              'text-offset': [0, -1.2],
              'text-anchor': 'bottom',
              'text-size': 10,
              'text-font': ['Open Sans Regular'],
            },
            paint: {
              'text-color': c.star,
              'text-halo-color': c.textHalo,
              'text-halo-width': 2,
            },
          })
        }
      }

      const allPointFeatures = [...routeFeatures, ...sidFeatures, ...starFeatures]
      m.addSource('all-points', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: allPointFeatures,
        },
      })
      m.addLayer({
        id: 'all-points',
        type: 'circle',
        source: 'all-points',
        paint: {
          'circle-radius': [
            'case',
            ['get', 'isEndpoint'], 6,
            ['get', 'isSidStar'], 4,
            4,
          ],
          'circle-color': [
            'case',
            ['get', 'isEndpoint'], c.endpoint,
            ['==', ['get', 'kind'], 'SID'], c.sid,
            ['==', ['get', 'kind'], 'STAR'], c.star,
            c.midpoint,
          ],
          'circle-stroke-width': 2,
          'circle-stroke-color': c.stroke,
        },
      })
      m.addLayer({
        id: 'all-labels',
        type: 'symbol',
        source: 'all-points',
        layout: {
          'text-field': ['get', 'name'],
          'text-offset': [0, 1.2],
          'text-anchor': 'top',
          'text-size': [
            'case',
            ['get', 'isEndpoint'], 12,
            11,
          ],
          'text-font': ['Open Sans Regular'],
        },
        paint: {
          'text-color': [
            'case',
            ['get', 'isEndpoint'], c.endpoint,
            ['==', ['get', 'kind'], 'SID'], c.sid,
            ['==', ['get', 'kind'], 'STAR'], c.star,
            c.midpoint,
          ],
          'text-halo-color': c.textHalo,
          'text-halo-width': 2,
        },
      })

      const bounds = new maplibregl.LngLatBounds()
      nodes.forEach(n => bounds.extend([n.lon, n.lat]))
      if (selectedSID.value) {
        selectedSID.value.points.forEach(p => bounds.extend([p.lon, p.lat]))
        if (selectedSIDTransition.value) {
          selectedSIDTransition.value.points.forEach(p => bounds.extend([p.lon, p.lat]))
        }
        const sidBoundEnd = findRunwayEnd(origRunways, selectedSID.value.runway)
        if (sidBoundEnd) bounds.extend([sidBoundEnd.lon, sidBoundEnd.lat])
      }
      if (selectedSTAR.value) {
        selectedSTAR.value.points.forEach(p => bounds.extend([p.lon, p.lat]))
        if (selectedSTARTransition.value) {
          selectedSTARTransition.value.points.forEach(p => bounds.extend([p.lon, p.lat]))
        }
        const starBoundEnd = findRunwayEnd(destRunways, selectedSTAR.value.runway)
        if (starBoundEnd) bounds.extend([starBoundEnd.lon, starBoundEnd.lat])
      }
      origRunways.forEach(r => r.thresholds.forEach(t => bounds.extend([t.lon, t.lat])))
      destRunways.forEach(r => r.thresholds.forEach(t => bounds.extend([t.lon, t.lat])))

      m.fitBounds(bounds, { padding: 60, maxZoom: 12, duration: 1500 })
    } catch (err) {
      console.error('[useMap] updateMap error:', err)
    } finally {
      isUpdating.value = false
    }
  } while (pendingUpdate.value)
}

  function scheduleUpdate() {
    if (updateTimer.value) {
      clearTimeout(updateTimer.value)
    }
    updateTimer.value = setTimeout(() => {
      updateTimer.value = null
      updateMap()
    }, 50)
  }

  watch(routeResult, () => { scheduleUpdate() })
  watch(selectedSID, () => { scheduleUpdate() })
  watch(selectedSTAR, () => { scheduleUpdate() })
  watch(selectedSIDTransition, () => { scheduleUpdate() })
  watch(selectedSTARTransition, () => { scheduleUpdate() })

  return { map, isMapReady, initMap, updateMap }
}
