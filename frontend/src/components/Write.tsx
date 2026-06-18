import { createMemo } from "solid-js"
import { sendMessage, isStreaming } from "../stores/chat-store"
import { writeLangs, llmApiKey } from "../stores/settings-store"

export default function Write() {
  const lang = createMemo(() => writeLangs()[0] || "en")
  const spellcheck = createMemo(() => writeLangs().length > 0)
  const hasApiKey = createMemo(() => llmApiKey() !== "")

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      if (!e.ctrlKey && !e.shiftKey) {
        e.preventDefault()
        const target = e.currentTarget as HTMLTextAreaElement
        const content = target.value.trim()
        if (content && !isStreaming()) {
          sendMessage(content)
          target.value = ""
        }
      } else if (e.shiftKey) {
        e.preventDefault()
        const target = e.currentTarget as HTMLTextAreaElement
        const start = target.selectionStart
        const end = target.selectionEnd
        target.value = target.value.substring(0, start) + "\n" + target.value.substring(end)
        target.selectionStart = target.selectionEnd = start + 1
      }
    }
  }

  return (
    <div class="h-full p-2">
      <textarea
        onKeyDown={onKeyDown}
        spellcheck={spellcheck()}
        lang={lang()}
        class="border border-white/20 px-3 py-3 text-[13px] bg-transparent text-[#e0e0e0] w-full h-full resize-none outline-none disabled:opacity-50"
        placeholder={!hasApiKey() ? "Configure an API key in Settings before chatting" : isStreaming() ? "AI is responding..." : "Type your message... (Enter to send, Shift+Enter for new line)"}
        disabled={isStreaming() || !hasApiKey()}
      />
    </div>
  )
}
