import {
  type Agent,
  type CallbackRecord,
  type CallRecord,
  type Campaign,
  type MeetingRecord,
  type PlatformData,
  type SummaryItem,
} from "@/lib/backend";

const BACKEND_API_BASE = process.env.SPARX_BACKEND_API_BASE ?? "http://127.0.0.1:8000/api";
const SERVER_FETCH_TIMEOUT_MS = Number(process.env.SPARX_SERVER_FETCH_TIMEOUT_MS ?? 10000);

type PlatformDataErrorKey = keyof PlatformData["errors"];

type EndpointConfig<T> = {
  key: PlatformDataErrorKey;
  path: string;
  fallback: T;
};

type ModuleStatus = {
  module?: string;
  status?: string;
};

async function fetchBackend<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), SERVER_FETCH_TIMEOUT_MS);

  try {
    const response = await fetch(`${BACKEND_API_BASE.replace(/\/$/, "")}${path}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
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
  } finally {
    clearTimeout(timeout);
  }
}

export async function loadInitialPlatformData(): Promise<PlatformData> {
  const callsEndpoint: EndpointConfig<CallRecord[]> = { key: "calls", path: "", fallback: [] };
  const campaignsEndpoint: EndpointConfig<Campaign[]> = { key: "campaigns", path: "", fallback: [] };
  const callbacksEndpoint: EndpointConfig<CallbackRecord[]> = { key: "callbacks", path: "", fallback: [] };
  const meetingsEndpoint: EndpointConfig<MeetingRecord[]> = { key: "meetings", path: "", fallback: [] };
  const summariesEndpoint: EndpointConfig<SummaryItem[]> = { key: "summaries", path: "", fallback: [] };
  const agentsEndpoint: EndpointConfig<Agent[]> = { key: "agents", path: "", fallback: [] };
  const healthEndpoint: EndpointConfig<ModuleStatus | null> = { key: "health", path: "", fallback: null };
  const endpoints = [
    callsEndpoint,
    campaignsEndpoint,
    callbacksEndpoint,
    meetingsEndpoint,
    summariesEndpoint,
    agentsEndpoint,
    healthEndpoint,
  ];

  const settled = await Promise.allSettled(
    endpoints.map((endpoint) => (endpoint.path ? fetchBackend(endpoint.path) : Promise.resolve(endpoint.fallback))),
  );
  const errors: PlatformData["errors"] = {};
  const isProtectedAuthError = (error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    return /firebase bearer token|required to access/i.test(message);
  };

  const value = <T>(index: number, endpoint: EndpointConfig<T>): T => {
    const entry = settled[index];
    if (entry.status === "fulfilled") {
      return entry.value as T;
    }
    if (isProtectedAuthError(entry.reason)) {
      return endpoint.fallback;
    }
    errors[endpoint.key] = entry.reason instanceof Error ? entry.reason.message : "Unable to load data.";
    return endpoint.fallback;
  };

  return {
    calls: value(0, callsEndpoint),
    campaigns: value(1, campaignsEndpoint),
    callbacks: value(2, callbacksEndpoint),
    meetings: value(3, meetingsEndpoint),
    summaries: value(4, summariesEndpoint),
    agents: value(5, agentsEndpoint),
    health: value(6, healthEndpoint) ? { status: "ready", backend: "healthy" } : null,
    errors,
  };
}
