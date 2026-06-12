import { createSignal, onMount } from "solid-js"
import FileTree from "./FileTree"
import type { FileNode } from "./types"

export default function FileTreeWrapper() {
  const [tree, setTree] = createSignal<FileNode | null>(null)

  onMount(async () => {
    try {
      const res = await fetch("/api/tree")
      setTree(await res.json())
    } catch (err) {
      console.error(err)
    }
  })

  return <FileTree node={tree} />
}
