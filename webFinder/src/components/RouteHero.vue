<template>
  <div v-if="route" class="py-6 md:py-8">
    <!-- Route string -->
    <div
      class="font-mono text-2xl md:text-4xl font-medium text-text-primary tracking-tight leading-tight"
      style="word-break: keep-all; overflow-wrap: anywhere;"
    >
      {{ route }}
    </div>

    <!-- Copy button + metadata row -->
    <div class="mt-4 flex items-center gap-3 flex-wrap">
      <button
        @click="copy(route)"
        class="shrink-0 w-9 h-9 flex items-center justify-center bg-bg-elevated hover:bg-bg-surface
               rounded-full border border-border text-text-secondary hover:text-text-primary
               transition-all duration-150 active:scale-95"
        :title="copied ? '已复制' : '复制航线'"
      >
        <Check v-if="copied" class="w-4 h-4 text-success" />
        <Copy v-else class="w-4 h-4" />
      </button>

      <div class="h-4 w-px bg-border shrink-0" />

      <div class="flex items-center gap-2 text-sm text-text-secondary flex-wrap">
        <span>{{ distance }}</span>
        <span class="text-border">·</span>
        <span>{{ totalTime }}s</span>
        <span class="text-border">·</span>
        <span class="text-text-tertiary">{{ dataVersion }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Copy, Check } from '@lucide/vue'
import { useClipboard } from '@/composables/useClipboard'

defineProps<{
  route: string
  distance: string
  totalTime: string
  dataVersion: string
}>()

const { copied, copy } = useClipboard()
</script>
