<template>
  <div class="relative w-full h-full min-h-[320px]">
    <div ref="mapContainer" class="w-full h-full" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouteStore } from '@/stores/routeStore'
import { useMap } from '@/composables/useMap'

const store = useRouteStore()
const { routeResult, selectedSID, selectedSTAR, selectedSIDTransition, selectedSTARTransition } = storeToRefs(store)
const mapContainer = ref<HTMLElement | null>(null)

const { initMap } = useMap(mapContainer, routeResult, selectedSID, selectedSTAR, selectedSIDTransition, selectedSTARTransition)

onMounted(() => {
  initMap()
})
</script>
