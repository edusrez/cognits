import { createSignal, createEffect, onCleanup, onMount, For } from "solid-js"

export interface MenuItem {
  label: string
  onClick: () => void
  class?: string
}

export default function ContextMenu(props: {
  items: MenuItem[]
  x: number
  y: number
  onClose: () => void
}) {
  const [hovered, setHovered] = createSignal<number | null>(null)
  const [pos, setPos] = createSignal({ x: props.x, y: props.y })
  let menuRef: HTMLDivElement | undefined

  // Reposicionar tras medir el menú para que no se salga del viewport.
  onMount(() => {
    if (!menuRef) return
    const rect = menuRef.getBoundingClientRect()
    setPos({
      x: Math.max(0, Math.min(props.x, window.innerWidth - rect.width)),
      y: Math.max(0, Math.min(props.y, window.innerHeight - rect.height)),
    })
  })

  createEffect(() => {
    setPos({ x: props.x, y: props.y })
    if (!menuRef) return
    const rect = menuRef.getBoundingClientRect()
    setPos({
      x: Math.max(0, Math.min(props.x, window.innerWidth - rect.width)),
      y: Math.max(0, Math.min(props.y, window.innerHeight - rect.height)),
    })
  })

  const handler = () => props.onClose()
  document.addEventListener("click", handler)
  onCleanup(() => document.removeEventListener("click", handler))

  return (
    <div
      ref={menuRef}
      class="fixed z-50 bg-[#1a1a1a] border border-white/20 shadow-lg min-w-[120px]"
      style={{ left: pos().x + "px", top: pos().y + "px" }}
      onClick={(e) => e.stopPropagation()}
    >
      <For each={props.items}>
        {(item, index) => (
          <button
            class={`w-full text-left px-3 py-1.5 text-[13px] cursor-pointer transition-colors${item.class ? " " + item.class : ""}`}
            classList={{ "bg-black/50": hovered() === index() }}
            onMouseEnter={() => setHovered(index())}
            onMouseLeave={() => setHovered(null)}
            onClick={item.onClick}
            onContextMenu={(e) => {
              e.preventDefault()
              e.stopPropagation()
              item.onClick()
            }}
          >
            {item.label}
          </button>
        )}
      </For>
    </div>
  )
}
