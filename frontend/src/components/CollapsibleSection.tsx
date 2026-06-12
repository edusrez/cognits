import { createSignal, type ParentProps } from "solid-js"

interface CollapsibleSectionProps extends ParentProps {
  title: string
  defaultOpen?: boolean
}

export default function CollapsibleSection(props: CollapsibleSectionProps) {
  const [open, setOpen] = createSignal(props.defaultOpen ?? false)

  return (
    <div>
      <button
        class="w-full text-left flex items-center justify-between text-[13px] text-[#6a6a6a] uppercase tracking-wider hover:text-[#9a9a9a] transition-colors cursor-pointer"
        onClick={() => setOpen((p) => !p)}
      >
        <span>{props.title}</span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
          class="transition-transform"
          classList={{ "rotate-90": open() }}
        >
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>
      {open() && <div class="mt-2">{props.children}</div>}
    </div>
  )
}
