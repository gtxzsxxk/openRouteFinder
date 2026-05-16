<template>
  <div class="min-h-screen bg-primary text-text">
    <header class="bg-secondary border-b border-border sticky top-0 z-50">
      <div class="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
        <h1 class="text-xl font-semibold text-white tracking-wide">
          OpenRouteFinder
        </h1>
        <nav class="flex gap-4 text-sm text-text-muted">
          <a href="https://github.com/gtxzsxxk/Airway-Route-Finder" target="_blank" class="hover:text-white transition-colors">
            GitHub
          </a>
        </nav>
      </div>
    </header>
    <main class="max-w-7xl mx-auto px-4 py-6">
      <HomeView />
    </main>
  </div>
</template>

<script setup lang="ts">
import HomeView from './views/HomeView.vue'
</script>