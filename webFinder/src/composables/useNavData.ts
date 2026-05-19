import { useQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, unref, type MaybeRef } from 'vue'

export interface NavDataCycle {
  cycle: string
  file_size_mb: number
  node_count: number
  edge_count: number
  airport_count: number
  procedure_count: number
}

export interface BuildProgress {
  status: 'building' | 'done' | 'error'
  step?: string
  current?: number
  total?: number
  percent?: number
  cycle?: string
  info?: NavDataCycle
  detail?: string
}

export interface ActiveBuild {
  build_id: string
  status: 'building'
  step: string
  current: number
  total: number
  percent: number
}

export function useNavData(adminKey: MaybeRef<string>) {
  const queryClient = useQueryClient()
  const uploadError = ref('')
  const key = computed(() => unref(adminKey))

  const { data: cycles, isLoading } = useQuery({
    queryKey: ['navdata', key],
    queryFn: async () => {
      const res = await fetch('/api/admin/navdata', {
        headers: { 'X-Admin-Key': key.value },
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `HTTP ${res.status}`)
      }
      const json = await res.json()
      return json.cycles as NavDataCycle[]
    },
    enabled: computed(() => !!key.value),
    refetchInterval: 10000,
  })

  const { data: activeBuilds } = useQuery({
    queryKey: ['navdata-builds', key],
    queryFn: async () => {
      const res = await fetch('/api/admin/navdata/builds', {
        headers: { 'X-Admin-Key': key.value },
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `HTTP ${res.status}`)
      }
      const json = await res.json()
      return json.builds as ActiveBuild[]
    },
    enabled: computed(() => !!key.value),
    refetchInterval: 5000,
  })

  const deleteMutation = useMutation({
    mutationFn: async (cycle: string) => {
      const res = await fetch(`/api/admin/navdata/${cycle}`, {
        method: 'DELETE',
        headers: { 'X-Admin-Key': key.value },
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `HTTP ${res.status}`)
      }
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['navdata', key.value] })
    },
  })

  const uploadMutation = useMutation({
    mutationFn: async (formData: FormData) => {
      const res = await fetch('/api/admin/navdata/upload', {
        method: 'POST',
        headers: { 'X-Admin-Key': key.value },
        body: formData,
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `HTTP ${res.status}`)
      }
      const data = await res.json()
      return data as { build_id: string; status: string; cycle: string }
    },
    onSuccess: () => {
      uploadError.value = ''
    },
    onError: (err: any) => {
      uploadError.value = err.message || 'Upload failed'
    },
  })

  function connectProgress(buildId: string, onProgress: (p: BuildProgress) => void) {
    const es = new EventSource(`/api/admin/navdata/build-progress/${buildId}?x_admin_key=${encodeURIComponent(key.value)}`)
    es.addEventListener('progress', (e) => {
      onProgress(JSON.parse(e.data))
    })
    es.addEventListener('done', (e) => {
      onProgress(JSON.parse(e.data))
      es.close()
      queryClient.invalidateQueries({ queryKey: ['navdata', key.value] })
    })
    es.addEventListener('error', (e: Event) => {
      let data: BuildProgress
      try {
        data = JSON.parse((e as MessageEvent).data)
      } catch {
        data = { status: 'error', detail: 'Build failed' }
      }
      onProgress(data)
      es.close()
    })
    es.onerror = () => {
      es.close()
    }
    return () => es.close()
  }

  return {
    cycles,
    isLoading,
    activeBuilds,
    uploadError,
    deleteCycle: deleteMutation.mutate,
    isDeleting: deleteMutation.isPending,
    uploadCycle: uploadMutation.mutate,
    uploadCycleAsync: uploadMutation.mutateAsync,
    isUploading: uploadMutation.isPending,
    connectProgress,
  }
}
