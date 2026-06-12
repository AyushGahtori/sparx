"use client";

import Link from "next/link";
import Image from "next/image";
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
  Phone,
  RefreshCw,
  RotateCcw,
  Send,
  Trash2,
  Upload,
  User,
  X,
} from "lucide-react";
import {
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useAuth } from "@/components/auth-provider";
import {
  AppShell,
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
  type MeetingCreatePayload,
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
  const { loading: authLoading, user } = useAuth();
  const [data, setData] = useState<PlatformData | null>(initialData ?? null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(initialData ? "ready" : "loading");
  const [error, setError] = useState("");
  const didLoadClientData = useRef(false);

  const refresh = useCallback(async (options: { silent?: boolean } = {}) => {
    if (!options.silent) {
      setStatus("loading");
    }
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
    if (!authLoading && user && !didLoadClientData.current) {
      const timer = window.setTimeout(() => {
        didLoadClientData.current = true;
        void refresh({ silent: Boolean(data) });
      }, 0);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [authLoading, data, refresh, user]);

  useEffect(() => {
    if (authLoading || !user) {
      return;
    }
    let eventSource: EventSource | null = null;
    let isDisposed = false;

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

    const connect = async () => {
      if (eventSource || (typeof document !== "undefined" && document.visibilityState === "hidden")) {
        return;
      }
      const token = await user.getIdToken();
      if (isDisposed || (typeof document !== "undefined" && document.visibilityState === "hidden")) {
        return;
      }
      const source = new EventSource(platformEventStreamUrl(token));
      eventSource = source;
      source.addEventListener("call.updated", (message) => {
        applyEvent(JSON.parse(message.data) as PlatformRealtimeEvent);
      });
      source.addEventListener("call.deleted", (message) => {
        applyEvent(JSON.parse(message.data) as PlatformRealtimeEvent);
      });
      source.onerror = () => {
        source.close();
        if (eventSource === source) {
          eventSource = null;
        }
      };
    };

    const disconnect = () => {
      eventSource?.close();
      eventSource = null;
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void connect();
      } else {
        disconnect();
      }
    };

    void connect();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      isDisposed = true;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      disconnect();
    };
  }, [authLoading, user]);

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
    <label className="grid min-w-0 gap-1.5">
      <span className="text-sm font-black">{label}</span>
      <select
        className="h-10 w-full min-w-0 truncate rounded-[6px] border border-[var(--sparx-line-strong)] bg-white px-3 text-sm font-semibold outline-none focus:border-[var(--sparx-yellow)] focus:ring-2 focus:ring-[rgba(241,231,47,0.36)]"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
    </label>
  );
}

function TextAreaField({
  label,
  value,
  onChange,
  placeholder,
  required,
  rows = 3,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  rows?: number;
}) {
  return (
    <label className="grid gap-1.5">
      <span className="text-sm font-black">{label}</span>
      <textarea
        className="min-h-24 resize-none rounded-[6px] border border-[var(--sparx-line-strong)] bg-white px-3 py-2 text-sm font-semibold outline-none focus:border-[var(--sparx-yellow)] focus:ring-2 focus:ring-[rgba(241,231,47,0.36)]"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        required={required}
        rows={rows}
      />
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
              <PrimaryButton icon={<RefreshCw className="size-4" />} onClick={() => void refresh()}>
                Refresh
              </PrimaryButton>
            </div>
          }
        >
          <DataNotice status={status} error={error} errors={data?.errors} />
          <section className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Active Calls" value={activeCalls.length} caption="Real-time Sessions" icon={previewIcons.calls} />
            <StatCard label="Transcripts" value={transcriptLines} caption="Live utterances" icon={previewIcons.transcript} />
            <StatCard label="Contacts" value={contacts} caption="Ready to Dial" icon={<User className="size-4" />} />
            <StatCard label="Meetings" value={meetingCount} caption="Booked Outcomes" icon={<CalendarCheck className="size-4" />} tone="olive" />
          </section>
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
          actions={<PrimaryButton icon={<RefreshCw className="size-4" />} onClick={() => void refresh()}>{currentMonthLabel()}</PrimaryButton>}
        >
          <p className="max-w-xl text-sm font-semibold text-[var(--sparx-muted)]">
            Open any call in a dedicated transcript window without touching the live dashboard transcripts.
          </p>
          <DataNotice status={status} error={error} errors={data?.errors} />
          <section className="mt-5 grid max-w-[920px] grid-cols-2 gap-x-12 gap-y-5 md:grid-cols-4 md:gap-x-14">
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

const supportedRenewalExtensions = [".csv", ".xlsx", ".xls"];

function isSupportedRenewalFile(file: File) {
  const lowered = file.name.toLowerCase();
  return supportedRenewalExtensions.some((extension) => lowered.endsWith(extension));
}

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
  const [recordStatus, setRecordStatus] = useState<"all" | Campaign["status"]>("all");
  const [recordSort, setRecordSort] = useState<"recent" | "progress" | "contacts">("recent");
  const formReady = Boolean(
    form.campaign_name.trim()
    && selectedAgentId
    && form.campaign_type.trim()
    && form.language.trim()
    && form.call_objective.trim()
    && form.product_description.trim(),
  );
  const fileValidationPassed = Boolean(
    preview
    && preview.valid_contacts > 0
    && preview.invalid_contacts === 0
    && preview.duplicate_contacts === 0,
  );
  const mappingComplete = Boolean(preview?.source_columns.length && preview?.contacts.length);
  const disabledReason = busy
    ? "Validation is still running."
    : !formReady
      ? "Complete campaign setup and product details first."
      : !preview
        ? "Upload a CSV or Excel renewal sheet."
        : !mappingComplete
          ? "The backend could not map the customer phone column."
          : !fileValidationPassed
            ? "Resolve invalid or duplicate rows before creating the campaign."
            : "";
  const canCreateCampaign = !disabledReason;
  const campaignMetrics = campaignTotals(campaigns);
  const filteredCampaigns = campaigns
    .filter((campaign) => recordStatus === "all" || campaign.status === recordStatus)
    .sort((a, b) => {
      if (recordSort === "contacts") return b.total_contacts - a.total_contacts;
      if (recordSort === "progress") return (b.progress_percent ?? 0) - (a.progress_percent ?? 0);
      return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
    });

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!isSupportedRenewalFile(file)) {
      setPreview(null);
      setMessage("Unsupported file. Upload a CSV, XLSX, or XLS renewal sheet.");
      event.target.value = "";
      return;
    }
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
    if (!canCreateCampaign || !preview) {
      setMessage(disabledReason || "Upload and validate a renewal sheet before creating a campaign.");
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

  async function runCampaignAction(action: Promise<Campaign>, success: string) {
    setBusy(true);
    setMessage("Updating campaign...");
    try {
      await action;
      setMessage(success);
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Campaign action failed.");
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
        <section className="rounded-[36px] bg-[#F5F2EE] p-5 sm:p-7 lg:p-9">
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
                {message ? <p className="mt-3 text-sm font-bold text-[var(--sparx-muted)]">{message}</p> : null}
                <div className="mt-4 flex flex-wrap gap-2">
                  <PrimaryButton disabled={!canCreateCampaign} title={disabledReason || "Create campaign"} type="submit">Create Campaign</PrimaryButton>
                  <PrimaryButton onClick={() => void refresh()} type="button" variant="soft">Refresh</PrimaryButton>
                </div>
                {disabledReason ? <p className="mt-2 text-xs font-bold text-[var(--sparx-muted)]">{disabledReason}</p> : null}
              </form>
              <div>
                <div className="rounded-[8px] bg-[var(--sparx-card-strong)] p-4 text-center">
                  <div className="mx-auto mb-3 grid size-12 place-items-center rounded-[8px] bg-white text-[var(--sparx-olive)]">
                    <Upload className="size-7" />
                  </div>
                  <h3 className="text-lg font-black">Renewal Sheet Import</h3>
                  <p className="mx-auto mt-2 max-w-[300px] text-sm font-semibold text-[var(--sparx-muted)]">
                    Upload CSV or Excel data. Sparx automatically maps the customer phone column before creating the queue.
                  </p>
                  <label className="mt-4 inline-flex min-h-11 cursor-pointer items-center justify-center rounded-full bg-white px-6 text-sm font-black text-black ring-1 ring-[var(--sparx-line)] transition hover:bg-[var(--sparx-panel)]">
                    <input accept=".csv,.xlsx,.xls" className="sr-only" disabled={busy} onChange={handleFile} type="file" />
                    Select Renewal File
                  </label>
                  {preview ? (
                    <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                      <MiniMetric value={preview.valid_contacts} label="Valid" />
                      <MiniMetric value={preview.invalid_contacts} label="Invalid" />
                      <MiniMetric value={preview.duplicate_contacts} label="Duplicate" />
                    </div>
                  ) : (
                    <p className="mt-3 text-xs font-bold text-[var(--sparx-muted)]">Supported formats: CSV, XLSX, XLS.</p>
                  )}
                  {preview ? (
                    <div className="mt-3 rounded-[8px] bg-white/70 p-3 text-left text-xs font-bold text-[var(--sparx-muted)]">
                      <p>{preview.filename}</p>
                      <p>{mappingComplete ? "Phone column mapped by backend." : "Phone column mapping pending."}</p>
                      <p>{fileValidationPassed ? "Validation passed." : "Validation needs attention before campaign creation."}</p>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </PageCanvas>
        </section>
        <section className="mt-5">
          <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h3 className="text-xl font-black">Campaign Records</h3>
              <p className="text-sm font-semibold text-[var(--sparx-muted)]">Track imports, validation quality, queue status, and campaign performance.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {["all", "scheduled", "running", "paused", "completed", "failed"].map((statusKey) => (
                <button
                  className={cn(
                    "rounded-full px-4 py-2 text-xs font-black transition",
                    recordStatus === statusKey ? "bg-[var(--sparx-olive)] text-white" : "bg-white text-[var(--sparx-muted)] ring-1 ring-[var(--sparx-line)]",
                  )}
                  key={statusKey}
                  onClick={() => setRecordStatus(statusKey as typeof recordStatus)}
                  type="button"
                >
                  {humanize(statusKey)}
                </button>
              ))}
              <select
                className="h-9 rounded-full border border-[var(--sparx-line)] bg-white px-3 text-xs font-black outline-none"
                value={recordSort}
                onChange={(event) => setRecordSort(event.target.value as typeof recordSort)}
              >
                <option value="recent">Newest</option>
                <option value="progress">Progress</option>
                <option value="contacts">Contacts</option>
              </select>
            </div>
          </div>

          <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Imported" value={formatNumber(campaignMetrics.imported)} caption="Total queued contacts" icon={<Download className="size-4" />} tone="white" />
            <StatCard label="Processing" value={formatNumber(campaignMetrics.processing)} caption="Pending or active" icon={<RefreshCw className="size-4" />} tone="white" />
            <StatCard label="Completed" value={formatNumber(campaignMetrics.completed)} caption="Finished calls" icon={<CheckCircle2 className="size-4" />} tone="olive" />
            <StatCard label="Failed" value={formatNumber(campaignMetrics.failed)} caption="Needs review" icon={<AlertCircle className="size-4" />} tone="white" />
          </div>

          {filteredCampaigns.length ? (
            <div className="grid gap-3">
              {filteredCampaigns.map((campaign) => {
                const leadSource = (campaign.metadata?.lead_source || {}) as Record<string, unknown>;
                const filename = typeof leadSource.filename === "string" && leadSource.filename ? leadSource.filename : "Manual import";
                const invalidContacts = Number(leadSource.invalid_contacts || 0);
                const duplicateContacts = Number(leadSource.duplicate_contacts || 0);
                const progress = Math.max(0, Math.min(100, campaign.progress_percent ?? campaign.progress_percentage ?? 0));
                return (
                  <article key={campaign.campaign_id} className="rounded-[8px] bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge tone={statusTone(campaign.status)}>{humanize(campaign.status)}</StatusBadge>
                          <span className="text-xs font-black text-[var(--sparx-muted)]">{formatDateTime(campaign.created_at)}</span>
                        </div>
                        <h4 className="mt-2 text-xl font-black">{campaign.campaign_name}</h4>
                        <p className="text-sm font-semibold text-[var(--sparx-muted)]">{campaign.agent_name} | {campaign.total_contacts} contacts | {campaign.dispatch_mode.replace(/_/g, " ")}</p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {campaign.status === "running" ? (
                          <PrimaryButton disabled={busy} onClick={() => void runCampaignAction(services.pauseCampaign(campaign.campaign_id), "Campaign paused.")} variant="soft">Pause</PrimaryButton>
                        ) : campaign.status === "paused" ? (
                          <PrimaryButton disabled={busy} onClick={() => void runCampaignAction(services.resumeCampaign(campaign.campaign_id), "Campaign resumed.")} variant="soft">Resume</PrimaryButton>
                        ) : campaign.status !== "completed" && campaign.status !== "cancelled" ? (
                          <PrimaryButton disabled={busy} onClick={() => void runCampaignAction(services.startCampaign(campaign.campaign_id), "Campaign started.")} variant="soft">Start</PrimaryButton>
                        ) : null}
                        {["running", "paused", "scheduled"].includes(campaign.status) ? (
                          <PrimaryButton disabled={busy} onClick={() => void runCampaignAction(services.stopCampaign(campaign.campaign_id), "Campaign stopped.")} variant="soft">Stop</PrimaryButton>
                        ) : null}
                      </div>
                    </div>
                    <div className="mt-4 h-2 overflow-hidden rounded-full bg-[var(--sparx-panel)]">
                      <div className="h-full rounded-full bg-[var(--sparx-olive)] transition-all duration-500" style={{ width: `${progress}%` }} />
                    </div>
                    <div className="mt-4 grid gap-3 md:grid-cols-3">
                      <div className="rounded-[8px] bg-[var(--sparx-panel)] p-3">
                        <p className="text-xs font-black uppercase text-[var(--sparx-muted)]">Import History</p>
                        <p className="mt-1 truncate text-sm font-black">{filename}</p>
                        <p className="text-xs font-semibold text-[var(--sparx-muted)]">{leadSource.file_type ? String(leadSource.file_type).toUpperCase() : "Source"} | {formatNumber(Number(leadSource.valid_contacts || campaign.total_contacts))} valid</p>
                      </div>
                      <div className="rounded-[8px] bg-[var(--sparx-panel)] p-3">
                        <p className="text-xs font-black uppercase text-[var(--sparx-muted)]">Validation History</p>
                        <p className="mt-1 text-sm font-black">{invalidContacts} invalid | {duplicateContacts} duplicate</p>
                        <p className="text-xs font-semibold text-[var(--sparx-muted)]">{invalidContacts || duplicateContacts ? "Review source data before reimport." : "Import validation passed."}</p>
                      </div>
                      <div className="rounded-[8px] bg-[var(--sparx-panel)] p-3">
                        <p className="text-xs font-black uppercase text-[var(--sparx-muted)]">Campaign Analytics</p>
                        <p className="mt-1 text-sm font-black">{campaign.completed_calls}/{campaign.total_contacts} completed | {formatNumber(campaign.success_rate)}% success</p>
                        <p className="text-xs font-semibold text-[var(--sparx-muted)]">{campaign.pending_calls} pending | {campaign.active_calls} active | {campaign.failed_calls} failed</p>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : <EmptyState title="No matching campaigns" description="Campaigns will appear here after a validated renewal sheet creates a queue." />}
        </section>
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
      void refresh();
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
            <PrimaryButton icon={<RefreshCw className="size-4" />} onClick={() => void refresh()} variant="soft">
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
          actions={<PrimaryButton icon={<RefreshCw className="size-4" />} onClick={() => void refresh()}>Refresh</PrimaryButton>}
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
          actions={<PrimaryButton icon={<RefreshCw className="size-4" />} onClick={() => void refresh()}>Refresh</PrimaryButton>}
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

  function toggleCallbackSchedule(callback: CallbackRecord) {
    const isCancelled = callback.status === "cancelled";
    const nextStatus = isCancelled ? "scheduled" : "cancelled";
    const success = isCancelled ? "Callback rescheduled." : "Callback cancelled.";
    return runAction(services.updateCallback(callback.callback_id, { status: nextStatus }), success);
  }

  return (
    <AppShell>
      <GreetingHeader />
      <PageFrame>
        <section className="rounded-[36px] bg-[#F5F2EE] p-5 sm:p-7 lg:p-9">
          <PageCanvas title="Reschedule">
            <DataNotice status={status} error={error} errors={data?.errors} />
            {message ? <p className="mt-2 text-sm font-bold text-[var(--sparx-muted)]">{message}</p> : null}
            <section className="mt-4 grid max-w-[920px] grid-cols-2 gap-x-12 gap-y-5 md:grid-cols-4 md:gap-x-14">
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
                    {upcomingCallbacks(callbacks).map((callback) => {
                      const isCancelled = callback.status === "cancelled";
                      return (
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
                            <PrimaryButton disabled={isCancelled} icon={<Phone className="size-4" />} onClick={() => void runAction(services.executeCallback(callback.callback_id), "Callback execution queued.")}>
                              Dial
                            </PrimaryButton>
                            <PrimaryButton disabled={isCancelled} icon={<CheckCircle2 className="size-4" />} onClick={() => void runAction(services.updateCallback(callback.callback_id, { status: "completed" }), "Callback marked completed.")} variant="soft">
                              Done
                            </PrimaryButton>
                            <button
                              aria-label={isCancelled ? "Reschedule callback" : "Cancel callback"}
                              className={cn(
                                "grid size-8 place-items-center rounded-full border bg-white",
                                isCancelled
                                  ? "border-[var(--sparx-olive)] text-[var(--sparx-olive)]"
                                  : "border-[var(--sparx-red)] text-[var(--sparx-red)]",
                              )}
                              onClick={() => void toggleCallbackSchedule(callback)}
                              title={isCancelled ? "Reschedule" : "Cancel"}
                              type="button"
                            >
                              {isCancelled ? <RotateCcw className="size-4" /> : <X className="size-4" />}
                            </button>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </ScrollPanel>
              ) : (
                <EmptyState title="No rescheduled calls" description="Backend callback records will appear here after callers ask for a later time." />
              )}
            </section>
          </PageCanvas>
        </section>
      </PageFrame>
    </AppShell>
  );
}
const schedulingTimeZones = [
  "Asia/Kolkata",
  "UTC",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Dubai",
  "Asia/Singapore",
];

type MeetingFormState = {
  full_name: string;
  phone: string;
  email: string;
  title: string;
  description: string;
  date: string;
  time: string;
  timezone: string;
  notes: string;
};

const initialMeetingForm = (): MeetingFormState => {
  const now = new Date();
  now.setMinutes(now.getMinutes() + 30);
  const localDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  return {
    full_name: "",
    phone: "",
    email: "",
    title: "SPARX consultation",
    description: "",
    date: localDate,
    time: `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata",
    notes: "",
  };
};

function validateMeetingForm(form: MeetingFormState) {
  const errors: Partial<Record<keyof MeetingFormState, string>> = {};
  if (!form.full_name.trim()) errors.full_name = "Full name is required.";
  if (!phonePattern.test(form.phone.trim())) errors.phone = "Enter a valid phone number.";
  if (!emailPattern.test(form.email.trim())) errors.email = "Enter a valid email address.";
  if (!form.title.trim()) errors.title = "Meeting title is required.";
  if (!form.description.trim()) errors.description = "Meeting description is required.";
  if (!form.date) errors.date = "Meeting date is required.";
  if (!form.time) errors.time = "Meeting time is required.";
  if (!form.timezone.trim()) errors.timezone = "Time zone is required.";

  if (form.date && form.time) {
    const candidate = new Date(`${form.date}T${form.time}:00`);
    if (Number.isNaN(candidate.getTime())) {
      errors.time = "Enter a valid meeting time.";
    } else if (candidate <= new Date()) {
      errors.date = "Choose a future meeting date and time.";
    }
  }

  return errors;
}

function meetingFormToPayload(form: MeetingFormState): MeetingCreatePayload {
  return {
    full_name: form.full_name.trim(),
    phone: form.phone.trim(),
    email: form.email.trim().toLowerCase(),
    title: form.title.trim(),
    description: form.description.trim(),
    scheduled_for: `${form.date}T${form.time}:00`,
    timezone: form.timezone.trim(),
    notes: form.notes.trim() || null,
  };
}

function SchedulingModal({
  isOpen,
  isClosing,
  onClose,
  onSubmit,
  busy,
  message,
}: {
  isOpen: boolean;
  isClosing: boolean;
  onClose: () => void;
  onSubmit: (payload: MeetingCreatePayload) => Promise<void>;
  busy: boolean;
  message?: string;
}) {
  const [form, setForm] = useState<MeetingFormState>(initialMeetingForm);
  const [errors, setErrors] = useState<Partial<Record<keyof MeetingFormState, string>>>({});

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [busy, isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  const update = <K extends keyof MeetingFormState>(key: K, value: MeetingFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: undefined }));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const nextErrors = validateMeetingForm(form);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) {
      return;
    }
    await onSubmit(meetingFormToPayload(form));
  };

  const fieldError = (key: keyof MeetingFormState) => errors[key]
    ? <span className="text-xs font-bold text-[var(--sparx-red)]">{errors[key]}</span>
    : null;

  return (
    <div className={cn("fixed inset-0 z-50 grid place-items-center bg-black/35 px-4 py-6 backdrop-blur-sm transition duration-200", isClosing ? "opacity-0" : "opacity-100 animate-[sparx-fade-up_180ms_ease-out_both]")}>
      <form
        aria-label="Schedule meeting"
        className={cn("w-[min(760px,92vw)] max-h-[84vh] overflow-auto rounded-[8px] border border-white/70 bg-[var(--sparx-panel)] p-5 shadow-[0_24px_80px_rgba(20,16,8,0.28)] transition duration-200", isClosing ? "translate-y-2 scale-[0.98] opacity-0" : "animate-[sparx-scale-in_220ms_ease-out_both]")}
        onSubmit={submit}
      >
        <div className="mb-4 flex items-start justify-between gap-4 border-b border-[var(--sparx-line)] pb-3">
          <div>
            <h3 className="text-2xl font-black">Schedule Meeting</h3>
            <p className="mt-1 text-sm font-semibold text-[var(--sparx-muted)]">Google Calendar will send the participant invitation and Google Meet link.</p>
          </div>
          <button
            aria-label="Close scheduling modal"
            className="grid size-10 shrink-0 place-items-center rounded-full bg-white text-[var(--sparx-muted)] transition hover:text-black"
            disabled={busy}
            onClick={onClose}
            type="button"
          >
            <X className="size-5" />
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Field label="Full Name" value={form.full_name} onChange={(value) => update("full_name", value)} required />
            {fieldError("full_name")}
          </div>
          <div>
            <Field label="Phone Number" value={form.phone} onChange={(value) => update("phone", value)} placeholder="+919999999999" required />
            {fieldError("phone")}
          </div>
          <div>
            <Field label="Email" value={form.email} onChange={(value) => update("email", value)} placeholder="name@example.com" required type="email" />
            {fieldError("email")}
          </div>
          <div>
            <Field label="Meeting Title" value={form.title} onChange={(value) => update("title", value)} required />
            {fieldError("title")}
          </div>
          <div className="sm:col-span-2">
            <TextAreaField label="Meeting Description" value={form.description} onChange={(value) => update("description", value)} required />
            {fieldError("description")}
          </div>
          <div>
            <Field label="Meeting Date" value={form.date} onChange={(value) => update("date", value)} required type="date" />
            {fieldError("date")}
          </div>
          <div>
            <Field label="Meeting Time" value={form.time} onChange={(value) => update("time", value)} required type="time" />
            {fieldError("time")}
          </div>
          <div className="sm:col-span-2">
            <SelectField label="Time Zone" value={form.timezone} onChange={(value) => update("timezone", value)}>
              {Array.from(new Set([form.timezone, ...schedulingTimeZones])).filter(Boolean).map((timezone) => (
                <option key={timezone} value={timezone}>{timezone}</option>
              ))}
            </SelectField>
            {fieldError("timezone")}
          </div>
          <div className="sm:col-span-2">
            <TextAreaField label="Notes (optional)" value={form.notes} onChange={(value) => update("notes", value)} rows={2} />
          </div>
        </div>

        {message ? (
          <div className="mt-4 rounded-[8px] border border-[var(--sparx-line)] bg-white px-3 py-2 text-sm font-bold text-[var(--sparx-muted)]">
            {message}
          </div>
        ) : null}

        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <PrimaryButton disabled={busy} onClick={onClose} type="button" variant="soft">Cancel</PrimaryButton>
          <PrimaryButton disabled={busy} icon={busy ? <RefreshCw className="size-4 animate-spin" /> : <CalendarCheck className="size-4" />} type="submit">
            Schedule Meeting
          </PrimaryButton>
        </div>
      </form>
    </div>
  );
}

function meetingTimeBounds(meeting: MeetingRecord) {
  const start = formatTime(meeting.scheduled_for);
  const end = formatTime(meeting.ends_at);
  return end ? `${start} - ${end}` : start;
}

type CalendarView = "month" | "week" | "day";

const calendarHourHeight = 72;
const dayNamesShort = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function startOfLocalDay(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addCalendarDays(date: Date, days: number) {
  const nextDate = new Date(date);
  nextDate.setDate(nextDate.getDate() + days);
  return nextDate;
}

function addCalendarMonths(date: Date, months: number) {
  const nextDate = new Date(date);
  nextDate.setMonth(nextDate.getMonth() + months);
  return nextDate;
}

function startOfWeek(date: Date) {
  const day = date.getDay();
  const mondayOffset = day === 0 ? -6 : 1 - day;
  return addCalendarDays(startOfLocalDay(date), mondayOffset);
}

function getWeekDates(date: Date) {
  const firstDay = startOfWeek(date);
  return Array.from({ length: 7 }, (_, index) => addCalendarDays(firstDay, index));
}

function sameLocalDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function parseMeetingStart(meeting: MeetingRecord) {
  const start = new Date(meeting.scheduled_for);
  return Number.isNaN(start.getTime()) ? null : start;
}

function parseMeetingEnd(meeting: MeetingRecord) {
  const start = parseMeetingStart(meeting);
  if (!start) return null;
  const explicitEnd = meeting.ends_at ? new Date(meeting.ends_at) : null;
  if (explicitEnd && !Number.isNaN(explicitEnd.getTime()) && explicitEnd > start) {
    return explicitEnd;
  }
  return new Date(start.getTime() + 60 * 60 * 1000);
}

function isMeetingExpired(meeting: MeetingRecord) {
  const end = parseMeetingEnd(meeting);
  return Boolean(end && end < new Date());
}

function isMeetingUnavailable(meeting: MeetingRecord) {
  return meeting.status === "canceled" || meeting.status === "completed" || !meeting.meet_link || isMeetingExpired(meeting);
}

function meetingJoinUnavailableReason(meeting: MeetingRecord) {
  if (meeting.status === "canceled") return "Canceled";
  if (meeting.status === "completed") return "Done";
  if (isMeetingExpired(meeting)) return "Expired";
  if (!meeting.meet_link) return "No link";
  return "Unavailable";
}

function meetingCategory(meeting: MeetingRecord) {
  const text = `${meeting.title} ${meeting.description ?? ""}`.toLowerCase();
  if (/renew|subscription|payment/.test(text)) return "Renewal";
  if (/support|issue|bug|problem/.test(text)) return "Support";
  if (/design|creative|brand/.test(text)) return "Design";
  if (/demo|product|walkthrough/.test(text)) return "Demo";
  if (/follow|callback|reschedule/.test(text)) return "Follow-up";
  return "Meeting";
}

function attendeeInitials(meeting: MeetingRecord) {
  const labels = [meeting.attendee_name, ...meeting.attendees].filter(Boolean) as string[];
  const uniqueLabels = [...new Set(labels)].slice(0, 3);
  const fallback = meeting.title || "Meeting";
  return (uniqueLabels.length ? uniqueLabels : [fallback]).map((label) => label.trim().charAt(0).toUpperCase() || "M");
}

function calendarTitle(anchorDate: Date) {
  return new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" }).format(anchorDate);
}

function dateCardLabel(date: Date) {
  return {
    weekday: new Intl.DateTimeFormat("en-IN", { weekday: "short" }).format(date),
    day: new Intl.DateTimeFormat("en-IN", { day: "2-digit" }).format(date),
  };
}

function getVisibleDates(anchorDate: Date, view: CalendarView) {
  if (view === "day") return [startOfLocalDay(anchorDate)];
  if (view === "week") return getWeekDates(anchorDate);
  const firstOfMonth = new Date(anchorDate.getFullYear(), anchorDate.getMonth(), 1);
  const firstGridDate = startOfWeek(firstOfMonth);
  return Array.from({ length: 42 }, (_, index) => addCalendarDays(firstGridDate, index));
}

function meetingIntersectsDay(meeting: MeetingRecord, day: Date) {
  const start = parseMeetingStart(meeting);
  const end = parseMeetingEnd(meeting);
  if (!start || !end) return false;
  const dayStart = startOfLocalDay(day);
  const dayEnd = addCalendarDays(dayStart, 1);
  return start < dayEnd && end > dayStart;
}

function getCalendarHourBounds(meetings: MeetingRecord[], visibleDates: Date[]) {
  const relevantMeetings = meetings.filter((meeting) => visibleDates.some((date) => meetingIntersectsDay(meeting, date)));
  const starts = relevantMeetings.map(parseMeetingStart).filter(Boolean) as Date[];
  const ends = relevantMeetings.map(parseMeetingEnd).filter(Boolean) as Date[];
  const minHour = Math.min(8, ...starts.map((date) => date.getHours()));
  const maxHour = Math.max(18, ...ends.map((date) => date.getHours() + (date.getMinutes() > 0 ? 1 : 0)));
  return {
    startHour: Math.max(0, minHour),
    endHour: Math.min(24, Math.max(minHour + 1, maxHour)),
  };
}

function layoutMeetingsForDay(meetings: MeetingRecord[], day: Date, startHour: number, endHour: number) {
  type CalendarLayoutItem = {
    meeting: MeetingRecord;
    start: Date;
    end: Date;
    lane: number;
    laneCount: number;
  };

  const dayStart = startOfLocalDay(day);
  const dayEnd = addCalendarDays(dayStart, 1);
  const visibleStart = new Date(dayStart);
  visibleStart.setHours(startHour, 0, 0, 0);
  const visibleEnd = new Date(dayStart);
  visibleEnd.setHours(endHour, 0, 0, 0);

  const items = meetings
    .map((meeting) => {
      const rawStart = parseMeetingStart(meeting);
      const rawEnd = parseMeetingEnd(meeting);
      if (!rawStart || !rawEnd || rawStart >= dayEnd || rawEnd <= dayStart) return null;
      const start = rawStart < visibleStart ? visibleStart : rawStart;
      const end = rawEnd > visibleEnd ? visibleEnd : rawEnd;
      if (end <= visibleStart || start >= visibleEnd) return null;
      return { meeting, start, end, lane: 0, laneCount: 1 };
    })
    .filter((item): item is CalendarLayoutItem => item !== null)
    .sort((a, b) => a.start.getTime() - b.start.getTime());

  const laneEnds: number[] = [];
  items.forEach((item) => {
    const lane = laneEnds.findIndex((endTime) => item.start.getTime() >= endTime);
    const selectedLane = lane >= 0 ? lane : laneEnds.length;
    item.lane = selectedLane;
    laneEnds[selectedLane] = item.end.getTime();
  });
  const laneCount = Math.max(1, laneEnds.length);
  return items.map((item) => ({ ...item, laneCount }));
}

function MeetingAvatarStack({ meeting }: { meeting: MeetingRecord }) {
  return (
    <div className="flex -space-x-2">
      {attendeeInitials(meeting).map((initial, index) => (
        <span
          className="grid size-6 place-items-center rounded-full border-2 border-white bg-[var(--sparx-panel)] text-[10px] font-black text-[var(--sparx-olive)]"
          key={`${meeting.meeting_id}-${initial}-${index}`}
        >
          {initial}
        </span>
      ))}
    </div>
  );
}

function CalendarToolbar({
  anchorDate,
  view,
  onChangeView,
  onMove,
  onToday,
}: {
  anchorDate: Date;
  view: CalendarView;
  onChangeView: (view: CalendarView) => void;
  onMove: (direction: -1 | 1) => void;
  onToday: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <h3 className="text-lg font-black">{calendarTitle(anchorDate)}</h3>
        <button className="rounded-full bg-[var(--sparx-card-strong)] px-4 py-2 text-xs font-black text-[var(--sparx-olive)]" onClick={onToday} type="button">
          Today
        </button>
        <div className="flex items-center gap-1">
          <button className="grid size-8 place-items-center rounded-full text-[var(--sparx-muted)] hover:bg-[var(--sparx-panel)]" onClick={() => onMove(-1)} type="button">
            <ChevronLeft className="size-4" />
          </button>
          <button className="grid size-8 place-items-center rounded-full text-[var(--sparx-muted)] hover:bg-[var(--sparx-panel)]" onClick={() => onMove(1)} type="button">
            <ChevronRight className="size-4" />
          </button>
        </div>
      </div>
      <div className="inline-flex rounded-full bg-[var(--sparx-panel)] p-1">
        {(["month", "week", "day"] as CalendarView[]).map((mode) => (
          <button
            className={cn(
              "rounded-full px-4 py-2 text-xs font-black capitalize text-[var(--sparx-muted)]",
              view === mode && "bg-white text-[var(--sparx-ink)] shadow-sm",
            )}
            key={mode}
            onClick={() => onChangeView(mode)}
            type="button"
          >
            {mode}
          </button>
        ))}
      </div>
    </div>
  );
}

function MonthCalendar({ anchorDate, meetings }: { anchorDate: Date; meetings: MeetingRecord[] }) {
  const visibleDates = getVisibleDates(anchorDate, "month");
  const today = new Date();
  return (
    <div className="mt-4 grid gap-2">
      <div className="grid grid-cols-7 gap-2 text-center text-[11px] font-black uppercase text-[var(--sparx-muted)]">
        {dayNamesShort.map((day) => <span key={day}>{day}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-2">
        {visibleDates.map((date) => {
          const dayMeetings = meetings.filter((meeting) => meetingIntersectsDay(meeting, date));
          const isCurrentMonth = date.getMonth() === anchorDate.getMonth();
          return (
            <div
              className={cn(
                "min-h-28 rounded-[8px] border border-[var(--sparx-line)] bg-white/80 p-2",
                !isCurrentMonth && "opacity-40",
                sameLocalDay(date, today) && "border-[var(--sparx-yellow)]",
              )}
              key={date.toISOString()}
            >
              <div className="mb-2 text-sm font-black">{date.getDate()}</div>
              <div className="grid gap-1">
                {dayMeetings.slice(0, 3).map((meeting) => (
                  <div className="truncate rounded-[6px] bg-[var(--sparx-card-strong)] px-2 py-1 text-[11px] font-black" key={meeting.meeting_id}>
                    {formatTime(meeting.scheduled_for)} {meeting.attendee_name || meeting.title}
                  </div>
                ))}
                {dayMeetings.length > 3 ? <span className="text-[11px] font-bold text-[var(--sparx-muted)]">+{dayMeetings.length - 3} more</span> : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TimeGridCalendar({
  view,
  anchorDate,
  meetings,
  onCreate,
}: {
  view: "week" | "day";
  anchorDate: Date;
  meetings: MeetingRecord[];
  onCreate: () => void;
}) {
  const visibleDates = getVisibleDates(anchorDate, view);
  const { startHour, endHour } = getCalendarHourBounds(meetings, visibleDates);
  const hours = Array.from({ length: endHour - startHour + 1 }, (_, index) => startHour + index);
  const gridHeight = (endHour - startHour) * calendarHourHeight;
  const today = new Date();

  return (
    <div className="mt-4 overflow-x-auto pb-2">
      <div className="min-w-[720px]">
        <div className="grid gap-2" style={{ gridTemplateColumns: `72px repeat(${visibleDates.length}, minmax(120px, 1fr))` }}>
          <button className="rounded-[8px] bg-[var(--sparx-panel)] py-4 text-xs font-black text-[var(--sparx-olive)] transition hover:bg-[var(--sparx-card)] active:scale-[0.98]" onClick={onCreate} type="button">
            + Create
          </button>
          {visibleDates.map((date) => {
            const label = dateCardLabel(date);
            return (
              <div
                className={cn(
                  "rounded-[8px] border border-[var(--sparx-line)] bg-white px-3 py-3 text-center",
                  sameLocalDay(date, today) && "bg-[var(--sparx-panel)]",
                )}
                key={date.toISOString()}
              >
                <div className="text-[11px] font-black uppercase text-[var(--sparx-muted)]">{label.weekday}</div>
                <div className="text-xl font-black">{label.day}</div>
              </div>
            );
          })}
        </div>
        <div className="mt-4 grid gap-2" style={{ gridTemplateColumns: `72px repeat(${visibleDates.length}, minmax(120px, 1fr))` }}>
          <div className="relative" style={{ height: gridHeight }}>
            {hours.slice(0, -1).map((hour, index) => (
              <span className="absolute text-xs font-bold text-[var(--sparx-muted)]" key={hour} style={{ top: index * calendarHourHeight - 2 }}>
                {new Intl.DateTimeFormat("en-IN", { hour: "numeric" }).format(new Date(2026, 0, 1, hour))}
              </span>
            ))}
          </div>
          {visibleDates.map((date) => {
            const laidOutMeetings = layoutMeetingsForDay(meetings, date, startHour, endHour);
            return (
              <div className="relative rounded-[8px] bg-white/60" key={date.toISOString()} style={{ height: gridHeight }}>
                {hours.slice(0, -1).map((hour, index) => (
                  <div className="absolute left-0 right-0 border-t border-dashed border-[var(--sparx-line)]" key={hour} style={{ top: index * calendarHourHeight }} />
                ))}
                {laidOutMeetings.map(({ meeting, start, end, lane, laneCount }) => {
                  const top = ((start.getHours() + start.getMinutes() / 60) - startHour) * calendarHourHeight;
                  const height = Math.max(54, ((end.getTime() - start.getTime()) / 3600000) * calendarHourHeight);
                  const width = `calc(${100 / laneCount}% - 6px)`;
                  const left = `calc(${(100 / laneCount) * lane}% + 3px)`;
                  return (
                    <article
                      className="absolute overflow-hidden rounded-[8px] bg-[var(--sparx-panel)] p-3 shadow-sm"
                      key={meeting.meeting_id}
                      style={{ top, height, left, width }}
                      title={`${meeting.title} ${meetingTimeBounds(meeting)}`}
                    >
                      <div className="truncate text-xs font-black">{meetingCategory(meeting)}</div>
                      <div className="truncate text-[11px] font-bold text-[var(--sparx-muted)]">{meetingTimeBounds(meeting)}</div>
                      <div className="mt-2 flex items-center justify-between gap-2">
                        <MeetingAvatarStack meeting={meeting} />
                        <span className="truncate text-[11px] font-black">{meeting.attendee_name || meeting.title}</span>
                      </div>
                    </article>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function MeetingsCalendar({ meetings, onCreate }: { meetings: MeetingRecord[]; onCreate: () => void }) {
  const [view, setView] = useState<CalendarView>("week");
  const [anchorDate, setAnchorDate] = useState(() => startOfLocalDay(new Date()));

  function moveCalendar(direction: -1 | 1) {
    setAnchorDate((current) => {
      if (view === "month") return addCalendarMonths(current, direction);
      if (view === "week") return addCalendarDays(current, direction * 7);
      return addCalendarDays(current, direction);
    });
  }

  return (
    <div className="rounded-[8px] bg-white/80 p-4">
      <CalendarToolbar
        anchorDate={anchorDate}
        onChangeView={setView}
        onMove={moveCalendar}
        onToday={() => setAnchorDate(startOfLocalDay(new Date()))}
        view={view}
      />
      {view === "month" ? (
        <MonthCalendar anchorDate={anchorDate} meetings={meetings} />
      ) : (
        <TimeGridCalendar anchorDate={anchorDate} meetings={meetings} onCreate={onCreate} view={view} />
      )}
    </div>
  );
}

export function MeetingsPage({ initialData }: PageDataProps) {
  const { data, status, error, refresh } = usePlatformData(initialData);
  const meetings = data?.meetings ?? emptyMeetings;
  const [message, setMessage] = useState("");
  const [isSchedulingOpen, setIsSchedulingOpen] = useState(false);
  const [isSchedulingClosing, setIsSchedulingClosing] = useState(false);
  const [scheduleBusy, setScheduleBusy] = useState(false);

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

  async function handleCreateMeeting(payload: MeetingCreatePayload) {
    if (scheduleBusy) {
      return;
    }
    setScheduleBusy(true);
    setMessage("Scheduling meeting...");
    try {
      const createdMeeting = await services.createMeeting(payload);
      setMessage(
        createdMeeting.meet_link
          ? "Meeting scheduled. Google Calendar sent the invite with the Google Meet link."
          : "Meeting scheduled, but the Google Meet link was not returned.",
      );
      closeSchedulingModal();
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Unable to schedule meeting.");
    } finally {
      setScheduleBusy(false);
    }
  }

  function openSchedulingModal() {
    setMessage("");
    setIsSchedulingClosing(false);
    setIsSchedulingOpen(true);
  }

  function closeSchedulingModal() {
    if (scheduleBusy) {
      return;
    }
    setIsSchedulingClosing(true);
    window.setTimeout(() => {
      setIsSchedulingOpen(false);
      setIsSchedulingClosing(false);
    }, 180);
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
          <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(360px,0.85fr)_minmax(560px,1.15fr)]">
            <section className="grid gap-4">
              <div className="overflow-hidden rounded-[8px] bg-[var(--sparx-card-strong)]">
                <Image
                  alt="Secured meetings"
                  className="h-full min-h-[190px] w-full object-cover"
                  height={760}
                  src="/sparx-assets/secured-meetings.svg"
                  width={1866}
                />
              </div>
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
                          {meeting.meet_link && !isMeetingUnavailable(meeting) ? (
                            <a className="inline-flex min-h-10 items-center rounded-full bg-[var(--sparx-olive)] px-5 text-sm font-black text-white transition hover:bg-[var(--sparx-olive-dark)] active:scale-[0.98]" href={meeting.meet_link} rel="noreferrer" target="_blank">
                              Join <ArrowUpRight className="ml-2 size-4" />
                            </a>
                          ) : (
                            <span className="inline-flex min-h-10 items-center rounded-full bg-white px-4 text-xs font-black text-[var(--sparx-muted)] ring-1 ring-[var(--sparx-line-strong)]" title={meetingJoinUnavailableReason(meeting)}>
                              {meetingJoinUnavailableReason(meeting)}
                            </span>
                          )}
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
            <MeetingsCalendar meetings={meetings} onCreate={openSchedulingModal} />
          </div>
        </PageCanvas>
      </PageFrame>
      <SchedulingModal
        busy={scheduleBusy}
        isClosing={isSchedulingClosing}
        isOpen={isSchedulingOpen}
        message={message}
        onClose={closeSchedulingModal}
        onSubmit={handleCreateMeeting}
      />
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
    if (!isSupportedRenewalFile(file)) {
      setPreview(null);
      setMessage("Unsupported file. Upload a CSV, XLSX, or XLS renewal sheet.");
      event.target.value = "";
      return;
    }
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
          actions={<PrimaryButton icon={<RefreshCw className="size-4" />} onClick={() => void refresh()}>Refresh</PrimaryButton>}
        >
          <p className="text-sm font-semibold text-[var(--sparx-muted)]">Upload CSV or Excel renewal sheets, manage your queue, and track imports.</p>
          <DataNotice status={status} error={error} errors={data?.errors} />
          {message ? <p className="mt-2 text-sm font-bold text-[var(--sparx-muted)]">{message}</p> : null}
          <section className="mt-4 grid gap-5 xl:grid-cols-2">
            <label className="grid min-h-[190px] cursor-pointer place-items-center rounded-[8px] border border-dashed border-[var(--sparx-line-strong)] bg-white/70 p-5 text-center">
              <input accept=".csv,.xlsx,.xls" className="sr-only" onChange={handleFile} type="file" />
              <span>
                <Upload className="mx-auto size-10 text-[var(--sparx-olive)]" />
                <strong className="mt-3 block text-lg font-black">Drag & drop CSV or Excel files</strong>
                <span className="mt-1 block text-sm font-semibold text-[var(--sparx-muted)]">Supported formats: CSV, XLSX, XLS</span>
                <span className="mt-4 inline-flex min-h-10 items-center rounded-full bg-[var(--sparx-olive)] px-6 text-sm font-black text-white">Upload</span>
              </span>
            </label>
            <EmptyState title="Queue is Empty" description="Running and pending backend campaign contacts will appear in the queue." />
          </section>
          <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
            <div className="rounded-[8px] bg-[linear-gradient(135deg,#6f5200,#2b1b0d)] p-5 text-white">
              <div className="grid gap-5 sm:grid-cols-[140px_1fr] sm:items-center">
                <div className="grid size-36 place-items-center rounded-full" style={{ background: conic }}>
                  <div className="grid size-[7.5rem] place-items-center rounded-full bg-[var(--sparx-olive)] text-center">
                    <div className="-translate-y-2">
                      <strong className="block text-3xl font-black leading-none">{formatNumber(totalImported)}</strong>
                      <span className="mt-2 block text-xs font-semibold leading-tight">Total Imported</span>
                    </div>
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
