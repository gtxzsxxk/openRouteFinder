<template>
  <div v-if="store.routeResult?.weather" class="bg-surface border border-border rounded-xl p-4 space-y-3">
    <h4 class="text-sm font-medium text-white">天气信息</h4>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div class="bg-primary rounded-lg p-3">
        <span class="text-xs text-text-muted block mb-1">出发机场</span>
        <p class="text-sm text-text font-mono break-all">
          {{ store.routeResult.weather[0] }}
        </p>
      </div>
      <div class="bg-primary rounded-lg p-3">
        <span class="text-xs text-text-muted block mb-1">到达机场</span>
        <p class="text-sm text-text font-mono break-all">
          {{ store.routeResult.weather[1] }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouteStore } from '@/stores/routeStore'

const store = useRouteStore()
</script>