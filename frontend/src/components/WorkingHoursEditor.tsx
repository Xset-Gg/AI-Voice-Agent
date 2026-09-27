"use client";

import { Plus, X } from "lucide-react";
import { WEEKDAYS, WEEKDAY_LABELS } from "@/lib/agents";
import type { WorkingHours } from "@/lib/types";
import { Button, Input } from "./ui";

export function WorkingHoursEditor({ value, onChange, disabled }: { value: WorkingHours; onChange: (v: WorkingHours) => void; disabled?: boolean }) {
  const set = (day: string, ranges: [string, string][]) => onChange({ ...value, [day]: ranges });

  return (
    <div className="divide-y divide-line">
      {WEEKDAYS.map((day) => {
        const ranges = value[day] ?? [];
        return (
          <div key={day} className="flex flex-wrap items-center gap-3 py-2.5">
            <div className="w-24 text-sm font-medium">{WEEKDAY_LABELS[day]}</div>
            <div className="flex flex-1 flex-wrap items-center gap-2">
              {ranges.length === 0 && <span className="text-sm text-ink-3">Closed</span>}
              {ranges.map(([start, end], i) => (
                <div key={i} className="flex items-center gap-1">
                  <Input type="time" className="w-28" value={start} disabled={disabled} aria-label={`${WEEKDAY_LABELS[day]} opens`}
                    onChange={(e) => set(day, ranges.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))} />
                  <span className="text-ink-3">–</span>
                  <Input type="time" className="w-28" value={end} disabled={disabled} aria-label={`${WEEKDAY_LABELS[day]} closes`}
                    onChange={(e) => set(day, ranges.map((r, j) => (j === i ? [r[0], e.target.value] : r)))} />
                  {!disabled && (
                    <button type="button" onClick={() => set(day, ranges.filter((_, j) => j !== i))} className="rounded p-1 text-ink-3 hover:bg-surface-2" aria-label="Remove hours">
                      <X className="size-4" />
                    </button>
                  )}
                </div>
              ))}
              {!disabled && (
                <Button type="button" size="sm" variant="ghost" onClick={() => set(day, [...ranges, ranges.length ? ["13:00", "17:00"] : ["09:00", "17:00"]])}>
                  <Plus className="size-3.5" /> Hours
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
