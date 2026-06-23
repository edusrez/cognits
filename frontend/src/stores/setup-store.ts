import { createSignal, createMemo } from "solid-js"
import type { ChatMessage } from "../lib/chat-stream"
import { llmApiKey, configLoaded } from "./settings-store"

const [setupStarted, setSetupStarted] = createSignal(false)
export const [setupStep, setSetupStep] = createSignal<"welcome" | "apikeys" | "onboarding" | "done">("welcome")
export const [setupMessages, setSetupMessages] = createSignal<ChatMessage[]>([])
export const [setupStreaming, setSetupStreaming] = createSignal(false)
export const [setupComplete, setSetupComplete] = createSignal(false)
export const [interviewMessageSent, setInterviewMessageSent] = createSignal(false)

export const isSetupActive = createMemo(() => {
  if (!configLoaded()) return false
  if (setupComplete()) return false
  return setupStarted()
})

export function beginSetup() { setSetupStarted(true) }
export function finishSetup() { setSetupComplete(true) }

export function resetSetup() {
  setSetupStarted(false)
  setSetupStep("welcome")
  setSetupMessages([])
  setSetupStreaming(false)
  setSetupComplete(false)
}
