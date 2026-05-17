<template>
  <div
    class="bg-bg-surface rounded-2xl transition-all duration-200"
    :class="[
      padding ? 'p-6' : '',
      hover ? 'hover:bg-bg-elevated' : '',
      className,
    ]"
  >
    <div v-if="title" class="flex items-center justify-between mb-4">
      <h3 class="text-sm font-semibold text-text-primary">{{ title }}</h3>
      <slot name="action" />
    </div>
    <slot />
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title?: string
  padding?: boolean
  hover?: boolean
  className?: string
}>()
</script>
