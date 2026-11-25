import { Scale, SplitSquareHorizontal } from "lucide-react";
import { useState } from "react";
import type { Guard } from "../App";
import { api, label, nowIso, pct, type Bootstrap, type Compare as CompareT, type Ticket, type Triage } from "../lib";
import { Badge, Button, Card, cx, Empty } from "../ui";
import TicketForm from "./TicketForm";

const KEYS: (keyof Triage)[] = ["category", "urgency", "sentiment", "lead_id", "churn_risk", "confidence"];
const fmt = (v: unknown) => (v == null ? "—" : typeof v === "number" ? pct(v) : label(v));

export default function Compare({ boot, ticket, setTicket, guard }: { boot: Bootstrap; ticket: Ticket; setTicket: (t: Ticket) => void; guard: Guard }) {
  const [busy, setBusy] = useState(false);
  const [cmp, setCmp] = useState<CompareT | null>(null);
  const run = async () => {
    setBusy(true); setCmp(null);
    setCmp(await guard(api<CompareT>("/api/compare", { ...ticket, received_at: ticket.received_at || nowIso() })));
    setBusy(false);
  };
  const differs = (k: keyof Triage) => !!(cmp?.claude && cmp?.grok && cmp.claude.triage[k] !== cmp.grok.triage[k]);
  const disagreements = KEYS.slice(0, 4).filter(differs);

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <Card className="h-fit p-5 lg:col-span-2">
        <h2 className="mb-5 font-semibold">Ticket</h2>
        <TicketForm boot={boot} ticket={ticket} setTicket={setTicket} onPick={() => setCmp(null)}>
          <Button onClick={run} loading={busy} disabled={!ticket.body.trim()} className="w-full">{!busy && <Scale className="size-4" />}Run both models</Button>
        </TicketForm>
      </Card>
      <div className="space-y-5 lg:col-span-3">
        {!cmp && <Card><Empty icon={<SplitSquareHorizontal className="size-7" />} title="Compare triage side by side">Model choice comes from measured accuracy, latency and failures, not preference.</Empty></Card>}
        {cmp?.claude && cmp?.grok && (
          <Card className={cx("px-5 py-3.5 text-sm font-medium", disagreements.length ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-800")}>
            {disagreements.length ? `Models disagree on ${disagreements.map(label).join(", ").toLowerCase()}` : "Models agree on category, urgency, sentiment and lead id"}
          </Card>
        )}
        {cmp && (
          <div className="grid gap-5 sm:grid-cols-2">
            {(["claude", "grok"] as const).map((m) => (
              <Card key={m} className="p-5">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold">{label(m)}</h3>
                  {cmp[m] && <Badge tone="slate">{(cmp[m]!.ms / 1000).toFixed(1)} s</Badge>}
                </div>
                {!cmp[m] ? (
                  <p className="mt-3 text-sm text-slate-500">The Claude path is implemented and covered by tests; this deployment has no Anthropic key.</p>
                ) : (
                  <>
                    <dl className="mt-4 space-y-1 text-sm">
                      {KEYS.map((k) => (
                        <div key={k} className={cx("flex justify-between rounded-md px-2 py-1.5", differs(k) && "bg-amber-50")}>
                          <dt className="text-slate-500">{label(k)}</dt><dd className="font-medium">{fmt(cmp[m]!.triage[k])}</dd>
                        </div>
                      ))}
                    </dl>
                    <p className="mt-3 border-t border-slate-100 pt-3 text-sm text-slate-700">{cmp[m]!.triage.summary}</p>
                  </>
                )}
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
