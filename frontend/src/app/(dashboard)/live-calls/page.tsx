"use client";

import clsx from "clsx";
import { PhoneOff, Radio, Wifi, WifiOff } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { EventTimeline, Transcript } from "@/components/CallTimeline";
import { StatusBadge } from "@/components/status";
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDuration, fmtPhone } from "@/lib/format";
import { useApi, useLiveEvents } from "@/lib/hooks";
import type { CallDetail, CallStatus, CallSummary, LiveMessage } from "@/lib/types";

const ACTIVE: CallStatus[] = ["ringing", "in_progress", "transferring"];

function Elapsed({ call }: { call: CallSummary }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const from = new Date(call.answered_at ?? call.started_at).getTime();
  return <span className="tabular-nums">{fmtDuration(Math.max(0, (now - from) / 1000))}</span>;
}

export default function LiveCallsPage() {
  const { can } = useAuth();
  const { data: calls, error, loading, reload, setData: setCalls } = useApi<CallSummary[]>("/calls/active");
  const [selected, setSelected] = useState<string | null>(null);
  const [hangingUp, setHangingUp] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const current = calls?.some((c) => c.id === selected) ? selected : (calls?.[0]?.id ?? null);
  const { data: loaded, error: detailError, setData: setDetail } = useApi<CallDetail>(current ? `/calls/${current}` : null);
  const detail = loaded?.id === current ? loaded : null;

  const connected = useLiveEvents((m: LiveMessage) => {
    const d = m.data;
    if (m.type === "status") {
      const status = d.status as CallStatus;
      const known = calls?.some((c) => c.id === m.call_id);
      if (!ACTIVE.includes(status)) setCalls((prev) => (prev ?? []).filter((c) => c.id !== m.call_id));
      else if (known)
        setCalls((prev) => (prev ?? []).map((c) => (c.id === m.call_id ? { ...c, status, answered_at: (d.answered_at as string) ?? c.answered_at } : c)));
      else reload();
      if (m.call_id === current) setDetail((prev) => (prev ? { ...prev, status } : prev));
      return;
    }
    if (m.call_id !== current) return;
    const at = (d.at as string) ?? new Date().toISOString();
    if (m.type === "transcript") {
      setDetail((prev) =>
        prev && !prev.segments.some((s) => s.id === d.segment_id)
          ? { ...prev, segments: [...prev.segments, { id: String(d.segment_id), sequence: Number(d.sequence), role: d.role as "user" | "assistant", text: String(d.text), interrupted: !!d.interrupted, created_at: at }] }
          : prev,
      );
    } else {
      setDetail((prev) =>
        prev && !prev.events.some((e) => e.id === d.event_id)
          ? { ...prev, events: [...prev.events, { id: String(d.event_id ?? crypto.randomUUID()), type: m.type, data: d, created_at: at }] }
          : prev,
      );
    }
  });

  const hangup = async () => {
    if (!current) return;
    setHangingUp(true);
    setActionError(null);
    try {
      await api(`/calls/${current}/hangup`, { method: "POST" });
      setCalls((prev) => (prev ?? []).filter((c) => c.id !== current));
      setSelected(null);
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setHangingUp(false);
    }
  };

  const active = calls?.find((c) => c.id === current);

  return (
    <>
      <PageHeader
        title="Live Calls"
        description="Watch conversations as they happen."
        actions={
          <Badge tone={connected ? "good" : "warn"}>
            {connected ? <Wifi className="size-3" /> : <WifiOff className="size-3" />} {connected ? "Connected" : "Reconnecting…"}
          </Badge>
        }
      />
      {error && <ErrorBox message={error} onRetry={reload} />}
      {(actionError || detailError) && <div className="mb-4"><ErrorBox message={(actionError || detailError)!} /></div>}
      {loading && !calls ? (
        <Loading />
      ) : !calls?.length ? (
        <Card>
          <Empty icon={<Radio className="size-6" />} title="No calls in progress" description="New calls appear here instantly — no refresh needed." />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <Card title={`${calls.length} active`}>
            <ul className="divide-y divide-line">
              {calls.map((c) => (
                <li key={c.id}>
                  <button
                    onClick={() => setSelected(c.id)}
                    className={clsx("w-full px-4 py-3 text-left hover:bg-surface-2", c.id === current && "bg-accent-soft")}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium tabular-nums">{fmtPhone(c.direction === "inbound" ? c.from_number : c.to_number)}</span>
                      <StatusBadge status={c.status} />
                    </div>
                    <div className="mt-0.5 flex justify-between text-xs text-ink-3">
                      <span>{c.direction === "inbound" ? "Inbound" : "Outbound"}</span>
                      <Elapsed call={c} />
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>

          {active && (
            <div className="grid min-w-0 gap-4 xl:grid-cols-[1fr_22rem]">
              <Card
                title={<span className="flex items-center gap-2">Transcript <Elapsed call={active} /></span>}
                action={
                  <div className="flex gap-2">
                    <Link href={`/calls/${active.id}`} className="inline-flex h-8 items-center rounded-lg px-3 text-xs font-medium text-ink-2 hover:bg-surface-2">Details</Link>
                    {can("member") && (
                      <Button size="sm" variant="danger" loading={hangingUp} onClick={hangup}><PhoneOff className="size-3.5" /> End call</Button>
                    )}
                  </div>
                }
              >
                <div className="max-h-[65vh] overflow-y-auto">
                  {detail ? <Transcript segments={detail.segments} live /> : <Loading />}
                </div>
              </Card>
              <Card title="Agent activity">
                <div className="max-h-[65vh] overflow-y-auto">{detail ? <EventTimeline events={detail.events} /> : <Loading />}</div>
              </Card>
            </div>
          )}
        </div>
      )}
    </>
  );
}
