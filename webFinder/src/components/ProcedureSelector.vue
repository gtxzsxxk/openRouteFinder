<template>
  <div>
    <label class="block text-xs font-medium text-text-secondary mb-2 uppercase tracking-wider">{{ label }}</label>
    <div v-if="isLoading" class="text-xs text-text-secondary py-2">{{ $t('common.loading') }}</div>
    <div v-else-if="error" class="text-xs text-red-500 py-2">{{ $t('common.loadFailed') }}</div>
    <div v-else-if="!hasLoaded" class="text-xs text-text-secondary py-2 cursor-pointer hover:text-text-primary transition-colors" @click="loadProcedures">
      <span class="mr-1">&#9660;</span> {{ type === 'sid' ? $t('search.expandSID') : $t('search.expandSTAR') }}
    </div>
    <div v-else-if="options.length === 0" class="text-xs text-text-secondary py-2">
      {{ type === 'sid' ? $t('search.noSID') : $t('search.noSTAR') }}
    </div>
    <div v-else class="space-y-2">
      <select
        v-model="selectedValue"
        class="w-full h-10 px-3 bg-bg-page border border-border rounded-lg text-text-primary focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent text-sm"
      >
        <option value="">&#128260; {{ $t('common.autoSelect') }}</option>
        <option v-for="opt in options" :key="opt.name" :value="opt.name">
          {{ opt.name }}（{{ opt.procedures.join('、') }}）
        </option>
      </select>

      <div v-if="selectedOption" class="text-xs text-text-secondary space-y-1 pt-1">
        <p>{{ $t('common.procedure') }}: {{ selectedOption.procedures.join('、') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import type { ProcedureOption } from '@/types'

const props = defineProps<{
  icao: string
  type: 'sid' | 'star'
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const label = computed(() => props.type === 'sid' ? t('search.sid') : t('search.star'))
const options = ref<ProcedureOption[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const hasLoaded = ref(false)

const selectedValue = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const selectedOption = computed(() => {
  if (!selectedValue.value) return null
  return options.value.find(o => o.name === selectedValue.value) || null
})

async function loadProcedures() {
  if (!props.icao) {
    options.value = []
    hasLoaded.value = true
    return
  }

  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`/api/airports/${encodeURIComponent(props.icao)}/procedures`)
    if (!response.ok) {
      if (response.status === 404) {
        options.value = []
      } else {
        error.value = t('common.loadFailed')
      }
      hasLoaded.value = true
      return
    }
    const data = await response.json()
    if (props.type === 'sid') {
      options.value = data.sid?.exits || []
    } else {
      options.value = data.star?.entries || []
    }
    hasLoaded.value = true
    // Defensive: if current selection is not in new options, reset to auto
    if (selectedValue.value && !options.value.some(o => o.name === selectedValue.value)) {
      selectedValue.value = ''
    }
  } catch {
    error.value = t('common.loadFailed')
    hasLoaded.value = true
  } finally {
    isLoading.value = false
  }
}

watch(() => props.icao, (newIcao, oldIcao) => {
  if (newIcao !== oldIcao) {
    selectedValue.value = ''
    options.value = []
    hasLoaded.value = false
    error.value = null
  }
})
</script>
