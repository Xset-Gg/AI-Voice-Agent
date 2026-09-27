"use client";

import clsx from "clsx";
import { AlertTriangle, BookOpen, Brain, FileText, PhoneForwarded, Wrench } from "lucide-react";
import { useEffect, useRef } from "react";
import { fmtTime, humanize } from "@/lib/format";
import type { CallEvent, Segment } from "@/lib/types";
import { Badge, Empty } from "./ui";

export function Transcript({ segments, live }: { segments: Pick<Segment, "id" | "role" | "text" | "interrupted" | "created_at">[]; live?: boolean }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (live) end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [segments.length, live]);

  if (!segments.length) return <Empty title={live ? "Waiting for the conversation to start…" : "No transcript recorded"} />;
  return (
    <div className="space-y-3 p-5">
      {segments.map((s) => (
        <div key={s.id} className={clsx("flex", s.role === "user" ? "justify-end" : "justify-start")}>
          <div className={clsx("max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
            s.role === "user" ? "rounded-br-sm bg-accent text-white" : "rounded-bl-sm bg-surface-2")}>
            <div className={clsx("mb-0.5 text-[11px] font-medium", s.role === "user" ? "text-white/75" : "text-ink-3")}>
              {s.role === "user" ? "Caller" : "Agent"} · {fmtTime(s.created_at)}{s.interrupted && " · interrupted"}
            </div>
            {s.text}
          </div>
        </div>
      ))}
      <div ref={end} />
    </div>
  );
}

const ICONS: Record<string, React.ReactNode> = {
  retrieval: <BookOpen className="size-3.5" />,
  tool_call: <Wrench className="size-3.5" />,
  intent: <Brain className="size-3.5" />,
  summary: <FileText className="size-3.5" />,
  transfer: <PhoneForwarded className="size-3.5" />,
  error: <AlertTriangle className="size-3.5" />,
};

type Sources = { document_title: string; heading: string | null; score: number }[];

function EventBody({ ev }: { ev: CallEvent }) {
  const d = ev.data as Record<string, unknown>;
  if (ev.type === "retrieval") {
    const sources = (d.sources as Sources) ?? [];
    return (
      <div>
        <div className="text-ink-2">“{String(d.query ?? "")}”</div>
        {sources.length ? (
          <ul className="mt-1 space-y-0.5 text-xs text-ink-3">
            {sources.map((s, i) => (
              <li key={i}>{s.document_title}{s.heading ? ` › ${s.heading}` : ""} · {s.score.toFixed(2)}</li>
            ))}
          </ul>
        ) : <div className="mt-1 text-xs text-warn">No matching knowledge found</div>}
      </div>
    );
  }
  if (ev.type === "tool_call") {
    return (
      <div>
        <span className="font-medium">{humanize(String(d.tool))}</span>{" "}
        <Badge tone={d.status === "ok" ? "good" : "bad"}>{String(d.status)}</Badge>
        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-surface-2 p-2 font-mono text-[11px] text-ink-2">
          {JSON.stringify({ arguments: d.arguments, result: d.result }, null, 2)}
        </pre>
      </div>
    );
  }
  if (ev.type === "intent") return <div><span className="font-medium">{humanize(String(d.intent))}</span>{d.confidence != null && <span className="text-ink-3"> · {Math.round(Number(d.confidence) * 100)}%</span>}</div>;
  if (ev.type === "summary") return <div className="text-ink-2">{String(d.summary ?? "")}</div>;
  if (ev.type === "transfer") return <div>Transferring to {String(d.to ?? "staff")} — {humanize(String(d.reason ?? ""))}</div>;
  if (ev.type === "status") return <div>{humanize(String(d.status))}</div>;
  if (ev.type === "error") return <div className="text-bad">{humanize(String(d.stage ?? "error"))}: {String(d.error ?? d.dial_status ?? "")}</div>;
  return <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-ink-2">{JSON.stringify(d, null, 2)}</pre>;
}

export function EventTimeline({ events }: { events: CallEvent[] }) {
  const shown = events.filter((e) => e.type !== "transcript");
  if (!shown.length) return <Empty title="No events yet" />;
  return (
    <ol className="space-y-3 p-5">
      {shown.map((ev) => (
        <li key={ev.id} className="flex gap-3 text-sm">
          <div className={clsx("mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full",
            ev.type === "error" ? "bg-bad-soft text-bad" : "bg-surface-2 text-ink-2")}>
            {ICONS[ev.type] ?? <span className="size-1.5 rounded-full bg-ink-3" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="mb-0.5 text-[11px] font-medium uppercase tracking-wide text-ink-3">
              {humanize(ev.type)} · {fmtTime(ev.created_at)}
            </div>
            <EventBody ev={ev} />
          </div>
        </li>
      ))}
    </ol>
  );
}
