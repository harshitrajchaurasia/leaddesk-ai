import { PhoneCall, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import type { Guard } from "../App";
import { api, label, pct, type Bootstrap, type CallResult } from "../lib";
import { Badge, Button, Card, Empty, Field, Meter } from "../ui";

type Sample = { id: string; client_id: string; title: string; transcript: string };

export default function Calls({ boot, guard }: { boot: Bootstrap; guard: Guard }) {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [history, setHistory] = useState<CallResult[]>([]);
  const [clientId, setClientId] = useState(boot.clients[0]?.id ?? "");
  const [transcript, setTranscript] = useState("");
  const [sampleId, setSampleId] = useState("");
  const [busy, setBusy] = useState(false);
  const [r, setR] = useState<CallResult | null>(null);

  const load = async () => {
    const d = await guard(api<{ samples: Sample[]; results: CallResult[] }>("/api/calls"));
    if (d) { setSamples(d.samples); setHistory(d.results); }
  };
  useEffect(() => { load(); }, []);

  async function analyse() {
    setBusy(true);
    const res = await guard(api<CallResult>("/api/call", { client_id: clientId, transcript }));
    setBusy(false);
    if (res) { setR(res); load(); toast.success("Call analysed", { description: res.monday_item_id ? `Monday item #${res.monday_item_id}` : "Saved (Monday outbox)" }); }
  }

  const client = boot.clients.find((c) => c.id === (r?.client_id ?? clientId));
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="space-y-6">
        <Card className="space-y-4 p-5">
          <h3 className="font-semibold">Call transcript</h3>
          <Field label="Load a sample">
            <select className="field" value={sampleId} onChange={(e) => { const s = samples.find((x) => x.id === e.target.value); setSampleId(e.target.value); if (s) { setClientId(s.client_id); setTranscript(s.transcript); setR(null); } }}>
              <option value="">Paste your own…</option>
              {samples.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.title}</option>)}
            </select>
          </Field>
          <Field label="Client">
            <select className="field" value={clientId} onChange={(e) => setClientId(e.target.value)}>
              {boot.clients.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}
            </select>
          </Field>
          <Field label="Transcript" hint="From a call recorder (Fathom, Zoom, a dialer). Emails and phone numbers are masked before the model sees it; names are not.">
            <textarea className="field min-h-64 font-mono text-[13px]" value={transcript} onChange={(e) => { setTranscript(e.target.value); setSampleId(""); }} placeholder="Speaker: what they said…" />
          </Field>
          <Button className="w-full" loading={busy} disabled={transcript.trim().length < 20} onClick={analyse}><Sparkles className="size-4" />Analyse call</Button>
        </Card>
        {history.length > 0 && (
          <Card className="p-5">
            <h3 className="font-semibold">Recent calls</h3>
            <ul className="mt-3 divide-y divide-slate-100 text-sm">
              {history.slice(0, 8).map((h) => (
                <li key={h.id}><button className="flex w-full justify-between gap-3 py-2.5 text-left hover:text-blue-700" onClick={() => setR(h)}>
                  <span className="truncate">{boot.clients.find((c) => c.id === h.client_id)?.name ?? h.client_id}: {h.insight.summary}</span>
                  <span className="shrink-0 text-slate-500">churn {pct(h.insight.churn_risk)}</span>
                </button></li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      {!r ? (
        <Card><Empty icon={<PhoneCall className="size-7" />} title="No call analysed yet">Load a sample or paste a transcript. You get a summary, churn risk, upsell signals and action items, plus a Monday item with a subitem per action.</Empty></Card>
      ) : (
        <div className="space-y-5">
          {r.alerts.length > 0 && (
            <Card className="border-l-4 border-l-amber-400 p-5">
              <div className="eyebrow">Alerts · rules in code</div>
              <ul className="mt-2 space-y-1.5 text-sm text-slate-800">{r.alerts.map((a) => <li key={a}>{a}</li>)}</ul>
            </Card>
          )}
          <Card className="p-5">
            <div className="eyebrow">Summary · {client?.name}</div>
            <p className="mt-2 text-sm leading-relaxed text-slate-800">{r.insight.summary}</p>
            <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
              <div className="flex justify-between"><dt className="text-slate-500">Sentiment</dt><dd className="font-medium">{label(r.insight.sentiment)}</dd></div>
              <div className="space-y-1.5">
                <div className="flex justify-between"><dt className="text-slate-500">Churn risk</dt><dd className="font-medium">{pct(r.insight.churn_risk)}</dd></div>
                <Meter value={r.insight.churn_risk} tone={r.insight.churn_risk >= 0.7 ? "bg-rose-500" : r.insight.churn_risk >= 0.4 ? "bg-amber-400" : "bg-emerald-500"} />
              </div>
            </dl>
          </Card>
          <div className="grid gap-5 sm:grid-cols-2">
            <Card className="p-5">
              <div className="eyebrow">Upsell signals</div>
              {r.insight.upsell_signals.length ? <ul className="mt-2 list-disc space-y-1 pl-4 text-sm">{r.insight.upsell_signals.map((u) => <li key={u}>{u}</li>)}</ul> : <p className="mt-2 text-sm text-slate-500">None mentioned.</p>}
            </Card>
            <Card className="p-5">
              <div className="eyebrow">Objections</div>
              {r.insight.objections.length ? <ul className="mt-2 list-disc space-y-1 pl-4 text-sm">{r.insight.objections.map((o) => <li key={o}>{o}</li>)}</ul> : <p className="mt-2 text-sm text-slate-500">None raised.</p>}
            </Card>
          </div>
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between p-5 pb-2">
              <h3 className="font-semibold">Action items</h3>
              <span className="text-xs text-slate-500">{r.monday_item_id ? `Monday item #${r.monday_item_id}, one subitem each` : "Monday not configured: saved to outbox"}</span>
            </div>
            <div className="overflow-x-auto px-5 pb-5">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-slate-500"><tr><th className="py-2 pr-4">Owner</th><th className="py-2 pr-4">Task</th><th className="py-2">Due</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {r.insight.action_items.map((a, i) => (
                    <tr key={i}><td className="py-2.5 pr-4"><Badge tone={a.owner === "us" ? "blue" : "slate"}>{a.owner === "us" ? "Acme" : "Client"}</Badge></td><td className="py-2.5 pr-4">{a.task}</td><td className="whitespace-nowrap py-2.5 text-slate-600">{a.due ?? "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <p className="text-xs text-slate-500">{r.provider} · {(r.latency_ms / 1000).toFixed(1)} s</p>
        </div>
      )}
    </div>
  );
}
