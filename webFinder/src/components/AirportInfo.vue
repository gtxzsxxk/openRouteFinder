<template>
  <div class="space-y-4">
    <AirportSection
      v-if="orig"
      :airport="orig"
    />
    <div v-if="orig && dest" class="border-t border-border" />
    <AirportSection
      v-if="dest"
      :airport="dest"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouteStore } from '@/stores/routeStore'
import AirportSection from './AirportSection.vue'

const store = useRouteStore()
const orig = computed(() => store.origAirportDetail)
const dest = computed(() => store.destAirportDetail)
</script>
