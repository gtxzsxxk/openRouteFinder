<template>
  <div>
    <div class="text-xs text-text-secondary mb-2">{{ title }}</div>

    <div class="flex items-center justify-between mb-3">
      <div class="flex gap-1.5 bg-bg-elevated rounded-lg p-0.5">
        <button
          v-for="mode in ['card', 'raw'] as const"
          :key="mode"
          @click="displayMode = mode"
          :class="[
            'px-3 py-1 text-xs font-medium rounded-md transition-all duration-150',
            displayMode === mode
              ? 'bg-bg-surface text-text-primary shadow-sm'
              : 'text-text-tertiary hover:text-text-secondary',
          ]"
        >
          {{ mode === 'card' ? $t('weather.card') : 'Raw' }}
        </button>
      </div>
    </div>

    <Transition
      mode="out-in"
      enter-active-class="transition-all duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-all duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="displayMode === 'card'" key="card" class="bg-bg-elevated rounded-xl p-4 space-y-4">
        <div class="flex items-baseline gap-2">
          <span v-if="data.temperature != null" class="text-3xl font-light text-text-primary">{{ data.temperature }}°C</span>
          <span v-else class="text-3xl font-light text-text-tertiary">--</span>
          <span v-if="data.clouds.length > 0" class="text-sm text-text-secondary">{{ cloudDescription }}</span>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div class="flex items-center gap-2">
            <ArrowUpRight
              v-if="data.windDirection != null"
              class="w-4 h-4 text-text-secondary"
              :style="{ transform: `rotate(${data.windDirection + 180}deg)` }"
            />
            <Wind v-else class="w-4 h-4 text-text-secondary" />
            <div>
              <div class="text-xs text-text-tertiary">{{ $t('weather.windSpeed') }}</div>
              <div class="text-sm text-text-primary font-mono">
                {{ data.windSpeed != null ? `${data.windSpeed} ${data.windSpeedUnit}` : '--' }}
              </div>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <Eye class="w-4 h-4 text-text-secondary" />
            <div>
              <div class="text-xs text-text-tertiary">{{ $t('weather.visibility') }}</div>
              <div class="text-sm text-text-primary font-mono">{{ data.visibility || '--' }}</div>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <Cloud class="w-4 h-4 text-text-secondary" />
            <div>
              <div class="text-xs text-text-tertiary">{{ $t('weather.cloudBase') }}</div>
              <div class="text-sm text-text-primary font-mono">{{ cloudBaseText }}</div>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <Droplets class="w-4 h-4 text-text-secondary" />
            <div>
              <div class="text-xs text-text-tertiary">{{ $t('weather.dewpoint') }}</div>
              <div class="text-sm text-text-primary font-mono">{{ data.dewpoint != null ? `${data.dewpoint}°C` : '--' }}</div>
            </div>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <Gauge class="w-4 h-4 text-text-secondary" />
          <div>
            <div class="text-xs text-text-tertiary">{{ $t('weather.pressure') }}</div>
            <div class="text-sm text-text-primary font-mono">{{ data.qnh != null ? `${data.qnh} hPa` : '--' }}</div>
          </div>
        </div>

        <div v-if="data.trend" class="pt-2 border-t border-border">
          <span class="text-xs bg-bg-page text-text-secondary px-2 py-0.5 rounded">{{ data.trend }}</span>
        </div>
      </div>

      <div v-else key="raw" class="bg-bg-elevated rounded-xl p-4">
        <p class="text-sm font-mono text-text-primary break-all leading-relaxed">{{ data.raw }}</p>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, Wind, Eye, Cloud, Droplets, Gauge } from '@lucide/vue'
import type { ParsedMetar } from '@/types'

const props = defineProps<{
  title: string
  data: ParsedMetar
}>()

const { t } = useI18n()
const displayMode = ref<'card' | 'raw'>('card')

const cloudDescription = computed(() => {
  if (props.data.clouds.length === 0) return t('weather.noClouds')
  const c = props.data.clouds[0]
  const coverMap: Record<string, string> = {
    FEW: t('weather.few'),
    SCT: t('weather.scattered'),
    BKN: t('weather.broken'),
    OVC: t('weather.overcast'),
    NSC: t('weather.nsc'),
    NCD: t('weather.ncd'),
    SKC: t('weather.skc'),
  }
  return coverMap[c.cover] || c.cover
})

const cloudBaseText = computed(() => {
  if (props.data.clouds.length === 0) return '--'
  const c = props.data.clouds[0]
  if (c.base == null) return c.cover
  return `${c.cover} ${c.base}ft`
})
</script>
