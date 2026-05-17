<template>
  <div class="space-y-8">
    <!-- Search Section -->
    <SearchForm @search="handleSearch" />

    <!-- Loading State -->
    <div v-if="store.isLoading" class="space-y-8">
      <div class="h-16 bg-bg-surface rounded-2xl animate-pulse" />
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div class="h-80 bg-bg-surface rounded-2xl animate-pulse md:col-span-2" />
        <div class="h-80 bg-bg-surface rounded-2xl animate-pulse" />
        <div class="h-40 bg-bg-surface rounded-2xl animate-pulse" />
        <div class="h-40 bg-bg-surface rounded-2xl animate-pulse" />
        <div class="h-40 bg-bg-surface rounded-2xl animate-pulse" />
      </div>
    </div>

    <!-- Error State -->
    <div
      v-else-if="store.error"
      class="bg-error/10 border border-error/20 rounded-xl p-4 flex items-center justify-between"
    >
      <p class="text-error text-sm">{{ store.error }}</p>
      <button
        @click="store.setError(null)"
        class="text-error/70 hover:text-error transition-colors"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <!-- Result State -->
    <div v-if="store.hasResult && store.routeResult" class="space-y-8">
      <!-- Route Hero -->
      <RouteHero
        :route="store.routeResult.route"
        :distance="store.routeResult.distance"
        :totalTime="store.routeResult.total_time"
        :dataVersion="store.routeResult.data_version"
      />

      <!-- Bento Grid -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <!-- Map Cell -->
        <BentoCell class="md:col-span-2 lg:col-span-2 p-0 overflow-hidden animate-fade-in-up stagger-1" :padding="false">
          <RouteMap />
        </BentoCell>

        <!-- Procedures Cell (SID + STAR merged) -->
        <BentoCell
          v-if="store.selectedSIDProcedures.length > 0 || store.selectedSTARProcedures.length > 0"
          title="进离场程序"
          class="md:col-span-2 lg:col-span-1 animate-fade-in-up stagger-2"
        >
          <div class="space-y-5">
            <!-- SID Section -->
            <div v-if="store.selectedSIDProcedures.length > 0">
              <div class="text-xs font-medium text-text-secondary mb-2 uppercase tracking-wider">离场 (SID)</div>
              <SIDSelector />
            </div>

            <!-- Divider between SID and STAR -->
            <div v-if="store.selectedSIDProcedures.length > 0 && store.selectedSTARProcedures.length > 0" class="border-t border-border" />

            <!-- STAR Section -->
            <div v-if="store.selectedSTARProcedures.length > 0">
              <div class="text-xs font-medium text-text-secondary mb-2 uppercase tracking-wider">进场 (STAR)</div>
              <STARSelector />
            </div>
          </div>
        </BentoCell>

        <!-- Airport Info Cell -->
        <BentoCell title="机场信息" class="animate-fade-in-up stagger-3">
          <AirportInfo />
        </BentoCell>

        <!-- Weather Cell -->
        <BentoCell v-if="store.parsedWeather" title="天气" class="animate-fade-in-up stagger-4">
          <WeatherCard />
        </BentoCell>

        <!-- Waypoints Cell -->
        <BentoCell title="航点" class="animate-fade-in-up stagger-5">
          <div class="max-h-80 overflow-y-auto space-y-0">
            <div
              v-for="(node, i) in store.routeResult.nodes"
              :key="i"
              class="flex items-center justify-between py-4 border-b border-border last:border-0"
            >
              <div class="flex items-center gap-3">
                <div
                  class="w-2 h-2 rounded-full"
                  :class="i === 0 || i === store.routeResult.nodes.length - 1 ? 'bg-accent' : 'bg-route-line'"
                />
                <span
                  class="font-mono text-sm font-medium"
                  :class="i === 0 || i === store.routeResult.nodes.length - 1 ? 'text-accent' : 'text-text-primary'"
                >
                  {{ node.name }}
                </span>
              </div>
              <div class="text-xs text-text-secondary font-mono">
                {{ node.lat.toFixed(4) }}, {{ node.lon.toFixed(4) }}
              </div>
            </div>
          </div>
        </BentoCell>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { X } from '@lucide/vue'
import { useRouteStore } from '@/stores/routeStore'
import { useRouteQuery } from '@/composables/useRouteQuery'
import SearchForm from '@/components/SearchForm.vue'
import RouteMap from '@/components/RouteMap.vue'
import RouteHero from '@/components/RouteHero.vue'
import BentoCell from '@/components/BentoCell.vue'
import SIDSelector from '@/components/SIDSelector.vue'
import STARSelector from '@/components/STARSelector.vue'
import AirportInfo from '@/components/AirportInfo.vue'
import WeatherCard from '@/components/WeatherCard.vue'

const store = useRouteStore()
const { mutate: searchRoute } = useRouteQuery()

const queryTime = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

function handleSearch(params: { orig: string; dest: string; validCode: string; validToken: string; sidExit: string; starEntry: string }) {
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

<style scoped>
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-fade-in-up {
  animation: fadeInUp 0.4s ease-out forwards;
  opacity: 0;
}

.stagger-1 { animation-delay: 80ms; }
.stagger-2 { animation-delay: 160ms; }
.stagger-3 { animation-delay: 240ms; }
.stagger-4 { animation-delay: 320ms; }
.stagger-5 { animation-delay: 400ms; }
</style>
