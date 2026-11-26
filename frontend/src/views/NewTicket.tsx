import { Check, ChevronDown, Code2, MessageSquareText, Send, UserRound } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import type { Guard } from "../App";
import { api, label, nowIso, pct, type Bootstrap, type Result, type Ticket } from "../lib";
import { Badge, Button, Card, cx, Empty, Meter, PriorityBadge, StatusBadge, VERDICT } from "../ui";
import TicketForm from "./TicketForm";

const STEPS = ["Mask PII", "Triage", "Dispute check", "Routing", "Draft reply", "Monday"];

export default function NewTicket({ boot, ticket, setTicket, result, setResult, guard, onSaved }: {
  boot: Bootstrap; ticket: Ticket; setTicket: (t: Ticket) => void; result: Result | null;
  setResult: (r: Result | null) => void; guard: Guard; onSaved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(result ? STEPS.length : -1);
  const [reply, setReply] = useState(result?.final_reply ?? result?.draft_reply ?? "");
  const [showJson, setShowJson] = useState(false);

  useEffect(() => { setReply(result?.final_reply ?? result?.draft_reply ?? ""); }, [result]);

  async function process() {
    setBusy(true); setResult(null); setStep(0);
    const tick = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 2)), 800);
    const r = await guard(api<Result>("/api/process", { ...ticket, received_at: ticket.received_at || nowIso() }));
    clearInterval(tick); setBusy(false);
    if (!r) return setStep(-1);
    setStep(STEPS.length); setResult(r); onSaved();
    toast.success(`Routed to ${label(r.route.queue)}`, { description: r.triage.summary });
  }

  async function approve() {
    if (!result) return;
    const r = await guard(api<Result>("/api/approve", { ticket_id: result.ticket.id, final_reply: reply }));
    if (r) { setResult(r); onSaved(); toast.success(r.status === "edited" ? "Edited reply approved" : "Reply approved"); }
  }

  const state = (i: number) => (step < 0 ? "idle" : step >= STEPS.length || i < step ? "done" : i === step ? "active" : "idle");
  const r = result;
  const v = r?.verdict ? VERDICT[r.verdict.verdict] : null;

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <Card className="h-fit p-5 lg:sticky lg:top-24 lg:col-span-2">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="font-semibold">Incoming ticket</h2>
          <span className="font-mono text-xs text-slate-400">{ticket.id}</span>
        </div>
        <TicketForm boot={boot} ticket={ticket} setTicket={setTicket} onPick={() => { setResult(null); setStep(-1); }}>
          <Button onClick={process} loading={busy} disabled={!ticket.body.trim()} className="w-full">
            {!busy && <Send className="size-4" />}{busy ? "Processing…" : "Process ticket"}
          </Button>
        </TicketForm>
      </Card>

      <div className="space-y-5 lg:col-span-3">
        <Card className="px-5 py-4">
          <ol className="flex flex-wrap items-center gap-x-1 gap-y-2 text-[13px]">
            {STEPS.map((s, i) => (
              <li key={s} className="flex items-center gap-2">
                <span className={cx("grid size-6 place-items-center rounded-full text-xs font-semibold transition-colors duration-300",
                  state(i) === "done" && "bg-emerald-500 text-white",
                  state(i) === "active" && "bg-blue-600 text-white ring-4 ring-blue-600/15",
                  state(i) === "idle" && "bg-slate-100 text-slate-400")}>
                  {state(i) === "done" ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
                </span>
                <span className={state(i) === "idle" ? "text-slate-400" : "font-medium text-slate-700"}>{s}</span>
                {i < STEPS.length - 1 && <span className="mx-0.5 h-px w-3 bg-slate-200" />}
              </li>
            ))}
          </ol>
        </Card>

        <AnimatePresence mode="wait">
          {!r && !busy && (
            <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <Card>
                <Empty icon={<MessageSquareText className="size-7" />} title="No ticket processed yet">
                  Pick a sample such as <b>T-001</b> (an exclusivity complaint) or <b>T-015</b> (a prompt-injection attempt), then press <b>Process ticket</b>.
                </Empty>
              </Card>
            </motion.div>
          )}
          {busy && (
            <motion.div key="busy" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-5">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="card h-20 animate-pulse bg-slate-100/70" />)}</div>
              <div className="card h-40 animate-pulse bg-slate-100/70" />
            </motion.div>
          )}
          {r && (
            <motion.div key={r.ticket.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat k="Category" v={label(r.triage.category)} />
                <Stat k="Queue" v={label(r.route.queue)} />
                <Stat k="Priority" v={<PriorityBadge p={r.route.priority} />} />
                <Stat k="Latency" v={<>{(r.latency_ms / 1000).toFixed(1)}<span className="text-sm font-normal text-slate-400"> s</span></>} />
              </div>

              {r.verdict && v && (
                <Card className="relative overflow-hidden p-5 pl-6">
                  <span className={cx("absolute inset-y-0 left-0 w-1", v.bar)} />
                  <div className="eyebrow">Lead dispute check · rules in code, not the model</div>
                  <div className="mt-2.5 flex flex-wrap items-center gap-2.5">
                    <Badge tone={v.tone} className="px-3 py-1 text-sm">{v.text}</Badge>
                    {(r.triage.lead_ids?.length ?? 0) > 0 && <span className="text-sm text-slate-500">for {r.triage.lead_ids!.length > 1 ? `${r.triage.lead_ids!.length} leads` : "lead"} <b className="font-mono text-slate-700">{r.triage.lead_ids!.join(", ")}</b></span>}
                  </div>
                  <Reasons items={r.verdict.reasons} />
                </Card>
              )}

              <div className="grid gap-5 sm:grid-cols-2">
                <Card className="p-5">
                  <div className="eyebrow">Triage</div>
                  <p className="mt-2 text-sm leading-relaxed text-slate-800">{r.triage.summary}</p>
                  <dl className="mt-4 space-y-3 text-sm">
                    <Row k="Sentiment" v={label(r.triage.sentiment)} />
                    <Row k="Urgency" v={label(r.triage.urgency)} />
                    <div className="space-y-1.5"><Row k="Churn risk" v={pct(r.triage.churn_risk)} />
                      <Meter value={r.triage.churn_risk} tone={r.triage.churn_risk >= 0.7 ? "bg-rose-500" : r.triage.churn_risk >= 0.4 ? "bg-amber-400" : "bg-emerald-500"} /></div>
                    <div className="space-y-1.5"><Row k="Confidence" v={pct(r.triage.confidence)} /><Meter value={r.triage.confidence} /></div>
                    {r.ml && <Row k="Local model" v={`${label(r.ml.category)} · ${pct(r.ml.confidence)} · ${r.ml.category === r.triage.category ? "agrees" : "disagrees"}`} />}
                  </dl>
                </Card>
                <Card className="flex flex-col p-5">
                  <div className="eyebrow">Routing</div>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{label(r.route.queue)}</span>
                    {r.route.assignee && <span className="inline-flex items-center gap-1 text-sm text-slate-500"><UserRound className="size-3.5" />{r.route.assignee}</span>}
                  </div>
                  <Reasons items={r.route.reasons} />
                  <div className="mt-auto flex items-center gap-2.5 border-t border-slate-100 pt-4 text-sm">
                    <MondayMark />
                    {r.monday_item_id
                      ? <span className="text-slate-700">Monday.com item <b className="font-mono">#{r.monday_item_id}</b> created</span>
                      : <span className="text-slate-500">Monday not configured · saved to outbox</span>}
                  </div>
                </Card>
              </div>

              <Card className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <div><div className="eyebrow">Drafted reply</div><p className="mt-0.5 text-xs text-slate-500">{r.ticket.ghl_contact_id ? "From Go High Level: on approval it is sent to the contact once, on the same channel." : "Edit if needed. Nothing is sent automatically."}</p></div>
                  <StatusBadge s={r.status} />
                </div>
                <textarea className="field mt-3 min-h-44 leading-relaxed" value={reply} onChange={(e) => setReply(e.target.value)} disabled={r.status !== "pending_approval"} />
                <div className="mt-3 flex items-center justify-between gap-3">
                  <Button variant="ghost" onClick={() => setShowJson(!showJson)} className="px-2">
                    <Code2 className="size-4" />Structured output<ChevronDown className={cx("size-4 transition", showJson && "rotate-180")} />
                  </Button>
                  <Button variant="success" onClick={approve} disabled={r.status !== "pending_approval" && !r.send_error}>
                    <Check className="size-4" />{r.send_error ? "Retry send" : r.status === "pending_approval" ? "Approve reply" : "Approved"}
                  </Button>
                </div>
                {r.send_error && <p className="mt-2 text-sm text-rose-600">{r.send_error}</p>}
                {r.ghl_message_id && <p className="mt-2 text-xs text-slate-500">Sent through Go High Level · message {r.ghl_message_id}</p>}
                <AnimatePresence>
                  {showJson && (
                    <motion.pre initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                      className="mt-3 overflow-auto rounded-xl bg-slate-950 p-4 font-mono text-xs leading-relaxed text-slate-100">
                      {JSON.stringify(r.triage, null, 2)}
                    </motion.pre>
                  )}
                </AnimatePresence>
              </Card>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

const Stat = ({ k, v }: { k: string; v: ReactNode }) => (
  <Card className="p-4"><div className="eyebrow">{k}</div><div className="mt-1.5 font-semibold text-slate-900">{v}</div></Card>
);
const Row = ({ k, v }: { k: string; v: string }) => (
  <div className="flex justify-between"><dt className="text-slate-500">{k}</dt><dd className="font-medium text-slate-800">{v}</dd></div>
);
const Reasons = ({ items }: { items: string[] }) => (
  <ul className="mt-3 space-y-1.5">
    {items.map((x) => <li key={x} className="flex gap-2 text-sm text-slate-700"><span className="mt-2 size-1 shrink-0 rounded-full bg-slate-400" />{x}</li>)}
  </ul>
);
const MondayMark = () => (
  <span className="flex gap-0.5">{["bg-rose-500", "bg-amber-400", "bg-emerald-500"].map((c) => <span key={c} className={cx("h-4 w-1.5 rounded-full", c)} />)}</span>
);
