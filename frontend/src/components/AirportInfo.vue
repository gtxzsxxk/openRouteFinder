<template>
  <div v-if="store.departureAirport && store.arrivalAirport" class="bg-surface border border-border rounded-xl p-4 space-y-3">
    <h4 class="text-sm font-medium text-white">机场信息</h4>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div class="bg-primary rounded-lg p-3 space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-highlight font-mono font-bold text-lg">{{ store.departureAirport.name }}</span>
          <span v-if="store.routeResult?.airportName?.[0]" class="text-xs text-text-muted">
            {{ store.routeResult.airportName[0] }}
          </span>
        </div>
        <div class="text-xs text-text-muted space-y-1">
          <p>纬度: {{ store.departureAirport.lat.toFixed(4) }}</p>
          <p>经度: {{ store.departureAirport.lon.toFixed(4) }}</p>
        </div>
      </div>
      <div class="bg-primary rounded-lg p-3 space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-highlight font-mono font-bold text-lg">{{ store.arrivalAirport.name }}</span>
          <span v-if="store.routeResult?.airportName?.[1]" class="text-xs text-text-muted">
            {{ store.routeResult.airportName[1] }}
          </span>
        </div>
        <div class="text-xs text-text-muted space-y-1">
          <p>纬度: {{ store.arrivalAirport.lat.toFixed(4) }}</p>
          <p>经度: {{ store.arrivalAirport.lon.toFixed(4) }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouteStore } from '@/stores/routeStore'

const store = useRouteStore()
</script>