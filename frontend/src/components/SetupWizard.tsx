import { createSignal, Show, For, onCleanup } from "solid-js"
import { setupStep, setSetupStep, setupMessages, setSetupMessages, setupStreaming, setSetupStreaming, finishSetup } from "../stores/setup-store"
import { llmApiKey, loadConfig } from "../stores/settings-store"
import { setTabHidden } from "../stores/viewport-tree-store"
import type { ChatMessage } from "../lib/chat-stream"
import MarkdownView from "./MarkdownView"

export default function SetupWizard() {
  const [answer, setAnswer] = createSignal("")
  const [error, setError] = createSignal("")
  let scrollRef!: HTMLDivElement
  let abortCtrl: AbortController | null = null

  onCleanup(() => {
    if (abortCtrl) abortCtrl.abort()
  })

  function scrollBottom() {
    if (scrollRef) {
      requestAnimationFrame(() => {
        scrollRef.scrollTop = scrollRef.scrollHeight
      })
    }
  }

  function openSettings() {
    setTabHidden("111", "settings", false)
  }

  async function startOnboarding() {
    setSetupStreaming(true)
    setError("")

    const msgs: ChatMessage[] = [
      { role: "user", content: "Start the onboarding interview. Ask your first question." },
    ]
    setSetupMessages(msgs)

    abortCtrl = new AbortController()

    try {
      const res = await fetch("/api/setup/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: msgs }),
        signal: abortCtrl.signal,
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let currentResponse = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const parsed = JSON.parse(line.slice(6))
              if (parsed.choices?.[0]?.delta?.content) {
                currentResponse += parsed.choices[0].delta.content
                setSetupMessages((prev) => {
                  const msgs = [...prev]
                  const last = msgs[msgs.length - 1]
                  if (last?.role === "assistant") {
                    msgs[msgs.length - 1] = { ...last, content: currentResponse }
                  } else {
                    msgs.push({ role: "assistant", content: currentResponse })
                  }
                  return msgs
                })
                scrollBottom()
              }
            } catch {}
          }
        }
      }

      if (currentResponse) {
        setSetupMessages((prev) => {
          const msgs = [...prev]
          const last = msgs[msgs.length - 1]
          if (last?.role === "assistant") {
            msgs[msgs.length - 1] = { ...last, content: currentResponse }
          }
          return msgs
        })
      }
    } catch (e: any) {
      if (e.name !== "AbortError") setError(e.message || "Connection failed")
    } finally {
      abortCtrl = null
      setSetupStreaming(false)
    }
  }

  async function sendAnswer() {
    const text = answer().trim()
    if (!text || setupStreaming()) return
    setAnswer("")
    setError("")

    setSetupMessages((prev) => [...prev, { role: "user", content: text }])
    scrollBottom()
    abortCtrl = new AbortController()

    try {
      const msgs = setupMessages()
      const res = await fetch("/api/setup/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: [...msgs, { role: "user", content: text }] }),
        signal: abortCtrl.signal,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      setSetupStreaming(true)
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let currentResponse = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const parsed = JSON.parse(line.slice(6))
              if (parsed.choices?.[0]?.delta?.content) {
                currentResponse += parsed.choices[0].delta.content
                setSetupMessages((prev) => {
                  const msgs = [...prev]
                  const last = msgs[msgs.length - 1]
                  if (last?.role === "assistant") {
                    msgs[msgs.length - 1] = { ...last, content: currentResponse }
                  } else {
                    msgs.push({ role: "assistant", content: currentResponse })
                  }
                  return msgs
                })
                scrollBottom()
              }
            } catch {}
          }
        }
      }

      if (currentResponse) {
        setSetupMessages((prev) => {
          const msgs = [...prev]
          const last = msgs[msgs.length - 1]
          if (last?.role === "assistant") {
            msgs[msgs.length - 1] = { ...last, content: currentResponse }
          }
          return msgs
        })
        if (currentResponse.includes("[PROFILE COMPLETE]")) {
          await loadConfig()
          setSetupStep("done")
        }
      }
    } catch (e: any) {
      if (e.name !== "AbortError") setError(e.message || "Connection failed")
    } finally {
      abortCtrl = null
      setSetupStreaming(false)
    }
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      sendAnswer()
    }
  }

  function completeSetup() {
    finishSetup()
  }

  return (
    <div class="h-full flex flex-col text-[#c0c0c0] text-sm">
      <Show when={setupStep() === "welcome"}>
        <div class="flex-1 flex flex-col items-center justify-center gap-6 px-4">
          <div class="text-center">
            <h1 class="text-xl font-bold mb-2">Welcome to Cognits</h1>
            <p class="text-[#6a6a6a] max-w-md text-xs">
              Your personal AI tutoring system. Let's configure your environment
              so the AI can understand you, your project, and how you learn best.
            </p>
          </div>
          <button
            class="px-6 py-2 border border-white/20 hover:bg-white/10 transition-colors"
            onClick={() => setSetupStep("apikeys")}
          >
            Start Setup →
          </button>
        </div>
      </Show>

      <Show when={setupStep() === "apikeys"}>
        <div class="flex-1 flex flex-col items-center justify-center gap-4 px-4">
          <div class="text-center max-w-md">
            <h2 class="text-base font-semibold mb-3">API Keys Required</h2>
            <p class="text-[#6a6a6a] mb-2 text-xs">
              Cognits needs an API key from an AI provider to work.
              Click below to open the Settings tab on the right side of the screen.
            </p>
            <p class="text-[#6a6a6a] mb-2 text-xs">
              In Settings you'll find the <span class="text-white">API Keys</span> section.
              Enter your DeepSeek API key there. Optionally, add a TinyFish key for web research.
            </p>
            <p class="text-[#6a6a6a] text-xs">
              Your keys are encrypted and stored only on your machine.
            </p>
          </div>
          <button
            class="px-6 py-2 border border-white/20 hover:bg-white/10 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            onClick={openSettings}
          >
            Open Settings →
          </button>
          <button
            class="px-6 py-2 border border-white/20 hover:bg-white/10 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            disabled={!llmApiKey()}
            onClick={() => setSetupStep("onboarding")}
          >
            Continue to Interview →
          </button>
          <Show when={!llmApiKey()}>
            <p class="text-[#6a6a6a] text-xs">Configure your API key in Settings to continue.</p>
          </Show>
        </div>
      </Show>

      <Show when={setupStep() === "onboarding"}>
        <div class="flex-1 flex flex-col min-h-0">
          <div
            ref={scrollRef}
            class="flex-1 overflow-y-auto overflow-x-hidden px-3 py-2"
          >
            <Show when={setupMessages().length <= 1}>
              <div class="flex-1 flex flex-col items-center justify-center h-full gap-3">
                <p class="text-[#6a6a6a] text-xs">The tutor will now interview you to build your learning profile.</p>
                <button
                  class="px-4 py-1.5 border border-white/20 hover:bg-white/10 transition-colors text-xs"
                  onClick={startOnboarding}
                  disabled={setupStreaming()}
                >
                  Start Interview →
                </button>
              </div>
            </Show>

            <For each={setupMessages().slice(1)}>
              {(msg) => (
                <div
                  class="mb-3"
                  classList={{ "flex justify-end": msg.role === "user" }}
                >
                  <div
                    classList={{
                      "border border-white/20 px-3 py-1.5 bg-white/5 max-w-[85%] whitespace-pre-wrap break-words text-xs":
                        msg.role === "user",
                      "py-1 w-full text-xs": msg.role === "assistant",
                    }}
                  >
                    {msg.role === "assistant"
                      ? <MarkdownView content={msg.content} streaming={false} />
                      : msg.content}
                  </div>
                </div>
              )}
            </For>

            <Show when={error()}>
              <div class="border border-red-500/40 bg-red-500/10 text-red-300 px-3 py-2 mb-3 text-xs">
                {error()}
              </div>
            </Show>
          </div>

          <div class="px-3 pb-2">
            <div class="flex gap-2">
              <textarea
                class="flex-1 border border-white/20 px-3 py-2 bg-transparent text-[#e0e0e0] resize-none text-xs outline-none disabled:opacity-50"
                rows={2}
                placeholder="Type your answer... (Enter to send)"
                value={answer()}
                onInput={(e) => setAnswer(e.currentTarget.value)}
                onKeyDown={onKeyDown}
                disabled={setupStreaming()}
              />
            </div>
          </div>
        </div>
      </Show>

      <Show when={setupStep() === "done"}>
        <div class="flex-1 flex flex-col items-center justify-center gap-4 px-4">
          <div class="text-center">
            <h2 class="text-lg font-bold text-green-400 mb-3">Profile Created!</h2>
            <p class="text-[#6a6a6a] max-w-md text-xs">
              Your learning profile has been saved. The AI will now
              personalize every session based on your background,
              goals, and learning preferences.
            </p>
          </div>
          <button
            class="px-6 py-2 border border-white/20 hover:bg-white/10 transition-colors"
            onClick={completeSetup}
          >
            Launch Cognits →
          </button>
        </div>
      </Show>
    </div>
  )
}
