<template>
  <div class="min-h-screen bg-bg-page text-text-primary font-body transition-colors duration-300">
    <header
      class="sticky top-0 z-50 h-14 flex items-center border-b border-transparent transition-all duration-300"
      :class="scrolled ? 'bg-bg-page/80 backdrop-blur-md border-border' : ''"
    >
      <div class="max-w-6xl w-full mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between">
        <h1 class="text-lg font-semibold tracking-tight" style="font-family: var(--font-display)">
          OpenRouteFinder
        </h1>
        <button
          @click="toggleTheme"
          class="w-9 h-9 flex items-center justify-center rounded-xl bg-bg-elevated border border-border text-text-secondary hover:text-text-primary hover:bg-bg-surface transition-all duration-150 active:scale-95"
          :title="mode === 'system' ? '跟随系统' : mode === 'dark' ? '深色模式' : '浅色模式'"
        >
          <Sun v-if="isDark" class="w-4 h-4" />
          <Moon v-else class="w-4 h-4" />
        </button>
      </div>
    </header>
    <main class="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <HomeView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Sun, Moon } from '@lucide/vue'
import HomeView from './views/HomeView.vue'
import { useTheme } from './composables/useTheme'

const { isDark, mode, toggleTheme } = useTheme()
const scrolled = ref(false)

function onScroll() {
  scrolled.value = window.scrollY > 10
}

onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>
