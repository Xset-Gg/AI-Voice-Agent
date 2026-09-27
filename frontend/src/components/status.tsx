import { AlertTriangle, CalendarCheck, CheckCircle2, CircleDashed, PhoneForwarded, PhoneMissed, XCircle } from "lucide-react";
import type { CallOutcome, CallStatus } from "@/lib/types";
import { humanize } from "@/lib/format";
import { Badge } from "./ui";

export function StatusBadge({ status }: { status: CallStatus }) {
  if (status === "in_progress")
    return (
      <Badge tone="good">
        <span className="live-dot size-1.5 rounded-full bg-good" /> Live
      </Badge>
    );
  if (status === "ringing") return <Badge tone="accent">Ringing</Badge>;
  if (status === "transferring") return <Badge tone="warn">Transferring</Badge>;
  if (status === "failed") return <Badge tone="bad"><XCircle className="size-3" /> Failed</Badge>;
  if (status === "no_answer") return <Badge><PhoneMissed className="size-3" /> No answer</Badge>;
  if (status === "transferred") return <Badge tone="warn"><PhoneForwarded className="size-3" /> Transferred</Badge>;
  return <Badge>Completed</Badge>;
}

export function OutcomeBadge({ outcome }: { outcome: CallOutcome | null }) {
  if (!outcome) return <Badge><CircleDashed className="size-3" /> Pending</Badge>;
  if (outcome.startsWith("appointment_")) return <Badge tone="good"><CalendarCheck className="size-3" /> {humanize(outcome.replace("appointment_", "appt "))}</Badge>;
  if (outcome === "resolved") return <Badge tone="good"><CheckCircle2 className="size-3" /> Resolved</Badge>;
  if (outcome === "transferred") return <Badge tone="warn"><PhoneForwarded className="size-3" /> Transferred</Badge>;
  if (outcome === "error") return <Badge tone="bad"><AlertTriangle className="size-3" /> Error</Badge>;
  return <Badge>{humanize(outcome)}</Badge>;
}
