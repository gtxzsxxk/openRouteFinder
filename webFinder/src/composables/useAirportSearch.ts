import { useQuery } from '@tanstack/vue-query'
import type { Airport } from '@/types'

export function useAirportSearch(query: string) {
  return useQuery<Airport[]>({
    queryKey: ['airports', query],
    queryFn: async () => {
      if (!query || query.length < 2) return []
      const response = await fetch(`/api/airports?q=${encodeURIComponent(query)}`)
      if (!response.ok) throw new Error('Failed to search airports')
      const data = await response.json()
      return data.airports || []
    },
    enabled: query.length >= 2,
    staleTime: 1000 * 60 * 5,
  })
}