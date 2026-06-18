import { createSignal, createEffect, onCleanup, onMount, For } from "solid-js"

export interface MenuItem {
  label: string
  onClick: () => void
  class?: string
  subItems?: MenuItem[]
}

export default function ContextMenu(props: {
  items: MenuItem[]
  x: number
  y: number
  onClose: () => void
}) {
  const [hovered, setHovered] = createSignal<number | null>(null)
  const [subHovered, setSubHovered] = createSignal<number | null>(null)
  const [pos, setPos] = createSignal({ x: props.x, y: props.y })
  let menuRef: HTMLDivElement | undefined

  const [subIndex, setSubIndex] = createSignal(-1)
  let itemRefs: (HTMLButtonElement | undefined)[] = []
  let subTimeout: ReturnType<typeof setTimeout> | null = null

  function openSub(idx: number) {
    if (subTimeout) { clearTimeout(subTimeout); subTimeout = null }
    setSubIndex(idx)
  }

  function scheduleCloseSub() {
    if (subTimeout) clearTimeout(subTimeout)
    subTimeout = setTimeout(() => { setSubIndex(-1); setSubHovered(null) }, 150)
  }

  function cancelCloseSub() {
    if (subTimeout) { clearTimeout(subTimeout); subTimeout = null }
  }

  // Reposition after measuring the menu so it doesn't overflow the viewport.
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

  const handler = () => { cancelCloseSub(); props.onClose() }
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
        {(item, index) => {
          const hasSub = () => !!(item.subItems && item.subItems.length > 0)
          return (
            <button
              ref={(el) => { itemRefs[index()] = el }}
              class={`w-full text-left px-3 py-1.5 text-[13px] cursor-pointer transition-colors${item.class ? " " + item.class : ""}`}
              classList={{ "bg-black/50": hovered() === index() }}
              onMouseEnter={() => { setHovered(index()); if (hasSub()) openSub(index()) }}
              onMouseLeave={() => { setHovered(null); if (hasSub()) scheduleCloseSub() }}
              onClick={(e) => { if (!hasSub()) { e.stopPropagation(); item.onClick() } }}
              onContextMenu={(e) => {
                e.preventDefault()
                e.stopPropagation()
                if (!hasSub()) item.onClick()
              }}
            >
              <span class="flex justify-between items-center w-full">
                <span>{item.label}</span>
                {hasSub() && <span class="text-[#5a5a5a] ml-3 text-sm">›</span>}
              </span>
            </button>
          )
        }}
      </For>

      {subIndex() >= 0 && (() => {
        const sub = props.items[subIndex()]?.subItems
        if (!sub) return null
        const btn = itemRefs[subIndex()]
        const sx = btn ? Math.min(btn.getBoundingClientRect().right + 4, window.innerWidth - 200) : pos().x + 180
        const sy = btn ? Math.max(0, Math.min(btn.getBoundingClientRect().top, window.innerHeight - (sub.length * 32 + 4))) : pos().y
        return (
          <div
            class="fixed z-50 bg-[#1a1a1a] border border-white/20 shadow-lg min-w-[120px]"
            style={{ left: sx + "px", top: sy + "px" }}
            onMouseEnter={cancelCloseSub}
            onMouseLeave={scheduleCloseSub}
            onClick={(e) => e.stopPropagation()}
          >
            <For each={sub}>
              {(sitem, sindex) => (
                <button
                  class="w-full text-left px-3 py-1.5 text-[13px] cursor-pointer transition-colors"
                  classList={{ "bg-black/50": subHovered() === sindex() }}
                  onMouseEnter={() => { cancelCloseSub(); setSubHovered(sindex()) }}
                  onMouseLeave={() => { setSubHovered(null); scheduleCloseSub() }}
                  onClick={(e) => { e.stopPropagation(); cancelCloseSub(); props.onClose(); sitem.onClick() }}
                  onContextMenu={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    cancelCloseSub()
                    props.onClose()
                    sitem.onClick()
                  }}
                >
                  {sitem.label}
                </button>
              )}
            </For>
          </div>
        )
      })()}
    </div>
  )
}
