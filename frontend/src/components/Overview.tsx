"use client";

import { BookOpen, CalendarCheck, Clock, Gauge, PhoneCall, Radio } from "lucide-react";
import Link from "next/link";
import { useApi, useLiveEvents } from "@/lib/hooks";
import { fmtDateTime, fmtDuration, fmtPct, fmtPhone, humanize } from "@/lib/format";
import type { CallPage, Overview as OverviewData } from "@/lib/types";
import { OutcomeBadge, StatusBadge } from "./status";
import { Card, Empty, ErrorBox, Loading, PageHeader, StatTile } from "./ui";

function CallsPerDay({ series }: { series: OverviewData["calls_per_day"] }) {
  const max = Math.max(1, ...series.map((d) => d.calls));
  return (
    <div className="px-5 pb-4 pt-5">
      <div className="flex h-40 items-end gap-1.5 border-b border-viz-grid" role="img" aria-label="Calls per day, last 14 days">
        {series.map((d) => (
          <div key={d.date} className="group relative flex h-full flex-1 items-end">
            <div
              className="w-full rounded-t-[3px] bg-viz transition-opacity group-hover:opacity-80"
              style={{ height: `${(d.calls / max) * 100}%`, minHeight: d.calls ? 2 : 0 }}
            />
            <div className="pointer-events-none absolute -top-7 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-ink px-1.5 py-0.5 text-[11px] text-surface group-hover:block">
              {d.calls} · {new Date(d.date + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-ink-3 tabular-nums">
        <span>{new Date(series[0].date + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span>
        <span>Today</span>
      </div>
    </div>
  );
}

function Breakdown({ data, empty }: { data: Record<string, number>; empty: string }) {
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((s, [, n]) => s + n, 0);
  if (!rows.length) return <Empty title={empty} />;
  return (
    <ul className="space-y-3 p-5">
      {rows.map(([k, n]) => (
        <li key={k}>
          <div className="mb-1 flex justify-between text-sm">
            <span>{humanize(k)}</span>
            <span className="tabular-nums text-ink-2">{n}</span>
          </div>
          <div className="h-1.5 rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-viz" style={{ width: `${(n / total) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function Overview() {
  const { data, error, loading, reload } = useApi<OverviewData>("/overview");
  const recent = useApi<CallPage>("/calls", { page_size: 8 });
  useLiveEvents((m) => {
    if (m.type === "status") {
      reload();
      recent.reload();
    }
  });

  return (
    <>
      <PageHeader title="Overview" description="How your AI receptionist is performing." />
      {error && <ErrorBox message={error} onRetry={reload} />}
      {loading && !data ? (
        <Loading />
      ) : data ? (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label="Calls today" value={data.calls_today} icon={<PhoneCall className="size-4" />} />
            <StatTile
              label="Active now"
              value={data.active_calls}
              icon={<Radio className="size-4" />}
              sub={<Link href="/live-calls" className="text-accent hover:underline">Watch live</Link>}
            />
            <StatTile label="Resolution rate (7d)" value={fmtPct(data.resolution_rate)} icon={<Gauge className="size-4" />}
              sub={`Transfer rate ${fmtPct(data.transfer_rate)}`} />
            <StatTile label="Appointments booked (7d)" value={data.appointments_booked_7d} icon={<CalendarCheck className="size-4" />} />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <StatTile label="Avg call length (7d)" value={fmtDuration(data.avg_duration_seconds)} icon={<Clock className="size-4" />} />
            <StatTile label="Avg response latency" value={data.avg_response_latency_ms ? `${Math.round(data.avg_response_latency_ms)} ms` : "—"}
              icon={<Gauge className="size-4" />} />
            <StatTile label="Knowledge docs ready" value={data.documents_ready} icon={<BookOpen className="size-4" />}
              sub={<Link href="/knowledge" className="text-accent hover:underline">Manage</Link>} />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Calls per day" className="lg:col-span-2"><CallsPerDay series={data.calls_per_day} /></Card>
            <Card title="Outcomes (7d)"><Breakdown data={data.outcomes_7d} empty="No calls this week" /></Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Top caller intents (7d)"><Breakdown data={data.intents_7d} empty="No intents detected yet" /></Card>
            <Card title="Recent calls" className="lg:col-span-2" action={<Link href="/calls" className="text-xs font-medium text-accent hover:underline">View all</Link>}>
              {recent.data?.items.length ? (
                <ul className="divide-y divide-line">
                  {recent.data.items.map((c) => (
                    <li key={c.id}>
                      <Link href={`/calls/${c.id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 hover:bg-surface-2">
                        <span className="w-36 font-medium tabular-nums">{fmtPhone(c.direction === "inbound" ? c.from_number : c.to_number)}</span>
                        <span className="min-w-0 flex-1 truncate text-sm text-ink-2">{c.summary || humanize(c.intent) }</span>
                        <StatusBadge status={c.status} />
                        <OutcomeBadge outcome={c.outcome} />
                        <span className="w-28 text-right text-xs text-ink-3">{fmtDateTime(c.started_at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty icon={<PhoneCall className="size-6" />} title="No calls yet" description="Connect a phone number and your agent will start answering." />
              )}
            </Card>
          </div>
        </div>
      ) : null}
    </>
  );
}
