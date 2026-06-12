import { createSignal, onCleanup, For, createEffect } from "solid-js"

interface DropdownOption<T extends string> {
  value: T
  label: string
}

interface DropdownProps<T extends string> {
  value: T
  options: DropdownOption<T>[]
  onChange: (value: T) => void
  class?: string
  disabled?: boolean
}

export default function Dropdown<T extends string>(props: DropdownProps<T>) {
  const [open, setOpen] = createSignal(false)
  const [hovered, setHovered] = createSignal<number | null>(null)
  let containerRef!: HTMLDivElement

  const toggle = (e: MouseEvent) => {
    if (props.disabled) return
    e.stopPropagation()
    setOpen((p) => !p)
    setHovered(null)
  }

  const select = (index: number, e: MouseEvent) => {
    e.stopPropagation()
    props.onChange(props.options[index].value)
    setOpen(false)
    setHovered(null)
  }

  createEffect(() => {
    if (!open()) return
    const handler = () => {
      setOpen(false)
      setHovered(null)
    }
    document.addEventListener("click", handler)
    document.addEventListener("contextmenu", handler)
    onCleanup(() => {
      document.removeEventListener("click", handler)
      document.removeEventListener("contextmenu", handler)
    })
  })

  const selectedLabel = () =>
    props.options.find((o) => o.value === props.value)?.label ?? props.value

  return (
    <div ref={containerRef} class={`relative ${props.class ?? ""}`}>
      <button
        class="w-full flex items-center justify-between bg-transparent border border-white/20 px-2 py-1 text-[13px] transition-colors"
        classList={{
          "text-[#e0e0e0] hover:bg-white/5 cursor-pointer": !props.disabled,
          "text-[#4a4a4a] cursor-not-allowed": props.disabled,
        }}
        onClick={toggle}
        disabled={props.disabled}
      >
        <span>{selectedLabel()}</span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
          class="ml-2 shrink-0"
          classList={{ "rotate-180": open() }}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open() && (
        <div class="absolute z-50 mt-1 left-0 right-0 bg-[#1a1a1a] border border-white/20 shadow-lg">
          <For each={props.options}>
            {(option, index) => (
              <button
                class="w-full text-left px-3 py-1.5 text-[13px] cursor-pointer transition-colors"
                classList={{ "bg-black/50": hovered() === index() }}
                onMouseEnter={() => setHovered(index())}
                onMouseLeave={() => setHovered(null)}
                onClick={(e) => select(index(), e)}
                onContextMenu={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  select(index(), e)
                }}
              >
                {option.label}
              </button>
            )}
          </For>
        </div>
      )}
    </div>
  )
}

export type { DropdownOption, DropdownProps }
