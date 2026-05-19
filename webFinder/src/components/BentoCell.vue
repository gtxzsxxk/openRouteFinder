<template>
  <div
    class="bg-bg-surface rounded-2xl border border-border transition-all duration-200 flex flex-col"
    :class="[
      padding ? 'p-6' : '',
      hover ? 'hover:border-text-tertiary' : '',
      className,
    ]"
  >
    <div v-if="title" class="flex items-center justify-between mb-4">
      <h3 class="text-sm font-semibold text-text-secondary">{{ title }}</h3>
      <slot name="action" />
    </div>
    <div class="flex-1 min-h-0">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title?: string
  padding?: boolean
  hover?: boolean
  className?: string
}>(), {
  padding: true,
})
</script>
