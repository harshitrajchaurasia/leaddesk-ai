import { Inbox as InboxIcon } from "lucide-react";
import { label, type Client, type Result } from "../lib";
import { Badge, Card, Empty, PriorityBadge, StatusBadge, VERDICT } from "../ui";

export default function Inbox({ results, clients, onOpen }: { results: Result[]; clients: Client[]; onOpen: (r: Result) => void }) {
  if (!results.length) return <Card><Empty icon={<InboxIcon className="size-7" />} title="Inbox is empty">Processed tickets appear here with their routing and approval status.</Empty></Card>;
  const name = (id: string) => clients.find((c) => c.id === id)?.name ?? id;
  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50/80 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>{["Ticket", "Client", "Category", "Verdict", "Queue", "Priority", "Status", "Summary"].map((h) => <th key={h} className="px-4 py-3 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {results.map((r) => (
              <tr key={r.ticket.id} onClick={() => onOpen(r)} className="cursor-pointer transition hover:bg-blue-50/50">
                <td className="px-4 py-3 font-mono text-xs font-medium text-blue-700">{r.ticket.id}</td>
                <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-800">{name(r.ticket.client_id)}</td>
                <td className="whitespace-nowrap px-4 py-3">{label(r.triage.category)}</td>
                <td className="px-4 py-3">{r.verdict && <Badge tone={VERDICT[r.verdict.verdict].tone}>{VERDICT[r.verdict.verdict].short}</Badge>}</td>
                <td className="whitespace-nowrap px-4 py-3">{label(r.route.queue)}</td>
                <td className="px-4 py-3"><PriorityBadge p={r.route.priority} /></td>
                <td className="px-4 py-3"><StatusBadge s={r.status} /></td>
                <td className="min-w-72 px-4 py-3 text-slate-600">{r.triage.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
