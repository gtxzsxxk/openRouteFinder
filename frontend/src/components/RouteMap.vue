<template>
  <div class="bg-surface border border-border rounded-xl overflow-hidden">
    <div class="px-4 py-3 border-b border-border flex items-center justify-between">
      <h3 class="font-medium text-white">航路地图</h3>
      <div class="flex gap-3 text-xs">
        <span class="flex items-center gap-1">
          <span class="w-3 h-0.5 bg-highlight rounded"></span>
          航路
        </span>
        <span class="flex items-center gap-1">
          <span class="w-3 h-0.5 bg-emerald-500 rounded border-dashed"></span>
          SID
        </span>
        <span class="flex items-center gap-1">
          <span class="w-3 h-0.5 bg-amber-500 rounded border-dashed"></span>
          STAR
        </span>
      </div>
    </div>
    <div ref="mapContainer" class="w-full h-[500px]"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouteStore } from '@/stores/routeStore'
import { useMap } from '@/composables/useMap'

const store = useRouteStore()
const { routeResult, selectedSID, selectedSTAR } = storeToRefs(store)
const mapContainer = ref<HTMLElement | null>(null)

const { initMap } = useMap(mapContainer, routeResult, selectedSID, selectedSTAR)

onMounted(() => {
  initMap()
})
</script>