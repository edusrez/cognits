import { createSignal, createResource, createMemo, batch } from "solid-js"

export interface ReportListItem {
  id: string
  sessionId: string
  title: string
  content: string
  summary: string
  sources: string[]
  subagent: string
  createdAt: string
}

interface SearchResult {
  reports: ReportListItem[]
  total: number
  page: number
  totalPages: number
}

export const [searchQuery, setSearchQuery] = createSignal("")
export const [sortBy, setSortBy] = createSignal("date_desc")
export const [currentPage, setCurrentPage] = createSignal(1)

let debounceTimer: ReturnType<typeof setTimeout> | null = null

export const [searchResults, { refetch: refetchReports }] = createResource(
  createMemo(() => ({
    page: currentPage(),
    sort: sortBy(),
    search: searchQuery(),
  })),
  async ({ page, sort, search }) => {
    const params = new URLSearchParams({
      page: String(page),
      limit: "10",
      sort,
    })
    if (search) params.set("search", search)

    const res = await fetch(`/api/reports?${params}`)
    if (!res.ok) return { reports: [], total: 0, page: 1, totalPages: 1 } as SearchResult
    return res.json() as Promise<SearchResult>
  },
)

// El createResource ya reacciona al memo fuente: basta con actualizar las
// señales (en batch, para un único fetch). refetchReports queda solo para
// recargar tras acciones sin cambio de señal (p. ej. borrar un informe).
export function setSearch(value: string) {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    batch(() => {
      setSearchQuery(value)
      setCurrentPage(1)
    })
  }, 200)
}

export function setSort(value: string) {
  batch(() => {
    setSortBy(value)
    setCurrentPage(1)
  })
}

export function goToPage(page: number) {
  setCurrentPage(page)
}

export const reports = createMemo(() => searchResults()?.reports ?? [])
export const totalPages = createMemo(() => searchResults()?.totalPages ?? 1)
export const totalResults = createMemo(() => searchResults()?.total ?? 0)
