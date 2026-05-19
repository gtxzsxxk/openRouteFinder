import { useQuery } from '@tanstack/vue-query'
import { ref } from 'vue'

export function useAdmin() {
  const key = ref('')
  const enabled = ref(false)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['admin'],
    queryFn: async () => {
      const res = await fetch('/api/admin', {
        headers: { 'X-Admin-Key': key.value },
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `HTTP ${res.status}`)
      }
      return res.json()
    },
    enabled,
    refetchInterval: 5000,
  })

  function authenticate(secret: string) {
    key.value = secret
    enabled.value = true
    return refetch()
  }

  function logout() {
    enabled.value = false
    key.value = ''
  }

  return { data, isLoading, error, authenticate, logout }
}
