<template>
  <div class="space-y-4">
    <!-- Airport Selection Row -->
    <div class="bg-surface border border-border rounded-xl p-6">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <AirportAutocomplete
          v-model="departure"
          label="出发机场"
          placeholder="ZBAA"
          @select="onDepartureSelect"
        />
        <AirportAutocomplete
          v-model="arrival"
          label="到达机场"
          placeholder="ZJSY"
          @select="onArrivalSelect"
        />
      </div>
    </div>

    <!-- Procedure Selection -->
    <div v-if="showProcedureSelectors" class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <ProcedureSelector
        :icao="departure"
        type="sid"
        v-model="sidExit"
      />
      <ProcedureSelector
        :icao="arrival"
        type="star"
        v-model="starEntry"
      />
    </div>

    <!-- Valid Code and Submit -->
    <div class="bg-surface border border-border rounded-xl p-6">
      <div class="grid grid-cols-1 md:grid-cols-12 gap-4 items-end">
        <div class="md:col-span-4">
          <label class="block text-sm font-medium text-text-muted mb-1.5">验证码</label>
          <div class="h-[38px] bg-primary border border-border rounded-lg flex items-center justify-center overflow-hidden cursor-pointer" @click="refreshValidCode">
            <img v-if="validCodeImage" :src="validCodeImage" alt="valid code" class="h-full w-auto" />
            <span v-else class="text-xs text-text-muted">点击加载</span>
          </div>
        </div>

        <div class="md:col-span-4">
          <label class="block text-sm font-medium text-text-muted mb-1.5">输入验证码</label>
          <input
            v-model="validCodeInput"
            type="text"
            maxlength="4"
            placeholder="****"
            class="w-full px-3 py-2 bg-primary border border-border rounded-lg text-white placeholder-text-muted focus:outline-none focus:ring-2 focus:ring-highlight focus:border-transparent transition-all"
          />
        </div>

        <div class="md:col-span-4">
          <button
            @click="handleSubmit"
            :disabled="!canSubmit || store.isLoading"
            class="w-full px-4 py-2 bg-highlight hover:bg-red-600 disabled:bg-surface-light disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors"
          >
            {{ store.isLoading ? '查询中...' : '查询航路' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouteStore } from '@/stores/routeStore'
import AirportAutocomplete from './AirportAutocomplete.vue'
import ProcedureSelector from './ProcedureSelector.vue'
import type { Airport } from '@/types'

const emit = defineEmits<{
  search: [params: { orig: string; dest: string; validCode: string; validToken: string; sidExit: string; starEntry: string }]
}>()

const store = useRouteStore()
const departure = ref('')
const arrival = ref('')
const sidExit = ref('')
const starEntry = ref('')
const validCodeInput = ref('')
const validCodeImage = ref('')
const validToken = ref('')

const showProcedureSelectors = computed(() => {
  return departure.value.length === 4 && arrival.value.length === 4
})

const canSubmit = computed(() => {
  return departure.value.length === 4 &&
    arrival.value.length === 4 &&
    validCodeInput.value.length === 4
})

function onDepartureSelect(airport: Airport) {
  departure.value = airport.icao
}

function onArrivalSelect(airport: Airport) {
  arrival.value = airport.icao
}

async function fetchValidCode() {
  try {
    const response = await fetch('/api/validcode')
    const data = await response.json()
    validCodeImage.value = data.image
    validToken.value = data.token
  } catch (err) {
    console.error('Failed to fetch valid code:', err)
  }
}

function refreshValidCode() {
  fetchValidCode()
}

function handleSubmit() {
  if (!canSubmit.value) return
  emit('search', {
    orig: departure.value,
    dest: arrival.value,
    validCode: validCodeInput.value,
    validToken: validToken.value,
    sidExit: sidExit.value,
    starEntry: starEntry.value,
  })
  validCodeInput.value = ''
  fetchValidCode()
}

onMounted(() => {
  fetchValidCode()
})
</script>
