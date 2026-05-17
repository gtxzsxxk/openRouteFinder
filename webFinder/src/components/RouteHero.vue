<template>
  <div v-if="route" class="py-6 md:py-8">
    <div class="flex items-center gap-4 flex-wrap">
      <div class="font-mono text-2xl md:text-4xl font-medium text-text-primary tracking-tight break-all">
        {{ route }}
      </div>
      <button
        @click="copy(route)"
        class="shrink-0 w-10 h-10 flex items-center justify-center bg-bg-surface hover:bg-bg-elevated
               rounded-full border border-border text-text-secondary hover:text-text-primary
               transition-all duration-150 active:scale-95"
        :title="copied ? '已复制' : '复制航线'"
      >
        <Check v-if="copied" class="w-4 h-4 text-success" />
        <Copy v-else class="w-4 h-4" />
      </button>
    </div>
    <div class="mt-3 flex items-center gap-3 text-sm text-text-secondary">
      <span>{{ distance }}</span>
      <span class="text-border">·</span>
      <span>{{ totalTime }}s</span>
      <span class="text-border">·</span>
      <span class="text-text-tertiary">{{ dataVersion }}</span>
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
