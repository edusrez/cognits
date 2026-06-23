import { createSignal, createMemo } from "solid-js"
import type { ChatMessage } from "../lib/chat-stream"
import { llmApiKey, configLoaded } from "./settings-store"

export const isSetupActive = createMemo(() => configLoaded() && !llmApiKey())

export const [setupStep, setSetupStep] = createSignal<"welcome" | "apikeys" | "onboarding" | "done">("welcome")

export const [setupMessages, setSetupMessages] = createSignal<ChatMessage[]>([])

export const [setupStreaming, setSetupStreaming] = createSignal(false)

export const [setupComplete, setSetupComplete] = createSignal(false)

export function finishSetup() {
  setSetupComplete(true)
}

export function resetSetup() {
  setSetupStep("welcome")
  setSetupMessages([])
  setSetupStreaming(false)
  setSetupComplete(false)
}
