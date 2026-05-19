<template>
  <div class="space-y-4">
    <WeatherSection
      v-if="weather"
      :title="$t('weather.departure')"
      :data="weather[0]"
    />
    <div v-if="weather" class="border-t border-border" />
    <WeatherSection
      v-if="weather"
      :title="$t('weather.arrival')"
      :data="weather[1]"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouteStore } from '@/stores/routeStore'
import WeatherSection from './WeatherSection.vue'

const store = useRouteStore()
const weather = computed(() => store.parsedWeather)
</script>
