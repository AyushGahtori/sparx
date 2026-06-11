"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  AlertCircle,
  ArrowUpRight,
  CalendarCheck,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Clock3,
  Download,
  Folder,
  Phone,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  Upload,
  User,
} from "lucide-react";
import {
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  AppShell,
  AssetFrame,
  EmptyState,
  GreetingHeader,
  PageCanvas,
  PrimaryButton,
  ScrollPanel,
  StatCard,
  StatusBadge,
  previewIcons,
} from "@/components/design-system";
import { cn } from "@/lib/cn";
import {
  type CallbackRecord,
  type CallRecord,
  type Campaign,
  type CampaignPreview,
  type IndividualCallPayload,
  type MeetingRecord,
  type PlatformRealtimeEvent,
  type PlatformData,
  type SummaryDetail,
  loadPlatformData,
  platformEventStreamUrl,
  services,
} from "@/lib/backend";

const activeCallStatuses = new Set(["initiated", "ringing", "answered", "in_progress"]);
const completedCallStatuses = new Set(["completed", "callback_requested", "meeting_requested"]);
const unansweredStatuses = new Set(["no_answer", "busy", "failed"]);
const hangedUpStatuses = new Set(["failed", "cancelled"]);
const emptyCalls: CallRecord[] = [];
const emptyCampaigns: Campaign[] = [];
const emptyCallbacks: CallbackRecord[] = [];
const emptyMeetings: MeetingRecord[] = [];
const emptySummaries: PlatformData["summaries"] = [];
const emptyAgents: PlatformData["agents"] = [];

type PageDataProps = {
  initialData?: PlatformData;
};

function usePlatformData(initialData?: PlatformData) {
  const [data, setData] = useState<PlatformData | null>(initialData ?? null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(initialData ? "ready" : "loading");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setStatus("loading");
    try {
      const nextData = await loadPlatformData();
      setData(nextData);
      setStatus("ready");
      setError("");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Unable to load backend data.");
    }
  }, []);

  useEffect(() => {
    let eventSource: EventSource | null = null;

    const applyEvent = (event: PlatformRealtimeEvent) => {
      if (event.topic === "call.deleted") {
        const callId = event.payload?.call_id || event.payload?.id;
        if (!callId) return;
        setData((current) => current ? { ...current, calls: current.calls.filter((call) => call.call_id !== callId) } : current);
        return;
      }

      if (event.topic !== "call.updated" || !event.payload?.record) {
        return;
      }

      const record = event.payload.record;
      setData((current) => {
        const base = current ?? {
          calls: [],
          campaigns: emptyCampaigns,
          callbacks: emptyCallbacks,
          meetings: emptyMeetings,
          summaries: emptySummaries,
          agents: emptyAgents,
          health: null,
          errors: {},
        };
        const existingIndex = base.calls.findIndex((call) => call.call_id === record.call_id);
        const calls = existingIndex >= 0
          ? base.calls.map((call, index) => index === existingIndex ? record : call)
          : [record, ...base.calls];
        const errors = { ...base.errors };
        delete errors.calls;
        return { ...base, calls, errors };
      });
      setStatus("ready");
      setError("");
    };

    const connect = () => {
      if (eventSource || (typeof document !== "undefined" && document.visibilityState === "hidden")) {
        return;
      }
      eventSource = new EventSource(platformEventStreamUrl());
      eventSource.addEventListener("call.updated", (message) => {
        applyEvent(JSON.parse(message.data) as PlatformRealtimeEvent);
      });
      eventSource.addEventListener("call.deleted", (message) => {
        applyEvent(JSON.parse(message.data) as PlatformRealtimeEvent);
      });
      eventSource.onerror = () => {
        eventSource?.close();
        eventSource = null;
      };
    };

    const disconnect = () => {
      eventSource?.close();
      eventSource = null;
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        connect();
      } else {
        disconnect();
      }
    };

    connect();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      disconnect();
    };
  }, []);

  return { data, status, error, refresh };
}

function formatNumber(value: number | undefined | null) {
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value ?? 0);
}

function formatDate(value?: string | null) {
  if (!value) return "Date pending";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date pending";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatTime(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatDateTime(value?: string | null) {
  const time = formatTime(value);
  return `${formatDate(value)}${time ? `, ${time}` : ""}`;
}

function formatDuration(seconds?: number | null) {
  if (!seconds) return "0 sec";
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return minutes ? `${minutes}m ${remaining}s` : `${remaining}s`;
}

function humanize(value?: string | null) {
  return value ? value.replace(/_/g, " ") : "Pending";
}

function shortText(value?: string | null, fallback = "No details recorded yet.") {
  return value?.trim() || fallback;
}

function currentMonthLabel() {
  return new Intl.DateTimeFormat("en-IN", { month: "short", year: "numeric" }).format(new Date());
}

const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function currentMonthValue() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function monthValueLabel(value: string) {
  const [year, month] = value.split("-");
  const monthIndex = Number(month) - 1;
  if (!year || monthIndex < 0 || monthIndex > 11) return currentMonthLabel();
  return `${monthNames[monthIndex]} ${year}`;
}

function getRecordDate(record: {
  created_at?: string | null;
  updated_at?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  scheduled_for?: string | null;
  meeting_time?: string | null;
}) {
  return record.started_at || record.scheduled_for || record.meeting_time || record.ended_at || record.created_at || record.updated_at || null;
}

function isInMonth(recordDate: string | null | undefined, monthValue: string) {
  if (!recordDate) return false;
  const date = new Date(recordDate);
  if (Number.isNaN(date.getTime())) return false;
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}` === monthValue;
}

function MonthControl({
  value,
  onChange,
  label = "Filter month",
}: {
  value: string;
  onChange: (value: string) => void;
  label?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const selectedYear = Number(value.split("-")[0]) || new Date().getFullYear();
  const selectedMonth = Number(value.split("-")[1]) || new Date().getMonth() + 1;
  const [viewYear, setViewYear] = useState(selectedYear);

  const chooseMonth = (month: number) => {
    onChange(`${viewYear}-${String(month).padStart(2, "0")}`);
    setIsOpen(false);
  };

  const chooseCurrentMonth = () => {
    onChange(currentMonthValue());
    setViewYear(new Date().getFullYear());
    setIsOpen(false);
  };

  return (
    <div
      className="relative"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setIsOpen(false);
        }
      }}
    >
      <button
        aria-expanded={isOpen}
        aria-label={label}
        className="inline-flex h-11 min-w-[150px] items-center justify-between gap-3 rounded-full border border-[var(--sparx-line-strong)] bg-white px-4 text-sm font-black text-[var(--sparx-olive)] shadow-[0_12px_26px_rgba(44,38,27,0.08)] transition hover:border-[var(--sparx-olive)] hover:bg-[var(--sparx-panel)]"
        onClick={() => {
          setViewYear(selectedYear);
          setIsOpen((open) => !open);
        }}
        type="button"
      >
        <span className="flex items-center gap-2">
          {previewIcons.filters}
          <span>{monthValueLabel(value)}</span>
        </span>
        <CalendarCheck className="size-4 text-[var(--sparx-muted)]" />
      </button>
      {isOpen ? (
        <div className="absolute right-0 top-[calc(100%+8px)] z-30 w-[270px] rounded-[8px] border border-[var(--sparx-line)] bg-[var(--sparx-panel)] p-3 text-black shadow-[0_18px_45px_rgba(44,38,27,0.16)]">
          <div className="flex items-center justify-between rounded-[8px] bg-white px-2 py-2">
            <button
              aria-label="Previous year"
              className="grid size-8 place-items-center rounded-full text-[var(--sparx-muted)] hover:bg-[var(--sparx-card)]"
              onClick={() => setViewYear((year) => year - 1)}
              type="button"
            >
              <ChevronLeft className="size-4" />
            </button>
            <strong className="text-base font-black">{viewYear}</strong>
            <button
              aria-label="Next year"
              className="grid size-8 place-items-center rounded-full text-[var(--sparx-muted)] hover:bg-[var(--sparx-card)]"
              onClick={() => setViewYear((year) => year + 1)}
              type="button"
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-2">
            {monthNames.map((month, index) => {
              const monthNumber = index + 1;
              const isSelected = viewYear === selectedYear && monthNumber === selectedMonth;
              return (
                <button
                  className={cn(
                    "h-9 rounded-[8px] text-sm font-black transition",
                    isSelected
                      ? "bg-[var(--sparx-olive)] text-white shadow-[0_10px_18px_rgba(104,77,0,0.18)]"
                      : "bg-white text-black hover:bg-[var(--sparx-card)]",
                  )}
                  key={month}
                  onClick={() => chooseMonth(monthNumber)}
                  type="button"
                >
                  {month}
                </button>
              );
            })}
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-[var(--sparx-line)] pt-3">
            <button
              className="text-xs font-black text-[var(--sparx-muted)] hover:text-black"
              onClick={() => {
                setViewYear(selectedYear);
                setIsOpen(false);
              }}
              type="button"
            >
              Close
            </button>
            <button
              className="rounded-full bg-[var(--sparx-olive)] px-4 py-2 text-xs font-black text-white"
              onClick={chooseCurrentMonth}
              type="button"
            >
              This month
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function DataNotice({
  status,
  error,
  errors,
}: {
  status: string;
  error?: string;
  errors?: PlatformData["errors"];
}) {
  const messages = [
    ...(error ? [error] : []),
    ...Object.entries(errors || {}).map(([key, message]) => `${key}: ${message}`),
  ];

  if (status === "loading") {
    return <div className="text-sm font-bold text-[var(--sparx-muted)]">Loading live backend data...</div>;
  }
  if (!messages.length) {
    return null;
  }
  return (
    <div className="rounded-[8px] border border-[var(--sparx-line-strong)] bg-white px-3 py-2 text-sm font-semibold text-[var(--sparx-muted)]">
      {messages.slice(0, 2).join(" | ")}
    </div>
  );
}

function PageFrame({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn("min-w-0", className)}>{children}</div>;
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  required,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  type?: string;
}) {
  return (
    <label className="grid gap-1.5">
      <span className="text-sm font-black">{label}</span>
      <input
        className="h-10 rounded-[6px] border border-[var(--sparx-line-strong)] bg-white px-3 text-sm font-semibold outline-none focus:border-[var(--sparx-yellow)] focus:ring-2 focus:ring-[rgba(241,231,47,0.36)]"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        required={required}
        type={type}
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <label className="grid gap-1.5">
      <span className="text-sm font-black">{label}</span>
      <select
        className="h-10 rounded-[6px] border border-[var(--sparx-line-strong)] bg-white px-3 text-sm font-semibold outline-none focus:border-[var(--sparx-yellow)] focus:ring-2 focus:ring-[rgba(241,231,47,0.36)]"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
    </label>
  );
}

function MiniMetric({ value, label }: { value: number | string; label: string }) {
  return (
    <div>
      <strong className="block text-[44px] font-black leading-none text-black">{value}</strong>
      <span className="mt-1 block text-sm font-medium text-black">{label}</span>
    </div>
  );
}

function callDisplayName(call: CallRecord | SummaryDetail) {
  return call.lead_name || call.phone || "Unknown lead";
}

function getLatestCall(calls: CallRecord[]) {
  return [...calls].sort((a, b) => {
    const left = new Date(a.started_at || a.created_at || 0).getTime();
    const right = new Date(b.started_at || b.created_at || 0).getTime();
    return right - left;
  })[0];
}

function getTranscriptLineCount(calls: CallRecord[]) {
  return calls.reduce((sum, call) => sum + (call.transcript?.length || 0), 0);
}

export function DashboardPage({ initialData }: PageDataProps) {
  const { data, status, error, refresh } = usePlatformData(initialData);
  const [selectedMonth, setSelectedMonth] = useState(currentMonthValue);
  const calls = data?.calls ?? emptyCalls;
  const campaigns = data?.campaigns ?? emptyCampaigns;
  const meetings = data?.meetings ?? emptyMeetings;
  const monthCalls = calls.filter((call) => isInMonth(getRecordDate(call), selectedMonth));
  const monthCampaigns = campaigns.filter((campaign) => isInMonth(getRecordDate(campaign), selectedMonth));
  const monthMeetings = meetings.filter((meeting) => isInMonth(getRecordDate(meeting), selectedMonth));
  const activeCalls = monthCalls.filter((call) => activeCallStatuses.has(call.status));
  const latestActiveCall = activeCalls[0] || getLatestCall(calls);
  const transcriptLines = getTranscriptLineCount(monthCalls);
  const contacts = monthCampaigns.reduce((sum, campaign) => sum + campaign.total_contacts, 0);
  const meetingCount = monthMeetings.length || monthCalls.filter((call) => call.meeting_requested || call.meeting_time).length;

  return (
    <AppShell>
      <GreetingHeader />
      <PageFrame>
        <PageCanvas
          title="Live Dashboard"
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <MonthControl value={selectedMonth} onChange={setSelectedMonth} />
              <StatusBadge tone={data?.health?.backend === "healthy" ? "active" : "warning"}>
                {data?.health?.backend === "healthy" ? "System Active" : "System Degraded"}
              </StatusBadge>
              <PrimaryButton icon={<RefreshCw className="size-4" />} onClick={refresh}>
                Refresh
              </PrimaryButton>
            </div>
          }
        >
          <DataNotice status={status} error={error} errors={data?.errors} />
          <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <section className="grid gap-4 sm:grid-cols-2">
              <StatCard label="Active- Calls" value={activeCalls.length} caption="Real-time Sessions" icon={previewIcons.calls} />
              <StatCard label="Transcripts" value={transcriptLines} caption="Live utterances" icon={previewIcons.transcript} />
              <StatCard label="Contacts" value={contacts} caption="Ready to Dial" icon={<User className="size-4" />} />
              <StatCard label="Meetings" value={meetingCount} caption="Booked Outcomes" icon={<CalendarCheck className="size-4" />} tone="olive" />
            </section>
            <section>
              <h3 className="mb-2 text-xl font-black">Call Transcript</h3>
              <div className="grid min-h-[360px] place-items-center rounded-[8px] bg-[var(--sparx-card-strong)] p-5">
                {latestActiveCall?.transcript?.length ? (
                  <ScrollPanel className="w-full bg-transparent p-0">
                    {latestActiveCall.transcript.slice(-8).map((entry) => (
                      <div key={entry.entry_id} className="mb-3 rounded-[8px] bg-white/75 p-3 text-sm font-semibold">
                        <span className="font-black capitalize">{entry.speaker}</span>
                        <p>{entry.text}</p>
                      </div>
                    ))}
                  </ScrollPanel>
                ) : (
                  <div className="text-center">
                    <Sparkles className="mx-auto size-10 text-white" />
                    <p className="mt-2 text-lg font-black">*Awkward Silence</p>
                    <p className="text-sm font-semibold text-[var(--sparx-muted)]">No live telemetry yet</p>
                  </div>
                )}
              </div>
            </section>
          </div>
        </PageCanvas>
      </PageFrame>
    </AppShell>
  );
}

function CallCard({ call }: { call: CallRecord }) {
  return (
    <article className="relative rounded-[8px] bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="text-[10px] font-semibold text-[var(--sparx-muted)]">
          <div>{formatDate(call.started_at || call.created_at)}</div>
          <div>{formatTime(call.started_at || call.created_at)}</div>
        </div>
        <Trash2 className="size-4 text-[var(--sparx-red)]" />
      </div>
      <h3 className="mt-2 truncate text-xl font-black">{callDisplayName(call)}</h3>
      <p className="text-sm font-medium text-[var(--sparx-muted)]">Call ended: {humanize(call.status)}</p>
      <div className="mt-4 border-t border-[var(--sparx-line)] pt-2 text-xs font-semibold text-[var(--sparx-muted)]">
        {call.transcript?.length || 0} Transcript lines
      </div>
      <div className="mt-2 flex justify-end gap-2">
        <Link className="rounded-full border border-[var(--sparx-line-strong)] px-3 py-1 text-xs font-bold" href={`/transcripts?callId=${call.call_id}`}>
          Transcript
        </Link>
        <Link className="rounded-full border border-[var(--sparx-line-strong)] px-3 py-1 text-xs font-bold" href={`/summaries?callId=${call.call_id}`}>
          Summary
        </Link>
      </div>
    </article>
  );
}

export function LogsPage({ initialData }: PageDataProps) {
  const { data, status, error, refresh } = usePlatformData(initialData);
  const [tab, setTab] = useState<"completed" | "unanswered" | "hanged">("completed");
  const calls = data?.calls ?? [];
  const filtered = calls.filter((call) => {
    if (tab === "completed") return completedCallStatuses.has(call.status);
    if (tab === "unanswered") return unansweredStatuses.has(call.status);
    return hangedUpStatuses.has(call.status);
  });

  return (
    <AppShell>
      <GreetingHeader />
      <PageFrame>
        <PageCanvas
          title="Session Logs"
          actions={<PrimaryButton icon={<RefreshCw className="size-4" />} onClick={refresh}>{currentMonthLabel()}</PrimaryButton>}
        >
          <p className="max-w-xl text-sm font-semibold text-[var(--sparx-muted)]">
            Open any call in a dedicated transcript window without touching the live dashboard transcripts.
          </p>
          <DataNotice status={status} error={error} errors={data?.errors} />
          <section className="mt-5 grid grid-cols-2 gap-5 md:grid-cols-4">
            <MiniMetric value={calls.length} label="Total Sessions" />
            <MiniMetric value={calls.filter((call) => activeCallStatuses.has(call.status)).length} label="Live now" />
            <MiniMetric value={calls.filter((call) => completedCallStatuses.has(call.status)).length} label="Completed Calls" />
            <MiniMetric value={getTranscriptLineCount(calls)} label="Transcripts" />
          </section>
          <section className="mt-5 rounded-[8px] bg-[var(--sparx-card-strong)] p-4">
            <div className="mb-4 flex flex-wrap gap-2">
              {[
                ["completed", "Completed Calls"],
                ["unanswered", "Unanswered"],
                ["hanged", "Hanged Up"],
              ].map(([key, label]) => (
                <button
                  className={cn(
                    "rounded-full px-5 py-2 text-sm font-black",
                    tab === key ? "bg-[var(--sparx-olive)] text-white" : "text-black",
                  )}
                  key={key}
                  onClick={() => setTab(key as typeof tab)}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
            {filtered.length ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
                {filtered.map((call) => <CallCard call={call} key={call.call_id} />)}
              </div>
            ) : (
              <EmptyState title="No calls in this tab" description="Matching backend call records will appear here." />
            )}
          </section>
        </PageCanvas>
      </PageFrame>
    </AppShell>
  );
}

type CampaignFormState = {
  campaign_name: string;
  agent_id: string;
  campaign_type: string;
  language: string;
  call_objective: string;
  product_name: string;
  product_description: string;
  priority: "high" | "medium" | "low";
  dispatch_mode: "parallel" | "one_by_one";
};

export function CampaignPage({ initialData }: PageDataProps) {
  const { data, status, error, refresh } = usePlatformData(initialData);
  const [preview, setPreview] = useState<CampaignPreview | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const agents = data?.agents ?? emptyAgents;
  const campaigns = data?.campaigns ?? emptyCampaigns;
  const [form, setForm] = useState<CampaignFormState>({
    campaign_name: "",
    agent_id: "",
    campaign_type: "",
    language: "English",
    call_objective: "",
    product_name: "",
    product_description: "",
    priority: "high",
    dispatch_mode: "parallel",
  });
  const selectedAgentId = form.agent_id || agents[0]?.agent_id || "";

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setMessage("Validating lead file...");
    try {
      const nextPreview = await services.previewLeads(file);
      setPreview(nextPreview);
      setMessage(`${nextPreview.valid_contacts} valid contacts detected from ${nextPreview.filename}.`);
    } catch (err) {
      setPreview(null);
      setMessage(err instanceof Error ? err.message : "Lead preview failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!preview?.contacts.length) {
      setMessage("Upload and validate a lead file before creating a campaign.");
      return;
    }
    setBusy(true);
    try {
      await services.createCampaign({
        campaign_name: form.campaign_name,
        agent_id: selectedAgentId,
        campaign_type: form.campaign_type,
        call_objective: form.call_objective,
        language: form.language,
        priority: form.priority,
        schedule_type: "immediate",
        dispatch_mode: form.dispatch_mode,
        contacts: preview.contacts,
        lead_source: {
          filename: preview.filename,
          file_type: preview.file_type,
          total_rows: preview.total_rows,
          invalid_contacts: preview.invalid_contacts,
          duplicate_contacts: preview.duplicate_contacts,
          source_columns: preview.source_columns,
          unmapped_columns: preview.unmapped_columns,
        },
        product_brief: {
          product_name: form.product_name || form.campaign_name,
          product_description: form.product_description || form.call_objective,
        },
      });
      setMessage("Campaign created from validated backend preview.");
      setPreview(null);
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Unable to create campaign.");
    } finally {
      setBusy(false);
    }
  }

  const updateForm = <K extends keyof CampaignFormState>(key: K, value: CampaignFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  return (
    <AppShell>
      <GreetingHeader />
      <PageFrame>
        <PageCanvas title="Campaign">
          <DataNotice status={status} error={error} errors={data?.errors} />
          <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <form className="sparx-grid rounded-[8px] bg-white/70 p-4" onSubmit={handleSubmit}>
              <h3 className="mb-4 text-lg font-black">Agent Setup</h3>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Campaign" value={form.campaign_name} onChange={(value) => updateForm("campaign_name", value)} required />
                <SelectField label="Agent Name" value={selectedAgentId} onChange={(value) => updateForm("agent_id", value)}>
                  {agents.length ? agents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.agent_name}</option>) : <option value="">No agents loaded</option>}
                </SelectField>
                <Field label="Campaign Type" value={form.campaign_type} onChange={(value) => updateForm("campaign_type", value)} required />
                <Field label="Language" value={form.language} onChange={(value) => updateForm("language", value)} required />
                <Field label="Call Objective" value={form.call_objective} onChange={(value) => updateForm("call_objective", value)} required />
                <Field label="Product Name" value={form.product_name} onChange={(value) => updateForm("product_name", value)} />
                <Field label="Product Description" value={form.product_description} onChange={(value) => updateForm("product_description", value)} required />
                <SelectField label="Dispatch" value={form.dispatch_mode} onChange={(value) => updateForm("dispatch_mode", value as CampaignFormState["dispatch_mode"])}>
                  <option value="parallel">All counted customers</option>
                  <option value="one_by_one">One by one</option>
                </SelectField>
              </div>
              <div className="mt-4 rounded-[8px] border border-dashed border-[var(--sparx-line-strong)] bg-white p-4">
                <label className="grid gap-2 text-sm font-black">
                  Renewal Sheet Import
                  <input accept=".csv,.xlsx,.xls,.pdf,.doc,.docx,.txt" disabled={busy} onChange={handleFile} type="file" />
                </label>
              </div>
              {message ? <p className="mt-3 text-sm font-bold text-[var(--sparx-muted)]">{message}</p> : null}
              <div className="mt-4 flex flex-wrap gap-2">
                <PrimaryButton disabled={busy || !preview?.contacts.length || !selectedAgentId} type="submit">Create Campaign</PrimaryButton>
                <PrimaryButton onClick={refresh} type="button" variant="soft">Refresh</PrimaryButton>
              </div>
            </form>
            <div className="grid gap-4">
              <AssetFrame title="Campaign visual asset" description="Frame reserved for exported Figma image." />
              <div className="rounded-[8px] bg-[var(--sparx-card-strong)] p-4">
                <h3 className="text-lg font-black">Renewal Sheet Import</h3>
                {preview ? (
                  <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                    <MiniMetric value={preview.valid_contacts} label="Valid" />
                    <MiniMetric value={preview.invalid_contacts} label="Invalid" />
                    <MiniMetric value={preview.duplicate_contacts} label="Duplicate" />
                  </div>
                ) : (
                  <p className="mt-2 text-sm font-semibold text-[var(--sparx-muted)]">Upload a file to show backend validation results.</p>
                )}
              </div>
            </div>
          </div>
          <section className="mt-5">
            <h3 className="mb-3 text-xl font-black">Campaign Records</h3>
            {campaigns.length ? (
              <div className="grid gap-3">
                {campaigns.map((campaign) => (
                  <article key={campaign.campaign_id} className="flex flex-col gap-3 rounded-[8px] bg-white p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <StatusBadge tone={campaign.status === "running" ? "active" : "neutral"}>{humanize(campaign.status)}</StatusBadge>
                      <h4 className="mt-2 text-xl font-black">{campaign.campaign_name}</h4>
                      <p className="text-sm font-semibold text-[var(--sparx-muted)]">{campaign.completed_calls}/{campaign.total_contacts} completed | {campaign.agent_name}</p>
                    </div>
                    <PrimaryButton onClick={() => services.startCampaign(campaign.campaign_id).then(refresh)} variant="soft">Start</PrimaryButton>
                  </article>
                ))}
              </div>
            ) : <EmptyState title="No campaigns yet" description="Created backend campaigns will appear here." />}
          </section>
        </PageCanvas>
      </PageFrame>
    </AppShell>
  );
}

type ManualCallFormState = {
  lead_name: string;
  phone: string;
  email: string;
  company: string;
  city: string;
  role: string;
  interest: string;
  agent_id: string;
  call_objective: string;
  additional_context: string;
  language: string;
  priority: "high" | "medium" | "low";
};

const initialManualCallForm: ManualCallFormState = {
  lead_name: "",
  phone: "",
  email: "",
  company: "",
  city: "",
  role: "",
  interest: "",
  agent_id: "",
  call_objective: "",
  additional_context: "",
  language: "",
  priority: "high",
};

const phonePattern = /^\+[1-9]\d{7,14}$/;
const emailPattern = /^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/i;
const fallbackManualCallEmail = "unknown@sparx.local";
const fallbackManualCallLanguage = "English";
const fallbackManualCallObjective = "Start a general outbound follow-up call.";

function compactOptional(value: string) {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function CallStatusPanel({ call }: { call: CallRecord | null }) {
  if (!call) {
    return <EmptyState title="No call started" description="Submit the form to create one individual outbound AI call." />;
  }

  const rows = [
    ["Status", humanize(call.status)],
    ["Call ID", call.call_id],
    ["Lead", `${call.lead_name} | ${call.phone}`],
    ["Email ID", call.email || "-"],
    ["Agent", call.agent_name],
    ["Twilio Call SID", call.twilio_call_sid || "Pending"],
    ["Started At", formatDateTime(call.started_at)],
    ["Ended At", call.ended_at ? formatDateTime(call.ended_at) : "In progress"],
    ["Retry Plan", `Retry Count: ${call.retry_count}`],
    ["Meeting / Callback", `Meeting: ${call.meeting_requested ? "Yes" : "No"} | Callback: ${call.callback_requested ? "Yes" : "No"}`],
    ["AI Processing", humanize(call.ai_processing_status)],
    ["AI Summary", call.summary || call.ai_error || "Post-call intelligence is not available yet."],
    ["Next Action", call.next_action || "No recommendation available yet."],
  ];

  return (
    <div className="rounded-[8px] bg-white p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <StatusBadge tone={statusTone(call.status)}>{humanize(call.status)}</StatusBadge>
          <h3 className="mt-2 text-xl font-black">{call.lead_name}</h3>
        </div>
        <Link className="text-sm font-black text-[var(--sparx-olive)]" href={`/transcripts?callId=${call.call_id}`}>
          Open Transcript
        </Link>
      </div>
      <div className="grid gap-2">
        {rows.map(([label, value]) => (
          <div className="grid gap-1 border-t border-[var(--sparx-line)] pt-2 sm:grid-cols-[150px_minmax(0,1fr)]" key={label}>
            <span className="text-xs font-black uppercase text-[var(--sparx-muted)]">{label}</span>
            <span className="min-w-0 break-words text-sm font-semibold">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ManualCallWorkflowSteps() {
  return (
    <section className="grid gap-2 sm:grid-cols-5">
      {[
        ["01", "Contact"],
        ["02", "Agent"],
        ["03", "Configure"],
        ["04", "Live Status"],
        ["05", "Results"],
      ].map(([step, label], index) => (
        <div
          className={cn(
            "rounded-[8px] border border-[var(--sparx-line)] bg-white px-3 py-3",
            index === 0 && "bg-[var(--sparx-olive)] text-white",
          )}
          key={step}
        >
          <span className="block text-xs font-black opacity-70">{step}</span>
          <strong className="block text-sm font-black">{label}</strong>
        </div>
      ))}
    </section>
  );
}

export function ManualCallPage({ initialData }: PageDataProps) {
  const { data, status, error, refresh } = usePlatformData(initialData);
  const searchParams = useSearchParams();
  const agents = data?.agents ?? emptyAgents;
  const calls = data?.calls ?? emptyCalls;
  const individualCalls = sortedCalls(calls.filter((call) => call.call_type === "individual"));
  const [form, setForm] = useState<ManualCallFormState>(() => ({
    ...initialManualCallForm,
    lead_name: searchParams.get("lead_name") || "",
    phone: searchParams.get("phone") || "",
    email: searchParams.get("email") || "",
    company: searchParams.get("company") || "",
    city: searchParams.get("city") || "",
    role: searchParams.get("role") || "",
    interest: searchParams.get("interest") || "",
    agent_id: searchParams.get("agent_id") || "",
    call_objective: searchParams.get("call_objective") || "",
    additional_context: searchParams.get("additional_context") || "",
    language: searchParams.get("language") || "",
    priority: (searchParams.get("priority") as ManualCallFormState["priority"] | null) || "high",
  }));
  const selectedAgentId = form.agent_id || agents[0]?.agent_id || "";
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<"active" | "danger" | "warning" | "neutral">("neutral");
  const [activeCall, setActiveCall] = useState<CallRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const displayedActiveCall = activeCall?.call_id
    ? calls.find((call) => call.call_id === activeCall.call_id) || activeCall
    : null;

  const updateForm = <K extends keyof ManualCallFormState>(key: K, value: ManualCallFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setMessage("");

    if (!phonePattern.test(form.phone.trim())) {
      setMessage("Phone number must be in E.164 format, for example +919999999999.");
      setMessageTone("danger");
      return;
    }
    if (form.email.trim() && !emailPattern.test(form.email.trim())) {
      setMessage("Email ID must be a valid email address.");
      setMessageTone("danger");
      return;
    }
    if (!selectedAgentId) {
      setMessage("Select a Deepgram agent before starting the call.");
      setMessageTone("danger");
      return;
    }

    const payload: IndividualCallPayload = {
      lead_name: form.lead_name.trim(),
      phone: form.phone.trim(),
      email: form.email.trim().toLowerCase() || fallbackManualCallEmail,
      company: compactOptional(form.company),
      city: compactOptional(form.city),
      role: compactOptional(form.role),
      interest: compactOptional(form.interest),
      agent_id: selectedAgentId,
      call_objective: form.call_objective.trim() || fallbackManualCallObjective,
      additional_context: compactOptional(form.additional_context),
      language: form.language.trim() || fallbackManualCallLanguage,
      priority: form.priority,
    };

    setBusy(true);
    try {
      const call = await services.startIndividualCall(payload);
      setActiveCall(call);
      setMessage(`Call ${call.call_id} was created and sent to Twilio.`);
      setMessageTone("active");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Unable to start the call.");
      setMessageTone("danger");
    } finally {
      setBusy(false);
    }
  }

  function handleReset() {
    setForm(initialManualCallForm);
    setActiveCall(null);
    setMessage("");
    setMessageTone("neutral");
  }

  return (
    <AppShell>
      <GreetingHeader />
      <PageFrame>
        <PageCanvas
          eyebrow="Manual Call"
          title="Single AI Call"
          actions={
            <PrimaryButton icon={<RefreshCw className="size-4" />} onClick={refresh} variant="soft">
              Refresh
            </PrimaryButton>
          }
        >
          <p className="max-w-3xl text-sm font-semibold text-[var(--sparx-muted)]">
            Start one outbound AI call, monitor its lifecycle, and jump into the transcript or summary after the call finishes.
          </p>
          <DataNotice status={status} error={error} errors={data?.errors} />
          <div className="mt-4">
            <ManualCallWorkflowSteps />
          </div>
          <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
            <form className="sparx-grid rounded-[8px] bg-white/75 p-4" onSubmit={handleSubmit}>
              <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-xl font-black">Contact Information & Call Configuration</h3>
                  <p className="text-sm font-semibold text-[var(--sparx-muted)]">
                    Only lead name and phone number are required to start a single call.
                  </p>
                </div>
                {message ? <StatusBadge tone={messageTone}>{message}</StatusBadge> : null}
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Lead Name" value={form.lead_name} onChange={(value) => updateForm("lead_name", value)} placeholder="Lead full name" required />
                <Field label="Phone Number" value={form.phone} onChange={(value) => updateForm("phone", value)} placeholder="+919999999999" required type="tel" />
                <Field label="Email ID" value={form.email} onChange={(value) => updateForm("email", value)} placeholder="lead@example.com" type="email" />
                <Field label="Company" value={form.company} onChange={(value) => updateForm("company", value)} placeholder="Company name" />
                <Field label="City" value={form.city} onChange={(value) => updateForm("city", value)} placeholder="City" />
                <Field label="Role" value={form.role} onChange={(value) => updateForm("role", value)} placeholder="Lead role" />
                <Field label="Interest" value={form.interest} onChange={(value) => updateForm("interest", value)} placeholder="Interest area" />
                <SelectField label="Select Deepgram Agent" value={selectedAgentId} onChange={(value) => updateForm("agent_id", value)}>
                  {agents.length ? (
                    agents.map((agent) => (
                      <option key={agent.agent_id} value={agent.agent_id}>
                        {agent.agent_name}{agent.purpose ? ` - ${agent.purpose}` : ""}
                      </option>
                    ))
                  ) : (
                    <option value="">No agents configured</option>
                  )}
                </SelectField>
                <Field label="Language Preference" value={form.language} onChange={(value) => updateForm("language", value)} placeholder="Preferred language" />
                <SelectField label="Priority" value={form.priority} onChange={(value) => updateForm("priority", value as ManualCallFormState["priority"])}>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </SelectField>
                <div className="md:col-span-2">
                  <Field label="Call Objective" value={form.call_objective} onChange={(value) => updateForm("call_objective", value)} placeholder="Call objective" />
                </div>
                <label className="grid gap-1.5 md:col-span-2">
                  <span className="text-sm font-black">Additional Context / Notes</span>
                  <textarea
                    className="min-h-28 rounded-[6px] border border-[var(--sparx-line-strong)] bg-white px-3 py-3 text-sm font-semibold outline-none focus:border-[var(--sparx-yellow)] focus:ring-2 focus:ring-[rgba(241,231,47,0.36)]"
                    onChange={(event) => updateForm("additional_context", event.target.value)}
                    placeholder="Optional notes, recent activity, or qualifying context"
                    value={form.additional_context}
                  />
                </label>
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                <PrimaryButton disabled={busy || !selectedAgentId} icon={<Phone className="size-4" />} type="submit">
                  {busy ? "Starting AI Call..." : "Start AI Call"}
                </PrimaryButton>
                <PrimaryButton onClick={handleReset} type="button" variant="soft">
                  Reset
                </PrimaryButton>
              </div>
            </form>
            <section className="grid content-start gap-4 rounded-[8px] bg-[var(--sparx-panel)] p-4">
              <div>
                <h3 className="text-xl font-black">Call Status</h3>
                <p className="text-sm font-semibold text-[var(--sparx-muted)]">
                  Status refreshes until the call and post-call intelligence reach a final state.
                </p>
              </div>
              <CallStatusPanel call={displayedActiveCall} />
            </section>
          </div>
          <section className="mt-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-xl font-black">Recent Individual Calls</h3>
              <StatusBadge>{individualCalls.length} Records</StatusBadge>
            </div>
            {individualCalls.length ? (
              <ScrollPanel className="max-h-[360px] bg-transparent p-0">
                <div className="grid gap-3 lg:grid-cols-2">
                  {individualCalls.slice(0, 8).map((call) => (
                    <article className="flex flex-col gap-3 rounded-[8px] bg-white p-4 sm:flex-row sm:items-center sm:justify-between" key={call.call_id}>
                      <div className="min-w-0">
                        <StatusBadge tone={statusTone(call.status)}>{humanize(call.status)}</StatusBadge>
                        <h4 className="mt-2 truncate text-lg font-black">{call.lead_name}</h4>
                        <p className="text-xs font-semibold text-[var(--sparx-muted)]">{call.phone} | {formatDateTime(call.started_at || call.created_at)}</p>
                      </div>
                      <div className="flex shrink-0 flex-wrap gap-2">
                        <Link className="inline-flex min-h-10 items-center rounded-full bg-white px-4 text-sm font-black text-[var(--sparx-olive)] ring-1 ring-[var(--sparx-line-strong)]" href={`/manual-call?lead_name=${encodeURIComponent(call.lead_name)}&phone=${encodeURIComponent(call.phone)}&email=${encodeURIComponent(call.email || "")}&company=${encodeURIComponent(call.company || "")}&city=${encodeURIComponent(call.city || "")}&role=${encodeURIComponent(call.role || "")}&interest=${encodeURIComponent(call.interest || "")}&call_objective=${encodeURIComponent(call.call_objective || "")}&language=${encodeURIComponent(call.language || "")}&priority=${encodeURIComponent(call.priority || "high")}&agent_id=${encodeURIComponent(call.agent_id || "")}`}>
                          Retry
                        </Link>
                        <Link className="inline-flex min-h-10 items-center rounded-full bg-[var(--sparx-olive)] px-4 text-sm font-black text-white" href={`/summaries?callId=${call.call_id}`}>
                          Summary
                        </Link>
                      </div>
                    </article>
                  ))}
                </div>
              </ScrollPanel>
            ) : (
              <EmptyState title="No individual calls yet" description="Single-person calls started from this page will appear here." />
            )}
          </section>
        </PageCanvas>
      </PageFrame>
    </AppShell>
  );
}

function statusTone(status?: string | null): "active" | "warning" | "danger" | "neutral" {
  if (!status) return "neutral";
  if (["completed", "confirmed", "running", "answered", "active", "scheduled", "queued"].includes(status)) {
    return "active";
  }
  if (["pending", "draft", "rescheduled", "in_progress", "callback_requested", "meeting_requested"].includes(status)) {
    return "warning";
  }
  if (["failed", "cancelled", "canceled", "missed", "no_answer", "busy"].includes(status)) {
    return "danger";
  }
  return "neutral";
}

function sortedCalls(calls: CallRecord[]) {
  return [...calls].sort((a, b) => {
    const left = new Date(a.started_at || a.created_at || 0).getTime();
    const right = new Date(b.started_at || b.created_at || 0).getTime();
    return right - left;
  });
}

function selectedCallIdFrom(searchParams: { get(name: string): string | null }) {
  return searchParams.get("callId") || "";
}

function recordTimestamp(call: CallRecord | SummaryDetail | null) {
  if (!call) return null;
  const callRecord = call as Partial<CallRecord>;
  const summaryRecord = call as Partial<SummaryDetail>;
  return (
    callRecord.started_at ||
    callRecord.created_at ||
    callRecord.ended_at ||
    summaryRecord.call_date ||
    summaryRecord.ended_at ||
    summaryRecord.processed_at ||
    null
  );
}

function recordDuration(call: CallRecord | SummaryDetail | null) {
  return call && "duration" in call ? call.duration : null;
}

function AvatarFrame({ label }: { label: string }) {
  return (
    <div className="relative mx-auto grid size-24 place-items-center rounded-full bg-[linear-gradient(135deg,#dbeeff,#ffe5c2)] text-xl font-black text-[var(--sparx-olive)]">
      {label.slice(0, 1).toUpperCase() || "A"}
      <span className="absolute bottom-2 right-2 size-4 rounded-full border-2 border-white bg-[var(--sparx-green)]" />
    </div>
  );
}

function leadIdentityKey(call: CallRecord) {
  const name = callDisplayName(call).trim().toLowerCase();
  const phone = call.phone?.trim();
  return name || phone || call.call_id;
}

function callsForSameLead(calls: CallRecord[], selectedCall: CallRecord | null) {
  if (!selectedCall) return [];
  const key = leadIdentityKey(selectedCall);
  return calls.filter((call) => leadIdentityKey(call) === key);
}

function LeadProfile({
  title,
  subtitle,
  status,
}: {
  title: string;
  subtitle?: string | null;
  status?: string | null;
}) {
  return (
    <div className="text-center">
      <AvatarFrame label={title} />
      <h3 className="mt-3 text-xl font-black">{title}</h3>
      {subtitle ? <p className="text-sm font-semibold text-[var(--sparx-muted)]">{subtitle}</p> : null}
      <StatusBadge tone={statusTone(status)}>{humanize(status)}</StatusBadge>
    </div>
  );
}

function HistoryList({
  calls,
  selectedCallId,
}: {
  calls: CallRecord[];
  selectedCallId?: string;
}) {
  if (!calls.length) {
    return <EmptyState title="No call history" description="Call records from the backend will appear here." />;
  }

  const grouped = sortedCalls(calls).reduce<Record<string, CallRecord[]>>((groups, call) => {
    const key = formatDate(call.started_at || call.created_at);
    groups[key] = [...(groups[key] || []), call];
    return groups;
  }, {});

  return (
    <ScrollPanel className="max-h-[310px] bg-white p-3">
      <h4 className="mb-3 text-sm font-black">History</h4>
      <div className="grid gap-4">
        {Object.entries(grouped).map(([date, dateCalls]) => (
          <div key={date}>
            <h5 className="mb-2 text-xs font-black">{date}</h5>
            <div className="grid gap-2">
              {dateCalls.map((call) => (
                <Link
                  className={cn(
                    "flex items-center justify-between gap-2 rounded-[8px] px-2 py-2 text-xs font-semibold hover:bg-[var(--sparx-panel)]",
                    selectedCallId === call.call_id && "bg-[var(--sparx-panel)]",
                  )}
                  href={`/transcripts?callId=${call.call_id}`}
                  key={call.call_id}
                >
                  <span className="min-w-0">
                    <span className="block truncate">Call ended</span>
                    <StatusBadge tone={statusTone(call.status)}>{humanize(call.status)}</StatusBadge>
                  </span>
                  <span className="shrink-0 text-[var(--sparx-muted)]">{formatTime(call.ended_at || call.started_at)}</span>
                </Link>
              ))}
            </div>
          </div>
        ))}
      </div>
    </ScrollPanel>
  );
}

function TranscriptPeopleGrid({
  calls,
}: {
  calls: CallRecord[];
}) {
  const people = Object.values(
    sortedCalls(calls).reduce<Record<string, { latest: CallRecord; calls: CallRecord[]; transcriptLines: number }>>(
      (groups, call) => {
        const key = leadIdentityKey(call);
        const existing = groups[key];
        const nextCalls = [...(existing?.calls || []), call];
        groups[key] = {
          latest: existing?.latest || call,
          calls: nextCalls,
          transcriptLines: nextCalls.reduce((sum, item) => sum + (item.transcript?.length || 0), 0),
        };
        return groups;
      },
      {},
    ),
  );

  if (!people.length) {
    return (
      <section className="rounded-[8px] bg-[var(--sparx-card-strong)] p-4">
        <EmptyState title="No transcript contacts" description="People with backend call records will appear here." />
      </section>
    );
  }

  return (
    <section className="rounded-[8px] bg-[var(--sparx-card-strong)] p-5">
      <div className="mb-3 flex items-end justify-between gap-3">
        <div>
          <h3 className="text-2xl font-black">Transcript Sessions</h3>
          <p className="text-xs font-semibold text-[var(--sparx-muted)]">
            One card per person
          </p>
        </div>
        <span className="shrink-0 text-xs font-black text-[var(--sparx-muted)]">
          {people.length} People
        </span>
      </div>
      <ScrollPanel className="max-h-[calc(100vh-285px)] min-h-[480px] bg-transparent p-0">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {people.map(({ latest, calls: leadCalls, transcriptLines }) => {
            const timestamp = recordTimestamp(latest);
            const completed = leadCalls.filter((call) => completedCallStatuses.has(call.status)).length;
            return (
              <Link
                className="grid min-h-[178px] content-between rounded-[8px] border border-transparent bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-[var(--sparx-olive)] hover:shadow-md"
                href={`/transcripts?callId=${latest.call_id}`}
                key={leadIdentityKey(latest)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 text-xs font-bold text-[var(--sparx-muted)]">
                    <div>{formatDate(timestamp)}</div>
                    <div>{formatTime(timestamp)}</div>
                  </div>
                  <StatusBadge tone={statusTone(latest.status)}>{humanize(latest.status)}</StatusBadge>
                </div>
                <div className="min-w-0">
                  <h4 className="truncate text-2xl font-black">{callDisplayName(latest)}</h4>
                  <p className="truncate text-sm font-semibold text-[var(--sparx-muted)]">
                    {latest.company || latest.phone || "Call contact"}
                  </p>
                </div>
                <div className="flex items-center justify-between border-t border-[var(--sparx-line)] pt-2 text-xs font-black text-[var(--sparx-muted)]">
                  <span>{leadCalls.length} calls | {completed} completed | {transcriptLines} lines</span>
                  <span className="rounded-full border border-[var(--sparx-line-strong)] px-3 py-1 text-black">
                    Open
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      </ScrollPanel>
    </section>
  );
}

function TranscriptWindow({
  call,
  compact = false,
}: {
  call: CallRecord | SummaryDetail | null;
  compact?: boolean;
}) {
  const transcript = call?.transcript ?? [];

  return (
    <div className="sparx-grid flex min-h-[440px] flex-col rounded-[8px] bg-white/80 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-black">{call ? callDisplayName(call) : "Transcript"}</h3>
          <p className="text-xs font-semibold text-[var(--sparx-muted)]">
            {call ? `${formatDateTime(recordTimestamp(call))} | ${formatDuration(recordDuration(call))}` : "No call selected"}
          </p>
        </div>
        <PrimaryButton icon={<Folder className="size-4" />} variant="soft">
          Notes
        </PrimaryButton>
      </div>
      {transcript.length ? (
        <ScrollPanel className={cn("flex-1 bg-transparent p-0", compact ? "max-h-[430px]" : "max-h-[540px]")}>
          <div className="grid gap-4">
            {transcript.map((entry) => {
              const isAgent = entry.speaker === "agent";
              return (
                <div className={cn("flex", isAgent ? "justify-end" : "justify-start")} key={entry.entry_id}>
                  <div className={cn("max-w-[78%] rounded-[8px] px-4 py-3 text-sm font-semibold", isAgent ? "bg-[var(--sparx-card-strong)]" : "bg-white border border-[var(--sparx-line-strong)]")}>
                    <div className="mb-1 flex items-center justify-between gap-4 text-[10px] font-black uppercase text-[var(--sparx-muted)]">
                      <span>{isAgent ? "You" : call ? callDisplayName(call) : "Lead"}</span>
                      <span>{formatTime(entry.timestamp)}</span>
                    </div>
                    <p>{entry.text}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </ScrollPanel>
      ) : (
        <EmptyState title="No transcript lines" description="Deepgram or manual transcript entries will appear here after the call." />
      )}
    </div>
  );
}

export function TranscriptPage({ initialData }: PageDataProps) {
  const { data, status, error, refresh } = usePlatformData(initialData);
  const searchParams = useSearchParams();
  const calls = data?.calls ?? emptyCalls;
  const selectedCallId = selectedCallIdFrom(searchParams);
  const listCall = useMemo(
    () => calls.find((call) => call.call_id === selectedCallId) ?? null,
    [calls, selectedCallId],
  );
  const [selectedCallDetail, setSelectedCallDetail] = useState<CallRecord | null>(null);
  const selectedCall = selectedCallDetail?.call_id === selectedCallId ? selectedCallDetail : listCall;
  const leadCalls = useMemo(() => callsForSameLead(calls, selectedCall), [calls, selectedCall]);

  useEffect(() => {
    let ignore = false;
    if (!selectedCallId) return;

    services
      .getCall(selectedCallId)
      .then((call) => {
        if (!ignore) setSelectedCallDetail(call);
      })
      .catch(() => {
        if (!ignore) setSelectedCallDetail(null);
      });

    return () => {
      ignore = true;
    };
  }, [selectedCallId]);

  return (
    <AppShell>
      <GreetingHeader />
      <PageFrame>
        <PageCanvas
          title="Call Transcript"
          actions={<PrimaryButton icon={<RefreshCw className="size-4" />} onClick={refresh}>Refresh</PrimaryButton>}
        >
          <DataNotice status={status} error={error} errors={data?.errors} />
          {selectedCallId ? (
            <div className="mt-4 grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
              <aside className="grid content-start gap-4 rounded-[8px] bg-[var(--sparx-panel)] p-4">
                <LeadProfile
                  title={selectedCall ? callDisplayName(selectedCall) : "No lead selected"}
                  subtitle={selectedCall?.company || selectedCall?.phone}
                  status={selectedCall?.status}
                />
                <HistoryList calls={leadCalls} selectedCallId={selectedCallId} />
              </aside>
              <TranscriptWindow call={selectedCall} />
            </div>
          ) : (
            <div className="mt-4">
              <TranscriptPeopleGrid calls={calls} />
            </div>
          )}
        </PageCanvas>
      </PageFrame>
    </AppShell>
  );
}

function SummarySelector({
  summaries,
  selectedCallId,
}: {
  summaries: PlatformData["summaries"];
  selectedCallId?: string;
}) {
  if (!summaries.length) {
    return <EmptyState title="No AI summaries" description="Completed AI processing results will appear here." />;
  }

  return (
    <ScrollPanel className="max-h-[310px] bg-white p-3">
      <h4 className="mb-3 text-sm font-black">History</h4>
      <div className="grid gap-2">
        {summaries.map((summary) => (
          <Link
            className={cn(
              "rounded-[8px] px-2 py-2 text-xs font-semibold hover:bg-[var(--sparx-panel)]",
              selectedCallId === summary.call_id && "bg-[var(--sparx-panel)]",
            )}
            href={`/summaries?callId=${summary.call_id}`}
            key={summary.call_id}
          >
            <span className="block truncate text-sm font-black">{summary.lead_name || summary.phone}</span>
            <span className="block text-[var(--sparx-muted)]">{formatDateTime(summary.call_date)}</span>
            <StatusBadge tone={statusTone(summary.ai_processing_status)}>{humanize(summary.ai_processing_status)}</StatusBadge>
          </Link>
        ))}
      </div>
    </ScrollPanel>
  );
}

export function SummariesPage({ initialData }: PageDataProps) {
  const { data, status, error, refresh } = usePlatformData(initialData);
  const searchParams = useSearchParams();
  const summaries = data?.summaries ?? emptySummaries;
  const calls = data?.calls ?? emptyCalls;
  const selectedCallId = searchParams.get("callId") || summaries[0]?.call_id || calls[0]?.call_id || "";
  const listCall = useMemo(
    () => calls.find((call) => call.call_id === selectedCallId) ?? null,
    [calls, selectedCallId],
  );
  const [summary, setSummary] = useState<SummaryDetail | null>(null);
  const selectedSummary = summary?.call_id === selectedCallId ? summary : null;

  useEffect(() => {
    let ignore = false;
    if (!selectedCallId) return;

    services
      .getSummary(selectedCallId)
      .then((detail) => {
        if (!ignore) setSummary(detail);
      })
      .catch(() => {
        if (!ignore && listCall) {
          setSummary({
            ...listCall,
            call_date: listCall.started_at || listCall.created_at || null,
            final_status: listCall.status,
            processed_at: listCall.updated_at || null,
            ai_error: null,
          });
        } else if (!ignore) {
          setSummary(null);
        }
      });

    return () => {
      ignore = true;
    };
  }, [listCall, selectedCallId]);

  return (
    <AppShell>
      <GreetingHeader />
      <PageFrame>
        <PageCanvas
          title="Gemini Call Summary"
          actions={<PrimaryButton icon={<RefreshCw className="size-4" />} onClick={refresh}>Refresh</PrimaryButton>}
        >
          <DataNotice status={status} error={error} errors={data?.errors} />
          <div className="mt-4 grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)_360px]">
            <aside className="grid content-start gap-4 rounded-[8px] bg-[var(--sparx-panel)] p-4">
              <LeadProfile
                title={selectedSummary ? callDisplayName(selectedSummary) : "No lead selected"}
                subtitle={selectedSummary?.company || selectedSummary?.phone}
                status={selectedSummary?.status || selectedSummary?.ai_processing_status}
              />
              <SummarySelector summaries={summaries} selectedCallId={selectedCallId} />
            </aside>
            <section className="grid content-start gap-4">
              {selectedSummary ? (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="text-lg font-black">AI generated</h3>
                    <StatusBadge tone={statusTone(selectedSummary.ai_processing_status)}>{humanize(selectedSummary.ai_processing_status)}</StatusBadge>
                  </div>
                  <p className="text-lg font-medium leading-relaxed">{shortText(selectedSummary.summary, "No AI summary has been generated for this call yet.")}</p>
                  <div className="flex flex-wrap gap-2">
                    {[selectedSummary.call_outcome, selectedSummary.sentiment, selectedSummary.lead_type].filter(Boolean).map((tag) => (
                      <StatusBadge key={String(tag)}>{humanize(String(tag))}</StatusBadge>
                    ))}
                  </div>
                  <div className="rounded-[8px] border border-[var(--sparx-line-strong)] bg-white p-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-black uppercase text-[var(--sparx-muted)]">Quality Score</span>
                      <strong className="text-2xl font-black text-[var(--sparx-card-strong)]">{selectedSummary.ai_score ?? 0}/100</strong>
                    </div>
                  </div>
                  <div className="grid gap-3">
                    <div className="rounded-[8px] border border-[var(--sparx-line-strong)] bg-white p-4">
                      <h4 className="font-black">Pain Points</h4>
                      <p className="mt-1 text-sm font-medium">{shortText(selectedSummary.lead_reason || selectedSummary.short_notes)}</p>
                    </div>
                    <div className="rounded-[8px] border border-[var(--sparx-line-strong)] bg-white p-4">
                      <h4 className="font-black">Objections</h4>
                      {selectedSummary.objections.length ? (
                        <ul className="mt-2 grid gap-1 text-sm font-medium">
                          {selectedSummary.objections.map((objection) => <li key={objection}>{objection}</li>)}
                        </ul>
                      ) : (
                        <p className="mt-1 text-sm font-medium">No objections recorded.</p>
                      )}
                    </div>
                    <div className="rounded-[8px] border border-[var(--sparx-line-strong)] bg-white p-4">
                      <h4 className="font-black">Next Action</h4>
                      <p className="mt-1 text-sm font-medium">{shortText(selectedSummary.next_action || selectedSummary.outcome_reason)}</p>
                    </div>
                  </div>
                </>
              ) : (
                <EmptyState title="No summary selected" description="Select a processed call summary from backend records." />
              )}
            </section>
            <TranscriptWindow call={selectedSummary} compact />
          </div>
        </PageCanvas>
      </PageFrame>
    </AppShell>
  );
}

function upcomingCallbacks(callbacks: CallbackRecord[]) {
  return [...callbacks].sort((a, b) => {
    const left = new Date(a.normalized_callback_time || a.created_at || 0).getTime();
    const right = new Date(b.normalized_callback_time || b.created_at || 0).getTime();
    return left - right;
  });
}

function callbackIsOpen(callback: CallbackRecord) {
  return !["completed", "cancelled", "failed"].includes(callback.status);
}

export function CallbacksPage({ initialData }: PageDataProps) {
  const { data, status, error, refresh } = usePlatformData(initialData);
  const callbacks = data?.callbacks ?? emptyCallbacks;
  const [message, setMessage] = useState("");
  const [now] = useState(() => Date.now());
  const openCallbacks = callbacks.filter(callbackIsOpen);
  const todayKey = new Date(now).toDateString();
  const dueToday = openCallbacks.filter((callback) => new Date(callback.normalized_callback_time).toDateString() === todayKey);
  const overdue = openCallbacks.filter((callback) => new Date(callback.normalized_callback_time).getTime() < now && new Date(callback.normalized_callback_time).toDateString() !== todayKey);
  const completed = callbacks.filter((callback) => callback.status === "completed");
  const latest = upcomingCallbacks(openCallbacks)[0];

  async function runAction(action: Promise<unknown>, success: string) {
    setMessage("Updating backend...");
    try {
      await action;
      setMessage(success);
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Action failed.");
    }
  }

  return (
    <AppShell>
      <GreetingHeader />
      <PageFrame>
        <PageCanvas title="Reschedule">
          <DataNotice status={status} error={error} errors={data?.errors} />
          {message ? <p className="mt-2 text-sm font-bold text-[var(--sparx-muted)]">{message}</p> : null}
          <section className="mt-4 grid grid-cols-2 gap-5 md:grid-cols-4">
            <MiniMetric value={openCallbacks.length} label="Scheduled" />
            <MiniMetric value={dueToday.length} label="Due Today" />
            <MiniMetric value={overdue.length} label="Overdue" />
            <MiniMetric value={completed.length} label="Completed" />
          </section>
          {latest ? (
            <section className="mt-5 rounded-[8px] bg-[var(--sparx-olive)] p-4 text-white">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="text-sm font-black text-[var(--sparx-yellow)]">Latest Upcoming</p>
                  <h3 className="text-2xl font-black">{latest.lead_name}</h3>
                  <p className="text-sm font-semibold text-white/70">{formatDateTime(latest.normalized_callback_time)} | {latest.phone}</p>
                  <p className="mt-3 text-sm font-medium text-white/70">{shortText(latest.callback_reason)}</p>
                </div>
                <div className="flex shrink-0 flex-wrap gap-2">
                  <PrimaryButton icon={<Phone className="size-4" />} onClick={() => void runAction(services.executeCallback(latest.callback_id), "Callback execution queued.")} variant="soft">
                    Dial
                  </PrimaryButton>
                  <PrimaryButton icon={<CheckCircle2 className="size-4" />} onClick={() => void runAction(services.updateCallback(latest.callback_id, { status: "completed" }), "Callback marked completed.")} variant="soft">
                    Done
                  </PrimaryButton>
                </div>
              </div>
            </section>
          ) : null}
          <section className="mt-5">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-xl font-black">Rescheduled Calls</h3>
              <span className="text-sm font-bold text-[var(--sparx-muted)]">{callbacks.length} Records</span>
            </div>
            {callbacks.length ? (
              <ScrollPanel className="max-h-[420px] bg-transparent p-0">
                <div className="grid gap-3">
                  {upcomingCallbacks(callbacks).map((callback) => (
                    <article className="grid gap-3 rounded-[8px] bg-white p-3 lg:grid-cols-[minmax(180px,320px)_minmax(0,1fr)_auto]" key={callback.callback_id}>
                      <div className="flex min-w-0 gap-3">
                        <AvatarFrame label={callback.lead_name} />
                        <div className="min-w-0">
                          <StatusBadge tone={statusTone(callback.status)}>{humanize(callback.status)}</StatusBadge>
                          <h4 className="truncate text-xl font-black">{callback.lead_name}</h4>
                          <p className="text-xs font-semibold text-[var(--sparx-muted)]">{formatDateTime(callback.normalized_callback_time)} | {callback.phone}</p>
                        </div>
                      </div>
                      <div className="min-w-0">
                        <h5 className="font-black">{shortText(callback.callback_reason)}</h5>
                        <p className="text-xs font-semibold text-[var(--sparx-muted)]">{shortText(callback.next_action || callback.notes)}</p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <PrimaryButton icon={<Phone className="size-4" />} onClick={() => void runAction(services.executeCallback(callback.callback_id), "Callback execution queued.")}>
                          Dial
                        </PrimaryButton>
                        <PrimaryButton icon={<CheckCircle2 className="size-4" />} onClick={() => void runAction(services.updateCallback(callback.callback_id, { status: "completed" }), "Callback marked completed.")} variant="soft">
                          Done
                        </PrimaryButton>
                        <button className="grid size-8 place-items-center rounded-full text-[var(--sparx-red)]" onClick={() => void runAction(services.updateCallback(callback.callback_id, { status: "cancelled" }), "Callback cancelled.")} type="button">
                          <AlertCircle className="size-5" />
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              </ScrollPanel>
            ) : (
              <EmptyState title="No rescheduled calls" description="Backend callback records will appear here after callers ask for a later time." />
            )}
          </section>
        </PageCanvas>
      </PageFrame>
    </AppShell>
  );
}

function meetingTimeBounds(meeting: MeetingRecord) {
  const start = formatTime(meeting.scheduled_for);
  const end = formatTime(meeting.ends_at);
  return end ? `${start} - ${end}` : start;
}

export function MeetingsPage({ initialData }: PageDataProps) {
  const { data, status, error, refresh } = usePlatformData(initialData);
  const meetings = data?.meetings ?? emptyMeetings;
  const [message, setMessage] = useState("");

  async function runAction(action: Promise<unknown>, success: string) {
    setMessage("Updating meetings...");
    try {
      await action;
      setMessage(success);
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Meeting action failed.");
    }
  }

  return (
    <AppShell>
      <GreetingHeader />
      <PageFrame>
        <PageCanvas
          title="Booked Meetings"
          actions={<PrimaryButton icon={<RefreshCw className="size-4" />} onClick={() => void runAction(services.syncMeetings(), "Calendar sync complete.")}>Sync</PrimaryButton>}
        >
          <DataNotice status={status} error={error} errors={data?.errors} />
          {message ? <p className="mt-2 text-sm font-bold text-[var(--sparx-muted)]">{message}</p> : null}
          <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
            <section className="grid gap-4">
              <AssetFrame className="min-h-[190px] bg-[linear-gradient(135deg,#f7d674,#c99b25)] text-white" title="Secured meetings image frame" description="Reserved for the yellow meeting asset from Figma." />
              <div className="rounded-[8px] bg-[var(--sparx-card-strong)] p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h3 className="text-lg font-black">Secured Meetings</h3>
                  <StatusBadge>{meetings.length} Records</StatusBadge>
                </div>
                {meetings.length ? (
                  <div className="grid gap-3">
                    {meetings.map((meeting) => (
                      <article className="flex flex-col gap-3 rounded-[8px] bg-white p-3 sm:flex-row sm:items-center sm:justify-between" key={meeting.meeting_id}>
                        <div className="flex min-w-0 gap-3">
                          <AvatarFrame label={meeting.attendee_name || meeting.title} />
                          <div className="min-w-0">
                            <StatusBadge tone={statusTone(meeting.status)}>{humanize(meeting.status)}</StatusBadge>
                            <h4 className="truncate text-xl font-black">{meeting.attendee_name || meeting.title}</h4>
                            <p className="text-xs font-semibold text-[var(--sparx-muted)]">{formatDate(meeting.scheduled_for)} | {meetingTimeBounds(meeting)}</p>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {meeting.meet_link ? (
                            <a className="inline-flex min-h-10 items-center rounded-full bg-[var(--sparx-olive)] px-5 text-sm font-black text-white" href={meeting.meet_link} rel="noreferrer" target="_blank">
                              Open Teams <ArrowUpRight className="ml-2 size-4" />
                            </a>
                          ) : null}
                          <PrimaryButton onClick={() => void runAction(services.markMeetingDone(meeting.meeting_id), "Meeting marked done.")} variant="soft">
                            Done
                          </PrimaryButton>
                          <button className="grid size-10 place-items-center rounded-full text-[var(--sparx-red)]" onClick={() => void runAction(services.cancelMeeting(meeting.meeting_id, "Cancelled from SPARX dashboard"), "Meeting cancelled.")} type="button">
                            <AlertCircle className="size-5" />
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No secured meetings" description="Calendar-linked backend meetings will appear here after sync." />
                )}
              </div>
            </section>
            <AssetFrame className="min-h-[520px] bg-white/70" title="Calendar layout frame" description="Reserved for the full calendar illustration/table from Figma." />
          </div>
        </PageCanvas>
      </PageFrame>
    </AppShell>
  );
}

function campaignTotals(campaigns: Campaign[]) {
  return campaigns.reduce(
    (totals, campaign) => ({
      imported: totals.imported + campaign.total_contacts,
      processing: totals.processing + campaign.pending_calls + campaign.active_calls,
      failed: totals.failed + campaign.failed_calls,
      completed: totals.completed + campaign.completed_calls,
      callsStarted: totals.callsStarted + campaign.answered_calls + campaign.completed_calls + campaign.failed_calls,
    }),
    { imported: 0, processing: 0, failed: 0, completed: 0, callsStarted: 0 },
  );
}

function ImportOutcomeRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="grid gap-1">
      <div className="flex items-center justify-between text-sm font-bold">
        <span>{label}</span>
        <span>{value}</span>
      </div>
      <div className="h-2 rounded-full bg-[var(--sparx-panel)]">
        <div className={cn("h-2 rounded-full", tone)} style={{ width: `${Math.min(100, value * 10)}%` }} />
      </div>
    </div>
  );
}

export function ImportsPage({ initialData }: PageDataProps) {
  const { data, status, error, refresh } = usePlatformData(initialData);
  const campaigns = data?.campaigns ?? emptyCampaigns;
  const calls = data?.calls ?? emptyCalls;
  const totals = campaignTotals(campaigns);
  const [preview, setPreview] = useState<CampaignPreview | null>(null);
  const [message, setMessage] = useState("");
  const [now] = useState(() => Date.now());
  const todayKey = new Date(now).toDateString();
  const importedToday = campaigns
    .filter((campaign) => campaign.created_at && new Date(campaign.created_at).toDateString() === todayKey)
    .reduce((sum, campaign) => sum + campaign.total_contacts, 0);
  const callsToday = calls.filter((call) => {
    const timestamp = call.started_at || call.created_at;
    return timestamp ? new Date(timestamp).toDateString() === todayKey : false;
  }).length;

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setMessage("Checking import file...");
    try {
      const nextPreview = await services.previewLeads(file);
      setPreview(nextPreview);
      setMessage(`${nextPreview.valid_contacts} valid contacts ready for campaign creation.`);
    } catch (err) {
      setPreview(null);
      setMessage(err instanceof Error ? err.message : "Import preview failed.");
    }
  }

  const outcomes = {
    callsStarted: calls.filter((call) => ["answered", "in_progress", "completed", "callback_requested", "meeting_requested"].includes(call.status)).length,
    notCalled: calls.filter((call) => ["no_answer", "busy"].includes(call.status)).length,
    invalidNumbers: campaigns.reduce((sum, campaign) => sum + campaign.failed_calls, 0),
    failedStarts: calls.filter((call) => call.status === "failed").length,
    pending: campaigns.reduce((sum, campaign) => sum + campaign.pending_calls, 0),
  };

  const totalImported = totals.imported + (preview?.valid_contacts ?? 0);
  const conic = totalImported
    ? `conic-gradient(var(--sparx-card) 0 ${Math.max(5, (totals.completed / totalImported) * 100)}%, var(--sparx-yellow) 0 ${Math.max(10, ((totals.completed + totals.processing) / totalImported) * 100)}%, var(--sparx-red) 0)`
    : "conic-gradient(var(--sparx-panel) 0 100%)";

  return (
    <AppShell>
      <GreetingHeader />
      <PageFrame>
        <PageCanvas
          title="Import and queue"
          actions={<PrimaryButton icon={<RefreshCw className="size-4" />} onClick={refresh}>Refresh</PrimaryButton>}
        >
          <p className="text-sm font-semibold text-[var(--sparx-muted)]">Upload content, manage your queue, and track your imports.</p>
          <DataNotice status={status} error={error} errors={data?.errors} />
          {message ? <p className="mt-2 text-sm font-bold text-[var(--sparx-muted)]">{message}</p> : null}
          <section className="mt-4 grid gap-5 xl:grid-cols-2">
            <label className="grid min-h-[190px] cursor-pointer place-items-center rounded-[8px] border border-dashed border-[var(--sparx-line-strong)] bg-white/70 p-5 text-center">
              <input accept=".csv,.xlsx,.xls,.pdf,.doc,.docx,.txt" className="sr-only" onChange={handleFile} type="file" />
              <span>
                <Upload className="mx-auto size-10 text-[var(--sparx-olive)]" />
                <strong className="mt-3 block text-lg font-black">Drag & drop images, videos, or any file</strong>
                <span className="mt-1 block text-sm font-semibold text-[var(--sparx-muted)]">or browse files on your computer</span>
                <span className="mt-4 inline-flex min-h-10 items-center rounded-full bg-[var(--sparx-olive)] px-6 text-sm font-black text-white">Upload</span>
              </span>
            </label>
            <EmptyState title="Queue is Empty" description="Running and pending backend campaign contacts will appear in the queue." />
          </section>
          <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
            <div className="rounded-[8px] bg-[linear-gradient(135deg,#6f5200,#2b1b0d)] p-5 text-white">
              <div className="grid gap-5 sm:grid-cols-[140px_1fr] sm:items-center">
                <div className="grid size-36 place-items-center rounded-full" style={{ background: conic }}>
                  <div className="grid size-24 place-items-center rounded-full bg-[var(--sparx-olive)] text-center">
                    <strong className="text-3xl font-black">{formatNumber(totalImported)}</strong>
                    <span className="text-xs font-semibold">Total Imported</span>
                  </div>
                </div>
                <div className="grid gap-3 text-sm font-bold">
                  <div className="flex justify-between"><span>Imported</span><span>{formatNumber(totals.completed)}</span></div>
                  <div className="flex justify-between"><span>Processing</span><span>{formatNumber(totals.processing)}</span></div>
                  <div className="flex justify-between"><span>Failed</span><span>{formatNumber(totals.failed)}</span></div>
                  <div className="flex items-center gap-2 border-t border-white/20 pt-3 text-white/80"><Clock3 className="size-4" /> Last 30 days</div>
                </div>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard label="Contacts" value={formatNumber(totalImported)} caption={preview ? `${preview.valid_contacts} in current preview` : "Imported leads"} icon={<User className="size-4" />} tone="white" />
              <StatCard label="Imported leads" value={formatNumber(totals.completed)} caption={`+${formatNumber(importedToday)} today`} icon={<Download className="size-4" />} tone="olive" />
              <StatCard label="Calls Started" value={formatNumber(outcomes.callsStarted || totals.callsStarted)} caption={`+${formatNumber(callsToday)} today`} icon={<Phone className="size-4" />} tone="white" />
              <StatCard label="Handed to TalkIQ" value={formatNumber(calls.length)} caption={`+${formatNumber(callsToday)} today`} icon={<Send className="size-4" />} tone="olive" />
            </div>
          </section>
          <section className="mt-5 grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
            <div className="rounded-[8px] bg-white p-4">
              <h3 className="mb-4 text-lg font-black">Outcome Breakdown</h3>
              <div className="grid gap-4">
                <ImportOutcomeRow label="Calls Started" value={outcomes.callsStarted} tone="bg-green-500" />
                <ImportOutcomeRow label="Not Called" value={outcomes.notCalled} tone="bg-yellow-400" />
                <ImportOutcomeRow label="Invalid Numbers" value={outcomes.invalidNumbers} tone="bg-red-200" />
                <ImportOutcomeRow label="Failed Starts" value={outcomes.failedStarts} tone="bg-purple-300" />
                <ImportOutcomeRow label="Pending" value={outcomes.pending} tone="bg-neutral-300" />
              </div>
            </div>
            <div className="rounded-[8px] bg-white p-4">
              <h3 className="text-lg font-black">Executive Summary</h3>
              <p className="mt-2 text-sm font-medium text-[var(--sparx-muted)]">
                {campaigns.length
                  ? `Campaigns are progressing. ${formatNumber(totals.processing)} contacts are pending or active, ${formatNumber(totals.failed)} failed, and ${formatNumber(totals.completed)} completed from backend campaign records.`
                  : "No backend campaign imports have been created yet."}
              </p>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <StatusBadge tone="active">Touched {formatNumber(outcomes.callsStarted)}</StatusBadge>
                <StatusBadge tone="warning">Not called {formatNumber(outcomes.notCalled)}</StatusBadge>
                <StatusBadge tone="danger">Errored {formatNumber(outcomes.failedStarts)}</StatusBadge>
              </div>
            </div>
          </section>
        </PageCanvas>
      </PageFrame>
    </AppShell>
  );
}
