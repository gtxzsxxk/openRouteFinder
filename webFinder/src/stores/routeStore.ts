import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { RouteResult, ProcedureTuple } from '@/types'

export interface ProcedureData {
  name: string
  runway: string
  points: { name: string; lat: number; lon: number }[]
}

export const useRouteStore = defineStore('route', () => {
  const routeResult = ref<RouteResult | null>(null)
  const selectedSIDIndex = ref(0)
  const selectedSTARIndex = ref(0)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

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
    if (!routeResult.value || !sidNode.value) return [] as ProcedureTuple[]
    const key = sidNode.value.name
    return routeResult.value.SID[key] || []
  })

  const selectedSTARProcedures = computed(() => {
    if (!routeResult.value || !starNode.value) return [] as ProcedureTuple[]
    const key = starNode.value.name
    return routeResult.value.STAR[key] || []
  })

  function toProcedureData(proc: ProcedureTuple | null): ProcedureData | null {
    if (!proc) return null
    return {
      name: proc[0],
      runway: proc[1],
      points: proc[2].map(p => ({ name: p[0], lat: p[1], lon: p[2] })),
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

  function setRouteResult(result: RouteResult | null) {
    routeResult.value = result
    selectedSIDIndex.value = 0
    selectedSTARIndex.value = 0
    error.value = null
  }

  function setLoading(loading: boolean) {
    isLoading.value = loading
  }

  function setError(err: string | null) {
    error.value = err
  }

  function setSelectedSID(index: number) {
    selectedSIDIndex.value = index
  }

  function setSelectedSTAR(index: number) {
    selectedSTARIndex.value = index
  }

  return {
    routeResult,
    selectedSIDIndex,
    selectedSTARIndex,
    isLoading,
    error,
    hasResult,
    departureAirport,
    arrivalAirport,
    sidNode,
    starNode,
    selectedSIDProcedures,
    selectedSTARProcedures,
    selectedSID,
    selectedSTAR,
    setRouteResult,
    setLoading,
    setError,
    setSelectedSID,
    setSelectedSTAR,
  }
})
