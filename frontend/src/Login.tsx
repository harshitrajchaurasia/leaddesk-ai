import { ArrowRight, CheckCircle2, ShieldCheck } from "lucide-react";
import { motion } from "motion/react";
import { useState, type FormEvent } from "react";
import { api } from "./lib";
import { Button, Field, Logo } from "./ui";

const POINTS = [
  "Replacement decisions made by audited rules, never by the model",
  "Every reply drafted for a human to approve",
  "Tickets land on your Monday.com board automatically",
];

export default function Login({ onDone }: { onDone: () => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/login", Object.fromEntries(new FormData(e.currentTarget)));
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-gradient-to-br from-blue-600 via-blue-600 to-teal-500 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -right-32 -top-32 size-[28rem] rounded-full bg-white/10 blur-2xl" />
        <div className="pointer-events-none absolute -bottom-24 -left-20 size-96 rounded-full bg-teal-300/20 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <Logo />
          <span className="text-lg font-semibold tracking-tight">LeadDesk AI</span>
        </div>
        <motion.div className="relative max-w-lg" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <h1 className="text-[2.6rem] font-bold leading-[1.1] tracking-tight">Every client ticket, triaged and answered in seconds.</h1>
          <p className="mt-5 text-lg text-blue-50/90">
            Lead disputes are checked against the lead record, routed to the right team, and answered with a reply drafted for your approval.
          </p>
          <ul className="mt-9 space-y-3.5">
            {POINTS.map((p, i) => (
              <motion.li key={p} className="flex items-start gap-3 text-blue-50" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.2 + i * 0.1 }}>
                <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-teal-200" />{p}
              </motion.li>
            ))}
          </ul>
        </motion.div>
        <p className="relative text-sm text-blue-50/75">Demo environment · synthetic data only</p>
      </section>

      <section className="flex items-center justify-center bg-gradient-to-b from-blue-50/60 to-white p-6">
        <motion.div className="w-full max-w-sm" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
          <div className="mb-8 flex items-center justify-center gap-3 lg:hidden"><Logo /><span className="text-lg font-semibold">LeadDesk AI</span></div>
          <div className="card p-8 shadow-xl shadow-slate-900/5">
            <h2 className="text-2xl font-bold tracking-tight">Welcome back</h2>
            <p className="mt-1 text-sm text-slate-500">Sign in to the support desk.</p>
            <form onSubmit={submit} className="mt-7 space-y-4">
              <Field label="Username"><input name="username" autoComplete="username" required autoFocus className="field" /></Field>
              <Field label="Password"><input name="password" type="password" autoComplete="current-password" required className="field" /></Field>
              {error && <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
              <Button type="submit" loading={busy} className="w-full">Sign in {!busy && <ArrowRight className="size-4" />}</Button>
            </form>
          </div>
          <p className="mt-6 flex items-center justify-center gap-1.5 text-xs text-slate-400"><ShieldCheck className="size-3.5" />Prototype built with Claude Code</p>
        </motion.div>
      </section>
    </main>
  );
}
