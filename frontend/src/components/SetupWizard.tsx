import { Show } from "solid-js"
import { setupStep, setSetupStep, finishSetup } from "../stores/setup-store"
import { llmApiKey } from "../stores/settings-store"
import { setTabHidden, setLinkedViewport } from "../stores/viewport-tree-store"

export default function SetupWizard() {

  function openSettings() {
    setTabHidden("111", "settings", false)
  }

  function beginInterview() {
    setTabHidden("1100", "setup", true)
    setTabHidden("1100", "chat", false)
    setTabHidden("1101", "write", false)
    setLinkedViewport("1100")
    setSetupStep("onboarding")
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
            onClick={beginInterview}
          >
            Continue to Interview →
          </button>
          <Show when={!llmApiKey()}>
            <p class="text-[#6a6a6a] text-xs">Configure your API key in Settings to continue.</p>
          </Show>
        </div>
      </Show>

      <Show when={setupStep() === "onboarding"}>
        <div class="flex-1 flex flex-col items-center justify-center gap-4 px-4">
          <div class="text-center max-w-md">
            <h2 class="text-base font-semibold mb-3">Interview in Chat</h2>
            <p class="text-[#6a6a6a] mb-2 text-xs">
              The Setup tab has been replaced with the Chat tab in this viewport.
              Switch to the Chat tab and start the conversation.
            </p>
            <p class="text-[#6a6a6a] text-xs">
              The AI will interview you to build your learning profile.
              When enough information is gathered, it will present a summary
              and you can return here to launch Cognits.
            </p>
          </div>
          <button
            class="px-6 py-2 border border-white/20 hover:bg-white/10 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            onClick={() => {
              setSetupStep("done")
              finishSetup()
            }}
          >
            Skip Interview & Launch →
          </button>
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
            onClick={finishSetup}
          >
            Launch Cognits →
          </button>
        </div>
      </Show>
    </div>
  )
}
