"use client";

import clsx from "clsx";
import { Bot, Eye, PhoneCall, Plus, Save, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { TestCall } from "@/components/TestCall";
import { WorkingHoursEditor } from "@/components/WorkingHoursEditor";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Loading, Modal, PageHeader, Select, Tabs, Textarea, Toggle } from "@/components/ui";
import { timezoneOptions, useAgents } from "@/lib/agents";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { AgentConfig, ToolSpec } from "@/lib/types";

type Section = "conversation" | "hours" | "actions" | "voice" | "handling";

const LLM_MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-flash-latest", "gemini-3.1-pro-preview"];
const OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"];
const TRIGGERS: { value: string; label: string; description: string }[] = [
  { value: "caller_request", label: "Caller asks for a person", description: "Transfer as soon as the caller requests a human." },
  { value: "repeated_failure", label: "Agent keeps failing", description: "After the configured number of turns the agent couldn't help with." },
  { value: "low_confidence", label: "Low confidence", description: "When the agent isn't sure it understood." },
  { value: "sensitive_topic", label: "Sensitive topic", description: "Complaints, legal, medical or billing disputes." },
  { value: "tool_error", label: "System error", description: "When booking or lookup actions fail." },
];

type Editable = Omit<AgentConfig, "id" | "created_at" | "updated_at">;

function diff(original: AgentConfig, draft: Editable): Partial<Editable> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(draft)) {
    if (JSON.stringify(v) !== JSON.stringify(original[k as keyof AgentConfig])) out[k] = v;
  }
  return out as Partial<Editable>;
}

function PromptPreview({ agentId, open, onClose }: { agentId: string; open: boolean; onClose: () => void }) {
  const { data, error, loading } = useApi<{ greeting: string; system_prompt: string; tools: string[] }>(open ? `/agents/${agentId}/prompt-preview` : null);
  return (
    <Modal open={open} onClose={onClose} title="What the agent is told" wide>
      {error && <ErrorBox message={error} />}
      {loading || !data ? <Loading /> : (
        <div className="space-y-4 text-sm">
          <div><div className="mb-1 text-xs font-medium text-ink-3">Greeting</div><p className="rounded-lg bg-surface-2 p-3">{data.greeting}</p></div>
          <div><div className="mb-1 text-xs font-medium text-ink-3">Tools</div><div className="flex flex-wrap gap-1.5">{data.tools.map((t) => <Badge key={t}>{humanize(t)}</Badge>)}</div></div>
          <div><div className="mb-1 text-xs font-medium text-ink-3">System prompt</div>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-3 font-mono text-xs leading-relaxed">{data.system_prompt}</pre></div>
        </div>
      )}
    </Modal>
  );
}

function AgentEditor({ agent, onSaved, onDeleted, canDelete }: { agent: AgentConfig; onSaved: (a: AgentConfig) => void; onDeleted: () => void; canDelete: boolean }) {
  const { can } = useAuth();
  const readOnly = !can("admin");
  const tools = useApi<ToolSpec[]>("/tools");
  const [section, setSection] = useState<Section>("conversation");
  const [draft, setDraft] = useState<Editable>(agent);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [preview, setPreview] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [testing, setTesting] = useState(false);

  // After a save the parent passes the updated agent; reset the draft to it.
  const [base, setBase] = useState(agent);
  if (base !== agent) {
    setBase(agent);
    setDraft(agent);
  }
  const changes = useMemo(() => diff(agent, draft), [agent, draft]);
  const dirty = Object.keys(changes).length > 0;
  const set = <K extends keyof Editable>(k: K, v: Editable[K]) => {
    setDraft((d) => ({ ...d, [k]: v }));
    setSaved(false);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      onSaved(await api<AgentConfig>(`/agents/${agent.id}`, { method: "PATCH", body: changes }));
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    try {
      await api(`/agents/${agent.id}`, { method: "DELETE" });
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
      setConfirmDelete(false);
    }
  };

  const toggleAction = (name: string, on: boolean) =>
    set("allowed_actions", on ? [...new Set([...draft.allowed_actions, name])] : draft.allowed_actions.filter((a) => a !== name));
  const toggleTrigger = (name: string, on: boolean) =>
    set("transfer_triggers", on ? [...new Set([...draft.transfer_triggers, name])] : draft.transfer_triggers.filter((a) => a !== name));

  return (
    <div className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs<Section>
          value={section}
          onChange={setSection}
          items={[
            { value: "conversation", label: "Conversation" },
            { value: "hours", label: "Hours" },
            { value: "actions", label: "Actions" },
            { value: "voice", label: "Voice & model" },
            { value: "handling", label: "Call handling" },
          ]}
        />
        <div className="flex gap-2">
          {can("member") && (
            <Button size="sm" onClick={() => setTesting(true)} disabled={dirty} title={dirty ? "Save your changes first" : undefined}>
              <PhoneCall className="size-3.5" /> Test call
            </Button>
          )}
          <Button size="sm" onClick={() => setPreview(true)}><Eye className="size-3.5" /> Preview prompt</Button>
          {!readOnly && (
            <Button size="sm" variant="primary" onClick={save} loading={saving} disabled={!dirty}>
              <Save className="size-3.5" /> {saved && !dirty ? "Saved" : "Save changes"}
            </Button>
          )}
        </div>
      </div>
      {readOnly && <div className="rounded-lg bg-surface-2 px-4 py-2.5 text-sm text-ink-2">You have read-only access. Ask an admin to change agent settings.</div>}
      {error && <ErrorBox message={error} />}

      {section === "conversation" && (
        <Card>
          <div className="grid gap-4 p-5 sm:grid-cols-2">
            <Field label="Agent name"><Input value={draft.name} disabled={readOnly} maxLength={100} onChange={(e) => set("name", e.target.value)} /></Field>
            <Field label="Language"><Input value={draft.language} disabled={readOnly} maxLength={16} onChange={(e) => set("language", e.target.value)} /></Field>
            <div className="sm:col-span-2">
              <Toggle label="Agent active" description="When off, calls to this agent's numbers get the fallback message and are transferred if possible."
                checked={draft.is_active} disabled={readOnly} onChange={(v) => set("is_active", v)} />
            </div>
            <Field label="Greeting" className="sm:col-span-2" hint="Leave empty for an automatic greeting that uses your business name.">
              <Textarea rows={2} value={draft.greeting} disabled={readOnly} maxLength={1000} onChange={(e) => set("greeting", e.target.value)} />
            </Field>
            <Field label="After-hours greeting" className="sm:col-span-2">
              <Textarea rows={2} value={draft.after_hours_greeting} disabled={readOnly} maxLength={1000} onChange={(e) => set("after_hours_greeting", e.target.value)} />
            </Field>
            <Field label="Personality" className="sm:col-span-2" hint="Tone and style, e.g. “Warm, concise, never pushy.”">
              <Textarea rows={3} value={draft.personality} disabled={readOnly} maxLength={4000} onChange={(e) => set("personality", e.target.value)} />
            </Field>
            <Field label="Business information" className="sm:col-span-2" hint="Address, services, pricing basics. Longer documents belong in the Knowledge Base.">
              <Textarea rows={5} value={draft.business_info} disabled={readOnly} maxLength={20000} onChange={(e) => set("business_info", e.target.value)} />
            </Field>
            <Field label="Extra instructions" className="sm:col-span-2" hint="Rules the agent must follow on every call.">
              <Textarea rows={5} value={draft.system_instructions} disabled={readOnly} maxLength={12000} onChange={(e) => set("system_instructions", e.target.value)} />
            </Field>
          </div>
        </Card>
      )}

      {section === "hours" && (
        <Card>
          <div className="space-y-4 p-5">
            <Field label="Timezone" className="max-w-xs">
              <Select value={draft.timezone} disabled={readOnly} onChange={(e) => set("timezone", e.target.value)}>
                {timezoneOptions(draft.timezone).map((tz) => <option key={tz}>{tz}</option>)}
              </Select>
            </Field>
            <WorkingHoursEditor value={draft.working_hours} disabled={readOnly} onChange={(v) => set("working_hours", v)} />
          </div>
        </Card>
      )}

      {section === "actions" && (
        <Card>
          {tools.error && <div className="p-4"><ErrorBox message={tools.error} /></div>}
          {!tools.data ? <Loading /> : (
            <ul className="divide-y divide-line px-5">
              {tools.data.map((t) => (
                <li key={t.name} className="py-1">
                  <Toggle
                    label={t.title}
                    description={t.always_on ? `${t.description} (always on)` : t.description}
                    checked={t.always_on || draft.allowed_actions.includes(t.name)}
                    disabled={readOnly || t.always_on}
                    onChange={(v) => toggleAction(t.name, v)}
                  />
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {section === "voice" && (
        <Card>
          <div className="grid gap-4 p-5 sm:grid-cols-2">
            <Field label="Main AI model" hint="OpenAI models need OPENAI_API_KEY; Gemini models need GEMINI_API_KEY.">
              <Select value={draft.llm_model} disabled={readOnly} onChange={(e) => set("llm_model", e.target.value)}>
                {[...new Set([draft.llm_model, ...LLM_MODELS])].map((m) => <option key={m}>{m}</option>)}
              </Select>
            </Field>
            <Field label="Fallback model" hint="Used automatically if the main provider fails or runs out of credits.">
              <Select value={draft.fallback_llm_model} disabled={readOnly} onChange={(e) => set("fallback_llm_model", e.target.value)}>
                {[...new Set([draft.fallback_llm_model, ...LLM_MODELS])].map((m) => <option key={m}>{m}</option>)}
              </Select>
            </Field>
            <Field label="Creativity" hint={`${draft.temperature.toFixed(1)} — lower is more predictable.`}>
              <input type="range" min={0} max={1.5} step={0.1} value={draft.temperature} disabled={readOnly}
                onChange={(e) => set("temperature", Number(e.target.value))} className="w-full accent-[var(--accent)]" />
            </Field>
            <Field label="Speech-to-text model"><Input value={draft.stt_model} disabled={readOnly} onChange={(e) => set("stt_model", e.target.value)} /></Field>
            <Field label="Voice provider">
              <Select value={draft.tts_provider} disabled={readOnly} onChange={(e) => set("tts_provider", e.target.value as Editable["tts_provider"])}>
                <option value="openai">OpenAI</option>
                <option value="cartesia">Cartesia</option>
              </Select>
            </Field>
            <Field label="Voice" hint={draft.tts_provider === "cartesia" ? "Cartesia voice ID." : undefined}>
              {draft.tts_provider === "openai" ? (
                <Select value={draft.tts_voice} disabled={readOnly} onChange={(e) => set("tts_voice", e.target.value)}>
                  {[...new Set([draft.tts_voice, ...OPENAI_VOICES])].map((v) => <option key={v}>{v}</option>)}
                </Select>
              ) : (
                <Input value={draft.tts_voice} disabled={readOnly} onChange={(e) => set("tts_voice", e.target.value)} />
              )}
            </Field>
          </div>
        </Card>
      )}

      {section === "handling" && (
        <div className="space-y-4">
          <Card title="Timing">
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <Field label="Min pause before replying (s)">
                <Input type="number" min={0.1} max={3} step={0.1} value={draft.min_endpointing_delay} disabled={readOnly} onChange={(e) => set("min_endpointing_delay", Number(e.target.value))} />
              </Field>
              <Field label="Max wait for caller to finish (s)">
                <Input type="number" min={0.5} max={15} step={0.5} value={draft.max_endpointing_delay} disabled={readOnly} onChange={(e) => set("max_endpointing_delay", Number(e.target.value))} />
              </Field>
              <Field label="Silence timeout (s)" hint="Hang up after this much silence.">
                <Input type="number" min={3} max={120} value={draft.silence_timeout_seconds} disabled={readOnly} onChange={(e) => set("silence_timeout_seconds", Number(e.target.value))} />
              </Field>
              <Field label="Max call length (min)">
                <Input type="number" min={1} max={120} value={draft.max_call_minutes} disabled={readOnly} onChange={(e) => set("max_call_minutes", Number(e.target.value))} />
              </Field>
              <Field label="Default appointment length (min)">
                <Input type="number" min={10} max={480} step={5} value={draft.appointment_duration_minutes} disabled={readOnly} onChange={(e) => set("appointment_duration_minutes", Number(e.target.value))} />
              </Field>
              <div className="self-end">
                <Toggle label="Let callers interrupt" checked={draft.allow_interruptions} disabled={readOnly} onChange={(v) => set("allow_interruptions", v)} />
              </div>
            </div>
          </Card>
          <Card title="Human handoff">
            <div className="space-y-4 p-5">
              <Toggle label="Transfer to a person" description="Let the agent hand calls to your team." checked={draft.transfer_enabled} disabled={readOnly} onChange={(v) => set("transfer_enabled", v)} />
              <div className={clsx("grid gap-4 sm:grid-cols-2", !draft.transfer_enabled && "opacity-50")}>
                <Field label="Transfer number" hint="E.164, e.g. +15551234567">
                  <Input value={draft.transfer_number ?? ""} disabled={readOnly || !draft.transfer_enabled} onChange={(e) => set("transfer_number", e.target.value || null)} />
                </Field>
                <Field label="Failed turns before handoff">
                  <Input type="number" min={1} max={10} value={draft.max_failed_turns} disabled={readOnly || !draft.transfer_enabled} onChange={(e) => set("max_failed_turns", Number(e.target.value))} />
                </Field>
              </div>
              <div className={clsx("divide-y divide-line", !draft.transfer_enabled && "opacity-50")}>
                {TRIGGERS.map((t) => (
                  <Toggle key={t.value} label={t.label} description={t.description} checked={draft.transfer_triggers.includes(t.value)}
                    disabled={readOnly || !draft.transfer_enabled} onChange={(v) => toggleTrigger(t.value, v)} />
                ))}
              </div>
              <Field label="Fallback message" hint="Said when the agent can't help safely.">
                <Textarea rows={2} value={draft.fallback_message} disabled={readOnly} maxLength={1000} onChange={(e) => set("fallback_message", e.target.value)} />
              </Field>
            </div>
          </Card>
          {!readOnly && canDelete && (
            <Card title="Danger zone">
              <div className="flex flex-wrap items-center justify-between gap-3 p-5 text-sm">
                <span className="text-ink-2">Delete this agent. Phone numbers assigned to it will stop answering.</span>
                <Button variant="danger" onClick={() => setConfirmDelete(true)}><Trash2 className="size-4" /> Delete agent</Button>
              </div>
            </Card>
          )}
        </div>
      )}

      <PromptPreview agentId={agent.id} open={preview} onClose={() => setPreview(false)} />
      {testing && <TestCall agent={agent} open onClose={() => setTesting(false)} />}
      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)} title={`Delete ${agent.name}?`}
        footer={<><Button onClick={() => setConfirmDelete(false)}>Cancel</Button><Button variant="danger" onClick={remove}>Delete</Button></>}>
        <p className="text-sm text-ink-2">This can&apos;t be undone. Call history is kept.</p>
      </Modal>
    </div>
  );
}

export default function AgentPage() {
  const { can, me } = useAuth();
  const { data: agents, error, loading, reload, setData } = useAgents();
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const agent = agents?.find((a) => a.id === selected) ?? agents?.[0];

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setCreateError(null);
    try {
      const a = await api<AgentConfig>("/agents", {
        body: {
          name: newName, timezone: me?.organization.timezone ?? "UTC",
          allowed_actions: ["check_availability", "book_appointment", "find_my_appointments", "reschedule_appointment", "cancel_appointment"],
        },
      });
      setData([...(agents ?? []), a]);
      setSelected(a.id);
      setCreating(false);
      setNewName("");
    } catch (err) {
      setCreateError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="AI Agents"
        description="Configure how your receptionists talk, what they know and what they're allowed to do."
        actions={can("admin") && <Button variant="primary" onClick={() => setCreating(true)}><Plus className="size-4" /> New agent</Button>}
      />
      {error && <ErrorBox message={error} onRetry={reload} />}
      {loading && !agents ? <Loading /> : !agent ? (
        <Card><Empty icon={<Bot className="size-6" />} title="No agents yet" description="Create an agent to start answering calls." /></Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[14rem_1fr]">
          <Card title={`${agents!.length} agent${agents!.length === 1 ? "" : "s"}`}>
            <ul className="max-h-[70vh] divide-y divide-line overflow-y-auto">
              {agents!.map((a) => (
                <li key={a.id}>
                  <button onClick={() => setSelected(a.id)} className={clsx("flex w-full items-center justify-between gap-2 px-4 py-3 text-left text-sm hover:bg-surface-2", a.id === agent.id && "bg-accent-soft")}>
                    <span className="truncate font-medium">{a.name}</span>
                    <Badge tone={a.is_active ? "good" : "neutral"}>{a.is_active ? "On" : "Off"}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <AgentEditor
            key={agent.id}
            agent={agent}
            canDelete={agents!.length > 1}
            onSaved={(a) => setData((agents ?? []).map((x) => (x.id === a.id ? a : x)))}
            onDeleted={() => { setData((agents ?? []).filter((x) => x.id !== agent.id)); setSelected(null); }}
          />
        </div>
      )}

      <Modal open={creating} onClose={() => setCreating(false)} title="New agent"
        footer={<><Button onClick={() => setCreating(false)}>Cancel</Button><Button variant="primary" type="submit" form="new-agent" loading={busy}>Create</Button></>}>
        <form id="new-agent" onSubmit={create} className="space-y-4">
          {createError && <ErrorBox message={createError} />}
          <Field label="Name" hint="Callers hear this name, e.g. “Ava”."><Input required maxLength={100} value={newName} onChange={(e) => setNewName(e.target.value)} autoFocus /></Field>
        </form>
      </Modal>
    </>
  );
}
