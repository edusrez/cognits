import FileTreeWrapper from "./FileTreeWrapper"
import Chat from "./components/Chat"
import Write from "./components/Write"
import Sessions from "./components/Sessions"
import Settings from "./components/Settings"
import ReportView from "./components/ReportView"
import LearnitView from "./components/LearnitView"

export type ViewportId = string

export interface TabDef {
  id: string
  label: string
  component: (props: { viewportId?: string; tabId?: string }) => any
  sessionScoped?: boolean
}

export const tabs: TabDef[] = [
  { id: "files",    label: "Archivos", component: FileTreeWrapper },
  { id: "sessions", label: "Sesiones", component: Sessions },
  { id: "chat",     label: "Chat",     component: Chat, sessionScoped: true },
  { id: "write",    label: "Escribir", component: Write, sessionScoped: true },
  { id: "settings", label: "Ajustes",  component: Settings },
  { id: "report",   label: "Informe Web",  component: ReportView },
  { id: "learnit",  label: ".learnit",  component: LearnitView },
]
