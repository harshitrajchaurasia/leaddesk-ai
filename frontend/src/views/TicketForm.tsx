import type { ReactNode } from "react";
import { blankTicket, label, type Bootstrap, type Ticket } from "../lib";
import { Field } from "../ui";

export default function TicketForm({ boot, ticket, setTicket, onPick, children }: {
  boot: Bootstrap; ticket: Ticket; setTicket: (t: Ticket) => void; onPick?: () => void; children?: ReactNode;
}) {
  const client = boot.clients.find((c) => c.id === ticket.client_id);
  const isSample = boot.samples.some((s) => s.id === ticket.id);
  const pick = (id: string) => {
    setTicket(boot.samples.find((s) => s.id === id) ?? blankTicket(ticket.client_id));
    onPick?.();
  };

  return (
    <div className="space-y-4">
      <Field label="Load a sample">
        <select className="field" value={isSample ? ticket.id : ""} onChange={(e) => pick(e.target.value)}>
          <option value="">Write your own…</option>
          {boot.samples.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.subject}</option>)}
        </select>
      </Field>
      <Field label="Client" hint={client && <>{label(client.vertical)} · licensed in {client.states.join(", ")} · AM {client.account_manager}</>}>
        <select className="field" value={ticket.client_id} onChange={(e) => setTicket({ ...ticket, client_id: e.target.value })}>
          {boot.clients.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}
        </select>
      </Field>
      <Field label="Subject">
        <input className="field" value={ticket.subject} placeholder="e.g. Lead L-105 is not exclusive"
          onChange={(e) => setTicket({ ...ticket, subject: e.target.value })} />
      </Field>
      <Field label="Message">
        <textarea className="field min-h-36 leading-relaxed" value={ticket.body} placeholder="Paste the client's message…"
          onChange={(e) => setTicket({ ...ticket, body: e.target.value })} />
      </Field>
      {children}
    </div>
  );
}
