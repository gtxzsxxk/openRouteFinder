<template>
  <div class="space-y-6">
    <!-- Search Form -->
    <SearchForm @search="handleSearch" />

    <!-- Loading State -->
    <div v-if="store.isLoading" class="flex items-center justify-center py-12">
      <div class="flex items-center gap-3 text-text-muted">
        <svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span>正在计算航路...</span>
        <span class="font-mono text-sm">{{ queryTime.toFixed(2) }}s</span>
      </div>
    </div>

    <!-- Error State -->
    <div v-else-if="store.error" class="bg-surface border border-border rounded-xl p-6 text-center">
      <p class="text-highlight">{{ store.error }}</p>
      <button @click="store.setError(null)" class="mt-3 text-sm text-text-muted hover:text-white transition-colors">
        清除错误
      </button>
    </div>

    <!-- Result -->
    <div v-if="store.hasResult && store.routeResult" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Left Column -->
      <div class="space-y-4">
        <RouteMap />
        <AirportInfo />
      </div>

      <!-- Right Column -->
      <div class="space-y-4">
        <RouteResult />
        <div class="flex gap-4">
          <SIDSelector class="flex-1" />
          <STARSelector class="flex-1" />
        </div>
        <WeatherCard />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouteStore } from '@/stores/routeStore'
import { useRouteQuery } from '@/composables/useRouteQuery'
import SearchForm from '@/components/SearchForm.vue'
import RouteMap from '@/components/RouteMap.vue'
import RouteResult from '@/components/RouteResult.vue'
import SIDSelector from '@/components/SIDSelector.vue'
import STARSelector from '@/components/STARSelector.vue'
import WeatherCard from '@/components/WeatherCard.vue'
import AirportInfo from '@/components/AirportInfo.vue'

const store = useRouteStore()
const { mutate: searchRoute } = useRouteQuery()

const queryTime = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

function handleSearch(params: { orig: string; dest: string; validCode: string; validToken: string }) {
  store.setLoading(true)
  store.setError(null)
  queryTime.value = 0

  timer = setInterval(() => {
    queryTime.value += 0.01
  }, 10)

  searchRoute(params, {
    onSuccess: (data) => {
      store.setRouteResult(data)
      store.setLoading(false)
      if (timer) clearInterval(timer)
    },
    onError: (err) => {
      store.setError(err.message)
      store.setLoading(false)
      if (timer) clearInterval(timer)
    },
  })
}

watch(() => store.isLoading, (loading) => {
  if (!loading && timer) {
    clearInterval(timer)
    timer = null
  }
})
</script>