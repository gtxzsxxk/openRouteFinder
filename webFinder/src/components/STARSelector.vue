<template>
  <div v-if="store.selectedSTARProcedures.length > 0" class="bg-surface border border-border rounded-xl p-4">
    <label class="block text-sm font-medium text-text-muted mb-2">进场程序 (STAR)</label>
    <div class="space-y-2">
      <select
        v-model="selectedIndex"
        class="w-full px-3 py-2 bg-primary border border-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-highlight focus:border-transparent"
      >
        <option
          v-for="(proc, i) in store.selectedSTARProcedures"
          :key="i"
          :value="i"
        >
          {{ proc[0] }} - 跑道 {{ proc[1] }}
        </option>
      </select>

      <!-- Transition selector -->
      <select
        v-if="store.selectedSTAR && store.selectedSTAR.transitions.length > 0"
        v-model="selectedTransitionIndex"
        class="w-full px-3 py-2 bg-primary border border-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-highlight focus:border-transparent"
      >
        <option :value="-1">无过渡点</option>
        <option
          v-for="(trans, i) in store.selectedSTAR.transitions"
          :key="i"
          :value="i"
        >
          过渡: {{ trans.name }}
        </option>
      </select>

      <div v-if="store.selectedSTAR" class="text-xs text-text-muted space-y-1">
        <p>程序: {{ store.selectedSTAR.name }}</p>
        <p>跑道: {{ store.selectedSTAR.runway }}</p>
        <p>航点: {{ store.selectedSTAR.points.length }} 个</p>
        <p v-if="store.selectedSTARTransition">
          过渡点: {{ store.selectedSTARTransition.name }} ({{ store.selectedSTARTransition.points.length }} 个航点)
        </p>
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

const selectedTransitionIndex = computed({
  get: () => store.selectedSTARTransitionIndex,
  set: (val) => store.setSelectedSTARTransition(val),
})
</script>
