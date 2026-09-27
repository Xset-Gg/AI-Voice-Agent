export type Role = "owner" | "admin" | "member" | "viewer";

export interface User { id: string; email: string; full_name: string; role: Role; is_active: boolean }
export interface Organization { id: string; name: string; slug: string; timezone: string }
export interface Me { user: User; organization: Organization }

export type WorkingHours = Record<string, [string, string][]>;

export interface AgentConfig {
  id: string;
  name: string;
  is_active: boolean;
  language: string;
  timezone: string;
  greeting: string;
  after_hours_greeting: string;
  personality: string;
  system_instructions: string;
  business_info: string;
  working_hours: WorkingHours;
  allowed_actions: string[];
  llm_model: string;
  fallback_llm_model: string;
  stt_model: string;
  tts_provider: "openai" | "cartesia";
  tts_voice: string;
  temperature: number;
  min_endpointing_delay: number;
  max_endpointing_delay: number;
  allow_interruptions: boolean;
  silence_timeout_seconds: number;
  max_call_minutes: number;
  transfer_enabled: boolean;
  transfer_number: string | null;
  transfer_triggers: string[];
  max_failed_turns: number;
  fallback_message: string;
  appointment_duration_minutes: number;
  created_at: string;
  updated_at: string;
}

export type CallStatus = "ringing" | "in_progress" | "transferring" | "completed" | "transferred" | "failed" | "no_answer";
export type CallOutcome =
  | "resolved" | "appointment_booked" | "appointment_rescheduled" | "appointment_cancelled"
  | "transferred" | "unresolved" | "abandoned" | "error";

export interface CallSummary {
  id: string;
  agent_id: string | null;
  customer_id: string | null;
  direction: "inbound" | "outbound";
  status: CallStatus;
  outcome: CallOutcome | null;
  from_number: string;
  to_number: string;
  intent: string | null;
  summary: string;
  started_at: string;
  answered_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  end_reason: string | null;
}

export interface Segment { id: string; sequence: number; role: "user" | "assistant"; text: string; interrupted: boolean; created_at: string }
export interface CallEvent { id: string; type: string; data: Record<string, unknown>; created_at: string }

export interface CallDetail extends CallSummary {
  livekit_room: string | null;
  provider_call_sid: string | null;
  metrics: Record<string, unknown>;
  segments: Segment[];
  events: CallEvent[];
}

export interface CallPage { items: CallSummary[]; total: number; page: number; page_size: number }

export interface Overview {
  calls_today: number;
  active_calls: number;
  avg_duration_seconds: number | null;
  resolution_rate: number | null;
  transfer_rate: number | null;
  appointments_booked_7d: number;
  outcomes_7d: Record<string, number>;
  intents_7d: Record<string, number>;
  calls_per_day: { date: string; calls: number }[];
  documents_ready: number;
  avg_response_latency_ms: number | null;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  source_type: "file" | "faq" | "text";
  filename: string | null;
  content_type: string | null;
  size_bytes: number;
  status: "pending" | "processing" | "ready" | "failed";
  error: string | null;
  chunk_count: number;
  risk_flags: { pattern: string; excerpt: string; chunk_index?: number }[];
  created_at: string;
  updated_at: string;
}

export interface Chunk { id: string; chunk_index: number; heading: string | null; text: string; token_count: number; flagged: boolean }

export interface Source {
  chunk_id: string; document_id: string; document_title: string; heading: string | null; text: string; score: number; flagged: boolean;
}

export interface Technician {
  id: string; name: string; email: string | null; skills: string[]; calendar_provider: "internal" | "google";
  calendar_id: string | null; timezone: string; working_hours: WorkingHours; is_active: boolean;
}

export interface Appointment {
  id: string; technician_id: string; customer_id: string | null; call_id: string | null; service: string;
  starts_at: string; ends_at: string; status: "scheduled" | "cancelled" | "completed"; external_event_id: string | null;
  notes: string; created_via: string; technician: Technician;
  customer: { id: string; phone: string; name: string; email: string | null } | null;
}

export interface Slot { technician_id: string; technician_name: string; starts_at: string; ends_at: string }

export interface PhoneNumber { id: string; e164: string; friendly_name: string; provider: string; provider_sid: string | null; agent_id: string | null; created_at: string }
export interface ProviderNumber { sid: string; e164: string; friendly_name: string; voice_url: string | null; claimed: boolean; points_here: boolean }

export interface ToolSpec { name: string; title: string; description: string; category: string; always_on: boolean; mutates: boolean; requires: string[] }

export interface AuditEntry {
  id: string; actor: string; action: string; resource_type: string | null; resource_id: string | null;
  user_id: string | null; data: Record<string, unknown>; ip_address: string | null; created_at: string;
}

export interface LiveMessage { call_id: string; type: string; data: Record<string, unknown> }
