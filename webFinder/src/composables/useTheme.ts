import { ref, onMounted, onUnmounted } from 'vue'

type ThemeMode = 'light' | 'dark' | 'system'

const THEME_STORAGE_KEY = 'orf-theme-mode'

export function useTheme() {
  const isDark = ref(false)
  const mode = ref<ThemeMode>('system')

  function applyTheme(newMode: ThemeMode) {
    mode.value = newMode
    localStorage.setItem(THEME_STORAGE_KEY, newMode)

    const html = document.documentElement

    if (newMode === 'system') {
      html.removeAttribute('data-theme')
      isDark.value = window.matchMedia('(prefers-color-scheme: dark)').matches
    } else {
      html.setAttribute('data-theme', newMode)
      isDark.value = newMode === 'dark'
    }
  }

  function toggleTheme() {
    // 只在 light / dark 之间切换
    applyTheme(mode.value === 'light' ? 'dark' : 'light')
  }

  function syncWithSystem() {
    if (mode.value === 'system') {
      isDark.value = window.matchMedia('(prefers-color-scheme: dark)').matches
    }
  }

  let mediaQuery: MediaQueryList | null = null

  onMounted(() => {
    const saved = localStorage.getItem(THEME_STORAGE_KEY) as ThemeMode | null
    let initialMode: ThemeMode
    if (saved && ['light', 'dark'].includes(saved)) {
      initialMode = saved
    } else {
      // 首次访问：直接根据系统偏好设置，不从 system 开始
      initialMode = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }

    applyTheme(initialMode)

    mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    mediaQuery.addEventListener('change', syncWithSystem)
  })

  onUnmounted(() => {
    if (mediaQuery) {
      mediaQuery.removeEventListener('change', syncWithSystem)
    }
  })

  return { isDark, mode, toggleTheme }
}
