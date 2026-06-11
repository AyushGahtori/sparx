"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  Clock3,
  FileText,
  Grid2X2,
  Inbox,
  LogOut,
  Moon,
  PhoneCall,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  UploadCloud,
  UsersRound,
} from "lucide-react";
import { cn } from "@/lib/cn";

const navItems = [
  { label: "Dashboard", href: "/", icon: Grid2X2 },
  { label: "Session Logs", href: "/logs", icon: PhoneCall },
  { label: "Manual Call", href: "/manual-call", icon: PhoneCall },
  { label: "Campaign", href: "/campaigns", icon: RefreshCw },
  { label: "Reschedule", href: "/callbacks", icon: Clock3 },
  { label: "Summaries", href: "/summaries", icon: BarChart3 },
  { label: "Transcripts", href: "/transcripts", icon: FileText },
  { label: "Meetings", href: "/meetings", icon: CalendarDays },
  { label: "Import Queue", href: "/imports", icon: UsersRound },
] as const;

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex min-h-screen bg-[var(--sparx-canvas)] text-[var(--sparx-ink)]">
      <Sidebar />
      <main className="min-w-0 flex-1 overflow-auto px-4 py-4 sm:px-6 lg:px-8 lg:py-6">
        {children}
      </main>
    </div>
  );
}

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 z-10 flex h-screen w-[64px] shrink-0 flex-col items-center border-r border-[var(--sparx-line)] bg-white px-2 py-4">
      <div className="grid size-11 shrink-0 place-items-center rounded-[8px] bg-[var(--sparx-brand-soft)] text-white shadow-sm">
        <Sparkles className="size-7" strokeWidth={2.6} />
      </div>

      <nav className="mt-6 flex flex-col items-center gap-2" aria-label="Primary">
        {navItems.map((item) => (
          <Link
            key={item.label}
            className={cn(
              "grid size-10 shrink-0 place-items-center rounded-full text-[var(--sparx-muted)] transition hover:bg-[var(--sparx-panel)]",
              (pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href))) &&
                "bg-[var(--sparx-night)] text-[var(--sparx-yellow)]",
            )}
            href={item.href}
            aria-label={item.label}
            title={item.label}
          >
            <item.icon className="size-5" />
          </Link>
        ))}
      </nav>

      <div className="mt-auto flex flex-col items-center gap-3">
        <IconButton aria-label="Theme preview" title="Theme preview" variant="dark">
          <Moon className="size-5 text-[var(--sparx-yellow)]" />
        </IconButton>
        <IconButton aria-label="Sign out" title="Sign out">
          <LogOut className="size-5" />
        </IconButton>
        <div className="size-12 shrink-0 rounded-full border-2 border-white bg-[linear-gradient(135deg,#9bd8ff,#ffe3b0_48%,#f36d42)] shadow-sm" />
      </div>
    </aside>
  );
}

type GreetingHeaderProps = {
  name?: string;
  subtitle?: string;
};

export function GreetingHeader({
  name = "Amanda",
  subtitle = "Let's take a look at your activity today.",
}: GreetingHeaderProps) {
  return (
    <header className="mb-5 border-b border-[var(--sparx-line)] pb-4">
      <h1 className="text-[24px] font-black leading-tight tracking-normal sm:text-[32px]">
        Hi, {name} !
      </h1>
      <p className="mt-1 text-sm font-medium text-[var(--sparx-muted)] sm:text-base">
        {subtitle}
      </p>
    </header>
  );
}

type PageCanvasProps = {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
};

export function PageCanvas({
  title,
  eyebrow,
  children,
  actions,
  className,
}: PageCanvasProps) {
  return (
    <section className={cn("min-w-0", className)}>
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          {eyebrow ? (
            <span className="text-xs font-black uppercase tracking-normal text-[var(--sparx-olive)]">
              {eyebrow}
            </span>
          ) : null}
          <h2 className="mt-1 text-[34px] font-black leading-none tracking-normal text-black sm:text-[48px]">
            {title}
          </h2>
        </div>
        {actions ? <div className="flex shrink-0 gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

type StatCardProps = {
  label: string;
  value: string | number;
  caption?: string;
  tone?: "warm" | "olive" | "white";
  icon?: ReactNode;
};

export function StatCard({
  label,
  value,
  caption,
  tone = "warm",
  icon,
}: StatCardProps) {
  const toneClass = {
    warm: "bg-[var(--sparx-card)] text-[var(--sparx-ink)]",
    olive: "bg-[var(--sparx-olive)] text-white",
    white: "bg-white text-[var(--sparx-ink)]",
  }[tone];

  return (
    <article
      className={cn(
        "grid min-h-[126px] content-between rounded-[8px] p-4",
        toneClass,
      )}
    >
      <div className="flex items-center gap-2">
        {icon ? (
          <span className="grid size-7 place-items-center rounded-full border border-current/35">
            {icon}
          </span>
        ) : null}
        <span className="text-sm font-black leading-tight">{label}</span>
      </div>
      <div>
        <strong className="block text-[48px] font-black leading-[0.88] tracking-normal sm:text-[56px]">
          {value}
        </strong>
        {caption ? (
          <span className="mt-2 block text-sm font-medium opacity-80">
            {caption}
          </span>
        ) : null}
      </div>
    </article>
  );
}

type StatusBadgeProps = {
  children: ReactNode;
  tone?: "active" | "warning" | "danger" | "neutral";
};

export function StatusBadge({ children, tone = "neutral" }: StatusBadgeProps) {
  const toneClass = {
    active:
      "border-[var(--sparx-green)] bg-[rgba(36,214,77,0.15)] text-[var(--sparx-green)]",
    warning:
      "border-[var(--sparx-yellow)] bg-[rgba(241,231,47,0.18)] text-[var(--sparx-olive)]",
    danger:
      "border-[var(--sparx-red)] bg-[rgba(255,88,78,0.12)] text-[var(--sparx-red)]",
    neutral:
      "border-[var(--sparx-line-strong)] bg-white/70 text-[var(--sparx-muted)]",
  }[tone];

  return (
    <span
      className={cn(
        "inline-flex min-h-7 w-fit items-center rounded-full border px-3 text-xs font-black tracking-normal",
        toneClass,
      )}
    >
      {children}
    </span>
  );
}

type IconButtonProps = ComponentPropsWithoutRef<"button"> & {
  active?: boolean;
  variant?: "light" | "dark";
};

export function IconButton({
  active,
  variant = "light",
  className,
  children,
  ...props
}: IconButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        "grid size-11 shrink-0 place-items-center rounded-full border transition",
        variant === "dark"
          ? "border-[var(--sparx-night)] bg-[var(--sparx-night)] text-white"
          : "border-transparent bg-transparent text-[var(--sparx-muted)] hover:bg-[var(--sparx-panel)]",
        active && "bg-[var(--sparx-night)] text-[var(--sparx-yellow)]",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

type PrimaryButtonProps = ComponentPropsWithoutRef<"button"> & {
  icon?: ReactNode;
  variant?: "solid" | "soft";
};

export function PrimaryButton({
  icon,
  variant = "solid",
  className,
  children,
  ...props
}: PrimaryButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex min-h-10 items-center justify-center gap-2 rounded-full px-5 text-sm font-black tracking-normal transition",
        variant === "solid"
          ? "bg-[var(--sparx-olive)] text-white shadow-[0_10px_22px_rgba(104,77,0,0.16)] hover:bg-[var(--sparx-olive-dark)]"
          : "bg-white text-[var(--sparx-olive)] ring-1 ring-[var(--sparx-line-strong)]",
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </button>
  );
}

type FormFieldProps = {
  label: string;
  placeholder?: string;
  value?: string;
  wide?: boolean;
};

export function FormField({
  label,
  placeholder = "",
  value,
  wide,
}: FormFieldProps) {
  return (
    <label className={cn("grid gap-2", wide && "sm:col-span-2")}>
      <span className="text-sm font-black text-[var(--sparx-ink)]">{label}</span>
      <input
        className="h-11 rounded-[6px] border border-[var(--sparx-line-strong)] bg-white px-3 text-sm font-semibold text-[var(--sparx-ink)] outline-none transition placeholder:text-[var(--sparx-muted)] focus:border-[var(--sparx-yellow)] focus:ring-2 focus:ring-[rgba(241,231,47,0.36)]"
        placeholder={placeholder}
        readOnly
        value={value}
      />
    </label>
  );
}

export function UploadPanel() {
  return (
    <div className="grid min-h-[174px] place-items-center rounded-[8px] border border-dashed border-[var(--sparx-line-strong)] bg-[rgba(255,249,238,0.7)] p-5 text-center">
      <div>
        <div className="mx-auto grid size-12 place-items-center rounded-[8px] bg-white text-[var(--sparx-olive)] shadow-sm">
          <UploadCloud className="size-7" />
        </div>
        <h3 className="mt-4 text-lg font-black">Renewal Sheet Import</h3>
        <p className="mx-auto mt-2 max-w-[280px] text-xs font-medium leading-relaxed text-[var(--sparx-muted)]">
          Upload CSV or Excel data for customer phone columns.
        </p>
        <PrimaryButton className="mt-4 bg-white text-[var(--sparx-ink)] ring-1 ring-[var(--sparx-line)]">
          Select Renewal File
        </PrimaryButton>
      </div>
    </div>
  );
}

export function AssetFrame({
  title,
  description = "Image asset slot",
  className,
}: {
  title: string;
  description?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid min-h-[160px] place-items-center rounded-[8px] bg-[var(--sparx-card-strong)] p-5 text-center text-[var(--sparx-muted)]",
        className,
      )}
    >
      <div>
        <Sparkles className="mx-auto size-8 text-white/80" />
        <p className="mt-2 text-sm font-black text-[var(--sparx-ink)]">{title}</p>
        <p className="mt-1 text-xs font-semibold">{description}</p>
      </div>
    </div>
  );
}

type EmptyStateProps = {
  title: string;
  description: string;
};

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <div className="grid min-h-[174px] place-items-center rounded-[8px] bg-[linear-gradient(135deg,#efe3d3,#fbf7ee)] p-5 text-center">
      <div>
        <Inbox className="mx-auto size-10 text-[var(--sparx-olive)]" />
        <h3 className="mt-3 text-xl font-black">{title}</h3>
        <p className="mt-1 text-sm font-semibold text-[var(--sparx-muted)]">
          {description}
        </p>
      </div>
    </div>
  );
}

type ScrollPanelProps = {
  children: ReactNode;
  className?: string;
};

export function ScrollPanel({ children, className }: ScrollPanelProps) {
  return (
    <div
      className={cn(
        "max-h-[360px] overflow-auto rounded-[8px] bg-white/80 p-3 [scrollbar-color:var(--sparx-night)_transparent] [scrollbar-width:thin]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export const previewIcons = {
  calls: <PhoneCall className="size-4" />,
  transcript: <FileText className="size-4" />,
  success: <CheckCircle2 className="size-4" />,
  warning: <AlertTriangle className="size-4" />,
  settings: <Settings2 className="size-4" />,
  upload: <UploadCloud className="size-4" />,
  filters: <SlidersHorizontal className="size-4" />,
};
