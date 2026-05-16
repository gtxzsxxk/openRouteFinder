import { ref, watch, type Ref } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { RouteResult, Runway, RunwayThreshold } from '@/types'

const STYLE_URL = 'https://demotiles.maplibre.org/style.json'

interface ProcedureData {
  name: string
  runway: string
  points: { name: string; lat: number; lon: number }[]
}

export function useMap(
  containerRef: Ref<HTMLElement | null>,
  routeResult: Ref<RouteResult | null>,
  selectedSID: Ref<ProcedureData | null>,
  selectedSTAR: Ref<ProcedureData | null>,
) {
  const map = ref<any>(null)
  const isMapReady = ref(false)
  const isUpdating = ref(false)

  function initMap() {
    if (!containerRef.value) return

    map.value = new maplibregl.Map({
      container: containerRef.value,
      style: STYLE_URL,
      center: [113.22, 28.19],
      zoom: 4,
    })

    map.value.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.value.addControl(new maplibregl.ScaleControl(), 'bottom-left')

    map.value.on('load', () => {
      isMapReady.value = true
      updateMap()
    })
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

  // Fly-by turn with circular arcs: straight to near waypoint, then arc, then straight.
  function flyByTurns(coords: number[][], baseRadius = 0.003): number[][] {
    if (coords.length < 3) return coords

    const result: number[][] = [coords[0]]

    function dist(a: number[], b: number[]): number {
      const dx = b[0] - a[0]
      const dy = b[1] - a[1]
      return Math.sqrt(dx * dx + dy * dy)
    }

    for (let i = 1; i < coords.length - 1; i++) {
      const prev = coords[i - 1]
      const curr = coords[i]
      const next = coords[i + 1]

      const v1x = curr[0] - prev[0]
      const v1y = curr[1] - prev[1]
      const v1len = dist(prev, curr)

      const v2x = next[0] - curr[0]
      const v2y = next[1] - curr[1]
      const v2len = dist(curr, next)

      if (v1len < 0.00001 || v2len < 0.00001) {
        result.push(curr)
        continue
      }

      const u1x = v1x / v1len
      const u1y = v1y / v1len
      const u2x = v2x / v2len
      const u2y = v2y / v2len

      const dot = (-u1x) * u2x + (-u1y) * u2y
      const cross = (-u1x) * u2y - (-u1y) * u2x
      const angle = Math.atan2(Math.abs(cross), dot)

      if (angle < 0.05) {
        result.push(curr)
        continue
      }

      const R = Math.min(baseRadius, v1len * 0.4, v2len * 0.4)
      if (R < 0.00001) {
        result.push(curr)
        continue
      }

      const halfAngle = angle / 2
      const tanHalf = Math.tan(halfAngle)
      if (tanHalf < 0.001) {
        result.push(curr)
        continue
      }
      const turnDist = R / tanHalf
      const d = Math.min(turnDist, v1len * 0.4, v2len * 0.4)
      if (d < 0.00001) {
        result.push(curr)
        continue
      }

      const A: [number, number] = [curr[0] - u1x * d, curr[1] - u1y * d]
      const B: [number, number] = [curr[0] + u2x * d, curr[1] + u2y * d]

      const bisectorX = -u1x + u2x
      const bisectorY = -u1y + u2y
      const bisectorLen = Math.sqrt(bisectorX * bisectorX + bisectorY * bisectorY)
      if (bisectorLen < 0.00001) {
        result.push(curr)
        continue
      }
      const bx = bisectorX / bisectorLen
      const by = bisectorY / bisectorLen

      const centerDist = R / Math.sin(halfAngle)
      const cx = curr[0] + bx * centerDist
      const cy = curr[1] + by * centerDist

      let finalCx = cx
      let finalCy = cy
      const distCA = Math.sqrt((A[0] - cx) ** 2 + (A[1] - cy) ** 2)
      if (Math.abs(distCA - R) > 0.01 * R) {
        finalCx = curr[0] - bx * centerDist
        finalCy = curr[1] - by * centerDist
      }

      const startAngle = Math.atan2(A[1] - finalCy, A[0] - finalCx)
      const endAngle = Math.atan2(B[1] - finalCy, B[0] - finalCx)
      let arcDiff = endAngle - startAngle

      if (cross < 0 && arcDiff < 0) arcDiff += 2 * Math.PI
      if (cross > 0 && arcDiff > 0) arcDiff -= 2 * Math.PI

      const segments = Math.max(8, Math.ceil(Math.abs(arcDiff) * 15))
      for (let j = 1; j < segments; j++) {
        const t = j / segments
        const a = startAngle + arcDiff * t
        result.push([finalCx + R * Math.cos(a), finalCy + R * Math.sin(a)])
      }

      result.push(B)
    }

    result.push(coords[coords.length - 1])
    return result
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

      const allLayers = [
        'route-line', 'all-points', 'all-labels',
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
          },
          paint: {
            'text-color': '#9ca3af',
            'text-halo-color': '#1a1a2e',
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
            'circle-stroke-color': '#fff',
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
          },
          paint: {
            'text-color': '#9ca3af',
            'text-halo-color': '#1a1a2e',
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
          id: 'route-line',
          type: 'line',
          source: 'route',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': '#e94560', 'line-width': 3 },
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

        sidRawCoords.push(...sidPoints.map(p => [p.lon, p.lat]))
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
            'line-color': '#10b981',
            'line-width': 2,
            'line-dasharray': [2, 1],
          },
        })

        sidFeatures = sidPoints.map(p => ({
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
            },
            paint: {
              'text-color': '#10b981',
              'text-halo-color': '#1a1a2e',
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
              'circle-color': '#10b981',
              'circle-stroke-width': 2,
              'circle-stroke-color': '#fff',
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

        const starRawCoords: number[][] = [[nodes[nodes.length - 2].lon, nodes[nodes.length - 2].lat]]
        starRawCoords.push(...starPoints.map(p => [p.lon, p.lat]))

        // Extension line aligned with runway heading before runway end
        if (starEnd) {
          const lastWp = starPoints.length > 0 ? starPoints[starPoints.length - 1] : null
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
            'line-color': '#f59e0b',
            'line-width': 2,
            'line-dasharray': [2, 1],
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
              'circle-color': '#f59e0b',
              'circle-stroke-width': 2,
              'circle-stroke-color': '#fff',
            },
          })
        }

        starFeatures = starPoints.map(p => ({
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
            },
            paint: {
              'text-color': '#f59e0b',
              'text-halo-color': '#1a1a2e',
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
            ['get', 'isEndpoint'], 8,
            ['get', 'isSidStar'], 3,
            5,
          ],
          'circle-color': [
            'case',
            ['get', 'isEndpoint'], '#e94560',
            ['==', ['get', 'kind'], 'SID'], '#10b981',
            ['==', ['get', 'kind'], 'STAR'], '#f59e0b',
            '#0f3460',
          ],
          'circle-stroke-width': 2,
          'circle-stroke-color': '#fff',
        },
      })
      m.addLayer({
        id: 'all-labels',
        type: 'symbol',
        source: 'all-points',
        layout: {
          'text-field': ['get', 'name'],
          'text-offset': [0, -1.2],
          'text-anchor': 'bottom',
          'text-size': [
            'case',
            ['get', 'isEndpoint'], 12,
            10,
          ],
        },
        paint: {
          'text-color': [
            'case',
            ['get', 'isEndpoint'], '#e94560',
            ['==', ['get', 'kind'], 'SID'], '#10b981',
            ['==', ['get', 'kind'], 'STAR'], '#f59e0b',
            '#e5e7eb',
          ],
          'text-halo-color': '#1a1a2e',
          'text-halo-width': 2,
        },
      })

      const bounds = new maplibregl.LngLatBounds()
      nodes.forEach(n => bounds.extend([n.lon, n.lat]))
      if (selectedSID.value) {
        selectedSID.value.points.forEach(p => bounds.extend([p.lon, p.lat]))
        const sidBoundEnd = findRunwayEnd(origRunways, selectedSID.value.runway)
        if (sidBoundEnd) bounds.extend([sidBoundEnd.lon, sidBoundEnd.lat])
      }
      if (selectedSTAR.value) {
        selectedSTAR.value.points.forEach(p => bounds.extend([p.lon, p.lat]))
        const starBoundEnd = findRunwayEnd(destRunways, selectedSTAR.value.runway)
        if (starBoundEnd) bounds.extend([starBoundEnd.lon, starBoundEnd.lat])
      }
      origRunways.forEach(r => r.thresholds.forEach(t => bounds.extend([t.lon, t.lat])))
      destRunways.forEach(r => r.thresholds.forEach(t => bounds.extend([t.lon, t.lat])))

      m.fitBounds(bounds, { padding: 80, maxZoom: 12, duration: 1500 })
    } finally {
      isUpdating.value = false
    }
  }

  watch([routeResult, selectedSID, selectedSTAR], () => {
    updateMap()
  }, { deep: true })

  return { map, isMapReady, initMap, updateMap }
}
