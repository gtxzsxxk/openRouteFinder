<template>
  <div v-if="store.selectedSTARProcedures.length > 0" class="space-y-3">
    <select
      v-model="selectedIndex"
      class="w-full h-10 px-3 bg-bg-page border border-border rounded-lg text-text-primary
             focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent
             text-sm"
    >
      <option
        v-for="(proc, i) in store.selectedSTARProcedures"
        :key="i"
        :value="i"
      >
        {{ proc[0] }} - {{ $t('airport.runway') }} {{ proc[1] }}
      </option>
    </select>

    <div v-if="store.selectedSTAR" class="text-xs text-text-secondary space-y-1">
      <div class="flex justify-between">
        <span>{{ $t('airport.program') }}</span>
        <span class="font-mono text-text-primary">{{ store.selectedSTAR.name }}</span>
      </div>
      <div class="flex justify-between">
        <span>{{ $t('airport.runway') }}</span>
        <span class="font-mono text-text-primary">{{ store.selectedSTAR.runway }}</span>
      </div>
      <div class="flex justify-between">
        <span>{{ $t('airport.waypoints') }}</span>
        <span class="font-mono text-text-primary">{{ $t('common.waypointCount', { count: store.selectedSTAR.points.length }) }}</span>
      </div>
      <div v-if="store.selectedSTARTransition" class="flex justify-between pt-2 border-t border-border">
        <span>{{ $t('airport.transition') }}</span>
        <span class="font-mono text-text-primary">{{ store.selectedSTARTransition.name }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRouteStore } from '@/stores/routeStore'

const store = useRouteStore()

const selectedIndex = computed({
  get: () => store.selectedSTARIndex,
  set: (val) => store.setSelectedSTAR(val),
})

// Defensive: reset index if it goes out of bounds after route changes
watch(() => store.selectedSTARProcedures.length, (len) => {
  if (len > 0 && store.selectedSTARIndex >= len) {
    store.setSelectedSTAR(0)
  }
})
</script>
