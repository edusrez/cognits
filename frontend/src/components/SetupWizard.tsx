import { createSignal, createEffect, Show, For, onCleanup } from "solid-js"
import { setupStep, setSetupStep, setupMessages, setSetupMessages, setupStreaming, setSetupStreaming, finishSetup } from "../stores/setup-store"
import { llmApiKey, loadConfig } from "../stores/settings-store"
import { createDefaultTree } from "../stores/viewport-tree-store"
import type { ChatMessage } from "../lib/chat-stream"
import MarkdownView from "./MarkdownView"

export default function SetupWizard() {
  const [answer, setAnswer] = createSignal("")
  const [error, setError] = createSignal("")
  let scrollRef!: HTMLDivElement
  let abortCtrl: AbortController | null = null

  createEffect(() => {
    if (setupStep() === "apikeys" && llmApiKey()) {
      setSetupStep("onboarding")
    }
  })

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

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }

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
            const data = line.slice(6)
            try {
              const parsed = JSON.parse(data)
              if (parsed.choices?.[0]?.delta?.content) {
                currentResponse += parsed.choices[0].delta.content
                setSetupMessages((prev) => {
                  const msgs = [...prev]
                  const last = msgs[msgs.length - 1]
                  if (last && last.role === "assistant") {
                    msgs[msgs.length - 1] = { ...last, content: currentResponse }
                  } else {
                    msgs.push({ role: "assistant", content: currentResponse })
                    scrollBottom()
                  }
                  return msgs
                })
                scrollBottom()
              }
            } catch { /* ignore parse errors */ }
          } else if (line.startsWith("event: ")) {
            const evt = line.slice(7)
            if (evt === "error") {
              // error data follows
            } else if (evt === "done") {
              break
            }
          }
        }
      }

      if (currentResponse) {
        setSetupMessages((prev) => {
          const msgs = [...prev]
          const last = msgs[msgs.length - 1]
          if (last && last.role === "assistant") {
            msgs[msgs.length - 1] = { ...last, content: currentResponse }
          }
          return msgs
        })
      }
    } catch (e: any) {
      if (e.name !== "AbortError") {
        setError(e.message || "Connection failed")
      }
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
      const body = { messages: [...msgs, { role: "user", content: text }] }

      const res = await fetch("/api/setup/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: abortCtrl.signal,
      })

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }

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
            const data = line.slice(6)
            try {
              const parsed = JSON.parse(data)
              if (parsed.choices?.[0]?.delta?.content) {
                currentResponse += parsed.choices[0].delta.content
                setSetupMessages((prev) => {
                  const msgs = [...prev]
                  const last = msgs[msgs.length - 1]
                  if (last && last.role === "assistant") {
                    msgs[msgs.length - 1] = { ...last, content: currentResponse }
                  } else {
                    msgs.push({ role: "assistant", content: currentResponse })
                    scrollBottom()
                  }
                  return msgs
                })
                scrollBottom()
              }
            } catch { /* ignore */ }
          } else if (line.startsWith("event: ")) {
            const evt = line.slice(7)
            if (evt === "done") {
              break
            }
          }
        }
      }

      if (currentResponse) {
        setSetupMessages((prev) => {
          const msgs = [...prev]
          const last = msgs[msgs.length - 1]
          if (last && last.role === "assistant") {
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
      if (e.name !== "AbortError") {
        setError(e.message || "Connection failed")
      }
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
    createDefaultTree("1")
  }

  return (
    <div class="h-full flex flex-col text-[#c0c0c0] text-sm">
      <Show when={setupStep() === "welcome"}>
        <div class="flex-1 flex flex-col items-center justify-center gap-6 px-8">
          <div class="text-center">
            <h1 class="text-2xl font-bold mb-2">Welcome to Cognits</h1>
            <p class="text-[#6a6a6a] max-w-md">
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
        <div class="flex-1 flex flex-col items-center justify-center gap-6 px-8">
          <div class="text-center max-w-md">
            <h2 class="text-lg font-semibold mb-4">Configure your AI Provider</h2>
            <p class="text-[#6a6a6a] mb-4">
              Open the Settings tab and add your DeepSeek API key.
              Optionally, add a TinyFish API key for web research.
            </p>
            <p class="text-[#6a6a6a]">
              The key is encrypted and stored only on your machine.
            </p>
          </div>
          <button
            class="px-6 py-2 border border-white/20 hover:bg-white/10 transition-colors"
            onClick={() => {
              const el = document.querySelector("[data-tab-id='settings']") as HTMLElement | null
              el?.click()
            }}
          >
            Open Settings →
          </button>
          <Show when={llmApiKey()}>
            <p class="text-green-400">API key configured. Advancing...</p>
          </Show>
        </div>
      </Show>

      <Show when={setupStep() === "onboarding"}>
        <div
          ref={scrollRef}
          class="flex-1 overflow-y-auto overflow-x-hidden px-4 py-3"
        >
          <Show when={setupMessages().length <= 1}>
            <div class="flex-1 flex flex-col items-center justify-center h-full gap-4">
              <p class="text-[#6a6a6a]">The tutor will now interview you to build your learning profile.</p>
              <button
                class="px-6 py-2 border border-white/20 hover:bg-white/10 transition-colors"
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
                class="mb-4"
                classList={{
                  "flex justify-end": msg.role === "user",
                }}
              >
                <div
                  classList={{
                    "border border-white/20 px-3 py-1.5 bg-white/5 max-w-[85%] whitespace-pre-wrap break-words":
                      msg.role === "user",
                    "py-1 w-full": msg.role === "assistant",
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
            <div class="border border-red-500/40 bg-red-500/10 text-red-300 px-3 py-2 mb-3">
              {error()}
            </div>
          </Show>
        </div>

        <div class="px-4 pb-3">
          <div class="flex gap-2">
            <textarea
              class="flex-1 border border-white/20 px-3 py-2 bg-transparent text-[#e0e0e0] resize-none text-sm outline-none disabled:opacity-50"
              rows={2}
              placeholder="Type your answer... (Enter to send)"
              value={answer()}
              onInput={(e) => setAnswer(e.currentTarget.value)}
              onKeyDown={onKeyDown}
              disabled={setupStreaming()}
            />
          </div>
        </div>
      </Show>

      <Show when={setupStep() === "done"}>
        <div class="flex-1 flex flex-col items-center justify-center gap-6 px-8">
          <div class="text-center">
            <h2 class="text-xl font-bold text-green-400 mb-4">Profile Created!</h2>
            <p class="text-[#6a6a6a] max-w-md">
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
