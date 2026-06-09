const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api";

export const apiConfig = {
  baseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL,
  timeoutMs: Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS ?? 20000),
} as const;

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), apiConfig.timeoutMs);

  try {
    const response = await fetch(`${apiConfig.baseUrl}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}.`);
    }

    const payload = await response.json();
    return payload?.success === true ? payload.data : payload;
  } finally {
    clearTimeout(timeout);
  }
}
