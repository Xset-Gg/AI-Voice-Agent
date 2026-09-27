"use client";

import { ChevronLeft, ChevronRight, History, PhoneOutgoing, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { OutcomeBadge, StatusBadge } from "@/components/status";
import { Button, Card, Empty, ErrorBox, Field, Input, Loading, Modal, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, fmtDuration, fmtPhone, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { CallPage, CallSummary, PhoneNumber } from "@/lib/types";

const STATUSES = ["ringing", "in_progress", "transferring", "completed", "transferred", "failed", "no_answer"];
const OUTCOMES = ["resolved", "appointment_booked", "appointment_rescheduled", "appointment_cancelled", "transferred", "unresolved", "abandoned", "error"];
const PAGE_SIZE = 25;

function OutboundModal({ open, onClose, onPlaced }: { open: boolean; onClose: () => void; onPlaced: (c: CallSummary) => void }) {
  const numbers = useApi<PhoneNumber[]>(open ? "/phone-numbers" : null);
  const [to, setTo] = useState("");
  const [from, setFrom] = useState("");
  const [purpose, setPurpose] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const usable = numbers.data?.filter((n) => n.agent_id) ?? [];

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onPlaced(await api<CallSummary>("/calls/outbound", { body: { to, from_number_id: from || usable[0]?.id, purpose } }));
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Place an outbound call"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="outbound" loading={busy} disabled={!usable.length}>Call now</Button></>}>
      <form id="outbound" onSubmit={submit} className="space-y-4">
        {error && <ErrorBox message={error} />}
        {numbers.data && !usable.length && <ErrorBox message="Assign an agent to one of your phone numbers first." />}
        <Field label="Call from">
          <Select value={from} onChange={(e) => setFrom(e.target.value)}>
            {usable.map((n) => <option key={n.id} value={n.id}>{fmtPhone(n.e164)} {n.friendly_name && `· ${n.friendly_name}`}</option>)}
          </Select>
        </Field>
        <Field label="Number to call" hint="E.164 format, e.g. +15551234567"><Input required value={to} onChange={(e) => setTo(e.target.value)} placeholder="+1…" /></Field>
        <Field label="Purpose" hint="Given to the agent as context for the call."><Input value={purpose} maxLength={500} onChange={(e) => setPurpose(e.target.value)} placeholder="Confirm tomorrow's appointment" /></Field>
      </form>
    </Modal>
  );
}

export default function CallsPage() {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [outcome, setOutcome] = useState("");
  const [direction, setDirection] = useState("");
  const [outbound, setOutbound] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(q.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);
  const filter = (set: (v: string) => void) => (e: React.ChangeEvent<HTMLSelectElement>) => {
    set(e.target.value);
    setPage(1);
  };

  const { data, error, loading, reload } = useApi<CallPage>("/calls", { page, page_size: PAGE_SIZE, q: search, status, outcome, direction });
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <PageHeader
        title="Call History"
        description="Every call your agents have handled, with transcripts and outcomes."
        actions={can("member") && <Button variant="primary" onClick={() => setOutbound(true)}><PhoneOutgoing className="size-4" /> Outbound call</Button>}
      />
      <Card>
        <div className="flex flex-wrap gap-2 border-b border-line p-3">
          <div className="relative min-w-48 flex-1">
            <Search className="absolute left-2.5 top-2.5 size-4 text-ink-3" />
            <Input className="pl-8" placeholder="Search number or summary" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search calls" />
          </div>
          <Select className="w-auto" value={status} onChange={filter(setStatus)} aria-label="Status">
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </Select>
          <Select className="w-auto" value={outcome} onChange={filter(setOutcome)} aria-label="Outcome">
            <option value="">All outcomes</option>
            {OUTCOMES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </Select>
          <Select className="w-auto" value={direction} onChange={filter(setDirection)} aria-label="Direction">
            <option value="">Both directions</option>
            <option value="inbound">Inbound</option>
            <option value="outbound">Outbound</option>
          </Select>
        </div>

        {error && <div className="p-4"><ErrorBox message={error} onRetry={reload} /></div>}
        {loading && !data ? (
          <Loading />
        ) : !data?.items.length ? (
          <Empty icon={<History className="size-6" />} title="No calls found" description={search || status || outcome || direction ? "Try clearing the filters." : "Calls will show up here once your number starts receiving them."} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-ink-3">
                <tr className="border-b border-line">
                  <th className="px-5 py-2.5 font-medium">Caller</th>
                  <th className="px-3 py-2.5 font-medium">Summary</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-3 py-2.5 font-medium">Outcome</th>
                  <th className="px-3 py-2.5 text-right font-medium">Duration</th>
                  <th className="px-5 py-2.5 text-right font-medium">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.items.map((c) => (
                  <tr key={c.id} className="hover:bg-surface-2">
                    <td className="whitespace-nowrap px-5 py-3">
                      <Link href={`/calls/${c.id}`} className="font-medium tabular-nums hover:text-accent">
                        {fmtPhone(c.direction === "inbound" ? c.from_number : c.to_number)}
                      </Link>
                      <div className="text-xs text-ink-3">{c.direction === "inbound" ? "Inbound" : "Outbound"}</div>
                    </td>
                    <td className="max-w-md px-3 py-3">
                      <Link href={`/calls/${c.id}`} className="line-clamp-2 text-ink-2">{c.summary || (c.intent ? humanize(c.intent) : "—")}</Link>
                    </td>
                    <td className="px-3 py-3"><StatusBadge status={c.status} /></td>
                    <td className="px-3 py-3"><OutcomeBadge outcome={c.outcome} /></td>
                    <td className="px-3 py-3 text-right tabular-nums text-ink-2">{fmtDuration(c.duration_seconds)}</td>
                    <td className="whitespace-nowrap px-5 py-3 text-right text-ink-2">{fmtDateTime(c.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data && data.total > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-line px-5 py-3 text-sm text-ink-2">
            <span>{data.total} calls · page {page} of {pages}</span>
            <div className="flex gap-2">
              <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft className="size-4" /></Button>
              <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight className="size-4" /></Button>
            </div>
          </div>
        )}
      </Card>
      <OutboundModal open={outbound} onClose={() => setOutbound(false)} onPlaced={() => reload()} />
    </>
  );
}
