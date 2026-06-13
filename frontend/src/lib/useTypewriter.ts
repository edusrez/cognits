import { createSignal, onCleanup } from "solid-js"

// Persist cursor position across component remounts (e.g. when <For>
// recreates the last message element on every 50ms store update).
// Keyed by session ID so each session has an independent cursor.
const cursors = new Map<string, number>()

/**
 * Smoothly reveals text character-by-character synced to the display
 * refresh rate via requestAnimationFrame. Adapts automatically to
 * 60 Hz / 120 Hz / 144 Hz monitors.
 *
 * @param key    stable identifier to preserve cursor across remounts
 * @param source getter for the full source text (may grow over time)
 * @param speed  reactive getter: minimum ms between character reveals
 */
export function useTypewriter(key: string, source: () => string, speed: () => number) {
  const [shown, setShown] = createSignal("")
  let last = 0
  let raf = 0

  const tick = (now: number) => {
    const full = source()
    const cur = cursors.get(key) ?? 0
    const delay = speed()
    if (delay <= 0) {
      setShown(full)
      cursors.set(key, full.length)
      last = now
    } else if (cur < full.length && now - last >= delay) {
      const step = Math.min(Math.max(1, Math.floor((now - last) / delay)), 3)
      const next = Math.min(cur + step, full.length)
      cursors.set(key, next)
      setShown(full.slice(0, next))
      last = now
    }
    raf = requestAnimationFrame(tick)
  }

  raf = requestAnimationFrame(tick)
  onCleanup(() => cancelAnimationFrame(raf))
  return shown
}
