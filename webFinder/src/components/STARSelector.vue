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
        {{ proc[0] }} - 跑道 {{ proc[1] }}
      </option>
    </select>

    <div v-if="store.selectedSTAR" class="text-xs text-text-secondary space-y-1">
      <div class="flex justify-between">
        <span>程序</span>
        <span class="font-mono text-text-primary">{{ store.selectedSTAR.name }}</span>
      </div>
      <div class="flex justify-between">
        <span>跑道</span>
        <span class="font-mono text-text-primary">{{ store.selectedSTAR.runway }}</span>
      </div>
      <div class="flex justify-between">
        <span>航点</span>
        <span class="font-mono text-text-primary">{{ store.selectedSTAR.points.length }} 个</span>
      </div>
      <div v-if="store.selectedSTARTransition" class="flex justify-between pt-2 border-t border-border">
        <span>过渡点</span>
        <span class="font-mono text-text-primary">{{ store.selectedSTARTransition.name }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouteStore } from '@/stores/routeStore'

const store = useRouteStore()

const selectedIndex = computed({
  get: () => store.selectedSTARIndex,
  set: (val) => store.setSelectedSTAR(val),
})
</script>
