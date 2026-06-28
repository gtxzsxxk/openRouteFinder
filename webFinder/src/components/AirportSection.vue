<template>
  <div>
    <button
      class="w-full flex items-center justify-between text-left group"
      @click="isOpen = !isOpen"
    >
      <div>
        <span class="font-mono text-sm font-semibold text-accent">{{ airport.icao }}</span>
        <span class="text-xs text-text-secondary ml-2">{{ airport.name }}</span>
      </div>
      <ChevronDown
        class="w-4 h-4 text-text-tertiary transition-transform duration-200"
        :class="isOpen ? 'rotate-180' : ''"
      />
    </button>

    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      enter-from-class="opacity-0 -translate-y-1"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-150 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 -translate-y-1"
    >
      <div v-show="isOpen" class="mt-3 space-y-3">
        <div class="bg-bg-elevated rounded-xl p-3 grid grid-cols-2 gap-2">
          <div class="text-xs">
            <span class="text-text-tertiary">{{ $t('airport.lat') }}</span>
            <span class="text-text-primary font-mono ml-1">{{ airport.lat.toFixed(4) }}</span>
          </div>
          <div class="text-xs">
            <span class="text-text-tertiary">{{ $t('airport.lon') }}</span>
            <span class="text-text-primary font-mono ml-1">{{ airport.lon.toFixed(4) }}</span>
          </div>
          <div class="text-xs">
            <span class="text-text-tertiary">{{ $t('airport.elevation') }}</span>
            <span class="text-text-primary font-mono ml-1">{{ airport.elevation }} ft</span>
          </div>
          <div class="text-xs">
            <span class="text-text-tertiary">{{ $t('airport.transitionAlt') }}</span>
            <span class="text-text-primary font-mono ml-1">{{ airport.transitionAltitude }} ft</span>
          </div>
          <div class="text-xs col-span-2">
            <span class="text-text-tertiary">{{ $t('airport.transitionLevel') }}</span>
            <span class="text-text-primary font-mono ml-1">{{ airport.transitionLevel }} ft</span>
          </div>
        </div>

        <div>
          <button
            class="flex items-center gap-1.5 text-xs font-medium text-text-secondary hover:text-text-primary transition-colors"
            @click="runwaysOpen = !runwaysOpen"
          >
            <ChevronDown
              class="w-3 h-3 transition-transform duration-200"
              :class="runwaysOpen ? 'rotate-180' : ''"
            />
            {{ $t('airport.runwayCount', { count: airport.runways.length }) }}
          </button>
          <Transition
            enter-active-class="transition-all duration-200 ease-out"
            enter-from-class="opacity-0 max-h-0"
            enter-to-class="opacity-100 max-h-[500px]"
            leave-active-class="transition-all duration-150 ease-in"
            leave-from-class="opacity-100 max-h-[500px]"
            leave-to-class="opacity-0 max-h-0"
          >
            <div v-show="runwaysOpen" class="mt-2 space-y-2 overflow-hidden">
              <div
                v-for="rwy in airport.runways"
                :key="rwy.name"
                class="bg-bg-elevated rounded-xl p-3 space-y-1.5"
              >
                <div class="flex items-center justify-between">
                  <span class="font-mono text-sm font-medium text-text-primary">{{ rwy.name }}</span>
                  <span class="text-xs text-text-secondary">{{ Math.round(rwy.lengthFt) }} × {{ Math.round(rwy.widthFt) }} ft</span>
                </div>
                <div v-if="rwy.lighting" class="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-text-secondary">
                  <span>{{ $t('airport.lighting') }}: {{ $t(`lighting.${rwy.lighting}`) }}</span>
                </div>
                <div v-if="rwy.ils && rwy.ils.length > 0" class="flex flex-wrap gap-2">
                  <span
                    v-for="ils in rwy.ils"
                    :key="ils.runwayEnd"
                    class="text-xs bg-accent/10 text-accent px-1.5 py-0.5 rounded font-mono"
                  >
                    {{ ils.runwayEnd }} ILS {{ ils.frequency }}
                  </span>
                </div>
              </div>
            </div>
          </Transition>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ChevronDown } from '@lucide/vue'
import type { AirportDetail } from '@/types'

defineProps<{
  airport: AirportDetail
}>()

const isOpen = ref(true)
const runwaysOpen = ref(true)
</script>
