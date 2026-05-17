<template>
  <div class="relative" ref="containerRef">
    <label class="block text-sm font-medium text-text-muted mb-1.5">{{ label }}</label>
    <input
      v-model="inputValue"
      type="text"
      maxlength="4"
      :placeholder="placeholder"
      class="w-full px-3 py-2 bg-primary border border-border rounded-lg text-white placeholder-text-muted focus:outline-none focus:ring-2 focus:ring-highlight focus:border-transparent transition-all uppercase"
      @input="onInput"
      @keydown.down.prevent="moveDown"
      @keydown.up.prevent="moveUp"
      @keydown.enter.prevent="onEnter"
      @keydown.esc="closeDropdown"
      @blur="onBlur"
    />
    <div
      v-if="isOpen && suggestions.length > 0"
      class="absolute z-50 w-full mt-1 bg-surface border border-border rounded-lg shadow-lg max-h-60 overflow-y-auto"
    >
      <div
        v-for="(airport, index) in suggestions"
        :key="airport.icao"
        :class="[
          'px-3 py-2 cursor-pointer text-sm transition-colors',
          index === highlightedIndex ? 'bg-highlight text-white' : 'text-text hover:bg-surface-light',
        ]"
        @mousedown.prevent="selectAirport(airport)"
        @mouseenter="highlightedIndex = index"
      >
        <span class="font-mono font-medium">{{ airport.icao }}</span>
        <span class="text-text-muted ml-2">{{ airport.name }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Airport } from '@/types'

const props = defineProps<{
  label: string
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
const containerRef = ref<HTMLElement | null>(null)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.modelValue, (val) => {
  inputValue.value = val
})

watch(inputValue, (val) => {
  emit('update:modelValue', val.toUpperCase())
})

async function onInput() {
  const val = inputValue.value.trim().toUpperCase()
  if (val.length < 1) {
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
  }, 300)
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
