const EXT_TO_CATEGORY: Record<string, string> = {
  ".py": "code", ".js": "code", ".ts": "code", ".tsx": "code",
  ".jsx": "code", ".go": "code", ".rs": "code", ".java": "code",
  ".c": "code", ".cpp": "code", ".h": "code", ".hpp": "code",
  ".css": "code", ".scss": "code", ".less": "code", ".html": "code",
  ".htm": "code", ".xml": "code", ".json": "code", ".yaml": "code",
  ".yml": "code", ".toml": "code", ".ini": "code", ".cfg": "code",
  ".conf": "code", ".sql": "code", ".sh": "code", ".bash": "code",
  ".zsh": "code", ".php": "code", ".rb": "code", ".swift": "code",
  ".kt": "code", ".kts": "code", ".lua": "code", ".r": "code",
  ".dart": "code", ".erl": "code", ".ex": "code", ".exs": "code",
  ".hs": "code", ".scala": "code", ".clj": "code", ".cs": "code",
  ".vue": "code", ".svelte": "code", ".gd": "code",
  ".diff": "code", ".patch": "code", ".graphql": "code",
  ".gql": "code", ".proto": "code", ".md": "code",
  ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
  ".svg": "image", ".webp": "image", ".bmp": "image", ".ico": "image",
  ".pdf": "pdf",
}

export function getFileCategory(path: string): "code" | "text" | "image" | "pdf" {
  const ext = path.match(/\.[^.]+$/)?.[0]?.toLowerCase() ?? ""
  const name = path.split("/").pop()?.toLowerCase() ?? ""
  return (EXT_TO_CATEGORY[ext] || EXT_TO_CATEGORY[name] || "text") as "code" | "text" | "image" | "pdf"
}
