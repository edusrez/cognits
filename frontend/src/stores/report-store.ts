import { createSignal } from "solid-js"

export interface ReportData {
  id: string
  title: string
  content: string
  sources: string[]
}

export const [reportData, setReportData] = createSignal<Record<string, ReportData>>({})

export async function loadReport(reportId: string): Promise<ReportData> {
  const existing = reportData()[reportId]
  if (existing) return existing

  const res = await fetch(`/api/reports/${reportId}`)
  if (!res.ok) throw new Error("report not found")
  const data: ReportData = await res.json()
  setReportData((prev) => ({ ...prev, [reportId]: data }))
  return data
}

export async function openReportInViewport(vpId: string, reportId: string) {
  const data = await loadReport(reportId)
  const tabId = `report:${reportId}`

  const { addDynamicTab } = await import("../stores/viewport-tree-store")

  addDynamicTab(vpId, {
    id: tabId,
    label: "Web Report",
    hidden: true,
  })
}

export function removeReportData(reportId: string) {
  setReportData((prev) => {
    const next = { ...prev }
    delete next[reportId]
    return next
  })
}
