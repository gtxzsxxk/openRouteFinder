<template>
  <div class="min-h-[calc(100vh-7rem)]">
    <!-- Login State -->
    <Transition
      enter-active-class="transition-all duration-500 ease-out"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition-all duration-300 ease-in"
      leave-from-class="opacity-100 scale-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div v-if="!isLoggedIn" class="flex items-center justify-center min-h-[calc(100vh-7rem)]">
        <div class="w-full max-w-sm">
          <div
            class="bg-bg-surface rounded-2xl border border-border p-8 shadow-lg"
            :class="shakeError ? 'animate-shake' : ''"
          >
            <div class="flex flex-col items-center mb-6">
              <div class="w-14 h-14 rounded-2xl bg-accent/10 flex items-center justify-center mb-4">
                <Shield class="w-7 h-7 text-accent" />
              </div>
              <h2 class="text-xl font-semibold text-text-primary" style="font-family: var(--font-display)">
                {{ $t('admin.login') }}
              </h2>
            </div>
            <div class="space-y-4">
              <div>
                <label class="block text-xs font-medium text-text-secondary mb-2 uppercase tracking-wider">
                  {{ $t('admin.enterKey') }}
                </label>
                <input
                  v-model="inputKey"
                  type="password"
                  :placeholder="$t('admin.enterKey')"
                  class="w-full h-14 px-4 bg-bg-elevated rounded-xl text-text-primary placeholder-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all duration-150 font-mono"
                  @keydown.enter="handleLogin"
                />
              </div>
              <p v-if="loginError" class="text-sm text-error text-center animate-fade-in">
                {{ loginError }}
              </p>
              <button
                @click="handleLogin"
                :disabled="isLoading || !inputKey"
                class="w-full h-12 bg-accent hover:bg-accent-hover text-white font-semibold rounded-full shadow-md hover:shadow-lg active:scale-[0.98] transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                <Loader2 v-if="isLoading" class="w-4 h-4 animate-spin" />
                <span>{{ $t('admin.submit') }}</span>
              </button>
            </div>
            <div class="mt-6 text-center">
              <button
                @click="goHome"
                class="text-sm text-text-secondary hover:text-text-primary transition-colors duration-150"
              >
                {{ $t('admin.back') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Dashboard State -->
    <Transition
      enter-active-class="transition-all duration-500 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-all duration-300 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="isLoggedIn" class="space-y-6">
        <!-- Header -->
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
              <Activity class="w-5 h-5 text-accent" />
            </div>
            <div>
              <h2 class="text-lg font-semibold text-text-primary" style="font-family: var(--font-display)">
                {{ $t('admin.title') }}
              </h2>
              <p v-if="data" class="text-xs text-text-secondary font-mono">
                {{ formatUptime(data.uptime_seconds) }}
              </p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <div class="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-bg-elevated border border-border text-xs text-text-secondary">
              <div class="w-1.5 h-1.5 rounded-full bg-success animate-pulse"></div>
              <span class="font-mono">LIVE</span>
            </div>
            <button
              @click="handleLogout"
              class="w-9 h-9 flex items-center justify-center rounded-xl bg-bg-elevated border border-border text-text-secondary hover:text-text-primary hover:bg-bg-surface transition-all duration-150 active:scale-95"
              :title="$t('admin.back')"
            >
              <ArrowLeft class="w-4 h-4" />
            </button>
          </div>
        </div>

        <!-- Stat Tiles -->
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            v-if="data"
            :label="$t('admin.totalRequests')"
            :value="data.total_requests"
            icon="Globe"
            :delay="0"
          />
          <StatCard
            v-if="data"
            :label="$t('admin.uniqueVisitors')"
            :value="data.unique_visitors"
            icon="Users"
            :delay="80"
          />
          <StatCard
            v-if="data"
            :label="$t('admin.routeSearches')"
            :value="data.route_searches.length"
            icon="Route"
            :delay="160"
          />
          <StatCard
            v-if="data"
            :label="$t('admin.errors')"
            :value="data.errors.length"
            icon="AlertTriangle"
            :delay="240"
            :danger="data.errors.length > 0"
          />
        </div>

        <!-- Navdata Management -->
        <BentoCell :title="$t('admin.navdata')" class="animate-fade-in-up" style="animation-delay: 300ms">
          <div class="space-y-4">
            <!-- Upload Form -->
            <div class="bg-bg-elevated/50 rounded-xl p-4 space-y-3">
              <h3 class="text-sm font-medium text-text-primary">{{ $t('admin.navdataUpload') }}</h3>
              <div class="flex items-center gap-3">
                <input
                  ref="fileInput"
                  type="file"
                  accept=".zip"
                  class="flex-1 text-xs text-text-primary file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:bg-accent file:text-white file:cursor-pointer"
                  @change="hasSelectedFile = !!fileInput?.files?.length"
                />
                <button
                  @click="handleUpload"
                  :disabled="isUploading || isBuilding || !hasSelectedFile"
                  class="px-4 h-9 bg-accent hover:bg-accent-hover text-white text-xs font-semibold rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 shrink-0"
                >
                  <Loader2 v-if="isUploading" class="w-3.5 h-3.5 animate-spin" />
                  <span>{{ isUploading ? $t('admin.navdataUploading') : $t('common.confirm') }}</span>
                </button>
              </div>
              <p class="text-xs text-text-secondary">{{ $t('admin.navdataUploadHint') }}</p>
              <p v-if="uploadError" class="text-xs text-error">{{ uploadError }}</p>
            </div>

            <!-- Build Progress Modal -->
            <Transition
              enter-active-class="transition-all duration-300 ease-out"
              enter-from-class="opacity-0 scale-95"
              enter-to-class="opacity-100 scale-100"
              leave-active-class="transition-all duration-200 ease-in"
              leave-from-class="opacity-100 scale-100"
              leave-to-class="opacity-0 scale-95"
            >
              <div v-if="showProgressModal" class="bg-bg-surface rounded-xl border border-border p-5 space-y-4">
                <div class="flex items-center justify-between">
                  <h3 class="text-sm font-medium text-text-primary">
                    {{ buildProgress.status === 'done' ? $t('admin.navdataUploadSuccess') : buildProgress.status === 'error' ? $t('admin.navdataUploadFailed') : $t('admin.navdataUploading') }}
                  </h3>
                  <span v-if="buildProgress.status === 'building'" class="text-xs text-text-secondary font-mono">{{ buildProgress.percent }}%</span>
                </div>

                <!-- Progress bar -->
                <div class="h-2 bg-bg-elevated rounded-full overflow-hidden">
                  <div
                    class="h-full bg-accent rounded-full transition-all duration-500 ease-out"
                    :style="{ width: `${buildProgress.percent}%` }"
                  />
                </div>

                <!-- Step info -->
                <div class="flex items-center justify-between text-xs">
                  <span class="text-text-secondary">{{ stepLabel }}</span>
                  <span v-if="buildProgress.status === 'error'" class="text-error">{{ buildProgress.detail }}</span>
                </div>
              </div>
            </Transition>

            <!-- Cycle List -->
            <div v-if="navCycles && navCycles.length > 0" class="overflow-x-auto">
              <table class="w-full text-xs">
                <thead>
                  <tr class="border-b border-border text-text-secondary">
                    <th class="text-left py-2 pr-3 font-medium uppercase tracking-wider">{{ $t('admin.navdataCycle') }}</th>
                    <th class="text-right py-2 pr-3 font-medium uppercase tracking-wider">{{ $t('admin.navdataSize') }}</th>
                    <th class="text-right py-2 pr-3 font-medium uppercase tracking-wider">{{ $t('admin.navdataNodes') }}</th>
                    <th class="text-right py-2 pr-3 font-medium uppercase tracking-wider">{{ $t('admin.navdataEdges') }}</th>
                    <th class="text-right py-2 pr-3 font-medium uppercase tracking-wider">{{ $t('admin.navdataAirports') }}</th>
                    <th class="text-right py-2 pr-3 font-medium uppercase tracking-wider">{{ $t('admin.navdataProcedures') }}</th>
                    <th class="text-right py-2 font-medium uppercase tracking-wider"></th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="c in navCycles"
                    :key="c.cycle"
                    class="border-b border-border/50 hover:bg-bg-elevated/50 transition-colors"
                  >
                    <td class="py-2 pr-3 font-mono text-text-primary">{{ c.cycle }}</td>
                    <td class="py-2 pr-3 text-right font-mono text-text-secondary">{{ c.file_size_mb }} MB</td>
                    <td class="py-2 pr-3 text-right font-mono text-text-secondary">{{ c.node_count.toLocaleString() }}</td>
                    <td class="py-2 pr-3 text-right font-mono text-text-secondary">{{ c.edge_count.toLocaleString() }}</td>
                    <td class="py-2 pr-3 text-right font-mono text-text-secondary">{{ c.airport_count.toLocaleString() }}</td>
                    <td class="py-2 pr-3 text-right font-mono text-text-secondary">{{ c.procedure_count.toLocaleString() }}</td>
                    <td class="py-2 text-right">
                      <button
                        @click="handleDelete(c.cycle)"
                        :disabled="isDeleting"
                        class="px-2 py-1 rounded text-xs bg-error/10 text-error hover:bg-error/20 transition-colors disabled:opacity-50"
                      >
                        {{ $t('admin.navdataDelete') }}
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="text-center text-text-tertiary text-xs py-4">{{ $t('admin.navdataNoCycles') }}</p>
          </div>
        </BentoCell>

        <!-- Recent Requests -->
        <BentoCell :title="$t('admin.recentRequests')" class="animate-fade-in-up" style="animation-delay: 320ms">
          <div v-if="data" class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-border text-text-secondary">
                  <th class="text-left py-2 pr-4 font-medium text-xs uppercase tracking-wider">{{ $t('admin.time') }}</th>
                  <th class="text-left py-2 pr-4 font-medium text-xs uppercase tracking-wider">{{ $t('admin.ip') }}</th>
                  <th class="text-left py-2 pr-4 font-medium text-xs uppercase tracking-wider">{{ $t('admin.method') }}</th>
                  <th class="text-left py-2 pr-4 font-medium text-xs uppercase tracking-wider">{{ $t('admin.path') }}</th>
                  <th class="text-left py-2 pr-4 font-medium text-xs uppercase tracking-wider">{{ $t('admin.status') }}</th>
                  <th class="text-right py-2 font-medium text-xs uppercase tracking-wider">{{ $t('admin.duration') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="req in data.recent_requests.slice(-50).reverse()"
                  :key="req.time + req.path + req.duration_ms"
                  class="border-b border-border/50 hover:bg-bg-elevated/50 transition-colors"
                >
                  <td class="py-2 pr-4 font-mono text-text-secondary text-xs">{{ formatTime(req.time) }}</td>
                  <td class="py-2 pr-4 font-mono text-text-secondary text-xs">{{ req.ip }}</td>
                  <td class="py-2 pr-4">
                    <span class="px-1.5 py-0.5 rounded text-xs font-mono bg-bg-elevated text-text-secondary">{{ req.method }}</span>
                  </td>
                  <td class="py-2 pr-4 font-mono text-text-primary text-xs truncate max-w-[200px]">{{ req.path }}</td>
                  <td class="py-2 pr-4">
                    <StatusBadge :code="req.status" />
                  </td>
                  <td class="py-2 text-right font-mono text-text-secondary text-xs">{{ req.duration_ms }}ms</td>
                </tr>
                <tr v-if="data.recent_requests.length === 0">
                  <td colspan="6" class="py-8 text-center text-text-tertiary text-sm">No requests yet</td>
                </tr>
              </tbody>
            </table>
          </div>
        </BentoCell>

        <!-- Route Searches -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <BentoCell :title="$t('admin.routeSearches')" class="animate-fade-in-up" style="animation-delay: 400ms">
            <div v-if="data" class="space-y-2 max-h-80 overflow-y-auto">
              <div
                v-for="search in data.route_searches.slice(-20).reverse()"
                :key="search.time + search.orig + search.dest"
                class="py-3 px-3 rounded-xl bg-bg-elevated/50 hover:bg-bg-elevated transition-colors"
              >
                <div class="flex items-center justify-between mb-1.5">
                  <div class="flex items-center gap-2">
                    <Plane class="w-4 h-4 text-accent" />
                    <span class="font-mono text-sm text-text-primary">{{ search.orig }} → {{ search.dest }}</span>
                  </div>
                  <span class="text-xs text-text-tertiary font-mono">{{ formatTime(search.time) }}</span>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                  <span v-if="search.sidExit" class="px-1.5 py-0.5 rounded text-xs font-mono bg-sid-line/10 text-sid-line">SID: {{ search.sidExit }}</span>
                  <span v-if="search.starEntry" class="px-1.5 py-0.5 rounded text-xs font-mono bg-star-line/10 text-star-line">STAR: {{ search.starEntry }}</span>
                  <span v-if="search.distance != null" class="px-1.5 py-0.5 rounded text-xs font-mono bg-accent/10 text-accent">{{ Math.round(search.distance) }} NM</span>
                  <span v-if="search.nodesCount != null" class="px-1.5 py-0.5 rounded text-xs font-mono bg-bg-page text-text-secondary">{{ search.nodesCount }} waypoints</span>
                  <span v-if="search.timeMin != null" class="px-1.5 py-0.5 rounded text-xs font-mono bg-bg-page text-text-secondary">{{ Math.round(search.timeMin) }} min</span>
                </div>
              </div>
              <p v-if="data.route_searches.length === 0" class="py-4 text-center text-text-tertiary text-sm">No route searches yet</p>
            </div>
          </BentoCell>

          <!-- Errors -->
          <BentoCell :title="$t('admin.errors')" class="animate-fade-in-up" style="animation-delay: 480ms">
            <div v-if="data" class="space-y-2 max-h-80 overflow-y-auto">
              <div
                v-for="err in data.errors.slice(-20).reverse()"
                :key="err.time + (err.path || '') + (err.detail || '')"
                class="py-2.5 px-3 rounded-xl bg-error/5 hover:bg-error/10 transition-colors"
              >
                <div class="flex items-center justify-between mb-1">
                  <div class="flex items-center gap-2 min-w-0">
                    <XCircle class="w-4 h-4 text-error flex-shrink-0" />
                    <span v-if="err.path" class="font-mono text-xs text-text-primary truncate">{{ err.method }} {{ err.path }}</span>
                  </div>
                  <div class="flex items-center gap-2 flex-shrink-0">
                    <StatusBadge v-if="err.status" :code="err.status" />
                    <span class="text-xs text-text-tertiary font-mono">{{ formatTime(err.time) }}</span>
                  </div>
                </div>
                <p class="text-xs text-error font-mono break-words pl-6">{{ err.detail }}</p>
              </div>
              <p v-if="data.errors.length === 0" class="py-4 text-center text-text-tertiary text-sm">No errors</p>
            </div>
          </BentoCell>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Shield,
  Loader2,
  Activity,
  ArrowLeft,
  Globe,
  Users,
  Route,
  AlertTriangle,
  Plane,
  XCircle,
} from '@lucide/vue'
import BentoCell from '@/components/BentoCell.vue'
import { useAdmin } from '@/composables/useAdmin'
import { useNavData } from '@/composables/useNavData'

const stepLabels: Record<string, string> = {
  starting: 'Preparing...',
  waypoints: 'Building waypoints...',
  airways: 'Building airways...',
  airports: 'Building airports...',
  navaids: 'Building navaids...',
  holdings: 'Building holdings...',
  markers: 'Building markers...',
  gls: 'Building GLS...',
  grid_mora: 'Building grid MORA...',
  airport_comms: 'Building airport comms...',
  serialization: 'Serializing...',
}

const emit = defineEmits<{
  goHome: []
}>()

const { t } = useI18n()
const { data, isLoading, error, authenticate, logout } = useAdmin()

const inputKey = ref('')
const loginError = ref('')
const shakeError = ref(false)
const isLoggedIn = computed(() => data.value !== undefined && !error.value)

// Navdata upload state
const fileInput = ref<HTMLInputElement | null>(null)
const hasSelectedFile = ref(false)
const isBuilding = ref(false)

const {
  cycles: navCycles,
  activeBuilds,
  uploadError,
  deleteCycle,
  isDeleting,
  uploadCycleAsync: doUpload,
  isUploading,
  connectProgress,
} = useNavData(computed(() => inputKey.value))

// Build progress tracking
const showProgressModal = ref(false)
const buildProgress = ref<{
  status: 'building' | 'done' | 'error'
  step?: string
  percent?: number
  detail?: string
}>({ status: 'building', step: 'starting', percent: 0 })

const stepLabel = computed(() => {
  if (buildProgress.value.status === 'done') return 'Complete'
  if (buildProgress.value.status === 'error') return 'Failed'
  return stepLabels[buildProgress.value.step || ''] || buildProgress.value.step || 'Processing...'
})

async function handleLogin() {
  if (!inputKey.value) return
  loginError.value = ''
  try {
    await authenticate(inputKey.value)
  } catch (e: any) {
    loginError.value = e.message || t('common.loadFailed')
    shakeError.value = true
    setTimeout(() => { shakeError.value = false }, 500)
  }
}

function handleLogout() {
  logout()
  inputKey.value = ''
  loginError.value = ''
  goHome()
}

function goHome() {
  window.location.hash = ''
  emit('goHome')
}

function handleDelete(cycle: string) {
  if (!confirm(t('admin.navdataDeleteConfirm'))) return
  deleteCycle(cycle)
}

const activeEsCleanups = new Map<string, () => void>()

function attachProgress(buildId: string) {
  const existing = activeEsCleanups.get(buildId)
  if (existing) {
    existing()
    activeEsCleanups.delete(buildId)
  }
  isBuilding.value = true
  const cleanup = connectProgress(buildId, (p) => {
    buildProgress.value = {
      status: p.status,
      step: p.step,
      percent: p.percent ?? 0,
      detail: p.detail,
    }
    if (p.status === 'done' || p.status === 'error') {
      isBuilding.value = false
      activeEsCleanups.delete(buildId)
      setTimeout(() => {
        showProgressModal.value = false
        hasSelectedFile.value = false
        if (fileInput.value) fileInput.value.value = ''
      }, p.status === 'done' ? 1500 : 4000)
    }
  })
  activeEsCleanups.set(buildId, cleanup)
}

async function handleUpload() {
  const file = fileInput.value?.files?.[0]
  if (!file) return
  uploadError.value = ''
  buildProgress.value = { status: 'building', step: 'starting', percent: 0 }
  showProgressModal.value = true
  isBuilding.value = true

  const formData = new FormData()
  formData.append('file', file)

  try {
    const result = await doUpload(formData)
    if (result?.build_id) {
      attachProgress(result.build_id)
    }
  } catch (e: any) {
    isBuilding.value = false
    showProgressModal.value = false
  }
}

watch(activeBuilds, (builds) => {
  if (!builds || builds.length === 0) return
  const first = builds[0]
  if (!isBuilding.value) {
    buildProgress.value = { status: 'building', step: first.step, percent: first.percent }
    showProgressModal.value = true
    attachProgress(first.build_id)
  }
})

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const parts = []
  if (h > 0) parts.push(`${h}h`)
  if (m > 0) parts.push(`${m}m`)
  parts.push(`${s}s`)
  return parts.join(' ')
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString('en-GB', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

onUnmounted(() => {
  for (const cleanup of activeEsCleanups.values()) {
    cleanup()
  }
  activeEsCleanups.clear()
})
</script>

<script lang="ts">
import { h, defineComponent } from 'vue'
import type { Component } from 'vue'

const iconMap: Record<string, Component> = {
  Globe,
  Users,
  Route,
  AlertTriangle,
}

const StatCard = defineComponent({
  props: {
    label: { type: String, required: true },
    value: { type: Number, required: true },
    icon: { type: String, required: true },
    delay: { type: Number, default: 0 },
    danger: { type: Boolean, default: false },
  },
  setup(props) {
    const IconComp = iconMap[props.icon] || Globe
    return () => h('div', {
      class: [
        'bg-bg-surface rounded-2xl border border-border p-5 animate-fade-in-up',
        props.danger ? 'border-error/30' : '',
      ],
      style: `animation-delay: ${props.delay}ms`,
    }, [
      h('div', { class: 'flex items-center justify-between mb-3' }, [
        h('span', { class: 'text-xs font-medium text-text-secondary uppercase tracking-wider' }, props.label),
        h('div', {
          class: [
            'w-8 h-8 rounded-lg flex items-center justify-center',
            props.danger ? 'bg-error/10' : 'bg-accent/10',
          ],
        }, [h(IconComp, { class: `w-4 h-4 ${props.danger ? 'text-error' : 'text-accent'}` })]),
      ]),
      h('div', {
        class: [
          'text-3xl font-semibold font-mono',
          props.danger ? 'text-error' : 'text-text-primary',
        ],
      }, props.value.toLocaleString()),
    ])
  },
})

const StatusBadge = defineComponent({
  props: { code: { type: Number, required: true } },
  setup(props) {
    const colorClass =
      props.code < 300 ? 'bg-success/10 text-success' :
      props.code < 400 ? 'bg-star-line/10 text-star-line' :
      'bg-error/10 text-error'
    return () => h('span', {
      class: `px-2 py-0.5 rounded text-xs font-mono font-medium ${colorClass}`,
    }, props.code)
  },
})
</script>

<style scoped>
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-8px); }
  40% { transform: translateX(8px); }
  60% { transform: translateX(-4px); }
  80% { transform: translateX(4px); }
}

.animate-fade-in-up {
  animation: fadeInUp 0.4s ease-out forwards;
  opacity: 0;
}

.animate-fade-in {
  animation: fadeInUp 0.2s ease-out forwards;
}

.animate-shake {
  animation: shake 0.4s ease-in-out;
}
</style>
