import { frontendConfig } from "../config.js";
import { buildQueryString } from "../router.js";

class ApiError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = "ApiError";
    this.status = options.status || 0;
    this.code = options.code || "api_error";
    this.details = options.details || {};
    this.requestId = options.requestId || null;
  }
}

class ApiService {
  constructor(baseUrl, timeoutMs) {
    this.baseUrl = baseUrl;
    this.timeoutMs = timeoutMs;
  }

  async get(path, params) {
    return this.request("GET", path, { params });
  }

  async post(path, body) {
    return this.request("POST", path, {
      body: body !== undefined ? JSON.stringify(body) : undefined,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    });
  }

  async postFormData(path, formData) {
    return this.request("POST", path, { body: formData });
  }

  async put(path, body) {
    return this.request("PUT", path, {
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    });
  }

  async delete(path) {
    return this.request("DELETE", path);
  }

  async request(method, path, options = {}) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), this.timeoutMs);
    const query = options.params ? buildQueryString(options.params) : "";
    const url = `${this.baseUrl}${path}${query ? `?${query}` : ""}`;

    try {
      const response = await fetch(url, {
        method,
        headers: {
          Accept: "application/json",
          ...(options.headers || {}),
        },
        body: options.body,
        signal: controller.signal,
      });

      const contentType = response.headers.get("content-type") || "";
      const isJson = contentType.includes("application/json");
      const payload = isJson ? await response.json() : null;

      if (payload?.success === false) {
        throw new ApiError(payload.error || `Request failed with status ${response.status}.`, {
          status: response.status,
          code: payload.error_code,
          details: payload.details,
          requestId: payload.request_id,
        });
      }

      if (!response.ok) {
        const apiMessage =
          payload?.error ||
          payload?.detail?.[0]?.msg ||
          payload?.detail ||
          `Request failed with status ${response.status}.`;
        throw new ApiError(String(apiMessage), {
          status: response.status,
          code: payload?.error_code || "http_error",
          details: payload?.details || {},
          requestId: payload?.request_id || null,
        });
      }

      if (payload?.success === true) {
        return payload.data;
      }

      return payload;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new ApiError("The request timed out. Please try again.", {
          code: "request_timeout",
        });
      }
      if (error instanceof TypeError) {
        throw new ApiError("Unable to connect. Please try again.", {
          code: "network_error",
        });
      }
      throw error instanceof ApiError ? error : new ApiError(error.message || "Unexpected request failure.");
    } finally {
      window.clearTimeout(timeoutId);
    }
  }
}

export const apiService = new ApiService(frontendConfig.apiBaseUrl, frontendConfig.requestTimeoutMs);
export { ApiError };
