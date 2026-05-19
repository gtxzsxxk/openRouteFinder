import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { RouteResult, ProcedureTuple } from '@/types'

export interface TransitionData {
  name: string
  points: { name: string; lat: number; lon: number }[]
}

export interface ProcedureData {
  name: string
  runway: string
  points: { name: string; lat: number; lon: number }[]
  transitions: TransitionData[]
}

export const useRouteStore = defineStore('route', () => {
  const routeResult = ref<RouteResult | null>(null)
  const selectedSIDIndex = ref(0)
  const selectedSTARIndex = ref(0)
  const selectedSIDTransitionIndex = ref(-1)  // -1 = no transition
  const selectedSTARTransitionIndex = ref(-1)  // -1 = no transition
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const preSelectedSidExit = ref('')
  const preSelectedStarEntry = ref('')

  const hasResult = computed(() => routeResult.value !== null)

  const departureAirport = computed(() => {
    if (!routeResult.value || routeResult.value.nodes.length === 0) return null
    return routeResult.value.nodes[0]
  })

  const arrivalAirport = computed(() => {
    if (!routeResult.value || routeResult.value.nodes.length === 0) return null
    return routeResult.value.nodes[routeResult.value.nodes.length - 1]
  })

  const sidNode = computed(() => {
    if (!routeResult.value || routeResult.value.nodes.length < 2) return null
    return routeResult.value.nodes[1]
  })

  const starNode = computed(() => {
    if (!routeResult.value || routeResult.value.nodes.length < 2) return null
    return routeResult.value.nodes[routeResult.value.nodes.length - 2]
  })

  const selectedSIDProcedures = computed(() => {
    if (!routeResult.value) return [] as ProcedureTuple[]
    const key = routeResult.value.sidNodeName || sidNode.value?.name
    if (!key) return [] as ProcedureTuple[]
    return routeResult.value.SID[key] || []
  })

  const selectedSTARProcedures = computed(() => {
    if (!routeResult.value) return [] as ProcedureTuple[]
    const key = routeResult.value.starNodeName || starNode.value?.name
    if (!key) return [] as ProcedureTuple[]
    return routeResult.value.STAR[key] || []
  })

  function toProcedureData(proc: ProcedureTuple | null): ProcedureData | null {
    if (!proc) return null
    return {
      name: proc[0],
      runway: proc[1],
      points: proc[2].map(p => ({ name: p[0], lat: p[1], lon: p[2] })),
      transitions: (proc[3] || []).map(t => ({
        name: t[0],
        points: t[1].map(p => ({ name: p[0], lat: p[1], lon: p[2] }))
      })),
    }
  }

  const selectedSID = computed(() => {
    const procs = selectedSIDProcedures.value
    if (procs.length === 0 || selectedSIDIndex.value >= procs.length) return null
    return toProcedureData(procs[selectedSIDIndex.value])
  })

  const selectedSTAR = computed(() => {
    const procs = selectedSTARProcedures.value
    if (procs.length === 0 || selectedSTARIndex.value >= procs.length) return null
    return toProcedureData(procs[selectedSTARIndex.value])
  })

  const selectedSIDTransition = computed(() => {
    const sid = selectedSID.value
    if (!sid || selectedSIDTransitionIndex.value < 0) return null
    return sid.transitions[selectedSIDTransitionIndex.value] || null
  })

  const selectedSTARTransition = computed(() => {
    const star = selectedSTAR.value
    if (!star || selectedSTARTransitionIndex.value < 0) return null
    return star.transitions[selectedSTARTransitionIndex.value] || null
  })

  const origAirportDetail = computed(() => routeResult.value?.airportDetails?.orig ?? null)
  const destAirportDetail = computed(() => routeResult.value?.airportDetails?.dest ?? null)
  const parsedWeather = computed(() => routeResult.value?.parsedWeather ?? null)
  const routeSegments = computed(() => routeResult.value?.routeSegments ?? [])

  function setRouteResult(result: RouteResult | null) {
    routeResult.value = result
    selectedSIDIndex.value = 0
    selectedSTARIndex.value = 0
    selectedSIDTransitionIndex.value = -1
    selectedSTARTransitionIndex.value = -1
    error.value = null

    if (!result) return

    // Auto-select active transitions returned by A*
    const sidKey = result.sidNodeName || result.nodes[1]?.name
    if (sidKey) {
      const sidProcs = result.SID[sidKey] || []
      if (sidProcs.length > 0 && result.activeSIDTransition) {
        const transitions = sidProcs[0][3] || []
        const idx = transitions.findIndex(t => t[0] === result.activeSIDTransition)
        if (idx >= 0) {
          selectedSIDTransitionIndex.value = idx
        }
      }
    }

    const starKey = result.starNodeName || result.nodes[result.nodes.length - 2]?.name
    if (starKey) {
      const starProcs = result.STAR[starKey] || []
      if (starProcs.length > 0 && result.activeSTARTransition) {
        const transitions = starProcs[0][3] || []
        const idx = transitions.findIndex(t => t[0] === result.activeSTARTransition)
        if (idx >= 0) {
          selectedSTARTransitionIndex.value = idx
        }
      }
    }
  }

  function setLoading(loading: boolean) {
    isLoading.value = loading
  }

  function setError(err: string | null) {
    error.value = err
  }

  function setSelectedSID(index: number) {
    selectedSIDIndex.value = index
    selectedSIDTransitionIndex.value = -1
  }

  function setSelectedSTAR(index: number) {
    selectedSTARIndex.value = index
    selectedSTARTransitionIndex.value = -1
  }

  function setSelectedSIDTransition(index: number) {
    selectedSIDTransitionIndex.value = index
  }

  function setSelectedSTARTransition(index: number) {
    selectedSTARTransitionIndex.value = index
  }

  return {
    routeResult,
    selectedSIDIndex,
    selectedSTARIndex,
    selectedSIDTransitionIndex,
    selectedSTARTransitionIndex,
    isLoading,
    error,
    preSelectedSidExit,
    preSelectedStarEntry,
    hasResult,
    departureAirport,
    arrivalAirport,
    sidNode,
    starNode,
    selectedSIDProcedures,
    selectedSTARProcedures,
    selectedSID,
    selectedSTAR,
    selectedSIDTransition,
    selectedSTARTransition,
    origAirportDetail,
    destAirportDetail,
    parsedWeather,
    routeSegments,
    setRouteResult,
    setLoading,
    setError,
    setSelectedSID,
    setSelectedSTAR,
    setSelectedSIDTransition,
    setSelectedSTARTransition,
  }
})
