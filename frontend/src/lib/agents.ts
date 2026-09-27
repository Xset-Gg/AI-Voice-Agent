"use client";

import { useApi } from "./hooks";
import type { AgentConfig } from "./types";

/** All agents in the organization (used for pickers and the agent editor). */
export function useAgents() {
  return useApi<AgentConfig[]>("/agents");
}

export const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export const WEEKDAY_LABELS: Record<(typeof WEEKDAYS)[number], string> = {
  mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday",
};

export const COMMON_TIMEZONES = [
  "UTC", "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles",
  "America/Toronto", "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Istanbul", "Asia/Dubai",
  "Asia/Riyadh", "Asia/Karachi", "Asia/Kolkata", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney",
];

export function timezoneOptions(current?: string): string[] {
  return current && !COMMON_TIMEZONES.includes(current) ? [current, ...COMMON_TIMEZONES] : COMMON_TIMEZONES;
}
