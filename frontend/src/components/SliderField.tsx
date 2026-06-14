import { Show, createSignal, type ParentProps } from "solid-js"

interface SliderFieldProps extends ParentProps {
  label: string
  value: number | string
  onInput: (value: number) => void
  min?: number
  max?: number
  step?: number
  formatValue?: (v: number) => string
  disabled?: boolean
  disabledHint?: string
}

export default function SliderField(props: SliderFieldProps) {
  const min = () => props.min ?? 0
  const max = () => props.max ?? 100
  const step = () => props.step ?? 1
  const display = () =>
    props.formatValue ? props.formatValue(Number(props.value)) : String(props.value)

  const [editing, setEditing] = createSignal(false)

  const startEdit = () => {
    if (props.disabled) return
    setEditing(true)
  }

  const commitEdit = () => setEditing(false)

  const onEditKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      (e.currentTarget as HTMLInputElement).blur()
    }
  }

  return (
    <div class="flex flex-col gap-1">
      <div class="flex items-center justify-between text-[#9a9a9a]">
        <span>{props.label}</span>
        <Show
          when={editing()}
          fallback={
            <span
              class="cursor-pointer hover:text-[#e0e0e0]"
              classList={{ "cursor-not-allowed opacity-40": props.disabled }}
              onClick={startEdit}
            >
              {display()}
            </span>
          }
        >
          <input
            type="number"
            min={min()}
            max={max()}
            step={step()}
            value={Number(props.value)}
            onInput={(e) => props.onInput(parseFloat(e.currentTarget.value))}
            onBlur={commitEdit}
            onKeyDown={onEditKeyDown}
            class="no-spinner bg-transparent border border-white/20 px-1 py-0 text-[13px] text-[#e0e0e0] outline-hidden focus:border-white/40 w-20"
            ref={(el) => {
              if (el) {
                el.focus()
                el.select()
              }
            }}
          />
        </Show>
      </div>
      <input
        type="range"
        min={min()}
        max={max()}
        step={step()}
        value={Number(props.value)}
        onInput={(e) => {
          setEditing(false)
          props.onInput(parseFloat(e.currentTarget.value))
        }}
        class="chat-font-slider"
        disabled={props.disabled}
      />
      <div class="flex justify-between text-[11px] text-[#6a6a6a]">
        <span>{min()}</span>
        <span>{max()}</span>
      </div>
      <Show when={props.disabled && props.disabledHint}>
        <div class="text-[11px] text-[#6a6a6a]">{props.disabledHint}</div>
      </Show>
    </div>
  )
}
