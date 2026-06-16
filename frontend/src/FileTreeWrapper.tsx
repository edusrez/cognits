import { createSignal, onMount } from "solid-js"
import FileTree from "./FileTree"
import type { FileNode } from "./types"
import { addDynamicTab } from "./stores/viewport-tree-store"
import { getFileCategory } from "./lib/file-category"
import { defaultFilesViewport } from "./stores/settings-store"

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
    const category = getFileCategory(path)
    const name = path.split("/").pop() ?? path
    const tabId = `${category}:${path}`
    addDynamicTab(defaultFilesViewport(), {
      id: tabId,
      label: name,
      hidden: false,
    })
  }

  return <FileTree node={tree} onFileClick={handleFileClick} />
}
