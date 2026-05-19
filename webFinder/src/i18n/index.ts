import { createI18n } from 'vue-i18n'
import zh from './locales/zh'
import en from './locales/en'

const saved = localStorage.getItem('orf-locale')
const initialLocale = saved === 'en' ? 'en' : 'zh'

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  fallbackLocale: 'zh',
  messages: { zh, en },
})
