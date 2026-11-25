// Types mirror leaddesk/models.py (pydantic). Keep in sync when the backend models change.
export type Category = "lead_quality" | "billing" | "campaign_change" | "appointments" | "tech_access" | "cancellation" | "other";
export type Queue = "lead_ops" | "account_manager" | "billing" | "campaign_ops" | "support" | "human_review";
export type Urgency = "low" | "normal" | "high" | "urgent";
export type Verdict = "REPLACE" | "VALID_COACH" | "NEEDS_REVIEW";
export type Status = "pending_approval" | "approved" | "edited";

export interface Client { id: string; name: string; vertical: string; states: string[]; plan: string; account_manager: string }
export interface Ticket { id: string; client_id: string; channel: "email" | "form" | "webhook"; subject: string; body: string; received_at: string }
export interface Triage {
  category: Category; urgency: Urgency; sentiment: "positive" | "neutral" | "frustrated" | "angry";
  churn_risk: number; lead_id: string | null; summary: string; confidence: number;
}
export interface Result {
  ticket: Ticket; triage: Triage; verdict: { verdict: Verdict; reasons: string[] } | null;
  route: { queue: Queue; priority: Urgency; assignee: string | null; reasons: string[] };
  draft_reply: string; provider: string; latency_ms: number; monday_item_id: string | null; status: Status; final_reply: string | null;
}
export interface Bootstrap { provider: string; has_claude: boolean; clients: Client[]; samples: Ticket[] }
export type Compare = Record<"claude" | "grok", { triage: Triage; ms: number } | null>;
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
export const pct = (x: number) => `${Math.round(x * 100)}%`;
export const nowIso = () => new Date().toISOString().slice(0, 19);

export const blankTicket = (client_id = "C-01"): Ticket => ({
  id: `T-${new Date().toTimeString().slice(0, 8).replaceAll(":", "")}`, client_id, channel: "form", subject: "", body: "", received_at: "",
});
