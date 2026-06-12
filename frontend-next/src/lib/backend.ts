import { apiConfig, backend } from "@/lib/api";

export type Status = "idle" | "loading" | "ready" | "error";

export type Agent = {
  agent_id: string;
  agent_name: string;
  purpose?: string;
};

export type TranscriptEntry = {
  entry_id: string;
  speaker: "agent" | "lead";
  text: string;
  timestamp: string;
  source: "deepgram" | "manual";
};

export type CallRecord = {
  call_id: string;
  lead_name: string;
  phone: string;
  email?: string | null;
  company?: string | null;
  city?: string | null;
  role?: string | null;
  interest?: string | null;
  agent_id: string;
  agent_name: string;
  call_objective: string;
  language: string;
  priority: "low" | "medium" | "high";
  call_type: "individual" | "campaign";
  campaign_id?: string | null;
  status: string;
  retry_count: number;
  meeting_requested: boolean;
  callback_requested: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  duration?: number | null;
  twilio_call_sid?: string | null;
  transcript: TranscriptEntry[];
  summary?: string | null;
  sentiment?: string | null;
  lead_type?: string | null;
  objections: string[];
  next_action?: string | null;
  short_notes?: string | null;
  meeting_time?: string | null;
  call_outcome?: string | null;
  outcome_reason?: string | null;
  ai_score?: number | null;
  processed_by_ai: boolean;
  ai_processing_status: string;
  ai_error?: string | null;
};

export type IndividualCallPayload = {
  lead_name: string;
  phone: string;
  email: string;
  company?: string | null;
  city?: string | null;
  role?: string | null;
  interest?: string | null;
  agent_id: string;
  call_objective: string;
  additional_context?: string | null;
  language: string;
  priority: "low" | "medium" | "high";
};

export type Campaign = {
  campaign_id: string;
  campaign_name: string;
  agent_id: string;
  agent_name: string;
  campaign_type: string;
  call_objective: string;
  language: string;
  priority: "low" | "medium" | "high";
  schedule_type: "immediate" | "scheduled";
  dispatch_mode: "parallel" | "one_by_one";
  status: string;
  total_contacts: number;
  completed_calls: number;
  successful_calls: number;
  failed_calls: number;
  retry_calls: number;
  pending_calls: number;
  active_calls: number;
  answered_calls: number;
  progress_percent?: number;
  progress_percentage?: number;
  success_rate: number;
  created_at?: string | null;
  updated_at?: string | null;
  scheduled_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  notes?: string | null;
  metadata: Record<string, unknown>;
};

export type CampaignPreviewRow = {
  row_number: number;
  name?: string | null;
  phone?: string | null;
  normalized_phone?: string | null;
  company?: string | null;
  email?: string | null;
  role?: string | null;
  interest?: string | null;
  validation_status: "valid" | "invalid" | "duplicate";
  validation_message: string;
};

export type CampaignPreview = {
  filename: string;
  file_type: string;
  total_rows: number;
  valid_contacts: number;
  invalid_contacts: number;
  duplicate_contacts: number;
  source_columns: string[];
  unmapped_columns: string[];
  preview_rows: CampaignPreviewRow[];
  contacts: Array<Record<string, unknown>>;
};

export type CallbackRecord = {
  callback_id: string;
  call_id?: string | null;
  campaign_id?: string | null;
  contact_id?: string | null;
  lead_name: string;
  phone: string;
  company?: string | null;
  agent_id: string;
  agent_name: string;
  call_objective: string;
  language: string;
  callback_reason: string;
  requested_time_raw: string;
  normalized_callback_time: string;
  timezone: string;
  priority: "high" | "medium" | "low";
  status: string;
  retry_count: number;
  source: string;
  created_at?: string | null;
  updated_at?: string | null;
  last_attempted_at?: string | null;
  completed_at?: string | null;
  notes?: string | null;
  next_action?: string | null;
};

export type MeetingRecord = {
  meeting_id: string;
  title: string;
  attendee_name?: string | null;
  attendee_phone?: string | null;
  attendee_email?: string | null;
  attendees: string[];
  scheduled_for: string;
  ends_at?: string | null;
  timezone: string;
  status: string;
  calendar_provider: "google" | "outlook" | "manual";
  event_link?: string | null;
  meet_link?: string | null;
  description?: string | null;
  notes?: string | null;
  delivery_status?: string | null;
  delivery_details?: Record<string, unknown>;
  call_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type MeetingCreatePayload = {
  full_name: string;
  phone: string;
  email: string;
  title: string;
  description: string;
  scheduled_for: string;
  timezone: string;
  notes?: string | null;
};

export type SummaryItem = {
  call_id: string;
  lead_name: string;
  phone: string;
  email?: string | null;
  call_date?: string | null;
  campaign_id?: string | null;
  final_status?: string | null;
  retry_count: number;
  summary?: string | null;
  sentiment?: string | null;
  lead_type?: string | null;
  call_outcome?: string | null;
  ai_score?: number | null;
  next_action?: string | null;
  meeting_time?: string | null;
  processed_by_ai: boolean;
  processed_at?: string | null;
  ai_processing_status: string;
  ai_error?: string | null;
};

export type SummaryDetail = SummaryItem & {
  company?: string | null;
  city?: string | null;
  role?: string | null;
  interest?: string | null;
  call_type: "individual" | "campaign";
  agent_id: string;
  agent_name: string;
  call_objective: string;
  language: string;
  priority: "low" | "medium" | "high";
  status: string;
  ended_at?: string | null;
  sentiment_confidence?: number | null;
  lead_confidence?: number | null;
  lead_reason?: string | null;
  objections: string[];
  short_notes?: string | null;
  outcome_reason?: string | null;
  transcript: TranscriptEntry[];
};

export type Health = {
  status?: string;
  backend?: string;
  firebase?: string;
  twilio?: string;
  deepgram?: string;
  details?: Record<string, unknown>;
};

type ModuleStatus = {
  module?: string;
  status?: string;
};

type PlatformDataKey = "calls" | "campaigns" | "callbacks" | "meetings" | "summaries" | "agents" | "health";

export type PlatformData = {
  calls: CallRecord[];
  campaigns: Campaign[];
  callbacks: CallbackRecord[];
  meetings: MeetingRecord[];
  summaries: SummaryItem[];
  agents: Agent[];
  health: Health | null;
  errors: Partial<Record<PlatformDataKey, string>>;
};

export type PlatformRealtimeEvent = {
  topic: string;
  action: string;
  payload?: {
    collection?: string;
    id?: string;
    call_id?: string;
    record?: CallRecord;
  };
  emitted_at?: string;
};

export function platformEventStreamUrl(token?: string) {
  const url = new URL(
    `${apiConfig.baseUrl.replace(/\/$/, "")}/events/stream`,
    typeof window === "undefined" ? "http://localhost:5501" : window.location.origin,
  );
  if (token) {
    url.searchParams.set("token", token);
  }
  return url.toString();
}

export async function loadPlatformData(): Promise<PlatformData> {
  const entries = await Promise.allSettled([
    backend.get<CallRecord[]>("/calls"),
    backend.get<Campaign[]>("/campaigns"),
    backend.get<CallbackRecord[]>("/callbacks"),
    backend.get<MeetingRecord[]>("/meetings?sync_google=false"),
    backend.get<SummaryItem[]>("/summaries"),
    backend.get<Agent[]>("/agents"),
    backend.get<ModuleStatus>("/twilio"),
  ]);

  const errors: PlatformData["errors"] = {};
  const isOptionalProtectedError = (key: PlatformDataKey, error: unknown) => {
    if (key !== "meetings") {
      return false;
    }
    const message = error instanceof Error ? error.message : String(error);
    return /firebase bearer token|required to access/i.test(message);
  };

  const unpack = <T>(index: number, key: PlatformDataKey, fallback: T): T => {
    const entry = entries[index];
    if (entry.status === "fulfilled") {
      return entry.value as T;
    }
    if (isOptionalProtectedError(key, entry.reason)) {
      return fallback;
    }
    errors[key] = entry.reason instanceof Error ? entry.reason.message : "Unable to load data.";
    return fallback;
  };

  return {
    calls: unpack(0, "calls", []),
    campaigns: unpack(1, "campaigns", []),
    callbacks: unpack(2, "callbacks", []),
    meetings: unpack(3, "meetings", []),
    summaries: unpack(4, "summaries", []),
    agents: unpack(5, "agents", []),
    health: unpack<ModuleStatus | null>(6, "health", null)
      ? { status: "ready", backend: "healthy" }
      : null,
    errors,
  };
}

export const services = {
  startIndividualCall(payload: IndividualCallPayload) {
    return backend.post<CallRecord>("/calls/individual", payload);
  },
  previewLeads(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    return backend.postFormData<CampaignPreview>("/campaigns/preview-leads", formData);
  },
  createCampaign(payload: Record<string, unknown>) {
    return backend.post<Campaign>("/campaigns", payload);
  },
  startCampaign(campaignId: string) {
    return backend.post<Campaign>(`/campaigns/${campaignId}/start`);
  },
  pauseCampaign(campaignId: string) {
    return backend.post<Campaign>(`/campaigns/${campaignId}/pause`);
  },
  resumeCampaign(campaignId: string) {
    return backend.post<Campaign>(`/campaigns/${campaignId}/resume`);
  },
  stopCampaign(campaignId: string) {
    return backend.post<Campaign>(`/campaigns/${campaignId}/stop`);
  },
  executeCallback(callbackId: string) {
    return backend.post<CallbackRecord>(`/callbacks/${callbackId}/execute`);
  },
  updateCallback(callbackId: string, payload: Record<string, unknown>) {
    return backend.put<CallbackRecord>(`/callbacks/${callbackId}`, payload);
  },
  syncMeetings() {
    return backend.post<{ synced: number; meetings: MeetingRecord[] }>("/meetings/sync");
  },
  createMeeting(payload: MeetingCreatePayload) {
    return backend.post<MeetingRecord>("/meetings", payload);
  },
  markMeetingDone(meetingId: string) {
    return backend.post<MeetingRecord>(`/meetings/${meetingId}/done`);
  },
  cancelMeeting(meetingId: string, reason: string) {
    return backend.post<{ meeting: MeetingRecord }>(`/meetings/${meetingId}/cancel`, { reason });
  },
  getCall(callId: string) {
    return backend.get<CallRecord>(`/calls/${callId}`);
  },
  getSummary(callId: string) {
    return backend.get<SummaryDetail>(`/summaries/${callId}`);
  },
};
