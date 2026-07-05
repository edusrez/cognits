/** Centralized fetch wrapper for Cognits API calls.

Handles base URL, JSON parsing, error normalization, and auth header
pass-through. All stores should use this instead of raw fetch().
*/

export async function apiFetch<T = any>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });

  if (res.status === 204) {
    return undefined as T;
  }

  const body = await res.json().catch(() => ({}));

  if (!res.ok) {
    const msg = body?.message || body?.error || `HTTP ${res.status}`;
    const err = new Error(msg) as Error & { status: number; body: any };
    err.status = res.status;
    err.body = body;
    throw err;
  }

  return body as T;
}

/** Fire-and-forget fetch (don't await, don't throw). */
export function apiPostFireAndForget(path: string, body: unknown): void {
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(console.error);
}
