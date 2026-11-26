import { FlaskConical } from "lucide-react";
import { label, pct, type EvalRow, type Result, type Usage } from "../lib";
import { Card, Empty } from "../ui";

export default function Metrics({ results, evals, usage }: { results: Result[]; evals: EvalRow[]; usage: Usage | null }) {
  const steps = Object.values(usage?.app ?? {});
  const spend = steps.reduce((a, s) => a + s.usd, 0);
  const calls = usage?.app.triage?.calls ?? 0;
  const n = results.length;
  const withMl = results.filter((r) => r.ml);
  const reviewed = results.filter((r) => r.status !== "pending_approval");
  const tiles = [
    { k: "Processed", v: String(n), s: "tickets in the log" },
    { k: "Avg latency", v: n ? `${(results.reduce((a, r) => a + r.latency_ms, 0) / n / 1000).toFixed(1)} s` : "—", s: "end to end" },
    { k: "Human review", v: n ? pct(results.filter((r) => r.route.queue === "human_review").length / n) : "—", s: "low confidence or model failure" },
    { k: "Replacements", v: String(results.filter((r) => r.verdict?.verdict === "REPLACE").length), s: "approved by rules" },
    { k: "Local model agrees", v: withMl.length ? pct(withMl.filter((r) => r.ml!.category === r.triage.category).length / withMl.length) : "—", s: "with the LLM's category" },
    { k: "Model spend", v: usage ? `$${spend.toFixed(3)}` : "—", s: "live tickets, all steps" },
    { k: "Cost per ticket", v: calls ? `$${(spend / calls).toFixed(4)}` : "—", s: Object.entries(usage?.app ?? {}).map(([k, s]) => `${k} $${(s.usd / s.calls).toFixed(4)}`).join(" · ") || "triage + draft" },
    { k: "Drafts edited", v: reviewed.length ? pct(reviewed.filter((r) => r.status === "edited").length / reviewed.length) : "—", s: "of approved replies" },
  ];
  const queues = Object.entries(results.reduce<Record<string, number>>((a, r) => ({ ...a, [r.route.queue]: (a[r.route.queue] ?? 0) + 1 }), {}))
    .sort((a, b) => b[1] - a[1]);
  const SETS = ["core", "hard", "blind"], PROVIDERS: Record<string, string> = { grok: "Grok", claude: "Claude", ml: "Local model" };
  const rows = [...evals].sort((a, b) => SETS.indexOf(String(a.set)) - SETS.indexOf(String(b.set)) || String(a.provider).localeCompare(String(b.provider)));
  const num = (v: unknown) => Number(v ?? 0);
  const cols: [string, (r: EvalRow) => string][] = [
    ["Set", (r) => String(r.set ?? "core")],
    ["Provider", (r) => PROVIDERS[String(r.provider)] ?? String(r.provider)],
    ["Category", (r) => pct(num(r.category_acc))],
    ["Queue", (r) => pct(num(r.queue_acc))],
    ["Escalation", (r) => pct(num(r.escalation_recall))],
    ["Lead id", (r) => pct(num(r.lead_id_acc))],
    ["Latency", (r) => num(r.avg_latency_ms) < 100 ? `${num(r.avg_latency_ms)} ms` : `${(num(r.avg_latency_ms) / 1000).toFixed(1)} s`],
    ["$/ticket", (r) => (num(r.usd_per_ticket) ? `$${num(r.usd_per_ticket).toFixed(5)}` : "$0")],
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {tiles.map((t) => (
          <Card key={t.k} className="p-4">
            <div className="eyebrow">{t.k}</div>
            <div className="mt-1.5 text-2xl font-semibold tracking-tight">{t.v}</div>
            <div className="mt-0.5 text-xs text-slate-500">{t.s}</div>
          </Card>
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="p-5">
          <h3 className="font-semibold">Tickets by queue</h3>
          {!n && <p className="mt-3 text-sm text-slate-500">Process a few tickets to see the distribution.</p>}
          <div className="mt-4 space-y-3.5">
            {queues.map(([q, c]) => (
              <div key={q}>
                <div className="flex justify-between text-sm"><span className="font-medium text-slate-700">{label(q)}</span><span className="text-slate-500">{c}</span></div>
                <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full bg-gradient-to-r from-blue-500 to-teal-400 transition-all duration-700" style={{ width: `${(100 * c) / n}%` }} />
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card className="overflow-hidden xl:col-span-2">
          <div className="p-5 pb-3"><h3 className="font-semibold">Triage eval · 40 everyday, 18 adversarial, 36 blind tickets</h3></div>
          {!evals.length ? (
            <Empty icon={<FlaskConical className="size-7" />} title="No eval run yet">Run <code className="rounded bg-slate-100 px-1 font-mono text-xs">python -m evals.run_eval</code> to populate.</Empty>
          ) : (
            <div className="overflow-x-auto px-5 pb-5">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-slate-500"><tr>{cols.map(([k]) => <th key={k} className="whitespace-nowrap py-2 pr-4 font-semibold">{k}</th>)}</tr></thead>
                <tbody className="divide-y divide-slate-100">{rows.map((row, i) => <tr key={i}>{cols.map(([k, f]) => <td key={k} className="whitespace-nowrap py-2.5 pr-4 tabular-nums">{f(row)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
