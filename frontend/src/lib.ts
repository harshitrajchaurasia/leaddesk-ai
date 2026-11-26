// Types mirror leaddesk/models.py (pydantic). Keep in sync when the backend models change.
export type Category = "lead_quality" | "billing" | "campaign_change" | "appointments" | "tech_access" | "cancellation" | "other";
export type Queue = "lead_ops" | "account_manager" | "billing" | "campaign_ops" | "support" | "human_review";
export type Urgency = "low" | "normal" | "high" | "urgent";
export type Verdict = "REPLACE" | "VALID_COACH" | "NEEDS_REVIEW";
export type Status = "pending_approval" | "approved" | "edited";

export interface Client { id: string; name: string; vertical: string; states: string[]; plan: string; account_manager: string }
export interface Ticket { id: string; client_id: string; channel: "email" | "form" | "webhook"; subject: string; body: string; received_at: string; ghl_contact_id?: string | null }
export interface Triage {
  category: Category; urgency: Urgency; sentiment: "positive" | "neutral" | "frustrated" | "angry";
  churn_risk: number; lead_id: string | null; lead_ids?: string[]; summary: string; confidence: number;
}
export interface Result {
  ticket: Ticket; triage: Triage; ml?: { category: Category; confidence: number } | null; verdict: { verdict: Verdict; reasons: string[] } | null;
  route: { queue: Queue; priority: Urgency; assignee: string | null; reasons: string[]; sla_minutes?: number | null };
  draft_reply: string; provider: string; latency_ms: number; monday_item_id: string | null; status: Status; final_reply: string | null;
  ghl_message_id?: string | null; send_error?: string | null;
  created_at?: string | null; approved_at?: string | null; due_at?: string | null;
}
export interface Bootstrap { provider: string; call_provider: string;
  time_saved: { manual_minutes_per_ticket: number; review_minutes_per_ticket: number }; sla_minutes: Record<string, number>; has_claude: boolean; clients: Client[]; samples: Ticket[] }
export type Compare = Record<"claude" | "grok", { triage: Triage; ms: number } | null>;
export interface Usage { app: Record<string, { calls: number; usd: number; avg_ms: number }>; other_usd: number }
export interface CallResult {
  id: string; client_id: string; transcript: string; alerts: string[]; provider: string; latency_ms: number; monday_item_id: string | null;
  insight: { summary: string; sentiment: string; churn_risk: number; upsell_signals: string[]; objections: string[];
    action_items: { owner: "us" | "client"; task: string; due: string | null }[] };
}
export type EvalRow = Record<string, string | number | null>;

export class Unauthorized extends Error {}

export async function api<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (r.status === 401 && url !== "/api/login") throw new Unauthorized();
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${r.status})`);
  }
  return r.json();
}

const LABELS: Record<string, string> = {
  lead_quality: "Lead quality", billing: "Billing", campaign_change: "Campaign change", appointments: "Appointments",
  tech_access: "Tech / access", cancellation: "Cancellation", other: "Other", lead_ops: "Lead ops",
  account_manager: "Account manager", campaign_ops: "Campaign ops", support: "Support", human_review: "Human review",
  pending_approval: "Pending approval", approved: "Approved", edited: "Edited & approved", final_expense: "Final expense",
  retirement_planning: "Retirement planning", debt_relief: "Debt relief", iul: "IUL", lead_id: "Lead id", annuity: "Annuity", life: "Life",
};
export const label = (k: unknown) => {
  const s = String(k ?? "");
  return LABELS[s] ?? s.charAt(0).toUpperCase() + s.slice(1).replaceAll("_", " ");
};
// Backend timestamps are naive UTC; without the Z, JS would read them as local time.
export const utc = (s?: string | null) => (s ? new Date(s.endsWith("Z") ? s : s + "Z") : null);
export const isOverdue = (r: Result, now = Date.now()) => r.status === "pending_approval" && !!r.due_at && utc(r.due_at)!.getTime() < now;
export const mins = (m: number) => (m < 60 ? `${Math.round(m)} min` : m < 1440 ? `${(m / 60).toFixed(1)} h` : `${(m / 1440).toFixed(1)} d`);
export const pct = (x: number) => `${Math.round(x * 100)}%`;
export const nowIso = () => new Date().toISOString().slice(0, 19);

export const blankTicket = (client_id = "C-01"): Ticket => ({
  id: `T-${new Date().toTimeString().slice(0, 8).replaceAll(":", "")}`, client_id, channel: "form", subject: "", body: "", received_at: "",
});
