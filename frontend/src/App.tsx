import { BarChart3, Inbox as InboxIcon, LogOut, PhoneCall, PlusCircle, ShieldCheck, Sparkles, SplitSquareHorizontal } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { Toaster, toast } from "sonner";
import { api, blankTicket, label, Unauthorized, type Bootstrap, type EvalRow, type Result, type Ticket, type Usage } from "./lib";
import Login from "./Login";
import { cx, Logo } from "./ui";
import Calls from "./views/Calls";
import Compare from "./views/Compare";
import Inbox from "./views/Inbox";
import Metrics from "./views/Metrics";
import NewTicket from "./views/NewTicket";

export type View = "new" | "inbox" | "calls" | "compare" | "metrics";
const NAV: { id: View; label: string; sub: string; icon: typeof PlusCircle }[] = [
  { id: "new", label: "New ticket", sub: "Triage, dispute check, routing and a drafted reply", icon: PlusCircle },
  { id: "inbox", label: "Inbox", sub: "Every processed ticket and its approval status", icon: InboxIcon },
  { id: "calls", label: "Call notes", sub: "Customer-success calls: summary, churn, upsell and action items to Monday", icon: PhoneCall },
  { id: "compare", label: "Model comparison", sub: "The same ticket triaged by Claude and Grok", icon: SplitSquareHorizontal },
  { id: "metrics", label: "Metrics", sub: "Throughput, human review rate and eval accuracy", icon: BarChart3 },
];

export default function App() {
  const [auth, setAuth] = useState<"checking" | "in" | "out">("checking");
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [view, setView] = useState<View>("new");
  const [results, setResults] = useState<Result[]>([]);
  const [evals, setEvals] = useState<EvalRow[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [ticket, setTicket] = useState<Ticket>(blankTicket());
  const [current, setCurrent] = useState<Result | null>(null);

  const guard = useCallback(async <T,>(p: Promise<T>): Promise<T | null> => {
    try {
      return await p;
    } catch (e) {
      if (e instanceof Unauthorized) setAuth("out");
      else toast.error(e instanceof Error ? e.message : "Something went wrong");
      return null;
    }
  }, []);

  const refresh = useCallback(async () => {
    const [r, e, u] = await Promise.all([guard(api<Result[]>("/api/results")), guard(api<EvalRow[]>("/api/eval")), guard(api<Usage>("/api/usage"))]);
    if (r) setResults(r);
    if (e) setEvals(e);
    if (u) setUsage(u);
  }, [guard]);

  const load = useCallback(async () => {
    try {
      setBoot(await api<Bootstrap>("/api/bootstrap"));
      setAuth("in");
      refresh();
    } catch (e) {
      setAuth(e instanceof Unauthorized ? "out" : "in");
    }
  }, [refresh]);

  useEffect(() => { load(); }, [load]);

  if (auth === "checking") return <div className="grid min-h-screen place-items-center"><Logo size="lg" /></div>;
  if (auth === "out") return <Login onDone={load} />;
  if (!boot) return null;

  const nav = NAV.find((n) => n.id === view)!;
  const go = (v: View) => { setView(v); if (v !== "new") refresh(); };
  const logout = async () => { await fetch("/api/logout", { method: "POST" }); setAuth("out"); };
  const open = (r: Result) => { setCurrent(r); setTicket(r.ticket); setView("new"); };

  return (
    <div className="flex min-h-screen">
      <Toaster position="top-right" richColors closeButton />
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="flex h-16 items-center gap-3 border-b border-slate-100 px-5">
          <Logo />
          <div className="leading-tight"><div className="font-semibold">LeadDesk AI</div><div className="text-xs text-slate-500">Support desk</div></div>
        </div>
        <nav className="space-y-1 p-3">
          {NAV.map((n) => (
            <button key={n.id} onClick={() => go(n.id)}
              className={cx("relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition",
                view === n.id ? "text-blue-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}>
              {view === n.id && <motion.span layoutId="nav" className="absolute inset-0 rounded-lg bg-blue-50 ring-1 ring-blue-100" transition={{ type: "spring", duration: 0.35 }} />}
              <n.icon className="relative size-[18px]" />
              <span className="relative">{n.label}</span>
              {n.id === "inbox" && results.length > 0 && (
                <span className="relative ml-auto rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{results.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="mt-auto space-y-3 border-t border-slate-100 p-4">
          <div className="rounded-xl bg-gradient-to-br from-blue-50 to-teal-50 p-3.5 ring-1 ring-blue-100">
            <div className="eyebrow">Model</div>
            <div className="mt-1 flex items-center gap-2 font-semibold text-slate-800">
              <span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-60" /><span className="relative inline-flex size-2 rounded-full bg-emerald-500" /></span>
              {label(boot.provider)}
            </div>
            <div className="mt-1 flex items-center gap-1 text-xs text-slate-500"><ShieldCheck className="size-3.5" />PII masked before every call</div>
          </div>
          <button onClick={logout} className="flex w-full items-center gap-2 px-1 text-sm text-slate-500 transition hover:text-slate-900"><LogOut className="size-4" />Sign out</button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 bg-gradient-to-b from-blue-50/50 via-slate-50 to-slate-50">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-slate-200 bg-white/80 px-6 backdrop-blur">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold leading-tight">{nav.label}</h1>
            <p className="truncate text-xs text-slate-500">{nav.sub}</p>
          </div>
          <div className="flex gap-1 md:hidden">
            {NAV.map((n) => (
              <button key={n.id} onClick={() => go(n.id)} className={cx("rounded-lg p-2", view === n.id ? "bg-blue-50 text-blue-700" : "text-slate-500")}><n.icon className="size-5" /></button>
            ))}
          </div>
          <span className="hidden items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-600/15 md:inline-flex">
            <Sparkles className="size-3.5" />Human approves every reply
          </span>
        </header>

        <div className="mx-auto max-w-7xl p-6">
          <AnimatePresence mode="wait">
            <motion.div key={view} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.18 }}>
              {view === "new" && <NewTicket boot={boot} ticket={ticket} setTicket={setTicket} result={current} setResult={setCurrent} guard={guard} onSaved={refresh} />}
              {view === "inbox" && <Inbox results={results} clients={boot.clients} onOpen={open} />}
              {view === "calls" && <Calls boot={boot} guard={guard} />}
              {view === "compare" && <Compare boot={boot} ticket={ticket} setTicket={setTicket} guard={guard} />}
              {view === "metrics" && <Metrics results={results} evals={evals} usage={usage} />}
            </motion.div>
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}

export type Guard = <T>(p: Promise<T>) => Promise<T | null>;
