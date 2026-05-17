import { ref, onMounted, onUnmounted } from 'vue'

export function useTheme() {
  const isDark = ref(false)

  const updateTheme = () => {
    isDark.value = window.matchMedia('(prefers-color-scheme: dark)').matches
  }

  let mediaQuery: MediaQueryList | null = null

  onMounted(() => {
    updateTheme()
    mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    mediaQuery.addEventListener('change', updateTheme)
  })

  onUnmounted(() => {
    if (mediaQuery) {
      mediaQuery.removeEventListener('change', updateTheme)
    }
  })

  return { isDark }
}
