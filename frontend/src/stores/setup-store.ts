import { createSignal, createMemo } from "solid-js"
import { configLoaded } from "./settings-store"

const [setupStarted, setSetupStarted] = createSignal(false)
export const [setupStep, setSetupStep] = createSignal<"welcome" | "apikeys" | "onboarding" | "done">("welcome")
const [setupComplete, setSetupComplete] = createSignal(false)
export const [interviewMessageSent, setInterviewMessageSent] = createSignal(false)

export const isSetupActive = createMemo(() => {
  if (!configLoaded()) return false
  if (setupComplete()) return false
  return setupStarted()
})

export function beginSetup() {
  setSetupStarted(true)
}

export function finishSetup() {
  setSetupComplete(true)
}

export async function initSetup() {
  let hasProfile = false
  try {
    const res = await fetch("/api/profile")
    if (res.ok) {
      const profile = await res.json()
      if (profile.declared?.background?.trim()) {
        hasProfile = true
      }
    }
  } catch {}

  if (hasProfile) {
    finishSetup()
    return
  }

  try {
    await fetch("/api/setup/state", { method: "DELETE" })
  } catch {}

  beginSetup()
}
