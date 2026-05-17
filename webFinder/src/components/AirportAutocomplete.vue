<template>
  <div class="relative">
    <label v-if="label" class="block text-xs font-medium text-text-secondary mb-1.5 uppercase tracking-wider">{{ label }}</label>
    <input
      v-model="inputValue"
      type="text"
      maxlength="4"
      :placeholder="placeholder"
      class="w-full h-14 px-4 bg-bg-elevated rounded-xl text-text-primary placeholder-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all duration-150 uppercase font-mono text-lg tracking-wider"
      @input="onInput"
      @keydown.down.prevent="moveDown"
      @keydown.up.prevent="moveUp"
      @keydown.enter.prevent="onEnter"
      @keydown.esc="closeDropdown"
      @blur="onBlur"
    />
    <div
      v-if="isOpen && suggestions.length > 0"
      class="absolute z-50 w-full mt-2 bg-bg-elevated border border-border rounded-xl shadow-lg max-h-60 overflow-y-auto"
    >
      <div
        v-for="(airport, index) in suggestions"
        :key="airport.icao"
        :class="[
          'px-4 py-3 cursor-pointer text-sm transition-colors',
          index === highlightedIndex ? 'bg-accent text-white' : 'text-text-primary hover:bg-bg-surface',
        ]"
        @mousedown.prevent="selectAirport(airport)"
        @mouseenter="highlightedIndex = index"
      >
        <span class="font-mono font-medium">{{ airport.icao }}</span>
        <span class="text-text-secondary ml-2">{{ airport.name }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Airport } from '@/types'

const props = defineProps<{
  label?: string
  placeholder?: string
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  select: [airport: Airport]
}>()

const inputValue = ref(props.modelValue)
const suggestions = ref<Airport[]>([])
const isOpen = ref(false)
const highlightedIndex = ref(-1)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.modelValue, (val) => {
  inputValue.value = val
})

watch(inputValue, (val) => {
  emit('update:modelValue', val.toUpperCase())
})

async function onInput() {
  const val = inputValue.value.trim().toUpperCase()
  if (val.length < 2) {
    suggestions.value = []
    isOpen.value = false
    return
  }

  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(async () => {
    try {
      const response = await fetch(`/api/airports?q=${encodeURIComponent(val)}`)
      if (!response.ok) {
        suggestions.value = []
        return
      }
      const data = await response.json()
      suggestions.value = data.airports || []
      isOpen.value = suggestions.value.length > 0
      highlightedIndex.value = -1
    } catch {
      suggestions.value = []
      isOpen.value = false
    }
  }, 500)
}

function moveDown() {
  if (!isOpen.value) return
  highlightedIndex.value = (highlightedIndex.value + 1) % suggestions.value.length
}

function moveUp() {
  if (!isOpen.value) return
  highlightedIndex.value = (highlightedIndex.value - 1 + suggestions.value.length) % suggestions.value.length
}

function onEnter() {
  if (!isOpen.value || highlightedIndex.value < 0) return
  selectAirport(suggestions.value[highlightedIndex.value])
}

function selectAirport(airport: Airport) {
  inputValue.value = airport.icao
  emit('update:modelValue', airport.icao)
  emit('select', airport)
  suggestions.value = []
  isOpen.value = false
  highlightedIndex.value = -1
}

function closeDropdown() {
  isOpen.value = false
}

function onBlur() {
  setTimeout(() => {
    isOpen.value = false
  }, 150)
}
</script>
