import { ref, watch, type Ref } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { RouteResult, Runway, RunwayThreshold } from '@/types'

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
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function useMap(
  containerRef: Ref<HTMLElement | null>,
  routeResult: Ref<RouteResult | null>,
  selectedSID: Ref<ProcedureData | null>,
  selectedSTAR: Ref<ProcedureData | null>,
  selectedSIDTransition: Ref<TransitionData | null>,
  selectedSTARTransition: Ref<TransitionData | null>,
) {
  const map = ref<any>(null)
  const isMapReady = ref(false)
  const isUpdating = ref(false)
  const currentStyle = ref(isDarkMode() ? STYLE_DARK : STYLE_LIGHT)

  function getColors() {
    const dark = isDarkMode()
    return {
      route: dark ? '#22d3ee' : '#06b6d4',
      routeGlow: dark ? '#22d3ee' : '#06b6d4',
      endpoint: '#6366f1',
      midpoint: dark ? '#22d3ee' : '#06b6d4',
      sid: dark ? '#34d399' : '#10b981',
      star: dark ? '#fbbf24' : '#f59e0b',
      stroke: dark ? '#111827' : '#ffffff',
      textHalo: dark ? '#111827' : '#ffffff',
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
    const onChange = (e: MediaQueryListEvent | MediaQueryList) => {
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
      mq.addEventListener('change', onChange)
    } else if ((mq as any).addListener) {
      (mq as any).addListener(onChange)
    }
  }

  function safeRemoveLayer(m: any, id: string) {
    try {
      if (m.getLayer(id)) m.removeLayer(id)
    } catch {
      // ignore
    }
  }

  function safeRemoveSource(m: any, id: string) {
    try {
      if (m.getSource(id)) m.removeSource(id)
    } catch {
      // ignore
    }
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

  // Compute a point along the actual runway centerline (from runway end coordinates)
  function pointAlongRunway(end: RunwayThreshold, runways: Runway[], distanceMeters: number, reverse = false): [number, number] {
    const runway = runways.find(r => r.thresholds.some(t => t.name === end.name))
    if (runway && runway.thresholds.length >= 2) {
      const other = runway.thresholds.find(t => t.name !== end.name)
      if (other) {
        const dNorth = (other.lat - end.lat) * 111320
        const dEast = (other.lon - end.lon) * (111320 * Math.cos((end.lat * Math.PI) / 180))
        const len = Math.sqrt(dNorth * dNorth + dEast * dEast)
        const uNorth = dNorth / len
        const uEast = dEast / len
        const dir = reverse ? -1 : 1
        const extNorth = distanceMeters * uNorth * dir
        const extEast = distanceMeters * uEast * dir
        const extLat = end.lat + extNorth / 111320
        const extLon = end.lon + extEast / (111320 * Math.cos((end.lat * Math.PI) / 180))
        return [extLon, extLat]
      }
    }
    return pointAlongHeading(end, distanceMeters, reverse)
  }

  // Compute extension line distance based on turn angle
  function computeExtensionDistance(end: RunwayThreshold, waypoint: { lon: number; lat: number }): number {
    const dx = waypoint.lon - end.lon
    const dy = waypoint.lat - end.lat
    let wpBearing = (Math.atan2(dx, dy) * 180) / Math.PI
    if (wpBearing < 0) wpBearing += 360
    let angle = Math.abs(wpBearing - end.heading)
    if (angle > 180) angle = 360 - angle

    if (angle < 10) return 500      // nearly aligned, short extension
    if (angle < 60) return 3000     // moderate turn
    return 8000                     // sharp turn needs more room
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

  function updateMap() {
    if (!map.value || !isMapReady.value || !routeResult.value) return
    if (isUpdating.value) return
    isUpdating.value = true

    try {
      const m = map.value
      const nodes = routeResult.value.nodes
      if (nodes.length === 0) return

      const c = getColors()

      const allLayers = [
        'route-glow', 'route-line', 'all-points', 'all-labels',
        'sid-line', 'sid-labels',
        'star-line', 'star-labels',
        'runways', 'runway-labels', 'runway-ends', 'runway-end-labels',
        'sid-active-runway', 'star-active-runway',
      ]
      const allSources = [
        'route', 'all-points',
        'sid', 'sid-points', 'star', 'star-points',
        'runways', 'runway-ends',
        'sid-active-runway', 'star-active-runway',
      ]

      allLayers.forEach(id => safeRemoveLayer(m, id))
      allSources.forEach(id => safeRemoveSource(m, id))

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

      const routeFeatures = nodes.map((n, i) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [n.lon, n.lat] },
        properties: {
          name: n.name,
          isEndpoint: i === 0 || i === nodes.length - 1,
          isSidStar: false,
        },
      }))

      const routeCoords = nodes.length > 2
        ? nodes.slice(1, -1).map(n => [n.lon, n.lat])
        : []

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

      // --- SID ---
      let sidFeatures: any[] = []
      if (selectedSID.value) {
        const sidPoints = selectedSID.value.points
        const sidEnd = findRunwayEnd(origRunways, selectedSID.value.runway)
        const sidStart = sidEnd
          ? [sidEnd.lon, sidEnd.lat]
          : [nodes[0].lon, nodes[0].lat]

        const sidRawCoords: number[][] = [sidStart]

        // Extension line from runway end along heading
        if (sidEnd) {
          const extDist = sidPoints.length > 0
            ? computeExtensionDistance(sidEnd, sidPoints[0])
            : 3000
          sidRawCoords.push(pointAlongRunway(sidEnd, origRunways, extDist, false))
        }

        // Main SID points
        sidRawCoords.push(...sidPoints.map(p => [p.lon, p.lat]))

        // Transition segment points (append after main points, skipping duplicates)
        if (selectedSIDTransition.value) {
          const transPoints = selectedSIDTransition.value.points
          const mainNames = new Set(sidPoints.map(p => p.name))
          for (const tp of transPoints) {
            if (!mainNames.has(tp.name)) {
              sidRawCoords.push([tp.lon, tp.lat])
            }
          }
        }

        sidRawCoords.push([nodes[1].lon, nodes[1].lat])
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

        sidFeatures = sidPoints.map(p => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
          properties: { name: p.name, isEndpoint: false, isSidStar: true, kind: 'SID' },
        }))

        // Add transition points as features
        if (selectedSIDTransition.value) {
          const transPoints = selectedSIDTransition.value.points
          const mainNames = new Set(sidPoints.map(p => p.name))
          for (const tp of transPoints) {
            if (!mainNames.has(tp.name)) {
              sidFeatures.push({
                type: 'Feature' as const,
                geometry: { type: 'Point' as const, coordinates: [tp.lon, tp.lat] },
                properties: { name: tp.name, isEndpoint: false, isSidStar: true, kind: 'SID' },
              })
            }
          }
        }

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

        const starRawCoords: number[][] = []

        // Transition segment points (already in flight order: transition_start -> ... -> common_entry)
        if (selectedSTARTransition.value) {
          const transPoints = selectedSTARTransition.value.points
          starRawCoords.push(...transPoints.map(p => [p.lon, p.lat]))
        } else {
          // No transition, start from the network entry point (common_entry)
          starRawCoords.push([nodes[nodes.length - 2].lon, nodes[nodes.length - 2].lat])
        }

        // Main STAR points (skip duplicates already in transition)
        const transNames = new Set(selectedSTARTransition.value?.points.map(p => p.name) || [])
        for (const p of starPoints) {
          if (!transNames.has(p.name)) {
            starRawCoords.push([p.lon, p.lat])
          }
        }

        // Extension line aligned with runway heading before runway end
        if (starEnd) {
          const allPoints = starPoints.length > 0 ? starPoints : []
          const lastWp = allPoints.length > 0 ? allPoints[allPoints.length - 1] : null
          const extDist = lastWp ? computeExtensionDistance(starEnd, lastWp) : 3000
          starRawCoords.push(pointAlongRunway(starEnd, destRunways, extDist, true))
        }

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

        starFeatures = starPoints.map(p => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
          properties: { name: p.name, isEndpoint: false, isSidStar: true, kind: 'STAR' },
        }))

        // Add transition points as features
        if (selectedSTARTransition.value) {
          const transPoints = selectedSTARTransition.value.points
          const mainNames = new Set(starPoints.map(p => p.name))
          for (const tp of transPoints) {
            if (!mainNames.has(tp.name)) {
              starFeatures.push({
                type: 'Feature' as const,
                geometry: { type: 'Point' as const, coordinates: [tp.lon, tp.lat] },
                properties: { name: tp.name, isEndpoint: false, isSidStar: true, kind: 'STAR' },
              })
            }
          }
        }

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
        selectedSID.value.transitions.forEach(t => t.points.forEach(p => bounds.extend([p.lon, p.lat])))
        const sidBoundEnd = findRunwayEnd(origRunways, selectedSID.value.runway)
        if (sidBoundEnd) bounds.extend([sidBoundEnd.lon, sidBoundEnd.lat])
      }
      if (selectedSTAR.value) {
        selectedSTAR.value.points.forEach(p => bounds.extend([p.lon, p.lat]))
        selectedSTAR.value.transitions.forEach(t => t.points.forEach(p => bounds.extend([p.lon, p.lat])))
        const starBoundEnd = findRunwayEnd(destRunways, selectedSTAR.value.runway)
        if (starBoundEnd) bounds.extend([starBoundEnd.lon, starBoundEnd.lat])
      }
      origRunways.forEach(r => r.thresholds.forEach(t => bounds.extend([t.lon, t.lat])))
      destRunways.forEach(r => r.thresholds.forEach(t => bounds.extend([t.lon, t.lat])))

      m.fitBounds(bounds, { padding: 60, maxZoom: 12, duration: 1500 })
    } finally {
      isUpdating.value = false
    }
  }

  watch([routeResult, selectedSID, selectedSTAR, selectedSIDTransition, selectedSTARTransition], () => {
    updateMap()
  }, { deep: true })

  return { map, isMapReady, initMap, updateMap }
}
