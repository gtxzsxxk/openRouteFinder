<template>
  <div class="space-y-5">
    <!-- Airport Selection — clean, no card wrapper -->
    <div class="flex items-center gap-3">
      <div class="flex-1 min-w-0">
        <label class="block text-xs font-medium text-text-secondary mb-2 uppercase tracking-wider">{{ $t('search.departure') }}</label>
        <AirportAutocomplete
          v-model="departure"
          placeholder="ZBAA"
          @select="onDepartureSelect"
        />
      </div>

      <button
        @click="swapAirports"
        :class="[
          'self-end h-14 w-14 flex items-center justify-center bg-bg-elevated rounded-xl border border-border text-text-secondary hover:text-text-primary hover:bg-bg-surface transition-all duration-200 shrink-0',
          isSwapping ? 'rotate-180' : '',
        ]"
        :title="$t('common.swap')"
      >
        <ArrowLeftRight class="w-5 h-5" />
      </button>

      <div class="flex-1 min-w-0">
        <label class="block text-xs font-medium text-text-secondary mb-2 uppercase tracking-wider">{{ $t('search.arrival') }}</label>
        <AirportAutocomplete
          v-model="arrival"
          placeholder="ZJSY"
          @select="onArrivalSelect"
        />
      </div>
    </div>

    <!-- Procedure Selection — compact, no card wrapper -->
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

    <!-- Search Button — prominent, standalone, centered capsule -->
    <div class="pt-2">
      <button
        @click="onSearchClick"
        :disabled="!canSubmit || store.isLoading"
        class="w-full md:w-auto md:min-w-[280px] h-14 mx-auto block bg-accent hover:bg-accent-hover disabled:bg-bg-elevated disabled:text-text-tertiary disabled:cursor-not-allowed disabled:shadow-none text-white font-semibold rounded-full transition-all duration-200 flex items-center justify-center gap-2.5 shadow-md hover:shadow-lg active:scale-[0.98]"
      >
        <Loader2 v-if="store.isLoading" class="w-5 h-5 animate-spin" />
        <Search v-else class="w-5 h-5" />
        <span class="text-base">{{ store.isLoading ? $t('common.searching') : $t('common.search') }}</span>
      </button>
    </div>

    <!-- Captcha Modal -->
    <CaptchaModal
      v-model="showCaptchaModal"
      @confirm="onCaptchaConfirm"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouteStore } from '@/stores/routeStore'
import AirportAutocomplete from './AirportAutocomplete.vue'
import ProcedureSelector from './ProcedureSelector.vue'
import CaptchaModal from './CaptchaModal.vue'
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
const isSwapping = ref(false)
const showCaptchaModal = ref(false)

const showProcedureSelectors = computed(() => {
  return departure.value.length === 4 && arrival.value.length === 4
})

const canSubmit = computed(() => {
  return departure.value.length === 4 && arrival.value.length === 4
})

function onDepartureSelect(airport: Airport) {
  departure.value = airport.icao
  sidExit.value = ''
}

function onArrivalSelect(airport: Airport) {
  arrival.value = airport.icao
  starEntry.value = ''
}

function swapAirports() {
  isSwapping.value = true
  const temp = departure.value
  departure.value = arrival.value
  arrival.value = temp
  const tempSid = sidExit.value
  sidExit.value = starEntry.value
  starEntry.value = tempSid
  setTimeout(() => {
    isSwapping.value = false
  }, 300)
}

function onSearchClick() {
  if (!canSubmit.value) return
  showCaptchaModal.value = true
}

function onCaptchaConfirm(code: string, token: string) {
  emit('search', {
    orig: departure.value,
    dest: arrival.value,
    validCode: code,
    validToken: token,
    sidExit: sidExit.value,
    starEntry: starEntry.value,
  })
}
</script>
