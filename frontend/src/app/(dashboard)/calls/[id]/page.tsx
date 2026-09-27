"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { EventTimeline, Transcript } from "@/components/CallTimeline";
import { OutcomeBadge, StatusBadge } from "@/components/status";
import { Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { fmtDateTime, fmtDuration, fmtPhone, humanize } from "@/lib/format";
import { useApi, useLiveEvents } from "@/lib/hooks";
import type { CallDetail } from "@/lib/types";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-2 text-sm">
      <dt className="text-ink-3">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}

export default function CallDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: call, error, loading, reload } = useApi<CallDetail>(`/calls/${id}`);
  useLiveEvents((m) => {
    if (m.call_id === id) reload();
  });

  const metrics = call?.metrics ?? {};
  const latency = metrics.avg_response_latency_ms as number | undefined;

  return (
    <>
      <Link href="/calls" className="mb-3 inline-flex items-center gap-1 text-sm text-ink-2 hover:text-ink">
        <ArrowLeft className="size-4" /> Call history
      </Link>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {loading && !call ? (
        <Loading />
      ) : call ? (
        <>
          <PageHeader
            title={fmtPhone(call.direction === "inbound" ? call.from_number : call.to_number)}
            description={`${call.direction === "inbound" ? "Inbound" : "Outbound"} call · ${fmtDateTime(call.started_at)}`}
            actions={<><StatusBadge status={call.status} /><OutcomeBadge outcome={call.outcome} /></>}
          />
          <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
            <div className="min-w-0 space-y-4">
              {call.summary && (
                <Card title="Summary"><p className="p-5 text-sm leading-relaxed text-ink-2">{call.summary}</p></Card>
              )}
              <Card title="Transcript"><Transcript segments={call.segments} /></Card>
            </div>
            <div className="space-y-4">
              <Card title="Details">
                <dl className="divide-y divide-line px-5 py-2">
                  <Row label="From"><span className="tabular-nums">{fmtPhone(call.from_number)}</span></Row>
                  <Row label="To"><span className="tabular-nums">{fmtPhone(call.to_number)}</span></Row>
                  <Row label="Intent">{humanize(call.intent)}</Row>
                  <Row label="Duration">{fmtDuration(call.duration_seconds)}</Row>
                  <Row label="Answered">{fmtDateTime(call.answered_at)}</Row>
                  <Row label="Ended">{fmtDateTime(call.ended_at)}</Row>
                  <Row label="End reason">{humanize(call.end_reason)}</Row>
                  {latency !== undefined && <Row label="Avg response latency">{Math.round(latency)} ms</Row>}
                </dl>
              </Card>
              <Card title="Agent activity"><EventTimeline events={call.events} /></Card>
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
