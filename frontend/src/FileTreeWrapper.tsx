import { createSignal, onMount } from "solid-js"
import FileTree from "./FileTree"
import type { FileNode } from "./types"
import { addDynamicTab } from "./stores/viewport-tree-store"
import { getFileCategory } from "./lib/file-category"

export default function FileTreeWrapper(props: { viewportId?: string; tabId?: string }) {
  const [tree, setTree] = createSignal<FileNode | null>(null)

  onMount(async () => {
    try {
      const res = await fetch("/api/tree")
      setTree(await res.json())
    } catch (err) {
      console.error(err)
    }
  })

  function handleFileClick(path: string) {
    console.log("[FileTreeWrapper] handleFileClick called", { path, viewportId: props.viewportId })
    if (!props.viewportId) {
      console.warn("[FileTreeWrapper] viewportId is undefined — tab not opened")
      return
    }
    const category = getFileCategory(path)
    const name = path.split("/").pop() ?? path
    const tabId = `${category}:${path}`
    console.log("[FileTreeWrapper] opening tab", { viewportId: props.viewportId, tabId, label: name })
    addDynamicTab(props.viewportId, {
      id: tabId,
      label: name,
      hidden: false,
    })
  }

  return <FileTree node={tree} onFileClick={handleFileClick} />
}
