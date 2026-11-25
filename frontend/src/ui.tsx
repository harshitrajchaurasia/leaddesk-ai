import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Status, Urgency, Verdict } from "./lib";
import { label } from "./lib";

export const cx = clsx;

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("card", className)}>{children}</div>;
}

type Tone = "blue" | "green" | "amber" | "rose" | "teal" | "slate";
const TONES: Record<Tone, string> = {
  blue: "bg-blue-50 text-blue-700 ring-blue-600/15",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/15",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  rose: "bg-rose-50 text-rose-700 ring-rose-600/15",
  teal: "bg-teal-50 text-teal-700 ring-teal-600/15",
  slate: "bg-slate-100 text-slate-600 ring-slate-500/15",
};

export function Badge({ tone = "slate", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset", TONES[tone], className)}>
      {children}
    </span>
  );
}

export const PRIORITY_TONE: Record<Urgency, Tone> = { urgent: "rose", high: "amber", normal: "blue", low: "slate" };
export const STATUS_TONE: Record<Status, Tone> = { pending_approval: "amber", approved: "green", edited: "teal" };
export const VERDICT: Record<Verdict, { text: string; short: string; tone: Tone; bar: string }> = {
  REPLACE: { text: "Replace lead", short: "Replace", tone: "green", bar: "bg-emerald-500" },
  VALID_COACH: { text: "Valid lead · coach the agent", short: "Valid · coach", tone: "blue", bar: "bg-blue-500" },
  NEEDS_REVIEW: { text: "Needs human review", short: "Review", tone: "amber", bar: "bg-amber-500" },
};

export const PriorityBadge = ({ p }: { p: Urgency }) => <Badge tone={PRIORITY_TONE[p]}>{label(p)}</Badge>;
export const StatusBadge = ({ s }: { s: Status }) => <Badge tone={STATUS_TONE[s]}>{label(s)}</Badge>;

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "success" | "ghost"; loading?: boolean };
export function Button({ variant = "primary", loading, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition focus:outline-none focus-visible:ring-4 disabled:cursor-not-allowed",
        variant === "primary" && "bg-blue-600 text-white shadow-sm shadow-blue-600/25 hover:bg-blue-700 focus-visible:ring-blue-500/30 disabled:bg-slate-300 disabled:shadow-none",
        variant === "success" && "bg-emerald-600 text-white shadow-sm shadow-emerald-600/25 hover:bg-emerald-700 focus-visible:ring-emerald-500/30 disabled:bg-slate-300 disabled:shadow-none",
        variant === "ghost" && "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
        className,
      )}
    >
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Field({ label: l, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-semibold text-slate-700">{l}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export function Meter({ value, tone = "bg-blue-500" }: { value: number; tone?: string }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
      <div className={cx("h-full rounded-full transition-all duration-700", tone)} style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

export function Logo({ size = "md" }: { size?: "md" | "lg" }) {
  return (
    <div className={cx("grid place-items-center rounded-xl bg-gradient-to-br from-blue-600 to-teal-500 text-white shadow-lg shadow-blue-600/25",
      size === "lg" ? "size-12 rounded-2xl" : "size-9")}>
      <svg viewBox="0 0 24 24" className={size === "lg" ? "size-6" : "size-5"} fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round">
        <path d="M4 17v-4a8 8 0 0 1 16 0v4" /><path d="M20 18a2 2 0 0 1-2 2h-1v-5h3zM4 18a2 2 0 0 0 2 2h1v-5H4z" />
      </svg>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="px-6 py-14 text-center">
      <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-gradient-to-br from-blue-50 to-teal-50 text-blue-600 ring-1 ring-blue-100">{icon}</div>
      <h3 className="mt-4 font-semibold text-slate-900">{title}</h3>
      {children && <p className="mx-auto mt-1 max-w-sm text-sm text-slate-500">{children}</p>}
    </div>
  );
}
