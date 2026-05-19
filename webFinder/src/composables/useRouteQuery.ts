import { useMutation } from '@tanstack/vue-query'
import type { RouteResult } from '@/types'

interface RouteQueryParams {
  orig: string
  dest: string
  validCode: string
  validToken: string
  sidExit: string
  starEntry: string
  cycle: string
}

export function useRouteQuery() {
  return useMutation<RouteResult, Error, RouteQueryParams>({
    mutationFn: async (params) => {
      const response = await fetch('/api/route', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(params),
      })

      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || `HTTP ${response.status}`)
      }

      return response.json()
    },
  })
}
