import { ref } from 'vue'

export function useClipboard() {
  const copied = ref(false)
  let timeout: ReturnType<typeof setTimeout> | null = null

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      copied.value = true
      if (timeout) clearTimeout(timeout)
      timeout = setTimeout(() => {
        copied.value = false
      }, 1500)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  return { copied, copy }
}
