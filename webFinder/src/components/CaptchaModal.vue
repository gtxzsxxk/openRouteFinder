<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-all duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="modelValue"
        class="fixed inset-0 z-[100] flex items-center justify-center px-4"
        @click.self="close"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" />

        <!-- Modal Card -->
        <div
          class="relative w-full max-w-sm bg-bg-surface rounded-2xl border border-border shadow-xl p-6 space-y-5"
        >
          <div class="text-center">
            <h3 class="text-base font-semibold text-text-primary">{{ $t('captcha.title') }}</h3>
            <p class="text-sm text-text-secondary mt-1">{{ $t('captcha.subtitle') }}</p>
          </div>

          <!-- Captcha Image -->
          <div
            class="h-16 bg-bg-elevated border border-border rounded-xl flex items-center justify-center overflow-hidden cursor-pointer hover:border-text-tertiary transition-colors"
            @click="refreshValidCode"
          >
            <img v-if="validCodeImage" :src="validCodeImage" alt="valid code" class="h-full w-auto" />
            <span v-else class="text-sm text-text-tertiary">{{ $t('captcha.refresh') }}</span>
          </div>

          <!-- Captcha Input -->
          <input
            ref="inputRef"
            v-model="validCodeInput"
            type="text"
            maxlength="4"
            :placeholder="$t('captcha.placeholder')"
            class="w-full h-14 px-4 bg-bg-elevated rounded-xl text-text-primary placeholder-text-tertiary focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all duration-150 uppercase font-mono text-lg tracking-wider text-center border border-border"
            @keydown.enter="confirm"
          />

          <!-- Actions -->
          <div class="flex gap-3">
            <button
              class="flex-1 h-12 bg-bg-elevated hover:bg-bg-page text-text-primary font-medium rounded-xl transition-all duration-150 border border-border"
              @click="close"
            >
              {{ $t('common.cancel') }}
            </button>
            <button
              :disabled="validCodeInput.length !== 4 || isLoading"
              class="flex-1 h-12 bg-accent hover:bg-accent-hover disabled:bg-bg-elevated disabled:text-text-tertiary disabled:cursor-not-allowed text-white font-semibold rounded-xl transition-all duration-150 flex items-center justify-center gap-2"
              @click="confirm"
            >
              <Loader2 v-if="isLoading" class="w-4 h-4 animate-spin" />
              <span>{{ $t('common.confirm') }}</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { Loader2 } from '@lucide/vue'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [code: string, token: string]
}>()

const inputRef = ref<HTMLInputElement | null>(null)
const validCodeInput = ref('')
const validCodeImage = ref('')
const validToken = ref('')
const isLoading = ref(false)

watch(() => props.modelValue, (open) => {
  if (open) {
    validCodeInput.value = ''
    fetchValidCode()
    nextTick(() => {
      inputRef.value?.focus()
    })
  }
})

async function fetchValidCode() {
  try {
    const response = await fetch('/api/validcode')
    const data = await response.json()
    validCodeImage.value = data.image
    validToken.value = data.token
  } catch (err) {
    console.error('Failed to fetch valid code:', err)
  }
}

function refreshValidCode() {
  fetchValidCode()
}

function close() {
  emit('update:modelValue', false)
}

function confirm() {
  if (validCodeInput.value.length !== 4) return
  emit('confirm', validCodeInput.value, validToken.value)
  close()
}
</script>
