import { createSignal, For, Show } from "solid-js"
import type { FileNode } from "./types"

function ChevronRight() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M9 18l6-6-6-6" />
    </svg>
  )
}

function ChevronDown() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M6 9l6 6 6-6" />
    </svg>
  )
}

function FolderIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
    </svg>
  )
}

function FileIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}

export default function FileTree(props: {
  node: () => FileNode | null
  onFileClick?: (path: string) => void
}) {
  return (
    <div style="padding: 4px 0">
      <Show when={props.node()}>
        {(n) => <NodeView node={n()} depth={0} onFileClick={props.onFileClick} />}
      </Show>
    </div>
  )
}

function ToggleIcon(props: { expanded: boolean }) {
  return (
    <span style={{ display: "inline-flex", "align-items": "center", width: "14px", color: "#6a6a6a" }}>
      {props.expanded ? <ChevronDown /> : <ChevronRight />}
    </span>
  )
}

function NodeView(props: { node: FileNode; depth: number; onFileClick?: (path: string) => void }) {
  const isRoot = props.depth === 0
  const [expanded, setExpanded] = createSignal(isRoot)
  const hasKids = props.node.isDir && props.node.children && props.node.children.length > 0

  function handleClick() {
    if (isRoot && hasKids) {
      // root always expanded, do nothing
    } else if (hasKids) {
      setExpanded(!expanded())
    } else if (!props.node.isDir) {
      props.onFileClick?.(props.node.path)
    }
  }

  return (
    <>
      <div
        style={{
          cursor: isRoot ? "default" : "pointer",
          padding: `1px 8px 1px ${8 + props.depth * 14}px`,
          "font-size": "13px",
          "line-height": "1.5",
          "white-space": "nowrap",
          overflow: "hidden",
          "text-overflow": "ellipsis",
          display: "flex",
          "align-items": "center",
          gap: "4px",
        }}
        onClick={handleClick}
      >
        <Show when={!isRoot && hasKids} fallback={
          <span style={{ display: "inline-flex", "align-items": "center", width: "14px" }}>
            {props.node.isDir ? (
              <span style={{ color: "#6a6a6a" }}><FolderIcon /></span>
            ) : (
              <span style={{ color: "#6a6a6a" }}><FileIcon /></span>
            )}
          </span>
        }>
          <ToggleIcon expanded={expanded()} />
        </Show>
        <span style={{ color: "#e0e0e0" }}>{props.node.name}</span>
      </div>
      <Show when={hasKids && (isRoot || expanded())}>
        <For each={props.node.children}>
          {(child) => <NodeView node={child} depth={props.depth + 1} onFileClick={props.onFileClick} />}
        </For>
      </Show>
    </>
  )
}
