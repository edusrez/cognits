import { streamSession, type StreamCallbacks } from "../lib/chat-stream"
import { setIsStreaming, setIsThinking, setChatError } from "./chat-store"

export class ChatConnection {
  private sid: string | null = null
  private controller: AbortController | null = null
  private version = 0
  private active = false

  get isActive(): boolean { return this.active }

  connect(sid: string, callbacks: StreamCallbacks, attempt = 0): void {
    if (this.sid === sid && this.active) return
    this.disconnect()
    this.sid = sid
    this.active = true
    this.version++
    const v = this.version
    const ctrl = new AbortController()
    this.controller = ctrl

    streamSession(sid, callbacks, ctrl.signal)
      .then(({ completed }) => {
        if (this.version !== v) return
        this.active = false
        if (completed) return
        if (attempt < 3) {
          setTimeout(() => {
            if (this.version === v) this.connect(sid, callbacks, attempt + 1)
          }, Math.min(1000 * Math.pow(2, attempt), 8000))
        }
      })
      .catch(() => {
        if (this.version !== v) return
        this.active = false
        this.controller = null
        setIsStreaming(false)
        setIsThinking(false)
      })
  }

  disconnect(): void {
    this.version++
    this.active = false
    this.controller?.abort()
    this.controller = null
  }
}
