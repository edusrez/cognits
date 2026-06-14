import { createSignal } from "solid-js"
import type { NoteData } from "../types"

export interface Note {
  id: string
  title: string
  content: string
  createdAt: string
  updatedAt: string
}

export const [notes, setNotes] = createSignal<Note[]>([])

export const [noteData, setNoteData] = createSignal<Record<string, NoteData>>({})

let notebookChannel: BroadcastChannel | null = null

try {
  notebookChannel = new BroadcastChannel("desktop-sync")
  notebookChannel.onmessage = (e: MessageEvent) => {
    if (e.data?.type === "NOTES_CHANGED") {
      loadNotes()
    }
  }
} catch {
  notebookChannel = null
}

function broadcastNotesChange() {
  if (notebookChannel) {
    notebookChannel.postMessage({ type: "NOTES_CHANGED" })
  }
}

export async function loadNotes() {
  const res = await fetch("/api/notes")
  if (res.ok) {
    setNotes(await res.json())
  }
}

export async function createNote(title: string): Promise<Note> {
  const res = await fetch("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  })
  const note: Note = await res.json()
  setNotes((prev) => [note, ...prev])
  broadcastNotesChange()
  return note
}

export async function deleteNote(id: string) {
  await fetch(`/api/notes/${id}`, { method: "DELETE" })
  setNotes((prev) => prev.filter((n) => n.id !== id))
  broadcastNotesChange()
}

export async function renameNote(id: string, title: string) {
  await fetch(`/api/notes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: title }),
  })
  setNotes((prev) =>
    prev.map((n) => (n.id === id ? { ...n, title } : n)),
  )
  broadcastNotesChange()
}

export async function loadNote(id: string): Promise<NoteData> {
  const existing = noteData()[id]
  if (existing) return existing

  const res = await fetch(`/api/notes/${id}`)
  if (!res.ok) throw new Error("note not found")
  const data: NoteData = await res.json()
  setNoteData((prev) => ({ ...prev, [id]: data }))
  return data
}

export async function saveNoteContent(id: string, content: string) {
  await fetch(`/api/notes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  })
  setNoteData((prev) => {
    const existing = prev[id]
    if (!existing) return prev
    return { ...prev, [id]: { ...existing, content } }
  })
  setNotes((prev) =>
    prev.map((n) => (n.id === id ? { ...n, updatedAt: "" } : n)),
  )
}

export async function openNoteInViewport(vpId: string, noteId: string) {
  const tabId = `note:${noteId}`
  const { addDynamicTab } = await import("../stores/viewport-tree-store")
  addDynamicTab(vpId, {
    id: tabId,
    label: "Note",
    hidden: false,
  })
}

export async function moveNote(itemId: string, insertIndex: number) {
  setNotes((prev) => {
    const fromIdx = prev.findIndex((n) => n.id === itemId)
    if (fromIdx < 0) return prev
    const item = prev[fromIdx]
    const rest = [...prev.slice(0, fromIdx), ...prev.slice(fromIdx + 1)]
    const clamped = Math.min(insertIndex, rest.length)
    return [...rest.slice(0, clamped), item, ...rest.slice(clamped)]
  })

  const order = notes().map((n) => n.id)
  await fetch("/api/notes/reorder", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order }),
  })
  broadcastNotesChange()
}
