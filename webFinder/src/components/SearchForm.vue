<template>
  <div class="space-y-4">
    <!-- Airport Selection Row -->
    <div class="bg-bg-surface border border-border rounded-xl p-6">
      <div class="flex items-center gap-3">
        <div class="flex-1">
          <AirportAutocomplete
            v-model="departure"
            label="出发机场"
            placeholder="ZBAA"
            @select="onDepartureSelect"
          />
        </div>

        <button
          @click="swapAirports"
          :class="[
            'h-14 w-14 flex items-center justify-center bg-bg-surface rounded-xl border border-border text-text-secondary hover:text-text-primary hover:bg-bg-elevated transition-all duration-150 shrink-0 mt-5',
            isSwapping ? 'rotate-180' : '',
          ]"
        >
          <ArrowLeftRight class="w-5 h-5" />
        </button>

        <div class="flex-1">
          <AirportAutocomplete
            v-model="arrival"
            label="到达机场"
            placeholder="ZJSY"
            @select="onArrivalSelect"
          />
        </div>
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
    <div class="bg-bg-surface border border-border rounded-xl p-6">
      <div class="grid grid-cols-1 md:grid-cols-12 gap-4 items-end">
        <div class="md:col-span-4">
          <label class="block text-xs font-medium text-text-secondary mb-1.5 uppercase tracking-wider">验证码</label>
          <div class="h-14 bg-bg-elevated border border-border rounded-xl flex items-center justify-center overflow-hidden cursor-pointer" @click="refreshValidCode">
            <img v-if="validCodeImage" :src="validCodeImage" alt="valid code" class="h-full w-auto" />
            <span v-else class="text-xs text-text-tertiary">点击加载</span>
          </div>
        </div>

        <div class="md:col-span-4">
          <label class="block text-xs font-medium text-text-secondary mb-1.5 uppercase tracking-wider">输入验证码</label>
          <input
            v-model="validCodeInput"
            type="text"
            maxlength="4"
            placeholder="****"
            class="w-full h-14 px-4 bg-bg-elevated rounded-xl text-text-primary placeholder-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all duration-150 uppercase font-mono text-lg tracking-wider text-center"
          />
        </div>

        <div class="md:col-span-4">
          <button
            @click="handleSubmit"
            :disabled="!canSubmit || store.isLoading"
            class="flex-1 h-14 bg-accent hover:bg-accent-hover disabled:bg-bg-surface disabled:text-text-tertiary disabled:cursor-not-allowed text-white font-medium rounded-xl transition-all duration-150 flex items-center justify-center gap-2"
          >
            <Loader2 v-if="store.isLoading" class="w-5 h-5 animate-spin" />
            <Search v-else class="w-5 h-5" />
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
import { ArrowLeftRight, Search, Loader2 } from '@lucide/vue'

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
const isSwapping = ref(false)

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

function swapAirports() {
  isSwapping.value = true
  const temp = departure.value
  departure.value = arrival.value
  arrival.value = temp
  setTimeout(() => {
    isSwapping.value = false
  }, 300)
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
