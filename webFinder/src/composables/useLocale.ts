import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const LOCALE_STORAGE_KEY = 'orf-locale'

const localeRef = ref(localStorage.getItem(LOCALE_STORAGE_KEY) || 'zh')

export function useLocale() {
  const { locale } = useI18n()

  watch(localeRef, (val) => {
    locale.value = val
    localStorage.setItem(LOCALE_STORAGE_KEY, val)
  }, { immediate: true })

  function toggleLocale() {
    localeRef.value = localeRef.value === 'zh' ? 'en' : 'zh'
  }

  return {
    locale: localeRef,
    toggleLocale,
  }
}
