import FileTreeWrapper from "./FileTreeWrapper"
import Chat from "./components/Chat"
import Write from "./components/Write"
import Sessions from "./components/Sessions"
import Settings from "./components/Settings"
import SetupWizard from "./components/SetupWizard"
import ReportView from "./components/ReportView"
import LearnitView from "./components/LearnitView"
import NoteView from "./components/NoteView"
import CodeView from "./components/CodeView"
import TextView from "./components/TextView"
import ImageView from "./components/ImageView"
import PdfView from "./components/PdfView"
import {
  TAB_LABELS,
  isDynamicTab,
  baseTabId,
  dynamicPayload,
  tabKind,
  tabDisplayName,
} from "./lib/tab-kinds"

export type ViewportId = string

export interface TabDef {
  id: string
  label: string
  component: (props: { viewportId?: string; tabId?: string }) => any
  sessionScoped?: boolean
}

export const tabs: TabDef[] = [
  { id: "setup",    label: TAB_LABELS.setup,    component: SetupWizard },
  { id: "files",    label: TAB_LABELS.files,    component: FileTreeWrapper },
  { id: "sessions", label: TAB_LABELS.sessions, component: Sessions },
  { id: "chat",     label: TAB_LABELS.chat,     component: Chat, sessionScoped: true },
  { id: "write",    label: TAB_LABELS.write,    component: Write, sessionScoped: true },
  { id: "settings", label: TAB_LABELS.settings, component: Settings },
  { id: "report",   label: TAB_LABELS.report,   component: ReportView },
  { id: "note",     label: TAB_LABELS.note,     component: NoteView },
  { id: "learnit",  label: TAB_LABELS.learnit,  component: LearnitView },
  { id: "code",     label: TAB_LABELS.code,     component: CodeView },
  { id: "text",     label: TAB_LABELS.text,     component: TextView },
  { id: "image",    label: TAB_LABELS.image,    component: ImageView },
  { id: "pdf",      label: TAB_LABELS.pdf,      component: PdfView },
]

// Re-export identity helpers for a convenient single import surface.
// The canonical home is lib/tab-kinds.ts (a pure leaf module); the registry
// imports directly from there to avoid a cycle through the Settings component.
export { isDynamicTab, baseTabId, dynamicPayload, tabKind, tabDisplayName }
