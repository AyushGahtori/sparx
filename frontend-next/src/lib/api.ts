const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api";

export const apiConfig = {
  baseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL,
  timeoutMs: Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS ?? 120000),
} as const;

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort(new DOMException("Request timed out. The backend may still be starting the call.", "TimeoutError"));
  }, apiConfig.timeoutMs);

  try {
    const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
    const response = await fetch(`${apiConfig.baseUrl}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body && !isFormData ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
      signal: controller.signal,
    });

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const message =
        typeof payload === "object" && payload && "error" in payload
          ? String(payload.error)
          : typeof payload === "object" && payload && "detail" in payload
            ? String(payload.detail)
            : `Request failed with status ${response.status}.`;
      throw new Error(message);
    }

    return payload?.success === true ? payload.data : payload;
  } catch (error) {
    if (error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError")) {
      throw new Error("The request timed out while waiting for the backend. Please refresh the call status before trying again.");
    }
    if (error instanceof Error && /aborted|abortsignal|signal is aborted/i.test(error.message)) {
      throw new Error("The request was cancelled before the backend responded. Please refresh the call status before trying again.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export const backend = {
  get<T>(path: string) {
    return apiRequest<T>(path);
  },
  post<T>(path: string, body?: unknown) {
    return apiRequest<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  },
  put<T>(path: string, body: unknown) {
    return apiRequest<T>(path, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },
  delete<T>(path: string) {
    return apiRequest<T>(path, { method: "DELETE" });
  },
  postFormData<T>(path: string, formData: FormData) {
    return apiRequest<T>(path, {
      method: "POST",
      body: formData,
    });
  },
};
