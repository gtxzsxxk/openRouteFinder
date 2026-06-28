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
        <div class="flex items-center gap-2">
          <button
            class="w-9 h-9 flex items-center justify-center rounded-xl bg-bg-elevated border border-border text-text-secondary hover:text-text-primary hover:bg-bg-surface transition-all duration-150 active:scale-95 text-xs font-semibold"
            :title="locale === 'zh' ? '切换到 English' : 'Switch to 中文'"
            @click="toggleLocale"
          >
            {{ locale === 'zh' ? 'EN' : '中' }}
          </button>
          <button
            class="w-9 h-9 flex items-center justify-center rounded-xl bg-bg-elevated border border-border text-text-secondary hover:text-text-primary hover:bg-bg-surface transition-all duration-150 active:scale-95"
            :title="$t(`theme.${mode}`)"
            @click="toggleTheme"
          >
            <Sun v-if="isDark" class="w-4 h-4" />
            <Moon v-else class="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
    <main class="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <Transition
        enter-active-class="transition-all duration-300 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-all duration-200 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
        mode="out-in"
      >
        <HomeView v-if="currentView === 'home'" />
        <AdminView v-else @go-home="currentView = 'home'" />
      </Transition>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Sun, Moon } from '@lucide/vue'
import HomeView from './views/HomeView.vue'
import AdminView from './views/AdminView.vue'
import { useTheme } from './composables/useTheme'
import { useLocale } from './composables/useLocale'

const { isDark, mode, toggleTheme } = useTheme()
const { locale, toggleLocale } = useLocale()
const scrolled = ref(false)
const currentView = ref<'home' | 'admin'>('home')

function updateViewFromHash() {
  currentView.value = window.location.hash === '#admin' ? 'admin' : 'home'
}

function onScroll() {
  scrolled.value = window.scrollY > 10
}

onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('hashchange', updateViewFromHash)
  updateViewFromHash()
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('hashchange', updateViewFromHash)
})
</script>
