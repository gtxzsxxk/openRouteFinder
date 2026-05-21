import { useQuery } from '@tanstack/vue-query'
import { ref, computed } from 'vue'

export interface CycleInfo {
  cycle: string
}

export interface CyclesData {
  cycles: CycleInfo[]
  default: string | null
  disableCaptcha: boolean
}

export function useCycles() {
  const enabled = ref(true)

  const { data, isLoading, error } = useQuery({
    queryKey: ['cycles'],
    queryFn: async () => {
      const res = await fetch('/api/cycles')
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }
      const json = await res.json()
      return {
        cycles: (json.cycles || []) as CycleInfo[],
        default: json.default as string | null,
        disableCaptcha: json.disableCaptcha as boolean,
      } as CyclesData
    },
    enabled,
    refetchInterval: 30000,
    staleTime: 10000,
  })

  const cycleList = computed(() => data.value?.cycles || [])
  const defaultCycle = computed(() => data.value?.default || '')
  const hasMultiple = computed(() => cycleList.value.length > 1)
  const hasAny = computed(() => cycleList.value.length > 0)
  const disableCaptcha = computed(() => data.value?.disableCaptcha || false)

  return {
    cycleList,
    defaultCycle,
    hasMultiple,
    hasAny,
    disableCaptcha,
    isLoading,
    error,
  }
}
